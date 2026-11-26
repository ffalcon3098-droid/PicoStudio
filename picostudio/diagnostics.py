"""
PicoStudio Zero-Dependency Instant Syntax Diagnostics.

Provides millisecond-fast local syntax checking on save/edit:
  - Python (.py): ast.parse() exact line, column & SyntaxError message
  - JSON (.json): json.loads() exact line, column & JSONDecodeError message

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import ast
import json
import pathlib
from typing import Any


def check_syntax(rel_path: str, content: str) -> list[dict[str, Any]]:
    """Return a list of syntax diagnostics [{line, col, severity, message}]."""
    ext = pathlib.Path(rel_path or "").suffix.lower()
    if ext == ".py":
        try:
            ast.parse(content or "", filename=rel_path or "<editor>")
            return []
        except SyntaxError as exc:
            return [{
                "line": int(exc.lineno or 1),
                "col": int(exc.offset or 1),
                "severity": "error",
                "message": f"SyntaxError: {exc.msg}",
            }]
        except Exception as exc:
            return [{"line": 1, "col": 1, "severity": "error", "message": str(exc)}]

    if ext == ".json":
        if not (content or "").strip():
            return []
        try:
            json.loads(content)
            return []
        except json.JSONDecodeError as exc:
            return [{
                "line": int(exc.lineno or 1),
                "col": int(exc.colno or 1),
                "severity": "error",
                "message": f"JSONError: {exc.msg}",
            }]

    return []
