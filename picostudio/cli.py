#!/usr/bin/env python3
"""
PicoStudio Unified Developer CLI (IDE + Interactive Terminal Agent + Video/Image Launcher).

Commands:
  picostudio ide [--port 7900] [--dir <path>] [--no-browser]
  picostudio status
  picostudio chat [--dir <path>] [--mode fast|think]
  picostudio ask "<prompt>" [--file path.py] [--mode fast|think]
  picostudio video "<prompt>" [--engine 5b|14b] [--cinema-hd] [--fast-preview]
  picostudio image "<prompt>"

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

STUDIO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(STUDIO_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_ROOT))

from picostudio.arbiter import GPUArbiter, load_config
from picostudio.web_ide import run_ide


def configure_utf8() -> None:
    for name in ("stdout", "stderr"):
        st = getattr(sys, name, None)
        if st is not None and hasattr(st, "reconfigure"):
            try:
                st.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def stream_chat_once(arbiter: GPUArbiter, messages: list[dict], mode: str = "fast") -> str:
    sys_msg = {"role": "system", "content": "You are PicoStudio, a concise senior software engineer running locally."}
    full_msgs = [sys_msg] + messages
    if mode == "fast" and "inkling" in (arbiter.coding_model or "").lower():
        full_msgs.append({"role": "assistant", "content": "Here is the answer:\n"})

    payload = {
        "model": arbiter.coding_model,
        "messages": full_msgs,
        "temperature": 0.3,
        "max_tokens": 2048,
        "stream": True,
    }
    req = urllib.request.Request(
        f"http://{arbiter.llm_host}:{arbiter.llm_port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    out: list[str] = []
    with urllib.request.urlopen(req, timeout=360) as resp:
        for raw in resp:
            ln = raw.decode("utf-8", errors="replace").strip()
            if not ln.startswith("data:"):
                continue
            ds = ln[5:].strip()
            if not ds or ds == "[DONE]":
                continue
            ev = json.loads(ds)
            ch = ev.get("choices") or []
            if ch:
                tok = (ch[0].get("delta") or {}).get("content")
                if tok:
                    print(tok, end="", flush=True)
                    out.append(tok)
    print()
    return "".join(out)


def cmd_status(arbiter: GPUArbiter) -> int:
    st = arbiter.get_status()
    inv = arbiter.get_inventory()
    hw = st["hardware"]
    print("\n================ PicoStudio Status ================")
    print(f"  GPU           : {hw['gpu_name']} ({hw['backend'].upper()}, {hw['vram_total_gib']:.1f} GiB)")
    if hw.get("vram_used_ded_gib") is not None:
        print(f"  Live VRAM     : {hw['vram_used_ded_gib']:.2f} / {hw['vram_total_gib']:.1f} GiB (Shared: {hw.get('vram_used_shr_gib') or 0:.2f} GiB)")
    if hw.get("ram_total_gib") is not None:
        print(f"  System RAM    : {hw.get('ram_used_gib') or 0:.1f} / {hw['ram_total_gib']:.1f} GiB")
    print("\n  [Coding Models — PicoCode]")
    for m in inv["coding_models"]:
        tag = "READY" if m["installed"] else "MISS"
        print(f"    [{tag:5s}] {m['id']:18s} ({m['size_gib']:.2f} GiB) — {m['label']}")
    print("\n  [Video & Image Models — PicoVid]")
    for m in inv["media_models"]:
        tag = "READY" if m["installed"] else "MISS"
        print(f"    [{tag:5s}] {m['id']:18s} — {m['label']}")
    print("===================================================\n")
    return 0


def cmd_media(arbiter: GPUArbiter, prompt: str, engine: str, mode: str, cinema_hd: bool, fast_preview: bool) -> int:
    w, h, f = (1024, 1024, 1) if mode == "t2i" else ((640, 384, 33) if engine == "14b" else (640, 384, 81))
    ok, msg, out_path = arbiter.start_media(
        prompt=prompt, engine=engine, mode=mode, width=w, height=h, frames=f,
        cinema_hd=cinema_hd, fast_preview=fast_preview,
    )
    if not ok:
        print(f"ERROR: {msg}", file=sys.stderr)
        return 1
    print(f"[PicoStudio] {msg}", flush=True)
    seen = 0
    try:
        while True:
            st = arbiter.get_status()
            logs = st["media_logs"]
            for ln in logs[seen:]:
                print(ln, flush=True)
            seen = len(logs)
            job = st.get("media_job") or {}
            if job.get("status") in ("done", "error", "stopped"):
                print(f"[PicoStudio] Finished ({job['status']}) -> {out_path}")
                return 0 if job.get("status") == "done" else 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        arbiter.stop_media()
        return 130


def cmd_chat(arbiter: GPUArbiter, work_dir: pathlib.Path, mode: str) -> int:
    print(f"[PicoStudio CLI] Working directory: {work_dir} | Mode: {mode}")
    print("[PicoStudio CLI] Loading coding model...")
    ok, msg = arbiter.start_coding(wait_ready=True)
    if not ok:
        print(f"ERROR: {msg}", file=sys.stderr)
        return 1
    print(f"[READY] Commands: /file <path> | /run <cmd> | /video <prompt> | /image <prompt> | /mode fast|think | /exit\n")
    history: list[dict] = []
    attached_ctx = ""
    try:
        while True:
            try:
                user_in = input("you> ").strip()
            except EOFError:
                break
            if not user_in:
                continue
            if user_in in ("/exit", "/quit"):
                break
            if user_in.startswith("/mode "):
                m = user_in.split(maxsplit=1)[1].strip().lower()
                if m in ("fast", "think"):
                    mode = m
                    print(f"[Mode switched -> {mode}]")
                continue
            if user_in.startswith("/file "):
                rel = user_in[6:].strip()
                fp = (work_dir / rel).resolve()
                if not fp.exists():
                    print(f"[ERROR] File not found: {fp}")
                    continue
                attached_ctx = f"File `{rel}`:\n```\n{fp.read_text(encoding='utf-8', errors='replace')[:12000]}\n```\n\n"
                print(f"[Attached] {rel} ({fp.stat().st_size} bytes)")
                continue
            if user_in.startswith("/run "):
                sh = user_in[5:].strip()
                res = subprocess.run(["powershell", "-NoProfile", "-Command", sh], cwd=str(work_dir))
                print(f"[exit code: {res.returncode}]")
                continue
            if user_in.startswith("/video "):
                cmd_media(arbiter, user_in[7:].strip(), engine="5b", mode="t2v", cinema_hd=True, fast_preview=False)
                print("[PicoStudio] Reloading coding model...")
                arbiter.start_coding(wait_ready=True)
                continue
            if user_in.startswith("/image "):
                cmd_media(arbiter, user_in[7:].strip(), engine="5b", mode="t2i", cinema_hd=False, fast_preview=False)
                print("[PicoStudio] Reloading coding model...")
                arbiter.start_coding(wait_ready=True)
                continue

            prompt = attached_ctx + user_in
            attached_ctx = ""
            history.append({"role": "user", "content": prompt})
            print("ai> ", end="", flush=True)
            reply = stream_chat_once(arbiter, history, mode=mode)
            history.append({"role": "assistant", "content": reply})
    finally:
        arbiter.stop_all()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="picostudio", description="PicoStudio — Local IDE, Terminal Agent & Video/Image Studio")
    sub = p.add_subparsers(dest="cmd")

    p_ide = sub.add_parser("ide", help="Launch PicoStudio Local Web IDE (http://127.0.0.1:7900)")
    p_ide.add_argument("--host", default=None)
    p_ide.add_argument("--port", type=int, default=None)
    p_ide.add_argument("--dir", default=None, help="Initial workspace folder")
    p_ide.add_argument("--no-browser", action="store_true")

    sub.add_parser("status", help="Show GPU/VRAM telemetry and installed Coding + Video models")

    p_chat = sub.add_parser("chat", help="Interactive terminal coding + video agent")
    p_chat.add_argument("--dir", default=None)
    p_chat.add_argument("--mode", choices=["fast", "think"], default="fast")

    p_ask = sub.add_parser("ask", help="One-shot coding question in terminal")
    p_ask.add_argument("prompt", help="Coding prompt")
    p_ask.add_argument("--file", default=None, help="Optional file context")
    p_ask.add_argument("--mode", choices=["fast", "think"], default="fast")

    p_vid = sub.add_parser("video", help="Generate video via PicoVid (auto-frees coding VRAM)")
    p_vid.add_argument("prompt", help="Video scene prompt")
    p_vid.add_argument("--engine", choices=["5b", "14b"], default="5b")
    p_vid.add_argument("--cinema-hd", action="store_true", default=True)
    p_vid.add_argument("--no-cinema-hd", dest="cinema_hd", action="store_false")
    p_vid.add_argument("--fast-preview", action="store_true")

    p_img = sub.add_parser("image", help="Generate image via Z-Image-Turbo (auto-frees coding VRAM)")
    p_img.add_argument("prompt", help="Image prompt")
    return p


def main(argv: list[str] | None = None) -> int:
    configure_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config()

    if not args.cmd or args.cmd == "ide":
        return run_ide(
            host=getattr(args, "host", None),
            port=getattr(args, "port", None),
            workspace_dir=getattr(args, "dir", None),
            open_browser=not getattr(args, "no_browser", False),
        )

    arbiter = GPUArbiter(cfg)
    if args.cmd == "status":
        return cmd_status(arbiter)
    if args.cmd == "chat":
        wdir = pathlib.Path(args.dir or cfg.get("default_workspace") or pathlib.Path.cwd()).resolve()
        return cmd_chat(arbiter, wdir, mode=args.mode)
    if args.cmd == "ask":
        ok, msg = arbiter.start_coding(wait_ready=True)
        if not ok:
            print(f"ERROR: {msg}", file=sys.stderr)
            return 1
        try:
            ctx = ""
            if args.file:
                fp = pathlib.Path(args.file)
                ctx = f"File `{fp.name}`:\n```\n{fp.read_text(encoding='utf-8', errors='replace')[:12000]}\n```\n\n"
            stream_chat_once(arbiter, [{"role": "user", "content": ctx + args.prompt}], mode=args.mode)
            return 0
        finally:
            arbiter.stop_all()
    if args.cmd == "video":
        return cmd_media(arbiter, args.prompt, engine=args.engine, mode="t2v", cinema_hd=args.cinema_hd, fast_preview=args.fast_preview)
    if args.cmd == "image":
        return cmd_media(arbiter, args.prompt, engine="5b", mode="t2i", cinema_hd=False, fast_preview=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
