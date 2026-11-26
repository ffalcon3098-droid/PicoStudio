#!/usr/bin/env python3
"""
PicoStudio Automated Test Suite.

Verifies:
  1. Workspace CRUD, file tree, text search & strict path-traversal blocking
  2. Embedded Terminal execution, persistent `cd` tracking & snapshot output
  3. GPU Arbiter inventory discovery (sibling PicoCode + localVid zero-copy models)
  4. CLI argument parser for ide / status / chat / ask / video / image
  5. Live Web IDE HTTP API endpoints (/, /api/status, /api/inventory, /api/workspace/*, /api/terminal/*)

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

STUDIO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(STUDIO_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_ROOT))

from picostudio import git_ops
from picostudio.agent import detect_test_command, execute_tool, run_agent_stream, run_workspace_tests
from picostudio.arbiter import GPUArbiter, load_config
from picostudio.cli import build_parser
from picostudio.terminal import TerminalManager, TerminalSession
from picostudio.web_ide import make_handler
from picostudio.workspace import Workspace


class TestPicoStudioSuite(unittest.TestCase):
    def test_01_workspace_crud_search_and_security(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(td)
            ws.write_file("src/hello.py", "def greet():\n    return 'merhaba picostudio'\n")
            tree = ws.list_tree()
            paths = {x["path"] for x in tree}
            self.assertIn("src", paths)
            self.assertIn("src/hello.py", paths)

            data = ws.read_file("src/hello.py")
            self.assertIn("merhaba picostudio", data["content"])

            hits = ws.search("picostudio")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["line"], 2)

            with self.assertRaises(PermissionError):
                ws.read_file("../../Windows/win.ini")

            self.assertTrue(ws.delete_file("src/hello.py"))
            self.assertFalse(ws.delete_file("src/hello.py"))

            # Verify agent tools + project snapshot
            ws.write_file("README.md", "# Araban Demo\n3D driving game.")
            snap = ws.project_context_snapshot()
            self.assertIn("Araban Demo", snap)
            res_txt, change_info = execute_tool(ws, "write_file", {"path": "agent_out.py", "content": "x = 42\n"})
            self.assertEqual(change_info["path"], "agent_out.py")
            self.assertIn("OK:", res_txt)
            ed_txt, ed_info = execute_tool(ws, "edit_file", {"path": "agent_out.py", "target": "x = 42", "replacement": "x = 99"})
            self.assertEqual(ed_info["added"], 1)
            self.assertEqual(ed_info["removed"], 1)
            self.assertIn("x = 99", ws.read_file("agent_out.py")["content"])
            ws.undo_edit(ed_info["undo_id"])
            self.assertIn("x = 42", ws.read_file("agent_out.py")["content"])
            read_txt, _ = execute_tool(ws, "read_file", {"path": "agent_out.py"})
            self.assertIn("x = 42", read_txt)

    def test_02_terminal_pro_multitab_stdin_and_autocomplete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sub = pathlib.Path(td) / "subproj"
            sub.mkdir()
            (sub / "alpha_script.py").write_text("print('hi')\n", encoding="utf-8")

            mgr = TerminalManager(td)
            t1 = mgr.get()
            t2 = mgr.create_session("Tab 2")
            self.assertEqual(len(mgr.list_sessions()), 2)

            # Tab-completion + cd persistence
            comp = t1.complete_path("cd sub")
            self.assertEqual(comp["completed"], "cd subproj/")
            ok, _ = t1.run_command("cd subproj")
            self.assertTrue(ok)
            self.assertEqual(t1.cwd, sub.resolve())
            self.assertEqual(t2.cwd, pathlib.Path(td).resolve())  # Independent CWD per tab!

            comp2 = t1.complete_path("py alpha")
            self.assertEqual(comp2["completed"], "py alpha_script.py")

            # Interactive stdin test
            ok, _ = t1.run_command('py -c "x = input(); print(\'ECHO:\' + x)"')
            self.assertTrue(ok)
            time.sleep(0.4)
            ok_in, _ = t1.send_input("merhaba_stdin")
            self.assertTrue(ok_in)
            for _ in range(50):
                snap = t1.snapshot()
                if not snap["running"]:
                    break
                time.sleep(0.1)
            snap = t1.snapshot()
            self.assertEqual(snap["last_exit"], 0)
            self.assertTrue(any("ECHO:merhaba_stdin" in ln for ln in snap["lines"]))
            self.assertTrue(mgr.close_session(t2.id))
            self.assertEqual(len(mgr.list_sessions()), 1)
            mgr.stop_all()

    def test_03_arbiter_discovers_sibling_models(self) -> None:
        arb = GPUArbiter(load_config())
        inv = arb.get_inventory()
        c_ids = {m["id"] for m in inv["coding_models"]}
        self.assertIn("inkling2-mini", c_ids)
        self.assertGreaterEqual(len(inv["media_models"]), 1)
        st = arb.get_status()
        self.assertEqual(st["owner"], "idle")

    def test_04_cli_subcommands(self) -> None:
        p = build_parser()
        a_ide = p.parse_args(["ide", "--port", "7910", "--no-browser"])
        self.assertEqual(a_ide.cmd, "ide")
        self.assertEqual(a_ide.port, 7910)
        a_vid = p.parse_args(["video", "drone shot", "--engine", "5b", "--fast-preview"])
        self.assertEqual(a_vid.cmd, "video")
        self.assertTrue(a_vid.fast_preview)
        a_chat = p.parse_args(["chat", "--mode", "fast"])
        self.assertEqual(a_chat.cmd, "chat")

    def test_05_web_ide_http_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            arb = GPUArbiter(load_config())
            ws = Workspace(td)
            ws.write_file("demo.py", "print('hello')\n")
            term = TerminalManager(td)
            srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(arb, ws, term))
            srv.daemon_threads = True
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            base = f"http://127.0.0.1:{port}"
            try:
                with urllib.request.urlopen(f"{base}/", timeout=5) as r:
                    html = r.read().decode("utf-8")
                    self.assertEqual(r.status, 200)
                    self.assertIn("PicoStudio IDE", html)
                    self.assertIn("v0.4.0", html)
                    self.assertIn("codeHighlight", html)
                    self.assertIn("findBar", html)
                    self.assertIn("quickOpenBackdrop", html)
                    self.assertIn("diffViewer", html)
                    self.assertIn("approvePlanAndRun", html)

                with urllib.request.urlopen(f"{base}/api/git/status", timeout=5) as r:
                    gst = json.loads(r.read().decode("utf-8"))
                    self.assertIn("is_repo", gst)

                with urllib.request.urlopen(f"{base}/api/status", timeout=5) as r:
                    st = json.loads(r.read().decode("utf-8"))
                    self.assertEqual(st["owner"], "idle")

                with urllib.request.urlopen(f"{base}/api/workspace/tree", timeout=5) as r:
                    tr = json.loads(r.read().decode("utf-8"))
                    self.assertTrue(any(x["path"] == "demo.py" for x in tr["items"]))

                req = urllib.request.Request(
                    f"{base}/api/workspace/file",
                    data=json.dumps({"path": "new_note.txt", "content": "ok123"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    self.assertEqual(r.status, 200)

                with urllib.request.urlopen(f"{base}/api/workspace/file?path=new_note.txt", timeout=5) as r:
                    self.assertEqual(json.loads(r.read().decode("utf-8"))["content"], "ok123")

                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"{base}/api/workspace/file?path=../../secret.txt", timeout=5)
                self.assertEqual(ctx.exception.code, 403)

                req_proj = urllib.request.Request(
                    f"{base}/api/workspace/create-project",
                    data=json.dumps({"path": str(pathlib.Path(td) / "yeni_proje")}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_proj, timeout=5) as r:
                    pj = json.loads(r.read().decode("utf-8"))
                    self.assertTrue(pj["ok"])
                    self.assertTrue(pathlib.Path(pj["root"]).exists())

                # Terminal Pro HTTP endpoints: multi-tab, Tab-complete, run + SSE stream
                with urllib.request.urlopen(f"{base}/api/terminal/sessions", timeout=5) as r:
                    ss = json.loads(r.read().decode("utf-8"))["sessions"]
                    self.assertGreaterEqual(len(ss), 1)
                    s1_id = ss[0]["id"]

                req_new = urllib.request.Request(
                    f"{base}/api/terminal/sessions",
                    data=json.dumps({"name": "Build Tab", "cwd": td}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_new, timeout=5) as r:
                    s2 = json.loads(r.read().decode("utf-8"))
                    self.assertTrue(s2["ok"])
                    s2_id = s2["id"]

                req_comp = urllib.request.Request(
                    f"{base}/api/terminal/complete",
                    data=json.dumps({"id": s2_id, "line": "py dem"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_comp, timeout=5) as r:
                    comp = json.loads(r.read().decode("utf-8"))
                    self.assertEqual(comp["completed"], "py demo.py")

                req_run = urllib.request.Request(
                    f"{base}/api/terminal/run",
                    data=json.dumps({"id": s2_id, "command": "py demo.py"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_run, timeout=5) as r:
                    self.assertTrue(json.loads(r.read().decode("utf-8"))["ok"])

                # Read live SSE stream from /api/terminal/stream until we see 'hello'
                got_hello = False
                with urllib.request.urlopen(f"{base}/api/terminal/stream?id={s2_id}&after=0", timeout=8) as r:
                    for _ in range(20):
                        raw_ln = r.readline().decode("utf-8", errors="replace").strip()
                        if raw_ln.startswith("data:"):
                            ev = json.loads(raw_ln[5:].strip())
                            if any("hello" in x for x in ev.get("lines", [])):
                                got_hello = True
                                break
                self.assertTrue(got_hello)

                req_close = urllib.request.Request(
                    f"{base}/api/terminal/sessions/close",
                    data=json.dumps({"id": s2_id}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_close, timeout=5) as r:
                    self.assertTrue(json.loads(r.read().decode("utf-8"))["ok"])
                self.assertNotEqual(s1_id, s2_id)
            finally:
                term.stop_all()
                srv.shutdown()
                srv.server_close()

    def test_06_git_ops_status_diff_stage_revert_commit(self) -> None:
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(td)
            self.assertFalse(git_ops.is_git_repo(ws))
            subprocess.run(["git", "init"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@picostudio.local"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "PicoTester"], cwd=td, check=True, capture_output=True)

            ws.write_file("calc.py", "def add(a, b):\n    return a + b\n")
            st = git_ops.get_status(ws)
            self.assertTrue(st["is_repo"])
            self.assertEqual(len(st["untracked"]), 1)

            # Untracked diff preview
            ud = git_ops.get_diff(ws, "calc.py", staged=False)
            self.assertEqual(ud["added"], 2)

            # Stage & commit
            ok, _ = git_ops.stage_path(ws, "calc.py")
            self.assertTrue(ok)
            cm = git_ops.commit_changes(ws, "feat: add calc")
            self.assertTrue(cm["ok"])
            self.assertTrue(cm["hash"])
            logs = git_ops.get_log(ws)
            self.assertEqual(logs[0]["subject"], "feat: add calc")

            # Modify -> diff -> stage -> unstage -> revert
            ws.write_file("calc.py", "def add(a, b):\n    return a + b + 1\n")
            d1 = git_ops.get_diff(ws, "calc.py", staged=False)
            self.assertEqual(d1["added"], 1)
            self.assertEqual(d1["removed"], 1)

            self.assertTrue(git_ops.stage_path(ws, "calc.py")[0])
            self.assertEqual(len(git_ops.get_status(ws)["staged"]), 1)
            self.assertTrue(git_ops.unstage_path(ws, "calc.py")[0])
            self.assertEqual(len(git_ops.get_status(ws)["staged"]), 0)

            self.assertTrue(git_ops.revert_path(ws, "calc.py")[0])
            self.assertIn("return a + b\n", ws.read_file("calc.py")["content"])
            with self.assertRaises(PermissionError):
                git_ops.revert_path(ws, "../../outside.txt")

    def test_07_agent_v2_plan_mode_and_auto_verify_self_heal(self) -> None:
        from http.server import BaseHTTPRequestHandler
        with tempfile.TemporaryDirectory() as td:
            ws = Workspace(td)
            ws.write_file("mathlib.py", "def mul(a, b):\n    return a + b\n")
            ws.write_file(
                "tests/test_math.py",
                "import unittest\nfrom mathlib import mul\nclass T(unittest.TestCase):\n    def test_mul(self):\n        self.assertEqual(mul(3, 4), 12)\n",
            )
            self.assertEqual(detect_test_command(ws), "py -m unittest discover -s tests -v")
            self.assertFalse(run_workspace_tests(ws)["passed"])

            # Local mock OpenAI SSE server driving:
            # 1) Plan mode (emits read-only plan)
            # 2) Self-heal loop (call 1 writes wrong fix -> unittest fails -> call 2 repairs -> unittest passes!)
            call_counter = {"n": 0}

            class MockLLM(BaseHTTPRequestHandler):
                def log_message(self, fmt, *args):
                    pass

                def do_POST(self):
                    n = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(n).decode("utf-8"))
                    sys_msg = body["messages"][0]["content"]
                    call_counter["n"] += 1
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()

                    def send_sse(delta_obj):
                        chunk = f"data: {json.dumps({'choices': [{'delta': delta_obj}]})}\n\n".encode("utf-8")
                        self.wfile.write(chunk)

                    if "READ-ONLY PLAN MODE" in sys_msg:
                        send_sse({"content": "1. mathlib.py icindeki mul fonksiyonunu duzelt\n2. unittest calistir"})
                    else:
                        idx = call_counter["n"]
                        if idx == 2:
                            # First edit (still buggy!)
                            send_sse({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "edit_file", "arguments": json.dumps({"path": "mathlib.py", "target": "return a + b", "replacement": "return a - b"})}}]})
                        elif idx == 3:
                            send_sse({"content": "İlk değişiklik uygulandı."})
                        elif idx == 4:
                            # Self-heal round: sees test failure, applies real fix!
                            send_sse({"tool_calls": [{"index": 0, "id": "c2", "function": {"name": "edit_file", "arguments": json.dumps({"path": "mathlib.py", "target": "return a - b", "replacement": "return a * b"})}}]})
                        else:
                            send_sse({"content": "Hata düzeltildi, testler geçiyor."})
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()

            mock_srv = ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
            mock_srv.daemon_threads = True
            t = threading.Thread(target=mock_srv.serve_forever, daemon=True)
            t.start()
            try:
                arb = GPUArbiter(load_config())
                arb.llm_host = "127.0.0.1"
                arb.llm_port = mock_srv.server_address[1]
                arb.coding_model = "mock-coder"

                # Verify Plan Mode emits plan_ready and modifies 0 files
                plan_evs = list(run_agent_stream(arb, ws, [{"role": "user", "content": "mul duzelt"}], mode="plan"))
                self.assertTrue(any(e["type"] == "plan_ready" for e in plan_evs))
                self.assertFalse(any(e["type"] == "file_changed" for e in plan_evs))

                # Verify Agent Mode + Auto-Verify Self-Heal heals failing test automatically!
                heal_evs = list(run_agent_stream(arb, ws, [{"role": "user", "content": "mul duzelt"}], mode="agent", auto_verify=True))
                verifies = [e for e in heal_evs if e["type"] == "verify"]
                self.assertEqual(len(verifies), 2)
                self.assertFalse(verifies[0]["passed"])
                self.assertTrue(verifies[1]["passed"])
                self.assertIn("return a * b", ws.read_file("mathlib.py")["content"])
            finally:
                mock_srv.shutdown()
                mock_srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
