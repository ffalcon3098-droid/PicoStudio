"""
PicoStudio Hardened Local Web IDE Server (v0.7.0).

Clean modular server backed by static assets in `picostudio/static/`:
  - Security Shield: Strict localhost Host check (DNS rebinding guard), per-session CSRF token
    (`X-PicoStudio-Token`), Same-Origin check & strict `application/json` enforcement on all POSTs.
  - Modular UI served from `static/index.html`, `static/style.css`, `static/app.js`.
  - Unified LLM helpers (`arbiter.chat_complete` & native `/infill` FIM) + server-side agent abort.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import difflib
import json
import mimetypes
import pathlib
import re
import secrets
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from picostudio import diagnostics, git_ops, symbols
from picostudio.agent import run_agent_stream
from picostudio.arbiter import GPUArbiter, load_config
from picostudio.sessions import ChatSessionStore
from picostudio.terminal import TerminalManager, TerminalSession
from picostudio.workspace import Workspace

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _is_local_origin(origin: str) -> bool:
    if not origin:
        return True
    try:
        u = urllib.parse.urlparse(origin)
        return u.scheme in ("http", "https") and (u.hostname in ("127.0.0.1", "localhost", "::1"))
    except Exception:
        return False


def _strip_code_fence(txt: str) -> str:
    m_blk = re.search(r"```[A-Za-z0-9_+-]*\n([\s\S]*?)```", txt)
    return m_blk.group(1).rstrip("\r\n") if m_blk else txt


def make_handler(
    arbiter: GPUArbiter,
    ws: Workspace,
    term_mgr: TerminalManager | TerminalSession,
    chat_store: ChatSessionStore | None = None,
    csrf_token: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    if isinstance(term_mgr, TerminalSession):
        mgr = TerminalManager(term_mgr.cwd)
        mgr.sessions = {term_mgr.id: term_mgr}
        mgr.active_id = term_mgr.id
        term_mgr = mgr
    if chat_store is None:
        chat_store = ChatSessionStore(pathlib.Path(__file__).resolve().parent.parent / "data" / "chats")

    session_csrf = csrf_token or secrets.token_urlsafe(24)
    active_cancels: dict[str, threading.Event] = {}
    cancels_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        csrf_token = session_csrf

        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _json(self, data: Any, status: int = 200) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def _check_host(self) -> bool:
            host_hdr = (self.headers.get("Host") or "").strip().lower()
            if not host_hdr:
                return True
            host_only = host_hdr.rsplit(":", 1)[0] if not host_hdr.startswith("[") else host_hdr.split("]")[0] + "]"
            return host_only in _ALLOWED_HOSTS

        def _check_post_security(self) -> tuple[bool, str]:
            if not self._check_host():
                return False, "Gecersiz Host basligi (DNS rebinding engellendi)."
            origin = (self.headers.get("Origin") or "").strip()
            if origin and not _is_local_origin(origin):
                return False, "Harici Origin engellendi."
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "application/json" not in ctype:
                return False, "Content-Type application/json zorunludur."
            tok = (self.headers.get("X-PicoStudio-Token") or "").strip()
            if not secrets.compare_digest(tok, session_csrf):
                return False, "Gecersiz veya eksik CSRF token (X-PicoStudio-Token)."
            return True, ""

        def _body_json(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(n) if n > 0 else b"{}"
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                return {}

        def _serve_static(self, filename: str, ctype: str, inject_csrf: bool = False) -> None:
            fp = STATIC_DIR / filename
            if not fp.is_file():
                self._json({"error": f"Static asset missing: {filename}"}, status=404)
                return
            if inject_csrf:
                text = fp.read_text(encoding="utf-8").replace("__PS_CSRF__", session_csrf)
                raw = text.encode("utf-8")
            else:
                raw = fp.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if not self._check_host():
                self._json({"error": "Invalid Host header"}, status=403)
                return
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = dict(urllib.parse.parse_qsl(parsed.query))

            if path in ("/", "/index.html"):
                self._serve_static("index.html", "text/html; charset=utf-8", inject_csrf=True)
                return
            if path == "/static/style.css":
                self._serve_static("style.css", "text/css; charset=utf-8")
                return
            if path == "/static/app.js":
                self._serve_static("app.js", "application/javascript; charset=utf-8")
                return

            if path == "/api/status":
                self._json(arbiter.get_status())
                return
            if path == "/api/inventory":
                self._json(arbiter.get_inventory())
                return
            if path == "/api/workspace/projects":
                self._json({"current": str(ws.root), "projects": ws.list_projects()})
                return
            if path == "/api/workspace/tree":
                self._json({"root": str(ws.root), "items": ws.list_tree()})
                return
            if path == "/api/workspace/file":
                try:
                    self._json(ws.read_file(qs.get("path", "")))
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                except Exception as exc:
                    self._json({"error": str(exc)}, status=404)
                return
            if path == "/api/workspace/search":
                self._json({"hits": ws.search(qs.get("q", ""))})
                return
            if path == "/api/workspace/symbols":
                exact = qs.get("exact") in ("1", "true", "True")
                self._json({"symbols": symbols.search_workspace_symbols(ws, qs.get("q", ""), exact=exact)})
                return
            if path == "/api/git/status":
                self._json(git_ops.get_status(ws))
                return
            if path == "/api/git/diff":
                try:
                    self._json(git_ops.get_diff(ws, qs.get("path", ""), staged=(qs.get("staged") in ("1", "true", "True"))))
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/git/log":
                self._json(git_ops.get_log(ws, limit=int(qs.get("limit", "12") or "12")))
                return
            if path == "/api/chat/sessions":
                self._json({"sessions": chat_store.list_sessions(ws.root)})
                return
            if path == "/api/chat/session":
                rec = chat_store.load_session(ws.root, qs.get("id", ""))
                self._json(rec if rec else {"error": "Sohbet bulunamadi"}, status=200 if rec else 404)
                return
            if path == "/api/terminal/sessions":
                self._json({"sessions": term_mgr.list_sessions()})
                return
            if path == "/api/terminal/status":
                self._json(term_mgr.get(qs.get("id")).snapshot())
                return
            if path == "/api/terminal/stream":
                sess = term_mgr.get(qs.get("id"))
                after = int(qs.get("after", "0") or "0")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for ev in sess.subscribe(after_seq=after, heartbeat_s=4.0):
                        chunk = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8")
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
                return
            if path == "/api/media/outputs":
                self._json(arbiter.list_media_outputs())
                return
            if path == "/api/media/file":
                out_root = (arbiter.picovid_dir / "outputs").resolve()
                rel_name = qs.get("name", "").lstrip("/\\")
                fpath = (out_root / rel_name).resolve()
                try:
                    fpath.relative_to(out_root)
                except ValueError:
                    self._json({"error": "Yetkisiz yol"}, status=403)
                    return
                if not fpath.exists() or not fpath.is_file():
                    self._json({"error": "Bulunamadi"}, status=404)
                    return
                data = fpath.read_bytes()
                ctype = mimetypes.guess_type(fpath.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            self._json({"error": "Not found"}, status=404)

        def do_POST(self) -> None:
            ok_sec, sec_err = self._check_post_security()
            if not ok_sec:
                self._json({"error": sec_err}, status=403)
                return

            path = urllib.parse.urlparse(self.path).path
            body = self._body_json()

            # ---- Workspace ----
            if path == "/api/workspace/select":
                try:
                    new_root = ws.set_root(str(body.get("path") or ""))
                    term_mgr.set_cwd_all(new_root)
                    self._json({"ok": True, "root": str(new_root)})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return
            if path == "/api/workspace/create-project":
                try:
                    new_root = ws.create_project(str(body.get("path") or ""))
                    term_mgr.set_cwd_all(new_root)
                    self._json({"ok": True, "root": str(new_root)})
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return
            if path == "/api/workspace/file":
                try:
                    content = str(body.get("content") or "")
                    res = ws.write_file(str(body.get("path") or ""), content)
                    diags = diagnostics.check_syntax(res["path"], content)
                    self._json({"ok": True, **res, "diagnostics": diags})
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return
            if path == "/api/workspace/delete":
                try:
                    ok = ws.delete_file(str(body.get("path") or ""))
                    self._json({"ok": ok}, status=200 if ok else 404)
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/workspace/undo":
                try:
                    res = ws.undo_edit(str(body.get("undo_id") or ""))
                    self._json({"ok": True, **res})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return
            if path == "/api/workspace/undo-batch":
                try:
                    raw_ids = [str(x) for x in (body.get("undo_ids") or []) if x]
                    res = ws.undo_batch(raw_ids)
                    self._json({"ok": True, **res})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return
            if path == "/api/workspace/replace":
                res = ws.replace_in_project(
                    str(body.get("query") or ""),
                    str(body.get("replacement") or ""),
                    dry_run=bool(body.get("dry_run", True)),
                )
                self._json(res, status=200 if res.get("ok") else 400)
                return

            # ---- Editor Intelligence ----
            if path == "/api/editor/check":
                self._json({"diagnostics": diagnostics.check_syntax(str(body.get("path") or ""), str(body.get("content") or ""))})
                return
            if path == "/api/editor/symbols":
                self._json({"symbols": symbols.extract_file_symbols(str(body.get("path") or ""), str(body.get("content") or ""))})
                return
            if path == "/api/editor/complete":
                rel_p = str(body.get("path") or "code.py")
                ok, code, txt = arbiter.infill_complete(
                    str(body.get("prefix") or ""),
                    str(body.get("suffix") or ""),
                    rel_path=rel_p,
                    max_tokens=160,
                )
                if not ok:
                    self._json({"error": txt}, status=code)
                    return
                self._json({"completion": _strip_code_fence(txt)})
                return
            if path == "/api/editor/inline-edit":
                rel_p = str(body.get("path") or "file.py")
                full_content = str(body.get("content") or "")
                selection = str(body.get("selection") or "")
                instruction = str(body.get("instruction") or "").strip()
                target_code = selection if selection else full_content
                scope_note = "ONLY the selected snippet" if selection else "the complete updated file"
                ok, code, txt = arbiter.chat_complete(
                    [
                        {
                            "role": "system",
                            "content": (
                                f"You are an expert inline code editor working on `{rel_p}`. "
                                f"Apply the user's edit instruction to {scope_note}. "
                                "Output ONLY the exact replacement code — NO explanations, NO markdown fences."
                            ),
                        },
                        {"role": "user", "content": f"Instruction: {instruction}\n\nCode to replace:\n```\n{target_code[:4500]}\n```"},
                    ],
                    temperature=0.15,
                    max_tokens=1200,
                    timeout=120,
                )
                if not ok:
                    self._json({"error": txt}, status=code)
                    return
                rep = _strip_code_fence(txt)
                diff_lines = list(difflib.unified_diff(
                    target_code.splitlines(), rep.splitlines(),
                    fromfile=f"a/{rel_p}", tofile=f"b/{rel_p}", n=2, lineterm="",
                ))
                added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
                removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))
                self._json({"replacement": rep, "diff": "\n".join(diff_lines[:120]), "added": added, "removed": removed})
                return

            # ---- Chat Sessions ----
            if path == "/api/chat/sessions/save":
                meta = chat_store.save_session(
                    ws.root,
                    list(body.get("messages") or []),
                    session_id=body.get("id"),
                    title=body.get("title"),
                )
                self._json({"ok": True, **meta})
                return
            if path == "/api/chat/sessions/delete":
                self._json({"ok": chat_store.delete_session(ws.root, str(body.get("id") or ""))})
                return

            # ---- Git & Diff ----
            if path == "/api/git/stage":
                try:
                    ok, msg = git_ops.stage_path(ws, body.get("path"))
                    self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/git/unstage":
                try:
                    ok, msg = git_ops.unstage_path(ws, body.get("path"))
                    self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/git/revert":
                try:
                    ok, msg = git_ops.revert_path(ws, str(body.get("path") or ""))
                    self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/git/commit":
                res = git_ops.commit_changes(ws, str(body.get("message") or ""))
                self._json(res, status=200 if res.get("ok") else 400)
                return
            if path == "/api/git/ai-message":
                diff_info = git_ops.get_diff(ws, "", staged=True)
                if not diff_info.get("raw"):
                    diff_info = git_ops.get_diff(ws, "", staged=False)
                raw_diff = (diff_info.get("raw") or "")[:3200]
                if not raw_diff:
                    self._json({"error": "Diff bos; once bir degisiklik yapin."}, status=400)
                    return
                ok, code, txt = arbiter.chat_complete(
                    [
                        {"role": "system", "content": "Write ONE concise Conventional Commit message line (e.g. 'feat: add syntax highlighting') for the git diff below. Output ONLY the single line, no quotes or markdown."},
                        {"role": "user", "content": raw_diff},
                    ],
                    temperature=0.2,
                    max_tokens=60,
                )
                if not ok:
                    self._json({"error": txt}, status=code)
                    return
                self._json({"message": txt.splitlines()[0].strip("`\"' ") if txt else ""})
                return

            # ---- Terminal Pro ----
            if path == "/api/terminal/sessions":
                s = term_mgr.create_session(name=body.get("name"), cwd=body.get("cwd"))
                self._json({"ok": True, "id": s.id, "name": s.name, "cwd": str(s.cwd)})
                return
            if path == "/api/terminal/sessions/close":
                self._json({"ok": term_mgr.close_session(str(body.get("id") or ""))})
                return
            if path == "/api/terminal/run":
                ok, msg = term_mgr.get(body.get("id")).run_command(str(body.get("command") or ""))
                self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/terminal/input":
                ok, msg = term_mgr.get(body.get("id")).send_input(str(body.get("text") or ""))
                self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/terminal/complete":
                self._json(term_mgr.get(body.get("id")).complete_path(str(body.get("line") or "")))
                return
            if path == "/api/terminal/stop":
                self._json({"ok": term_mgr.get(body.get("id")).stop()})
                return
            if path == "/api/terminal/clear":
                term_mgr.get(body.get("id")).clear()
                self._json({"ok": True})
                return
            if path == "/api/terminal/nl2cmd":
                sess = term_mgr.get(body.get("id"))
                query = str(body.get("query") or "").strip()
                ok, code, txt = arbiter.chat_complete(
                    [
                        {
                            "role": "system",
                            "content": (
                                f"Convert the user's request into ONE safe Windows PowerShell command for cwd `{sess.cwd}`. "
                                'Return ONLY valid JSON: {"command": "...", "explanation": "brief Turkish 1-line explanation"}.'
                            ),
                        },
                        {"role": "user", "content": query},
                    ],
                    temperature=0.1,
                    max_tokens=180,
                )
                if not ok:
                    self._json({"error": txt}, status=code)
                    return
                txt_clean = re.sub(r"^```(?:json|powershell|ps1)?\s*|\s*```$", "", txt, flags=re.I).strip()
                m = re.search(r"\{[\s\S]*\}", txt_clean)
                parsed_obj: dict[str, Any] = {}
                if m:
                    raw_j = m.group(0)
                    try:
                        parsed_obj = json.loads(raw_j)
                    except json.JSONDecodeError:
                        try:
                            parsed_obj = json.loads(re.sub(r'(?<!\\)\\(?![\\/"bfnrtu])', r'\\\\', raw_j))
                        except Exception:
                            parsed_obj = {}
                if not parsed_obj.get("command"):
                    parsed_obj = {"command": txt_clean.strip("` \n"), "explanation": ""}
                self._json({
                    "command": str(parsed_obj.get("command") or "").strip(),
                    "explanation": str(parsed_obj.get("explanation") or "").strip(),
                })
                return

            # ---- GPU Arbiter & Media ----
            if path == "/api/gpu/start-coding":
                ok, msg = arbiter.start_coding(body.get("model"))
                self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/gpu/stop-coding":
                arbiter.stop_coding()
                self._json({"ok": True})
                return
            if path == "/api/gpu/stop-all":
                arbiter.stop_all()
                self._json({"ok": True})
                return
            if path == "/api/media/upload-init":
                import base64 as _b64
                data_url = str(body.get("data_url") or "")
                raw_name = re.sub(r"[^a-zA-Z0-9._-]", "_", str(body.get("name") or "init.png"))
                ext = pathlib.Path(raw_name).suffix.lower()
                if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                    self._json({"error": "Sadece PNG, JPG veya WEBP yuklenebilir."}, status=400)
                    return
                if "," not in data_url:
                    self._json({"error": "Gecersiz gorsel verisi."}, status=400)
                    return
                raw_bytes = _b64.b64decode(data_url.split(",", 1)[1])
                if len(raw_bytes) > 15 * 1024 * 1024:
                    self._json({"error": "Gorsel 15 MB sinirini asiyor."}, status=413)
                    return
                up_dir = arbiter.picovid_dir / "outputs" / "_uploads"
                up_dir.mkdir(parents=True, exist_ok=True)
                dest = up_dir / f"ide_{int(time.time())}_{raw_name}"
                dest.write_bytes(raw_bytes)
                self._json({"ok": True, "path": str(dest), "name": dest.name})
                return
            if path == "/api/media/start":
                init_img = body.get("init_img")
                if init_img:
                    cand = pathlib.Path(str(init_img)).resolve()
                    allowed_roots = [
                        (arbiter.picovid_dir / "outputs").resolve(),
                        ws.root.resolve(),
                    ]
                    if not any(str(cand).startswith(str(rt)) for rt in allowed_roots) or not cand.exists():
                        self._json({"error": "Gecersiz giris gorseli yolu."}, status=403)
                        return
                    init_img = str(cand)
                ok, msg, out_path = arbiter.start_media(
                    prompt=str(body.get("prompt") or ""),
                    engine=str(body.get("engine") or "ltx23"),
                    mode=str(body.get("mode") or "t2v"),
                    width=int(body.get("width") or 640),
                    height=int(body.get("height") or 384),
                    frames=int(body.get("frames") or 81),
                    cinema_hd=bool(body.get("cinema_hd", False)),
                    fast_preview=bool(body.get("fast_preview", False)),
                    init_img=init_img,
                )
                self._json({"ok": ok, "message": msg, "output": out_path}, status=200 if ok else 400)
                return
            if path == "/api/media/timeline":
                raw_clips = list(body.get("clips") or [])
                if not raw_clips:
                    self._json({"error": "Zaman cizelgesi icin en az 1 klip secin."}, status=400)
                    return
                out_root = (arbiter.picovid_dir / "outputs").resolve()
                clip_specs: list[dict[str, Any]] = []
                for c in raw_clips:
                    rel = str(c.get("name") if isinstance(c, dict) else c).lstrip("/\\")
                    cand = (out_root / rel).resolve()
                    try:
                        cand.relative_to(out_root)
                    except ValueError:
                        self._json({"error": f"Yetkisiz klip yolu: {rel}"}, status=403)
                        return
                    if not cand.exists() or not cand.is_file():
                        self._json({"error": f"Klip bulunamadi: {rel}"}, status=404)
                        return
                    clip_specs.append({
                        "path": cand,
                        "start": c.get("start") if isinstance(c, dict) else None,
                        "end": c.get("end") if isinstance(c, dict) else None,
                    })
                pv_scripts = str(arbiter.picovid_dir / "scripts")
                if pv_scripts not in sys.path:
                    sys.path.insert(0, pv_scripts)
                import postprocess as _pv_pp  # type: ignore
                out_file = out_root / f"ide_timeline_{time.strftime('%Y%m%d_%H%M%S')}_{len(clip_specs)}clips.mp4"
                try:
                    res = _pv_pp.build_timeline_video(
                        clip_specs,
                        out_file,
                        transition=str(body.get("transition") or "dissolve"),
                        transition_sec=float(body.get("transition_sec") or 0.6),
                        crf=15,
                    )
                    self._json({"ok": True, "name": out_file.relative_to(out_root).as_posix(), **res})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=500)
                return
            if path == "/api/media/stop":
                arbiter.stop_media()
                self._json({"ok": True})
                return
            if path == "/api/media/enhance-prompt":
                raw_p = str(body.get("prompt") or "").strip()
                use_prefill = "inkling" in (arbiter.coding_model or "").lower()
                msgs = [
                    {"role": "system", "content": "Rewrite short scene ideas into one rich, photorealistic English cinematic video + ambient sound prompt for LTX-2.3 (camera motion, lighting, lens, crisp detail, natural sound effects/ambience, 2-3 sentences). Output ONLY the prompt."},
                    {"role": "user", "content": raw_p},
                ]
                if use_prefill:
                    msgs.append({"role": "assistant", "content": "Cinematic shot of "})
                ok, code, txt = arbiter.chat_complete(msgs, temperature=0.6, max_tokens=180, timeout=120)
                if not ok:
                    self._json({"error": txt}, status=code)
                    return
                enhanced = ("Cinematic shot of " + txt) if use_prefill else txt
                self._json({"enhanced": enhanced})
                return

            # ---- Coding Agent v2 (with Server-Side Abort) ----
            if path == "/api/agent/abort":
                rid = str(body.get("req_id") or "")
                with cancels_lock:
                    ev = active_cancels.get(rid)
                    if ev is not None:
                        ev.set()
                self._json({"ok": True})
                return
            if path == "/api/agent/chat":
                ok, code, err = arbiter.ensure_coding_ready()
                if not ok:
                    self._json({"error": err}, status=code)
                    return
                req_id = str(body.get("req_id") or secrets.token_hex(6))
                cancel_ev = threading.Event()
                with cancels_lock:
                    active_cancels[req_id] = cancel_ev
                msgs = list(body.get("messages") or [])
                mode = str(body.get("mode") or "agent")
                auto_verify = bool(body.get("auto_verify", False))
                test_cmd = body.get("test_cmd")
                active_file = body.get("active_file")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for ev in run_agent_stream(
                        arbiter, ws, msgs, active_file=active_file, mode=mode,
                        auto_verify=auto_verify, test_cmd=test_cmd, cancel_event=cancel_ev,
                    ):
                        line = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8")
                        self.wfile.write(line)
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    cancel_ev.set()
                except Exception as exc:
                    try:
                        err_line = f"data: {json.dumps({'type': 'error', 'error': str(exc)}, ensure_ascii=False)}\n\n".encode("utf-8")
                        self.wfile.write(err_line)
                        self.wfile.flush()
                    except OSError:
                        pass
                finally:
                    with cancels_lock:
                        active_cancels.pop(req_id, None)
                return

            self._json({"error": "Not found"}, status=404)

    return Handler


class PicoStudioHTTPServer(ThreadingHTTPServer):
    """Disable SO_REUSEADDR on Windows so two IDE instances never silently share port 7900."""
    allow_reuse_address = False
    daemon_threads = True


def run_ide(
    *,
    host: str | None = None,
    port: int | None = None,
    workspace_dir: str | None = None,
    open_browser: bool = True,
) -> int:
    cfg = load_config()
    h = host or cfg.get("ide_host", "127.0.0.1")
    p = int(port or cfg.get("ide_port", 7900))
    ws_path = workspace_dir or cfg.get("default_workspace") or str(pathlib.Path.cwd())

    arbiter = GPUArbiter(cfg)
    ws = Workspace(ws_path, projects_root=cfg.get("projects_root"))
    term_mgr = TerminalManager(ws.root)
    chat_store = ChatSessionStore(pathlib.Path(__file__).resolve().parent.parent / "data" / "chats")

    httpd = PicoStudioHTTPServer((h, p), make_handler(arbiter, ws, term_mgr, chat_store=chat_store))
    url = f"http://{h}:{p}/"
    print("============================================================")
    print(f"  PicoStudio Local IDE v0.9.0 -> {url}")
    print(f"  Aktif Proje                 -> {ws.root}")
    print(f"  Kodlama Motoru              -> {arbiter.picocode_dir}")
    print(f"  Video/Gorsel Motoru         -> {arbiter.picovid_dir}")
    print("  Guvenlik                    -> Host + Origin + CSRF Aktif")
    print("  Kapatmak icin Ctrl+C")
    print("============================================================", flush=True)
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        term_mgr.stop_all()
        arbiter.stop_all()
        httpd.server_close()
    return 0
