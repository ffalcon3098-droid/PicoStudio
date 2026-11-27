"""
PicoStudio Local Coding Agent v3 (16-Step Loop · AST Repo Map · Git Tools · Instant Syntax Feedback · Context Compaction · Batch Turn Undo).

Gives local coding models (Qwen3-Coder-30B-A3B, Inkling 2 Mini, Qwen2.5-Coder) real IDE superpowers:
  - Fast Mode: instant project-snapshot response without tool overhead
  - Plan + Approval Mode: read-only codebase inspection -> structured multi-file plan card -> user approval
  - Agent v3 Mode + Auto-Verify Self-Heal:
      * Read tools: list_files, read_file, search_code, repo_map (AST outline), find_symbols, git_status, git_diff
      * Write/Exec tools: edit_file, write_file (both with instant syntax diagnostics), delete_file (undo-recorded), run_terminal
      * Smart context compaction keeps 16-step multi-file runs fast inside 32K context
      * Consecutive duplicate tool-call loop guard prevents wasted steps
      * Automatically detects and runs workspace tests after edits, feeding failures back for self-healing
      * Emits turn_checkpoint with all turn undo_ids for 1-click full-turn rollback
  - Streams structured SSE events (status, metrics, tool, tool_result, file_changed, plan_ready, verify, turn_checkpoint, delta, done, error).

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import threading
import urllib.request
from typing import Any, Iterator

from picostudio import diagnostics, git_ops, symbols
from picostudio.arbiter import GPUArbiter
from picostudio.workspace import Workspace

AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in subdir ('' for root).",
            "parameters": {"type": "object", "properties": {"subdir": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read text file with 1-based start_line/end_line.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Grep substring across source files.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_map",
            "description": "Get a compact AST/symbol map (classes, functions, methods, line numbers) of workspace code files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subdir": {"type": "string", "description": "Optional relative subdirectory filter."},
                    "max_files": {"type": "integer", "description": "Maximum files to include (default 25)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_symbols",
            "description": "Find class, function, method, or interface definitions across the workspace by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Symbol name or substring to match."},
                    "exact": {"type": "boolean", "description": "If true, match exact symbol name."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Inspect current git branch and staged/unstaged/untracked changes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "View unified git diff for a specific file or the whole workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional relative file path (empty for all)."},
                    "staged": {"type": "boolean", "description": "If true, show staged diff."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact target text block inside an existing file with replacement text. Runs instant syntax check.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "target": {"type": "string"},
                    "replacement": {"type": "string"},
                },
                "required": ["path", "target", "replacement"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with full content. Runs instant syntax check.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Safely delete a file inside the workspace (recorded for undo).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_terminal",
            "description": "Run PowerShell command in project root (with PYTHONPATH set).",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        },
    },
]

READONLY_TOOL_NAMES = {
    "list_files", "read_file", "search_code",
    "repo_map", "find_symbols", "git_status", "git_diff",
}
READONLY_AGENT_TOOLS = [t for t in AGENT_TOOLS if t["function"]["name"] in READONLY_TOOL_NAMES]
KNOWN_TOOL_NAMES = {t["function"]["name"] for t in AGENT_TOOLS}
_CODE_MAP_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def detect_test_command(ws: Workspace) -> str | None:
    """Auto-detect the best local test command for the active workspace."""
    tests_dir = ws.root / "tests"
    if tests_dir.is_dir() and any(tests_dir.glob("test_*.py")):
        return "py -m unittest discover -s tests -v"
    if any(ws.root.glob("test_*.py")):
        return "py -m unittest discover -v"
    pkg_json = ws.root / "package.json"
    if pkg_json.is_file():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            t_cmd = str((pkg.get("scripts") or {}).get("test") or "")
            if t_cmd and "no test specified" not in t_cmd.lower():
                return "npm test"
        except Exception:
            pass
    return None


def _build_ws_env(ws: Workspace) -> dict[str, str]:
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ws.root) + (os.pathsep + existing_pp if existing_pp else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # Avoid same-second/same-size stale .pyc during self-heal loops
    return env


def run_workspace_tests(ws: Workspace, custom_cmd: str | None = None, timeout: int = 45) -> dict[str, Any]:
    """Execute workspace tests and return structured pass/fail diagnostics."""
    cmd = (custom_cmd or "").strip() or detect_test_command(ws)
    if not cmd:
        return {"ran": False, "passed": True, "command": "", "exit_code": 0, "output": "Projede otomatik test komutu bulunamadi."}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = _build_ws_env(ws)
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            cwd=str(ws.root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
        )
        out = ((res.stdout or "") + ("\n" + res.stderr if res.stderr else "")).strip()
        return {
            "ran": True,
            "passed": res.returncode == 0,
            "command": cmd,
            "exit_code": res.returncode,
            "output": out[-3500:],
        }
    except subprocess.TimeoutExpired:
        return {"ran": True, "passed": False, "command": cmd, "exit_code": 124, "output": f"Test komutu zaman asimina ugradi ({timeout}s)."}
    except Exception as exc:
        return {"ran": True, "passed": False, "command": cmd, "exit_code": 1, "output": str(exc)}


def build_repo_map(ws: Workspace, subdir: str = "", max_files: int = 25) -> str:
    """Build a compact AST/symbol outline across workspace code files for fast codebase orientation."""
    sub_clean = (subdir or "").strip().replace("\\", "/").strip("/")
    if sub_clean:
        ws.safe_path(sub_clean)  # Enforce path safety
    limit = max(1, min(60, int(max_files or 25)))
    blocks: list[str] = []
    file_count = 0
    total_chars = 0
    for item in ws.list_tree(max_depth=4, max_items=400):
        if item["kind"] != "file" or item["size"] > 200_000:
            continue
        rel = item["path"]
        if sub_clean and not (rel == sub_clean or rel.startswith(sub_clean + "/")):
            continue
        if pathlib.Path(rel).suffix.lower() not in _CODE_MAP_EXTS:
            continue
        try:
            content = (ws.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n_lines = content.count("\n") + (1 if content else 0)
        syms = symbols.extract_file_symbols(rel, content)
        lines = [f"{rel} ({n_lines}L):"]
        if syms:
            for s in syms[:35]:
                indent = "    " if "." in s["name"] else "  "
                lines.append(f"{indent}L{s['line']} {s['kind']} {s['name']}")
            if len(syms) > 35:
                lines.append(f"  ... (+{len(syms) - 35} more symbols)")
        else:
            lines.append("  (no top-level symbols)")
        blk = "\n".join(lines)
        if total_chars + len(blk) > 7800:
            blocks.append("... (repo_map truncated for context budget)")
            break
        blocks.append(blk)
        total_chars += len(blk) + 1
        file_count += 1
        if file_count >= limit:
            break
    if not blocks:
        return f"No supported source files ({', '.join(sorted(_CODE_MAP_EXTS))}) found" + (f" under '{sub_clean}'." if sub_clean else ".")
    return f"Repo Map ({file_count} files):\n" + "\n".join(blocks)


def _format_syntax_feedback(rel_path: str, content: str) -> tuple[str, list[dict[str, Any]]]:
    diags = diagnostics.check_syntax(rel_path, content)
    if not diags:
        return "", []
    parts = [f"Line {d.get('line', 1)}: {d.get('message', 'Syntax error')}" for d in diags[:5]]
    msg = "\n[SYNTAX ERROR] " + "; ".join(parts) + "\nFix this syntax error immediately before finishing."
    return msg, diags


def estimate_context_tokens(conv: list[dict[str, Any]]) -> int:
    """Fast local token estimate (~4 chars/token) for telemetry and compaction decisions."""
    chars = 0
    for m in conv:
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "text":
                    chars += len(str(part.get("text") or ""))
                else:
                    chars += 256  # approximate image token cost
        tcs = m.get("tool_calls")
        if tcs:
            chars += len(json.dumps(tcs, ensure_ascii=False))
    return max(1, chars // 4)


def compact_conversation(
    conv: list[dict[str, Any]],
    *,
    keep_recent_tool_msgs: int = 4,
    max_total_chars: int = 88000,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Hysteresis/epoch KV-cache-friendly compaction:
    NEVER mutates earlier messages while total_chars <= max_total_chars (preserving 100% KV prefix hits!).
    Only when crossing the high-water mark, batch-compacts older tool outputs once while keeping recent ones verbatim.
    """
    tool_indices = [i for i, m in enumerate(conv) if m.get("role") == "tool"]
    total_chars = estimate_context_tokens(conv) * 4
    if total_chars <= max_total_chars or len(tool_indices) <= keep_recent_tool_msgs:
        return conv, False

    cutoff_idx = tool_indices[-keep_recent_tool_msgs]
    compacted: list[dict[str, Any]] = []
    did_compact = False
    for i, m in enumerate(conv):
        if i < cutoff_idx and m.get("role") == "tool" and isinstance(m.get("content"), str):
            txt = m["content"]
            if len(txt) > 520 and not txt.startswith("[Compacted"):
                lines = txt.splitlines()
                head = "\n".join(lines[:3])[:220]
                tail = "\n".join(lines[-2:])[:140] if len(lines) > 5 else ""
                summary = f"[Compacted older tool output: {len(txt)} chars, {len(lines)} lines]\n{head}"
                if tail:
                    summary += f"\n...\n{tail}"
                compacted.append({**m, "content": summary})
                did_compact = True
                continue
        compacted.append(m)
    return compacted, did_compact


def _extract_fallback_tool_calls(text: str, step: int, allowed: set[str] | None = None) -> list[dict[str, Any]]:
    """Parse JSON tool calls emitted in content by models without native OpenAI tool_calls (e.g. Qwen2.5)."""
    valid_names = allowed if allowed is not None else KNOWN_TOOL_NAMES
    found: list[dict[str, Any]] = []
    candidates = re.findall(r"```(?:json)?\s*\n(\{[\s\S]*?\})\s*```", text)
    if not candidates and text.strip().startswith("{") and text.strip().endswith("}"):
        candidates = [text.strip()]
    for idx, raw in enumerate(candidates):
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("name") in valid_names and isinstance(obj.get("arguments"), dict):
            found.append({
                "id": f"fb_{step}_{idx}",
                "type": "function",
                "function": {"name": obj["name"], "arguments": json.dumps(obj["arguments"], ensure_ascii=False)},
            })
    return found


_DANGEROUS_CMD_PATTERNS = [
    re.compile(r"\brm\s+[^\n]*(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-r\b[^\n]*-f\b|-f\b[^\n]*-r\b)", re.I | re.S),
    re.compile(r"\b(remove-item|ri|del|erase|rmdir|rd)\b[^\n]*(-rec\w*[^\n]*-fo\w*|-fo\w*[^\n]*-rec\w*|-r\b[^\n]*-fo\w*|/[sqf]\s*[^\n]*/[sqf])", re.I | re.S),
    re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|push\s+[^\n]*(--force|-f\b)|checkout\s+--\s+\.|restore\s+\.)", re.I | re.S),
    re.compile(r"\b(invoke-expression|iex)\b|\|\s*(sh|bash|powershell|pwsh)\b|-(enc|encodedcommand)\b", re.I | re.S),
    re.compile(r"\[(?:system\.)?io\.(?:directory|file)\]::delete\b|\bshutil\.rmtree\b|\bfs\.rmSync\b", re.I | re.S),
    re.compile(r"\b(format-volume|format\s+[a-z]:|diskpart|shutdown|stop-computer|reg\s+delete)\b", re.I | re.S),
]


def is_dangerous_command(cmd: str) -> str | None:
    """Return matched safety reason if an agent terminal command is destructive, else None."""
    for pat in _DANGEROUS_CMD_PATTERNS:
        if pat.search(cmd or ""):
            return f"Guvenlik engeli: yikici komut ajan tarafindan otomatik calistirilamaz (`{pat.pattern[:48]}`). Kullanicidan terminalde manuel calistirmasini isteyin."
    return None


def execute_tool(ws: Workspace, name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Execute one workspace tool safely. Returns (result_text, change_info_or_None)."""
    try:
        if name == "list_files":
            subdir = str(args.get("subdir") or "").strip()
            base = ws.safe_path(subdir) if subdir else ws.root
            if not base.exists() or not base.is_dir():
                return f"ERROR: Directory not found: {subdir}", None
            entries = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = []
            for e in entries[:120]:
                rel = e.relative_to(ws.root).as_posix()
                lines.append(f"{rel}/" if e.is_dir() else f"{rel} ({e.stat().st_size} B)")
            return "\n".join(lines) or "(empty directory)", None

        if name == "read_file":
            rel = str(args.get("path") or "")
            data = ws.read_file(rel)
            all_lines = data["content"].splitlines()
            s = max(1, int(args.get("start_line") or 1))
            e = min(len(all_lines), int(args.get("end_line") or (s + 199)))
            numbered = [f"{i}: {all_lines[i - 1]}" for i in range(s, e + 1)]
            hdr = f"File: {data['path']} (lines {s}-{e} of {len(all_lines)})\n"
            return hdr + "\n".join(numbered)[:9000], None

        if name == "search_code":
            q = str(args.get("query") or "")
            hits = ws.search(q, max_hits=30)
            if not hits:
                return f"No matches for {q!r}.", None
            return "\n".join(f"{h['path']}:{h['line']}: {h['text']}" for h in hits), None

        if name == "repo_map":
            subdir = str(args.get("subdir") or "").strip()
            max_files = int(args.get("max_files") or 25)
            return build_repo_map(ws, subdir=subdir, max_files=max_files), None

        if name == "find_symbols":
            q = str(args.get("query") or "").strip()
            exact = bool(args.get("exact", False))
            hits = symbols.search_workspace_symbols(ws, q, exact=exact, limit=40)
            if not hits:
                return f"No symbols matching {q!r}.", None
            return "\n".join(f"{h['path']}:{h['line']} [{h['kind']}] {h['name']}" for h in hits), None

        if name == "git_status":
            st = git_ops.get_status(ws)
            if not st.get("is_repo"):
                return "Workspace is not a Git repository.", None
            ab = ""
            if st.get("ahead"):
                ab += f" ahead={st['ahead']}"
            if st.get("behind"):
                ab += f" behind={st['behind']}"
            lines = [f"Branch: {st.get('branch', '?')}{ab} (total changes: {st.get('total_changes', 0)})"]
            if st.get("staged"):
                lines.append("Staged: " + ", ".join(f"{f['code']} {f['path']}" for f in st["staged"][:30]))
            if st.get("unstaged"):
                lines.append("Unstaged: " + ", ".join(f"{f['code']} {f['path']}" for f in st["unstaged"][:30]))
            if st.get("untracked"):
                lines.append("Untracked: " + ", ".join(f["path"] for f in st["untracked"][:30]))
            if st.get("total_changes", 0) == 0:
                lines.append("Working tree clean.")
            return "\n".join(lines), None

        if name == "git_diff":
            rel = str(args.get("path") or "").strip()
            staged = bool(args.get("staged", False))
            if rel:
                ws.safe_path(rel)
            d = git_ops.get_diff(ws, rel, staged=staged)
            raw = (d.get("raw") or "").strip()
            if not raw:
                return f"No {'staged ' if staged else ''}diff for {rel or 'workspace'}.", None
            hdr = f"Diff {d.get('path', rel or 'workspace')} (+{d.get('added', 0)}/-{d.get('removed', 0)}):\n"
            return hdr + raw[:7000], None

        if name == "edit_file":
            rel = str(args.get("path") or "")
            target = str(args.get("target") or "").replace("\r\n", "\n")
            replacement = str(args.get("replacement") or "").replace("\r\n", "\n")
            data = ws.read_file(rel)
            if not target or target not in data["content"]:
                return f"ERROR: Target text not found in {rel}. Read the file first.", None
            occurrences = data["content"].count(target)
            if occurrences > 1:
                return (
                    f"ERROR: Ambiguous edit — target appears {occurrences} times in {rel}. "
                    "Include 1-2 surrounding lines so the target is unique."
                ), None
            new_content = data["content"].replace(target, replacement, 1)
            res = ws.write_file_with_diff(rel, new_content)
            syn_msg, diags = _format_syntax_feedback(res["path"], new_content)
            if diags:
                res["diagnostics"] = diags
            return f"OK: Edited {res['path']} (+{res['added']}/-{res['removed']}).{syn_msg}", res

        if name == "write_file":
            rel = str(args.get("path") or "")
            content = str(args.get("content") or "")
            res = ws.write_file_with_diff(rel, content)
            syn_msg, diags = _format_syntax_feedback(res["path"], content)
            if diags:
                res["diagnostics"] = diags
            return f"OK: Wrote {res['path']} (+{res['added']}/-{res['removed']}, {res['size']} bytes).{syn_msg}", res

        if name == "delete_file":
            rel = str(args.get("path") or "")
            res = ws.delete_file_with_undo(rel)
            return f"OK: Deleted {res['path']} (-{res['removed']} lines, undo_id={res['undo_id']}).", res

        if name == "run_terminal":
            cmd = str(args.get("command") or "").strip()
            if not cmd:
                return "ERROR: Empty command.", None
            danger = is_dangerous_command(cmd)
            if danger:
                return f"ERROR: {danger}", None
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            env = _build_ws_env(ws)
            env["PYTHONIOENCODING"] = "utf-8"
            ps_cmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                cwd=str(ws.root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
            )
            try:
                out, _ = proc.communicate(timeout=45)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, creationflags=flags)
                else:
                    proc.kill()
                return "ERROR: Command timed out after 45s (process tree terminated).", None
            return f"exit_code={proc.returncode}\n{(out or '').strip()[:5000]}", None

        return f"ERROR: Unknown tool {name}", None
    except Exception as exc:
        return f"ERROR: {exc}", None


def load_project_rules(ws: Workspace, max_chars: int = 1200) -> str:
    """Auto-load workspace custom AI instructions from `.picostudio.md` or `AGENTS.md` if present."""
    for fname in (".picostudio.md", "AGENTS.md"):
        fp = ws.root / fname
        if fp.is_file():
            try:
                txt = fp.read_text(encoding="utf-8", errors="replace").strip()
                if txt:
                    return f"\nProject rules ({fname}):\n{txt[:max_chars]}\n"
            except OSError:
                pass
    return ""


def extract_at_file_context(ws: Workspace, user_messages: list[dict[str, Any]], max_files: int = 3) -> str:
    """Resolve @path/to/file references in the latest user prompt and return safe file snippets."""
    if not user_messages:
        return ""
    last = user_messages[-1].get("content")
    if isinstance(last, list):
        text = " ".join(str(p.get("text") or "") for p in last if isinstance(p, dict) and p.get("type") == "text")
    else:
        text = str(last or "")
    refs = re.findall(r"@([A-Za-z0-9_.\-/\\]+\.[A-Za-z0-9_]+)", text)
    if not refs:
        return ""
    blocks: list[str] = []
    seen: set[str] = set()
    for raw_ref in refs:
        rel = raw_ref.replace("\\", "/").lstrip("/")
        if rel in seen:
            continue
        seen.add(rel)
        try:
            data = ws.read_file(rel)
            blocks.append(f"\nReferenced file `@{data['path']}`:\n```\n{data['content'][:2400]}\n```")
        except Exception:
            continue
        if len(blocks) >= max_files:
            break
    return "\n".join(blocks)


def run_agent_stream(
    arbiter: GPUArbiter,
    ws: Workspace,
    user_messages: list[dict[str, Any]],
    *,
    active_file: dict[str, str] | None = None,
    mode: str = "agent",
    max_steps: int = 16,
    auto_verify: bool = False,
    test_cmd: str | None = None,
    max_heal_rounds: int = 2,
    cancel_event: threading.Event | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Generator yielding structured IDE events:
      {"type": "status", "text": "..."}
      {"type": "metrics", "step": int, "max_steps": int, "est_ctx_tokens": int, "ctx_limit": int, "compacted": bool}
      {"type": "tool", "name": "...", "args": {...}}
      {"type": "tool_result", "name": "...", "summary": "..."}
      {"type": "file_changed", "path": "...", "added": N, "removed": M, "undo_id": "...", "diff": "...", "deleted": bool}
      {"type": "plan_ready", "plan": "..."}
      {"type": "verify", "passed": bool, "command": "...", "exit_code": int, "output": "...", "round": int}
      {"type": "turn_checkpoint", "undo_ids": [...], "files": [...], "count": int}
      {"type": "delta", "content": "..."}
      {"type": "done", "full_text": "..."}
      {"type": "error", "error": "..."}
    """
    url = f"http://{arbiter.llm_host}:{arbiter.llm_port}/v1/chat/completions"
    at_context = extract_at_file_context(ws, user_messages)
    project_rules = load_project_rules(ws)
    plan_ctx = int((arbiter.coding_plan or {}).get("ctx_size") or 0)
    is_inkling = "inkling" in (arbiter.coding_model or "").lower()
    ctx_limit = plan_ctx if plan_ctx >= 2048 else (16384 if is_inkling else 32768)
    sampling_extra: dict[str, Any] = {
        "temperature": 0.4 if is_inkling else 0.3,
        "top_p": 0.95 if is_inkling else 0.9,
        "min_p": 0.01 if is_inkling else 0.05,
        "cache_prompt": True,
    }
    if is_inkling:
        sampling_extra["reasoning_budget"] = 1536

    # 1) Fast mode: direct complete answer using snapshot (NO tools)
    if mode == "fast":
        snapshot = ws.project_context_snapshot(max_chars=2400)
        active_block = ""
        if active_file and active_file.get("path"):
            active_block = f"\nOpen file `{active_file['path']}`:\n```\n{(active_file.get('content') or '')[:2200]}\n```\n"
        fast_sys = (
            "You are PicoStudio, a concise local coding assistant. "
            "No tools in fast mode; ALL project context is below. "
            "Never say 'let me read files first'. Answer directly in the user's language.\n\n"
            f"{snapshot}{project_rules}{active_block}{at_context}"
        )
        conv_fast: list[dict[str, Any]] = [{"role": "system", "content": fast_sys}] + list(user_messages)
        yield {"type": "metrics", "step": 1, "max_steps": 1, "est_ctx_tokens": estimate_context_tokens(conv_fast), "ctx_limit": ctx_limit, "compacted": False}
        yield {"type": "status", "text": "Proje bağlamıyla yanıt üretiliyor..."}
        use_prefill = is_inkling
        prefill = "### " if use_prefill else ""
        msgs_send = conv_fast + ([{"role": "assistant", "content": prefill}] if use_prefill else [])
        payload = {
            "model": arbiter.coding_model,
            "messages": msgs_send,
            "max_tokens": 1400,
            "stream": True,
            **sampling_extra,
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        full = [prefill] if prefill else []
        if prefill:
            yield {"type": "delta", "content": prefill}
        with urllib.request.urlopen(req, timeout=360) as resp:
            for raw in resp:
                if cancel_event is not None and cancel_event.is_set():
                    yield {"type": "status", "text": "İptal edildi."}
                    yield {"type": "done", "full_text": "".join(full)}
                    return
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
                        full.append(tok)
                        yield {"type": "delta", "content": tok}
        yield {"type": "done", "full_text": "".join(full)}
        return

    # 2) Plan Mode (read-only inspection -> approval card) vs Full Agent v3 Mode (with optional Auto-Verify Self-Heal)
    is_plan_mode = (mode == "plan")
    tools_spec = READONLY_AGENT_TOOLS if is_plan_mode else AGENT_TOOLS
    allowed_names = READONLY_TOOL_NAMES if is_plan_mode else KNOWN_TOOL_NAMES
    effective_steps = min(max_steps, 6) if is_plan_mode else max_steps

    # Keep messages[0] immutable across turns for 100% KV prefix caching; attach per-turn context to latest user msg
    active_hint = f"\n[Active editor file: `{active_file['path']}`]" if (active_file and active_file.get("path")) else ""
    if is_plan_mode:
        sys_prompt = (
            f"You are PicoStudio Planning Agent v3. Workspace: `{ws.root.name}`. "
            "You are in READ-ONLY PLAN MODE. Do NOT modify files. "
            "Use `repo_map`, `find_symbols`, `list_files`, `read_file`, `search_code`, `git_status`, or `git_diff` to inspect efficiently, "
            "then produce a clear, numbered multi-file implementation plan (1. Hedef Dosyalar, 2. Yapılacak Değişiklikler, 3. Test/Doğrulama) in the user's language."
            f"{project_rules}"
        )
    else:
        sys_prompt = (
            f"You are PicoStudio Coding Agent v3. Workspace: `{ws.root.name}`. "
            "Use `repo_map` or `find_symbols` first to locate code quickly, `git_status`/`git_diff` to inspect changes, "
            "and `edit_file` (preferred for targeted edits), `write_file`, `delete_file`, or `run_terminal` to implement and verify. "
            "If an edit reports `[SYNTAX ERROR]`, fix it immediately. Be brief; reply in the user's language."
            f"{project_rules}"
        )

    msgs_copy = [dict(m) for m in user_messages]
    turn_extra = (active_hint + at_context).strip()
    if turn_extra and msgs_copy and msgs_copy[-1].get("role") == "user":
        last_c = msgs_copy[-1].get("content")
        if isinstance(last_c, str):
            msgs_copy[-1]["content"] = last_c + "\n\n" + turn_extra
        elif isinstance(last_c, list):
            msgs_copy[-1]["content"] = list(last_c) + [{"type": "text", "text": "\n" + turn_extra}]

    conv: list[dict[str, Any]] = [{"role": "system", "content": sys_prompt}] + msgs_copy
    final_chunks: list[str] = []
    modified_files: list[str] = []
    turn_undo_ids: list[str] = []
    turn_touched_files: list[str] = []
    recent_call_sigs: list[str] = []
    heal_round = 0
    step = 0

    def _emit_checkpoint() -> dict[str, Any] | None:
        if not turn_undo_ids:
            return None
        return {
            "type": "turn_checkpoint",
            "undo_ids": list(turn_undo_ids),
            "files": sorted(set(turn_touched_files)),
            "count": len(turn_undo_ids),
        }

    while step < effective_steps:
        if cancel_event is not None and cancel_event.is_set():
            yield {"type": "status", "text": "İptal edildi."}
            cp = _emit_checkpoint()
            if cp:
                yield cp
            yield {"type": "done", "full_text": "".join(final_chunks)}
            return
        step += 1
        conv, did_compact = compact_conversation(conv, max_total_chars=int(ctx_limit * 4 * 0.72))
        est_toks = estimate_context_tokens(conv)
        yield {
            "type": "metrics",
            "step": step,
            "max_steps": effective_steps,
            "est_ctx_tokens": est_toks,
            "ctx_limit": ctx_limit,
            "compacted": did_compact,
        }
        phase_lbl = "Plan hazırlanıyor" if is_plan_mode else "Ajan v3 düşünüyor"
        yield {"type": "status", "text": f"{phase_lbl} (adım {step}/{effective_steps})..."}
        payload = {
            "model": arbiter.coding_model,
            "messages": conv,
            "tools": tools_spec,
            "tool_choice": "auto",
            "max_tokens": 4096,
            "stream": True,
            **sampling_extra,
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        step_content: list[str] = []
        tool_calls_map: dict[int, dict[str, Any]] = {}
        r_toks = 0

        with urllib.request.urlopen(req, timeout=360) as resp:
            for raw in resp:
                if cancel_event is not None and cancel_event.is_set():
                    yield {"type": "status", "text": "İptal edildi."}
                    cp = _emit_checkpoint()
                    if cp:
                        yield cp
                    yield {"type": "done", "full_text": "".join(final_chunks)}
                    return
                ln = raw.decode("utf-8", errors="replace").strip()
                if not ln.startswith("data:"):
                    continue
                ds = ln[5:].strip()
                if not ds or ds == "[DONE]":
                    continue
                ev = json.loads(ds)
                ch = ev.get("choices") or []
                if not ch:
                    continue
                delta = ch[0].get("delta") or {}
                if delta.get("reasoning_content"):
                    r_toks += 1
                    if r_toks % 15 == 1:
                        yield {"type": "status", "text": f"{phase_lbl} (adım {step}/{effective_steps} · {r_toks} tok)..."}
                if delta.get("content"):
                    step_content.append(delta["content"])
                    final_chunks.append(delta["content"])
                    yield {"type": "delta", "content": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index", 0))
                    entry = tool_calls_map.setdefault(
                        idx,
                        {"id": tc.get("id") or f"call_{step}_{idx}", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        entry["function"]["arguments"] += fn["arguments"]

        if not tool_calls_map:
            fb_calls = _extract_fallback_tool_calls("".join(step_content), step, allowed=allowed_names)
            if not fb_calls:
                # Plan Mode finishes with an interactive Approval Card
                if is_plan_mode:
                    plan_txt = "".join(final_chunks).strip()
                    yield {"type": "plan_ready", "plan": plan_txt}
                    yield {"type": "done", "full_text": plan_txt}
                    return

                # Agent Mode Auto-Verify & Self-Heal Loop!
                if auto_verify and modified_files:
                    heal_round += 1
                    yield {"type": "status", "text": f"Otomatik test çalıştırılıyor (tur {heal_round})..."}
                    vres = run_workspace_tests(ws, custom_cmd=test_cmd)
                    if vres["ran"]:
                        yield {
                            "type": "verify",
                            "passed": vres["passed"],
                            "command": vres["command"],
                            "exit_code": vres["exit_code"],
                            "output": vres["output"],
                            "round": heal_round,
                        }
                        if not vres["passed"] and heal_round <= max_heal_rounds:
                            conv.append({"role": "assistant", "content": "".join(step_content)})
                            conv.append({
                                "role": "user",
                                "content": (
                                    f"Otomatik test komutu `{vres['command']}` HATA verdi (exit_code={vres['exit_code']}):\n"
                                    f"```\n{vres['output'][-2200:]}\n```\n"
                                    "Hatayı incele, `edit_file` veya `write_file` ile düzelt ve özetle."
                                ),
                            })
                            modified_files.clear()
                            effective_steps = max(effective_steps, step + 4)
                            yield {"type": "status", "text": f"Test başarısız — ajan otomatik düzeltiyor (tur {heal_round}/{max_heal_rounds})..."}
                            continue

                cp = _emit_checkpoint()
                if cp:
                    yield cp
                yield {"type": "done", "full_text": "".join(final_chunks)}
                return
            tool_calls = fb_calls
        else:
            tool_calls = [tool_calls_map[k] for k in sorted(tool_calls_map)]

        conv.append({
            "role": "assistant",
            "content": "".join(step_content) or None,
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            raw_args = tc["function"]["arguments"]
            parse_err = None
            try:
                parsed_args = json.loads(raw_args) if raw_args else {}
            except Exception as exc:
                parsed_args = {}
                parse_err = str(exc)

            sig = f"{fn_name}:{json.dumps(parsed_args, sort_keys=True, ensure_ascii=False)}"
            is_dup_loop = (
                not parse_err
                and len(recent_call_sigs) >= 2
                and recent_call_sigs[-1] == sig
                and recent_call_sigs[-2] == sig
            )
            recent_call_sigs.append(sig)
            if len(recent_call_sigs) > 6:
                recent_call_sigs.pop(0)

            if parse_err:
                result_text = f"ERROR: Tool '{fn_name}' JSON arguments were invalid or truncated ({parse_err}). Retry with valid JSON or write one file at a time."
                change_info = None
            elif is_plan_mode and fn_name not in READONLY_TOOL_NAMES:
                result_text = f"ERROR: Plan modunda '{fn_name}' engellendi. Sadece okuma araclarini kullanin."
                change_info = None
            elif is_dup_loop:
                result_text = (
                    f"ERROR: Repeated identical call to '{fn_name}' detected 3 times in a row. "
                    "Do not repeat the same call; use the information already gathered, try another tool, or finish."
                )
                change_info = None
            else:
                yield {"type": "tool", "name": fn_name, "args": parsed_args}
                result_text, change_info = execute_tool(ws, fn_name, parsed_args)

            if change_info:
                modified_files.append(change_info["path"])
                turn_touched_files.append(change_info["path"])
                if change_info.get("undo_id"):
                    turn_undo_ids.append(change_info["undo_id"])
                yield {
                    "type": "file_changed",
                    "path": change_info["path"],
                    "added": change_info["added"],
                    "removed": change_info["removed"],
                    "undo_id": change_info["undo_id"],
                    "diff": change_info["diff"],
                    "deleted": bool(change_info.get("deleted", False)),
                }
            first_ln = result_text.splitlines()[0][:120] if result_text else "OK"
            if "[SYNTAX ERROR]" in result_text:
                first_ln = first_ln[:70] + " ⚠ SYNTAX ERROR"
            yield {"type": "tool_result", "name": fn_name, "summary": first_ln}
            conv.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            })

    if is_plan_mode:
        plan_txt = "".join(final_chunks).strip()
        yield {"type": "plan_ready", "plan": plan_txt}
    else:
        cp = _emit_checkpoint()
        if cp:
            yield cp
    yield {"type": "done", "full_text": "".join(final_chunks)}
