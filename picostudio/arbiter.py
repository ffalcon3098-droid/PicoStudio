"""
PicoStudio 6 GB VRAM GPU Arbiter.

Coordinates mutually-exclusive GPU ownership between:
  - Coding LLM Engine (PicoCode -> llama-server.exe with Inkling 2 Mini / Qwen3-Coder / Qwen2.5-Coder)
  - Video & Image Engine (PicoVid/localVid -> Wan 2.2 TI2V-5B Turbo / Wan 2.2 14B / Z-Image-Turbo)

Guarantees zero VRAM collisions on 4-6 GB GPUs by cleanly unloading the Coding LLM
before launching Video/Image diffusion, streaming live logs & VRAM telemetry, and
zero-copying all model files directly from sibling PicoCode & localVid directories.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any

STUDIO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = STUDIO_ROOT / "configs" / "studio_config.json"


def load_config(path: pathlib.Path = DEFAULT_CONFIG) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in ("picocode_dir", "picovid_dir", "projects_root", "default_workspace"):
        val = raw.get(key)
        if val:
            p = pathlib.Path(val)
            raw[key] = str((STUDIO_ROOT / p).resolve() if not p.is_absolute() else p)
    return raw


class GPUArbiter:
    """Thread-safe 6 GB VRAM orchestrator for Coding LLM + Video/Image diffusion."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.cfg = config or load_config()
        self.picocode_dir = pathlib.Path(self.cfg["picocode_dir"])
        self.picovid_dir = pathlib.Path(self.cfg["picovid_dir"])
        self.llm_host = self.cfg.get("ide_host", "127.0.0.1")
        self.llm_port = int(self.cfg.get("llm_port", 8080))

        self._picocode_probe = None
        self._picocode_serve = None
        self._load_picocode_modules()

        self.lock = threading.Lock()
        self._op_lock = threading.RLock()  # Serializes GPU start/stop transitions against TOCTOU races
        self.owner: str = "idle"  # idle | coding_starting | coding | media
        self.coding_model: str = self.cfg.get("default_coding_model", "inkling2-mini")
        self.coding_proc: subprocess.Popen[str] | None = None
        self._last_coding_pid: int | None = None
        self.coding_plan: dict[str, Any] | None = None
        self.media_proc: subprocess.Popen[str] | None = None
        self.media_job: dict[str, Any] | None = None
        self.logs: list[str] = []
        self.media_logs: list[str] = []
        self.last_error: str = ""
        self.hw_base: dict[str, Any] = self._probe_hw()

    def _load_picocode_modules(self) -> None:
        scripts = self.picocode_dir / "scripts"
        if scripts.exists() and str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        try:
            import probe_hardware  # type: ignore
            import serve  # type: ignore
            self._picocode_probe = probe_hardware
            self._picocode_serve = serve
        except Exception:
            pass

    def _probe_hw(self) -> dict[str, Any]:
        if self._picocode_probe is not None:
            try:
                return self._picocode_probe.probe_hardware(self.picocode_dir / "models")
            except Exception:
                pass
        return {
            "gpu_name": "GPU",
            "backend": "vulkan",
            "vram_total_gib": 6.0,
            "ram_total_gib": 32.0,
            "disk_free_gib": 20.0,
            "cpu_threads": os.cpu_count() or 8,
        }

    def _log(self, msg: str, media: bool = False) -> None:
        with self.lock:
            target = self.media_logs if media else self.logs
            target.append(msg)
            if len(target) > 160:
                del target[:-160]

    # ---------- Model inventory across PicoCode & localVid ----------

    def get_inventory(self) -> dict[str, Any]:
        coding_models: list[dict[str, Any]] = []
        reg_path = self.picocode_dir / "configs" / "models_registry.json"
        if reg_path.exists():
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
            files_map = reg.get("files", {})
            for mid, mcfg in reg.get("models", {}).items():
                fitem = files_map.get(mcfg["model_file"], {})
                fpath = self.picocode_dir / fitem.get("path", "")
                installed = fpath.exists() and fpath.stat().st_size == int(fitem.get("expected_bytes", -1))
                coding_models.append({
                    "id": mid,
                    "label": mcfg["label"],
                    "installed": installed,
                    "size_gib": round(int(fitem.get("expected_bytes", 0)) / (1024**3), 2),
                })

        media_models: list[dict[str, Any]] = []
        vid_reg_path = self.picovid_dir / "configs" / "models_registry.json"
        if vid_reg_path.exists():
            vreg = json.loads(vid_reg_path.read_text(encoding="utf-8"))
            vfiles = vreg.get("files", {})
            checks = [
                ("ltx23-distilled", "LTX-2.3 22B Distilled (Ses + Video · T2V/I2V)", ("ltx23_distilled_q4_k_m",)),
                ("z-image-turbo", "Z-Image-Turbo (Hızlı Görsel Üretimi)", ("z_image_turbo_q4_k", "z_image_turbo_q4_k_m", "z_image_turbo")),
            ]
            for eid, label, keys in checks:
                fitem = next((vfiles[k] for k in keys if k in vfiles), None)
                if fitem is None and eid == "z-image-turbo":
                    fitem = next((v for k, v in vfiles.items() if "z_image" in k or "zimage" in k), None)
                if fitem:
                    fpath = self.picovid_dir / fitem.get("path", "")
                    ok = fpath.exists() and fpath.stat().st_size > 100_000_000
                    media_models.append({"id": eid, "label": label, "installed": ok})
        else:
            # Fallback check by directory scan
            dm = self.picovid_dir / "models" / "diffusion_models"
            if dm.exists():
                for f in sorted(dm.glob("*.gguf")):
                    media_models.append({"id": f.stem, "label": f.name, "installed": True})

        return {
            "picocode_dir": str(self.picocode_dir),
            "picovid_dir": str(self.picovid_dir),
            "coding_models": coding_models,
            "media_models": media_models,
        }

    # ---------- Stop helpers (VRAM Release) ----------

    def _kill_port_llama_server(self) -> None:
        """Kill ONLY our tracked llama-server PID or a llama-server listening on self.llm_port (never unrelated instances)."""
        if os.name != "nt":
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        pids_to_kill: set[int] = set()
        if self._last_coding_pid:
            pids_to_kill.add(self._last_coding_pid)
        try:
            ns = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=5, creationflags=flags,
            )
            needle = f":{self.llm_port}"
            for ln in (ns.stdout or "").splitlines():
                parts = ln.split()
                if len(parts) >= 5 and parts[1].endswith(needle) and parts[3].upper() == "LISTENING":
                    if parts[4].isdigit():
                        pids_to_kill.add(int(parts[4]))
        except Exception:
            pass
        for pid in pids_to_kill:
            try:
                chk = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=5, creationflags=flags,
                )
                if "llama-server.exe" in (chk.stdout or "").lower():
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
                    )
            except Exception:
                pass
        self._last_coding_pid = None

    def stop_coding(self) -> None:
        with self._op_lock:
            with self.lock:
                proc = self.coding_proc
                self.coding_proc = None
                self.coding_plan = None
                if self.owner in ("coding", "coding_starting"):
                    self.owner = "idle"
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
                self._log("[Arbiter] Kodlama modeli durduruldu — GPU VRAM serbest birakildi.")
            self._kill_port_llama_server()

    def stop_media(self) -> None:
        with self._op_lock:
            with self.lock:
                proc = self.media_proc
                self.media_proc = None
                if self.media_job:
                    self.media_job["status"] = "stopped"
                if self.owner == "media":
                    self.owner = "idle"
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
                self._log("[Arbiter] Video/Gorsel uretimi durduruldu.", media=True)

    def stop_all(self) -> None:
        self.stop_media()
        self.stop_coding()

    # ---------- Start Coding LLM ----------

    def start_coding(
        self,
        model_id: str | None = None,
        *,
        use_draft: bool | None = None,
        use_vision: bool | None = None,
        ctx_size: int | None = None,
        wait_ready: bool = False,
    ) -> tuple[bool, str]:
        existing_proc: subprocess.Popen[str] | None = None
        proc: subprocess.Popen[str] | None = None

        with self._op_lock:
            with self.lock:
                if self.owner == "media" and self.media_proc is not None and self.media_proc.poll() is None:
                    return False, "Su an Video/Gorsel uretimi GPU'yu kullaniyor. Once bitmesini bekleyin veya durdurun."
                chosen_model = model_id or self.coding_model
                if self.owner == "coding" and self.coding_proc is not None and self.coding_proc.poll() is None and chosen_model == self.coding_model:
                    return True, f"{chosen_model} zaten hazir."
                if self.owner == "coding_starting" and self.coding_proc is not None and self.coding_proc.poll() is None and chosen_model == self.coding_model:
                    existing_proc = self.coding_proc

            if existing_proc is None:
                self.stop_coding()
                if self._picocode_serve is None:
                    return False, f"PicoCode bulunamadi: {self.picocode_dir}"

                reg = self._picocode_serve.load_registry(self.picocode_dir / "configs" / "models_registry.json")
                if chosen_model in reg["models"]:
                    if self._picocode_serve.resolve_model_file(reg["models"][chosen_model], reg, allow_missing=False) is None:
                        chosen_model = self._picocode_serve.pick_installed_model(reg)
                hw = self._probe_hw()
                self.hw_base = hw
                exe = self._picocode_serve.find_llama_server(hw.get("backend", "vulkan"))
                if exe is None:
                    return False, "llama-server.exe bulunamadi! PicoCode klasorunde setup.cmd calistirin."

                draft_flag = self.cfg.get("coding_use_draft", False) if use_draft is None else use_draft
                vision_flag = self.cfg.get("coding_use_vision", True) if use_vision is None else use_vision

                try:
                    cmd, plan = self._picocode_serve.build_server_command(
                        chosen_model,
                        hw,
                        reg,
                        server_exe=exe,
                        host=self.llm_host,
                        port=self.llm_port,
                        ctx_size=ctx_size,
                        use_draft=draft_flag,
                        use_vision=vision_flag,
                    )
                except Exception as exc:
                    return False, str(exc)

                with self.lock:
                    self.owner = "coding_starting"
                    self.coding_model = chosen_model
                    self.coding_plan = plan
                    self.last_error = ""
                    self.logs = [f"[Arbiter] Kodlama modeli yukleniyor: {plan['label']}"]

                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=flags,
                )
                with self.lock:
                    self.coding_proc = proc
                    self._last_coding_pid = proc.pid

                def _watch() -> None:
                    assert proc is not None and proc.stdout is not None
                    for line in proc.stdout:
                        self._log(line.rstrip())
                    code = proc.wait()
                    with self.lock:
                        if self.coding_proc is proc:
                            self.coding_proc = None
                            if self.owner in ("coding", "coding_starting"):
                                self.owner = "idle"
                                self.last_error = f"llama-server cikti (kod={code})"

                threading.Thread(target=_watch, daemon=True).start()

        if existing_proc is not None:
            if wait_ready and self._picocode_serve is not None:
                ok = self._picocode_serve.wait_for_health(self.llm_host, self.llm_port, existing_proc, timeout_s=180.0)
                return ok, ("Hazir" if ok else "Sunucu hazir olamadi.")
            return True, f"{self.coding_model} zaten yukleniyor..."

        assert proc is not None
        def _wait_health() -> None:
            ok = self._picocode_serve.wait_for_health(self.llm_host, self.llm_port, proc, timeout_s=180.0)
            with self.lock:
                if self.coding_proc is proc:
                    if ok:
                        self.owner = "coding"
                        self.logs.append(f"[Arbiter] HAZIR -> http://{self.llm_host}:{self.llm_port}/v1")
                    elif self.owner == "coding_starting":
                        self.owner = "idle"
                        self.last_error = "Kodlama sunucusu hazir olamadi."

        if wait_ready:
            _wait_health()
            with self.lock:
                return (self.owner == "coding"), ("Hazir" if self.owner == "coding" else self.last_error)
        threading.Thread(target=_wait_health, daemon=True).start()
        return True, f"{chosen_model} baslatiliyor..."

    # ---------- Unified LLM Helpers (Eliminates boilerplate across IDE endpoints) ----------

    def ensure_coding_ready(self) -> tuple[bool, int, str]:
        """Ensure coding LLM is ready; returns (ok, http_status, error_msg)."""
        if self.owner == "media":
            return False, 409, "GPU su an Video/Gorsel uretiminde."
        if self.owner != "coding":
            ok, msg = self.start_coding(wait_ready=True)
            if not ok:
                return False, 503, msg
        return True, 200, ""

    def chat_complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 256,
        timeout: int = 90,
    ) -> tuple[bool, int, str]:
        """Single-shot local LLM chat completion returning (ok, status, content_or_error)."""
        ok, code, err = self.ensure_coding_ready()
        if not ok:
            return False, code, err
        payload = {
            "model": self.coding_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"http://{self.llm_host}:{self.llm_port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res = json.loads(resp.read().decode("utf-8", errors="replace"))
            txt = (res["choices"][0]["message"].get("content") or "").strip()
            return True, 200, txt
        except Exception as exc:
            return False, 502, str(exc)

    def infill_complete(
        self,
        prefix: str,
        suffix: str,
        *,
        rel_path: str = "code.py",
        max_tokens: int = 160,
        timeout: int = 90,
    ) -> tuple[bool, int, str]:
        """Native llama-server `/infill` FIM completion (far higher accuracy on Qwen2.5-Coder), with chat fallback."""
        ok, code, err = self.ensure_coding_ready()
        if not ok:
            return False, code, err
        infill_payload = {
            "input_prefix": prefix[-2200:],
            "input_suffix": suffix[:800],
            "n_predict": max_tokens,
            "temperature": 0.12,
            "stop": ["\n\n\n", "<|endoftext|>", "<|file_sep|>", "<|fim_pad|>"],
        }
        req = urllib.request.Request(
            f"http://{self.llm_host}:{self.llm_port}/infill",
            data=json.dumps(infill_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res = json.loads(resp.read().decode("utf-8", errors="replace"))
            comp = str(res.get("content") or "").rstrip("\r\n")
            if comp.strip():
                return True, 200, comp
        except Exception:
            pass
        # Fallback to chat completion if model/server doesn't produce infill output
        return self.chat_complete(
            [
                {
                    "role": "system",
                    "content": (
                        f"You are an inline code autocomplete engine for `{rel_path}`. "
                        "Continue code strictly at <CURSOR>. Output ONLY raw code (1-8 lines), NO fences, NO prose."
                    ),
                },
                {"role": "user", "content": f"PREFIX:\n{prefix[-1800:]}<CURSOR>\nSUFFIX:\n{suffix[:600]}"},
            ],
            temperature=0.12,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    # ---------- Start Video / Image via PicoVid (Auto-Unloads Coding LLM!) ----------

    def start_media(
        self,
        *,
        prompt: str,
        engine: str = "ltx23",
        mode: str = "t2v",
        width: int = 768,
        height: int = 448,
        frames: int = 25,
        cinema_hd: bool = False,
        fast_preview: bool = False,
        seed: int | None = None,
        init_img: str | None = None,
    ) -> tuple[bool, str, str | None]:
        gen_script = self.picovid_dir / "scripts" / "generate.py"
        if not gen_script.exists():
            return False, f"PicoVid bulunamadi: {gen_script}", None

        with self._op_lock:
            with self.lock:
                if self.owner == "media" and self.media_proc is not None and self.media_proc.poll() is None:
                    return False, "Zaten bir Video/Gorsel uretimi calisiyor.", None
                was_coding = self.owner in ("coding", "coding_starting")

            # CRITICAL 6 GB VRAM HANDOFF: unload Coding LLM before launching Wan 2.2 / Z-Image!
            if was_coding:
                self._log("[Arbiter] 6 GB VRAM korumasi: Kodlama modeli kapatiliyor, GPU Video motoruna devrediliyor...", media=True)
                self.stop_coding()
                time.sleep(1.0)

            out_dir = self.picovid_dir / "outputs"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            ext = "png" if mode == "t2i" else "mp4"
            out_file = out_dir / f"studio_{engine}_{mode}_{stamp}.{ext}"

            cmd = [
                sys.executable, "-u", str(gen_script),
                "--engine", engine,
                "--mode", mode,
                "-p", prompt,
                "-o", str(out_file),
                "-W", str(int(width)),
                "-H", str(int(height)),
                "--raw-logs",
                "--auto-approve",
            ]
            if mode != "t2i":
                cmd += ["-f", str(int(frames))]
                if cinema_hd:
                    cmd += ["--cinema-hd"]
                if fast_preview and engine != "ltx23":
                    cmd += ["--fast-preview"]
            if init_img:
                cmd += ["-i", init_img]
            if seed is not None:
                cmd += ["--seed", str(int(seed))]

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["SD_SEG_TIMING"] = "2"

            with self.lock:
                self.owner = "media"
                self.last_error = ""
                self.media_logs = [
                    f"[Arbiter] GPU devralindi -> PicoVid ({engine.upper()} / {mode.upper()})",
                    f"[Arbiter] Cikti: {out_file.name}",
                ]
                self.media_job = {
                    "status": "running",
                    "engine": engine,
                    "mode": mode,
                    "prompt": prompt,
                    "output": str(out_file),
                    "output_name": out_file.name,
                    "started_at": time.time(),
                    "finished_at": None,
                    "returncode": None,
                }

            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.picovid_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=flags,
            )
            with self.lock:
                self.media_proc = proc

        def _watch_media() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                clean = line.rstrip()
                if clean:
                    self._log(clean, media=True)
            code = proc.wait()
            with self.lock:
                if self.media_proc is proc:
                    self.media_proc = None
                if self.media_job is not None:
                    self.media_job["returncode"] = code
                    self.media_job["finished_at"] = time.time()
                    if self.media_job["status"] == "running":
                        self.media_job["status"] = "done" if code == 0 else "error"
                if self.owner == "media":
                    self.owner = "idle"
            self._log(f"[Arbiter] Uretim tamamlandi (kod={code}) — GPU tekrar bosta.", media=True)
            if was_coding and self.cfg.get("auto_resume_coding_after_media"):
                self.start_coding(self.coding_model)

        threading.Thread(target=_watch_media, daemon=True).start()
        return True, f"Uretim baslatildi: {out_file.name}", str(out_file)

    def list_media_outputs(self, limit: int = 24) -> list[dict[str, Any]]:
        out_dir = self.picovid_dir / "outputs"
        if not out_dir.exists():
            return []
        files = [f for f in out_dir.iterdir() if f.is_file() and f.suffix.lower() in (".mp4", ".png", ".jpg", ".webp")]
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return [
            {
                "name": f.name,
                "kind": "video" if f.suffix.lower() == ".mp4" else "image",
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "mtime": int(f.stat().st_mtime),
            }
            for f in files[:limit]
        ]

    # ---------- Status snapshot ----------

    def get_status(self) -> dict[str, Any]:
        ded_m, shr_m = (None, None)
        ram_tot, ram_avail = (None, None)
        if self._picocode_probe is not None:
            try:
                ded_m, shr_m = self._picocode_probe.probe_live_vram_mib()
                ram_tot, ram_avail = self._picocode_probe.probe_ram_gib()
            except Exception:
                pass
        with self.lock:
            return {
                "owner": self.owner,
                "coding_model": self.coding_model,
                "api_base": f"http://{self.llm_host}:{self.llm_port}/v1",
                "last_error": self.last_error,
                "coding_logs": self.logs[-30:],
                "media_job": dict(self.media_job) if self.media_job else None,
                "media_logs": self.media_logs[-40:],
                "hardware": {
                    "gpu_name": self.hw_base.get("gpu_name", "GPU"),
                    "backend": self.hw_base.get("backend", "vulkan"),
                    "vram_total_gib": self.hw_base.get("vram_total_gib", 6.0),
                    "vram_used_ded_gib": round(ded_m / 1024.0, 2) if ded_m is not None else None,
                    "vram_used_shr_gib": round(shr_m / 1024.0, 2) if shr_m is not None else None,
                    "ram_total_gib": ram_tot,
                    "ram_used_gib": round(max(0.0, (ram_tot or 0) - (ram_avail or 0)), 2) if ram_tot and ram_avail else None,
                },
            }
