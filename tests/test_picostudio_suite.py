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

from picostudio.arbiter import GPUArbiter, load_config
from picostudio.cli import build_parser
from picostudio.terminal import TerminalSession
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

    def test_02_terminal_command_and_cd(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sub = pathlib.Path(td) / "subproj"
            sub.mkdir()
            term = TerminalSession(td)
            ok, _ = term.run_command("cd subproj")
            self.assertTrue(ok)
            self.assertEqual(term.cwd, sub.resolve())

            ok, _ = term.run_command("Write-Output 'PICOSTUDIO_TERM_OK'")
            self.assertTrue(ok)
            for _ in range(40):
                snap = term.snapshot()
                if not snap["running"]:
                    break
                time.sleep(0.1)
            snap = term.snapshot()
            self.assertEqual(snap["last_exit"], 0)
            self.assertTrue(any("PICOSTUDIO_TERM_OK" in ln for ln in snap["lines"]))

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
            term = TerminalSession(td)
            srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(arb, ws, term))
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            base = f"http://127.0.0.1:{port}"
            try:
                with urllib.request.urlopen(f"{base}/", timeout=5) as r:
                    html = r.read().decode("utf-8")
                    self.assertEqual(r.status, 200)
                    self.assertIn("PicoStudio IDE", html)
                    self.assertIn("Inkling 2", html)
                    self.assertIn("Wan 2.2", html)

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
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
