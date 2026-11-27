"""
PicoStudio Zero-Dependency Code Symbol Indexer (Outline + F12 Go-to-Definition).

Extracts classes, functions, methods, interfaces, and types from:
  - Python (.py): via ast.parse() with regex fallback for work-in-progress files
  - JS / TS / JSX / TSX (.js, .ts, .jsx, .tsx, .mjs): via fast regex scanner

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Any

from picostudio.workspace import Workspace

_PY_FALLBACK_RE = re.compile(r"^([ \t]*)(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)", re.M)
_JS_SYM_RE = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?(?:async\s+)?"
    r"(?:(function)\s+([A-Za-z_$][\w$]*)"
    r"|(class|interface|type)\s+([A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)",
    re.M,
)


def extract_file_symbols(rel_path: str, content: str) -> list[dict[str, Any]]:
    """Return ordered list of symbols [{name, kind, line, detail}] in a single file."""
    ext = pathlib.Path(rel_path or "").suffix.lower()
    out: list[dict[str, Any]] = []

    if ext == ".py":
        try:
            tree = ast.parse(content or "", filename=rel_path or "<mem>")
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    out.append({"name": node.name, "kind": "class", "line": node.lineno, "detail": f"class {node.name}"})
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            args = ", ".join(a.arg for a in item.args.args[:5])
                            out.append({
                                "name": f"{node.name}.{item.name}",
                                "short": item.name,
                                "kind": "method",
                                "line": item.lineno,
                                "detail": f"def {item.name}({args})",
                            })
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = ", ".join(a.arg for a in node.args.args[:5])
                    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                    out.append({
                        "name": node.name,
                        "short": node.name,
                        "kind": "function",
                        "line": node.lineno,
                        "detail": f"{prefix} {node.name}({args})",
                    })
            return out
        except SyntaxError:
            # Regex fallback while user is mid-edit
            for m in _PY_FALLBACK_RE.finditer(content or ""):
                ln = (content or "").count("\n", 0, m.start()) + 1
                kind = "class" if m.group(2) == "class" else ("method" if m.group(1) else "function")
                out.append({"name": m.group(3), "short": m.group(3), "kind": kind, "line": ln, "detail": f"{m.group(2)} {m.group(3)}"})
            return out

    if ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
        for m in _JS_SYM_RE.finditer(content or ""):
            ln = (content or "").count("\n", 0, m.start()) + 1
            if m.group(2):
                out.append({"name": m.group(2), "short": m.group(2), "kind": "function", "line": ln, "detail": f"function {m.group(2)}"})
            elif m.group(4):
                out.append({"name": m.group(4), "short": m.group(4), "kind": m.group(3), "line": ln, "detail": f"{m.group(3)} {m.group(4)}"})
            elif m.group(5):
                out.append({"name": m.group(5), "short": m.group(5), "kind": "function", "line": ln, "detail": f"const {m.group(5)} =>"})
        return out

    if ext == ".rs":
        prev_tauri = False
        for idx, ln in enumerate((content or "").splitlines(), 1):
            st = ln.strip()
            if "#[tauri::command" in st:
                prev_tauri = True
                continue
            m = re.match(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(fn|struct|enum|trait|mod)\s+([A-Za-z_]\w*)", ln)
            if m:
                kind = "tauri_cmd" if (prev_tauri and m.group(1) == "fn") else m.group(1)
                out.append({"name": m.group(2), "short": m.group(2), "kind": kind, "line": idx, "detail": f"{m.group(1)} {m.group(2)}"})
                prev_tauri = False
                continue
            if st and not st.startswith("#[") and not st.startswith("//"):
                prev_tauri = False
        return out

    if ext == ".go":
        for idx, ln in enumerate((content or "").splitlines(), 1):
            m = re.match(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", ln)
            if m:
                out.append({"name": m.group(1), "short": m.group(1), "kind": "function", "line": idx, "detail": f"func {m.group(1)}"})
                continue
            m2 = re.match(r"^\s*type\s+([A-Za-z_]\w*)\s+(struct|interface)\b", ln)
            if m2:
                out.append({"name": m2.group(1), "short": m2.group(1), "kind": m2.group(2), "line": idx, "detail": f"type {m2.group(1)} {m2.group(2)}"})
        return out

    return out


def search_workspace_symbols(ws: Workspace, query: str = "", exact: bool = False, limit: int = 40) -> list[dict[str, Any]]:
    """Index symbols across the workspace for project-wide Ctrl+Shift+O (#) and F12 Go-to-Definition."""
    q = (query or "").strip().lower()
    hits: list[dict[str, Any]] = []
    for item in ws.list_tree(max_depth=5, max_items=400):
        if item["kind"] != "file" or item["size"] > 256 * 1024:
            continue
        p = ws.root / item["path"]
        if p.suffix.lower() not in (".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".rs", ".go"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for sym in extract_file_symbols(item["path"], text):
            name_l = sym["name"].lower()
            short_l = str(sym.get("short") or sym["name"]).lower()
            if exact:
                if name_l == q or short_l == q:
                    hits.append({**sym, "path": item["path"]})
            elif not q or q in name_l or q in short_l:
                hits.append({**sym, "path": item["path"]})
            if len(hits) >= limit:
                return hits
    return hits
