"""
PicoStudio Terminal Pro Engine (v0.3.0).

Features:
  - Multi-tab terminal sessions (run dev server in Tab 1 while running tests/git in Tab 2)
  - Real-time zero-lag SSE output streaming via Condition sequence notifications
  - Interactive `stdin` piping (answer y/n prompts, Python input(), REPLs live)
  - Persistent `cd` working-directory tracking & `Tab` file/folder autocompletion
  - ANSI color preservation (FORCE_COLOR=1) & clean Windows process-tree kill (taskkill /T /F)

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import threading
import time
from typing import Any, Iterator


class TerminalSession:
    def __init__(self, session_id: str, name: str, cwd: str | pathlib.Path) -> None:
        self.id = session_id
        self.name = name
        self.cwd = pathlib.Path(cwd).resolve()
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.proc: subprocess.Popen[str] | None = None
        self.running: bool = False
        self.last_exit: int | None = None
        self.history: list[str] = []
        self._seq: int = 0
        self._entries: list[tuple[int, str]] = []
        self._emit(f"\x1b[36m[PicoStudio Terminal · {self.name}]\x1b[0m {self.cwd}")

    def _emit(self, line: str) -> None:
        """Append one output line and wake all live SSE subscribers immediately."""
        with self.cond:
            self._seq += 1
            self._entries.append((self._seq, line))
            if len(self._entries) > 800:
                self._entries = self._entries[-800:]
            self.cond.notify_all()

    def set_cwd(self, cwd: str | pathlib.Path) -> None:
        resolved = pathlib.Path(cwd).resolve()
        with self.lock:
            self.cwd = resolved
        self._emit(f"\x1b[36m$ cd {resolved}\x1b[0m")

    def clear(self) -> None:
        with self.cond:
            self._entries = []
            self._seq += 1
            self._entries.append((self._seq, f"\x1b[36m[Temizlendi]\x1b[0m {self.cwd}"))
            self.cond.notify_all()

    def stop(self) -> bool:
        with self.lock:
            proc = self.proc
        if proc is not None and proc.poll() is None:
            if os.name == "nt":
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
            else:
                proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
            with self.cond:
                self.running = False
                self.proc = None
                self.cond.notify_all()
            self._emit("\x1b[33m[İşlem durduruldu]\x1b[0m")
            return True
        return False

    def send_input(self, text: str) -> tuple[bool, str]:
        """Deliver interactive stdin line to the currently running child process."""
        with self.lock:
            proc = self.proc
            is_running = self.running and proc is not None and proc.poll() is None
        if not is_running or proc is None or proc.stdin is None:
            return False, "Aktif çalışan bir işlem yok."
        try:
            payload = text if text.endswith("\n") else (text + "\n")
            proc.stdin.write(payload)
            proc.stdin.flush()
            self._emit(f"\x1b[90m› {text.rstrip()}\x1b[0m")
            return True, "Gönderildi"
        except Exception as exc:
            return False, str(exc)

    def complete_path(self, line: str) -> dict[str, Any]:
        """Tab-complete the last token against files/directories in self.cwd."""
        raw = line or ""
        parts = raw.rsplit(" ", 1)
        prefix = parts[-1] if parts else ""
        head = (parts[0] + " ") if len(parts) == 2 else ""

        norm = prefix.replace("\\", "/")
        if "/" in norm:
            dir_part, name_part = norm.rsplit("/", 1)
            search_dir = (self.cwd / dir_part).resolve() if not pathlib.Path(dir_part).is_absolute() else pathlib.Path(dir_part).resolve()
            lead = dir_part + "/"
        else:
            search_dir = self.cwd
            name_part = norm
            lead = ""

        matches: list[str] = []
        if search_dir.exists() and search_dir.is_dir():
            low = name_part.lower()
            try:
                for entry in sorted(search_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    if entry.name.lower().startswith(low):
                        suffix = "/" if entry.is_dir() else ""
                        cand = f"{lead}{entry.name}{suffix}"
                        if " " in cand:
                            cand = f'"{cand}"'
                        matches.append(cand)
                        if len(matches) >= 25:
                            break
            except OSError:
                pass

        if not matches:
            return {"completed": raw, "matches": []}
        if len(matches) == 1:
            return {"completed": head + matches[0], "matches": matches}
        common = os.path.commonprefix(matches)
        completed = (head + common) if len(common) > len(prefix) else raw
        return {"completed": completed, "matches": matches}

    def run_command(self, command: str) -> tuple[bool, str]:
        cmd = (command or "").strip()
        if not cmd:
            return False, "Boş komut."

        with self.lock:
            if not self.history or self.history[-1] != cmd:
                self.history.append(cmd)
                if len(self.history) > 150:
                    self.history = self.history[-150:]

        # Built-in persistent `cd`
        if cmd.lower() == "cd":
            self._emit(str(self.cwd))
            return True, str(self.cwd)
        if cmd.lower().startswith("cd "):
            target_raw = cmd[3:].strip().strip('"').strip("'")
            target = (self.cwd / target_raw).resolve() if not pathlib.Path(target_raw).is_absolute() else pathlib.Path(target_raw).resolve()
            if target.exists() and target.is_dir():
                self.set_cwd(target)
                return True, str(target)
            self._emit(f"\x1b[36mPS {self.cwd}>\x1b[0m {cmd}")
            self._emit(f"\x1b[31mHATA: Dizin bulunamadı: {target}\x1b[0m")
            return False, f"Dizin bulunamadı: {target}"

        if cmd.lower() in ("cls", "clear"):
            self.clear()
            return True, "Temizlendi"

        with self.lock:
            if self.running and self.proc is not None and self.proc.poll() is None:
                return False, "Önceki komut hâlâ çalışıyor — girdi gönderebilir veya Durdur'a basabilirsiniz."
            self.running = True
            self.last_exit = None
            cwd_str = str(self.cwd)

        self._emit(f"\x1b[36mPS {cwd_str}>\x1b[0m \x1b[1m{cmd}\x1b[0m")

        shell_cmd = (
            ["powershell", "-NoProfile", "-Command", cmd]
            if os.name == "nt"
            else ["/bin/sh", "-c", cmd]
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["FORCE_COLOR"] = "1"
        env["CLICOLOR_FORCE"] = "1"
        env["TERM"] = "xterm-256color"

        proc = subprocess.Popen(
            shell_cmd,
            cwd=cwd_str,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=flags,
        )
        with self.cond:
            self.proc = proc
            self.cond.notify_all()

        def _drain() -> None:
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    self._emit(line.rstrip("\r\n"))
            finally:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass
            code = proc.wait()
            with self.cond:
                self.last_exit = code
                self.running = False
                if self.proc is proc:
                    self.proc = None
                self.cond.notify_all()
            color = "\x1b[32m" if code == 0 else "\x1b[31m"
            self._emit(f"{color}[çıkış kodu: {code}]\x1b[0m")

        threading.Thread(target=_drain, daemon=True).start()
        return True, "Başlatıldı"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "name": self.name,
                "cwd": str(self.cwd),
                "running": self.running,
                "last_exit": self.last_exit,
                "seq": self._seq,
                "history": list(self.history[-50:]),
                "lines": [txt for _, txt in self._entries[-300:]],
            }

    def subscribe(self, after_seq: int = 0, heartbeat_s: float = 4.0) -> Iterator[dict[str, Any]]:
        """Yield incremental live events as soon as output or state changes."""
        cursor = int(after_seq)
        last_running: bool | None = None
        last_cwd: str | None = None
        while True:
            with self.cond:
                new_items = [(s, txt) for s, txt in self._entries if s > cursor]
                cur_running = self.running
                cur_cwd = str(self.cwd)
                cur_exit = self.last_exit
                if not new_items and cur_running == last_running and cur_cwd == last_cwd:
                    self.cond.wait(timeout=heartbeat_s)
                    new_items = [(s, txt) for s, txt in self._entries if s > cursor]
                    cur_running = self.running
                    cur_cwd = str(self.cwd)
                    cur_exit = self.last_exit

            if new_items:
                cursor = new_items[-1][0]
                last_running = cur_running
                last_cwd = cur_cwd
                yield {
                    "type": "output",
                    "seq": cursor,
                    "lines": [txt for _, txt in new_items],
                    "running": cur_running,
                    "cwd": cur_cwd,
                    "last_exit": cur_exit,
                }
            elif cur_running != last_running or cur_cwd != last_cwd:
                last_running = cur_running
                last_cwd = cur_cwd
                yield {
                    "type": "state",
                    "seq": cursor,
                    "running": cur_running,
                    "cwd": cur_cwd,
                    "last_exit": cur_exit,
                }
            else:
                yield {"type": "ping", "seq": cursor}


class TerminalManager:
    """Manages multiple concurrent TerminalSession tabs for PicoStudio IDE."""

    def __init__(self, default_cwd: str | pathlib.Path) -> None:
        self.default_cwd = pathlib.Path(default_cwd).resolve()
        self.lock = threading.Lock()
        self._counter = 0
        self.sessions: dict[str, TerminalSession] = {}
        self.active_id: str = self.create_session("Terminal 1").id

    def create_session(self, name: str | None = None, cwd: str | pathlib.Path | None = None) -> TerminalSession:
        with self.lock:
            self._counter += 1
            sid = f"term-{self._counter}"
            sname = name or f"Terminal {self._counter}"
            sess = TerminalSession(sid, sname, cwd or self.default_cwd)
            self.sessions[sid] = sess
            self.active_id = sid
            return sess

    def get(self, sid: str | None = None) -> TerminalSession:
        with self.lock:
            if sid and sid in self.sessions:
                return self.sessions[sid]
            if self.active_id in self.sessions:
                return self.sessions[self.active_id]
            first = next(iter(self.sessions.values()))
            self.active_id = first.id
            return first

    def close_session(self, sid: str) -> bool:
        with self.lock:
            sess = self.sessions.get(sid)
            if sess is None:
                return False
            if len(self.sessions) <= 1:
                # Reset instead of deleting the last tab
                sess.stop()
                sess.clear()
                return True
            del self.sessions[sid]
            if self.active_id == sid:
                self.active_id = next(iter(self.sessions.keys()))
        sess.stop()
        return True

    def set_cwd_all(self, new_cwd: str | pathlib.Path) -> None:
        resolved = pathlib.Path(new_cwd).resolve()
        with self.lock:
            self.default_cwd = resolved
            sessions = list(self.sessions.values())
        for s in sessions:
            if not s.running:
                s.set_cwd(resolved)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.lock:
            sessions = list(self.sessions.values())
            active = self.active_id
        out = []
        for s in sessions:
            snap = s.snapshot()
            out.append({
                "id": s.id,
                "name": s.name,
                "cwd": snap["cwd"],
                "running": snap["running"],
                "last_exit": snap["last_exit"],
                "active": s.id == active,
            })
        return out

    def stop_all(self) -> None:
        with self.lock:
            sessions = list(self.sessions.values())
        for s in sessions:
            s.stop()
