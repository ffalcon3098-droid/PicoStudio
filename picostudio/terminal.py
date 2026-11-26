"""
PicoStudio Embedded Terminal Runner.

Executes PowerShell / shell commands inside the active workspace directory with
persistent `cd` tracking, live buffered output polling, and clean process cancellation.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import threading
import time
from typing import Any


class TerminalSession:
    def __init__(self, cwd: str | pathlib.Path) -> None:
        self.cwd = pathlib.Path(cwd).resolve()
        self.lock = threading.Lock()
        self.proc: subprocess.Popen[str] | None = None
        self.running: bool = False
        self.last_exit: int | None = None
        self.output: list[str] = [f"[PicoStudio Terminal] Calisma dizini: {self.cwd}"]

    def set_cwd(self, cwd: str | pathlib.Path) -> None:
        with self.lock:
            self.cwd = pathlib.Path(cwd).resolve()
            self.output.append(f"$ cd {self.cwd}")

    def clear(self) -> None:
        with self.lock:
            self.output = [f"[PicoStudio Terminal] {self.cwd}"]

    def stop(self) -> bool:
        with self.lock:
            proc = self.proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
            with self.lock:
                self.output.append("[Durduruldu]")
                self.running = False
            return True
        return False

    def run_command(self, command: str) -> tuple[bool, str]:
        cmd = (command or "").strip()
        if not cmd:
            return False, "Bos komut."

        # Handle built-in `cd <dir>` so working directory persists cleanly across commands
        if cmd.lower().startswith("cd "):
            target_raw = cmd[3:].strip().strip('"').strip("'")
            target = (self.cwd / target_raw).resolve() if not pathlib.Path(target_raw).is_absolute() else pathlib.Path(target_raw).resolve()
            if target.exists() and target.is_dir():
                self.set_cwd(target)
                return True, str(target)
            with self.lock:
                self.output.append(f"$ {cmd}")
                self.output.append(f"HATA: Dizin bulunamadi: {target}")
            return False, f"Dizin bulunamadi: {target}"

        with self.lock:
            if self.running and self.proc is not None and self.proc.poll() is None:
                return False, "Onceki komut hala calisiyor — once Durdur tusuna basin."
            self.running = True
            self.last_exit = None
            self.output.append(f"PS {self.cwd}> {cmd}")
            cwd_str = str(self.cwd)

        shell_cmd = (
            ["powershell", "-NoProfile", "-Command", cmd]
            if os.name == "nt"
            else ["/bin/sh", "-c", cmd]
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        proc = subprocess.Popen(
            shell_cmd,
            cwd=cwd_str,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=flags,
        )
        with self.lock:
            self.proc = proc

        def _drain() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                with self.lock:
                    self.output.append(line.rstrip("\r\n"))
                    if len(self.output) > 600:
                        self.output = self.output[-600:]
            code = proc.wait()
            with self.lock:
                self.last_exit = code
                self.running = False
                if self.proc is proc:
                    self.proc = None
                self.output.append(f"[cikis kodu: {code}]")

        threading.Thread(target=_drain, daemon=True).start()
        return True, "Baslatildi"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "cwd": str(self.cwd),
                "running": self.running,
                "last_exit": self.last_exit,
                "lines": self.output[-250:],
            }
