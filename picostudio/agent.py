"""
PicoStudio Real Tool-Calling Local Coding Agent.

Gives local Inkling 2 Mini (and Qwen3-Coder) real IDE superpowers:
  - Automatic project snapshot (clean file tree + README / package.json / key configs)
  - Live multi-step OpenAI tool-calling loop:
      * list_files(subdir)
      * read_file(path, start_line, end_line)
      * search_code(query)
      * write_file(path, content)
      * run_terminal(command)
  - Streams structured SSE events (status, tool_call, tool_result, delta, file_changed, done)
    so the Web IDE shows real-time agent steps and auto-reloads modified files!

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from typing import Any, Callable, Iterator

from picostudio.arbiter import GPUArbiter
from picostudio.workspace import Workspace

AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories inside the active project workspace (optional relative subdirectory).",
            "parameters": {
                "type": "object",
                "properties": {
                    "subdir": {"type": "string", "description": "Relative subdirectory path, or empty string for project root."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text/source file from the active project workspace with optional 1-based line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file (e.g. 'README.md' or 'apps/server/src/index.ts')."},
                    "start_line": {"type": "integer", "description": "Optional 1-based start line (default 1)."},
                    "end_line": {"type": "integer", "description": "Optional 1-based end line (default 200)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a text substring across source files in the active project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Case-insensitive text to search for."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file in the active project workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to write."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_terminal",
            "description": "Run a shell command in the active project root and return stdout/stderr and exit code (timeout 30s).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell command to execute."},
                },
                "required": ["command"],
            },
        },
    },
]


def execute_tool(ws: Workspace, name: str, args: dict[str, Any]) -> tuple[str, str | None]:
    """Execute one workspace tool safely. Returns (result_text, modified_rel_path_or_None)."""
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

        if name == "write_file":
            rel = str(args.get("path") or "")
            content = str(args.get("content") or "")
            res = ws.write_file(rel, content)
            return f"OK: Wrote {res['path']} ({res['size']} bytes).", res["path"]

        if name == "run_terminal":
            cmd = str(args.get("command") or "").strip()
            if not cmd:
                return "ERROR: Empty command.", None
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                cwd=str(ws.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                creationflags=flags,
            )
            out = ((res.stdout or "") + ("\n" + res.stderr if res.stderr else "")).strip()
            return f"exit_code={res.returncode}\n{out[:5000]}", None

        return f"ERROR: Unknown tool {name}", None
    except Exception as exc:
        return f"ERROR: {exc}", None


def run_agent_stream(
    arbiter: GPUArbiter,
    ws: Workspace,
    user_messages: list[dict[str, Any]],
    *,
    active_file: dict[str, str] | None = None,
    mode: str = "agent",
    max_steps: int = 5,
) -> Iterator[dict[str, Any]]:
    """
    Generator yielding structured IDE events:
      {"type": "status", "text": "..."}
      {"type": "tool", "name": "...", "args": {...}}
      {"type": "tool_result", "name": "...", "summary": "..."}
      {"type": "file_changed", "path": "..."}
      {"type": "delta", "content": "..."}
      {"type": "done", "full_text": "..."}
      {"type": "error", "error": "..."}
    """
    snapshot = ws.project_context_snapshot(max_chars=4500)
    active_block = ""
    if active_file and active_file.get("path"):
        active_block = (
            f"\nCurrently open file in IDE editor: `{active_file['path']}`\n"
            f"```\n{(active_file.get('content') or '')[:5000]}\n```\n"
        )

    sys_prompt = (
        "You are PicoStudio, an expert local coding agent inside a Windows IDE.\n"
        "You ALWAYS ground your answers in the real project files below — NEVER invent placeholder code "
        "when the user asks to analyze or modify their project. Respond in the user's language (Turkish if they write Turkish).\n"
        "If you need to inspect more files, search code, edit a file, or run tests, call the provided tools.\n"
        "Keep answers concrete, clear, and concise.\n\n"
        f"=== ACTIVE PROJECT SNAPSHOT ===\n{snapshot}\n{active_block}"
    )

    conv: list[dict[str, Any]] = [{"role": "system", "content": sys_prompt}] + list(user_messages)
    url = f"http://{arbiter.llm_host}:{arbiter.llm_port}/v1/chat/completions"

    # Fast mode: skip tool loop & prefill concise direct answer (still has full project snapshot!)
    if mode == "fast":
        yield {"type": "status", "text": "Proje bağlamıyla yanıt üretiliyor..."}
        payload = {
            "model": arbiter.coding_model,
            "messages": conv + [{"role": "assistant", "content": "Proje dosyalarına göre:\n"}],
            "temperature": 0.3,
            "max_tokens": 1800,
            "stream": True,
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        full = ["Proje dosyalarına göre:\n"]
        yield {"type": "delta", "content": full[0]}
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
                        full.append(tok)
                        yield {"type": "delta", "content": tok}
        yield {"type": "done", "full_text": "".join(full)}
        return

    # Full tool-calling Agent loop (up to max_steps)
    final_chunks: list[str] = []
    for step in range(1, max_steps + 1):
        yield {"type": "status", "text": f"Ajan düşünüyor (adım {step}/{max_steps})..."}
        payload = {
            "model": arbiter.coding_model,
            "messages": conv,
            "tools": AGENT_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.25,
            "max_tokens": 1800,
            "stream": True,
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        step_content: list[str] = []
        tool_calls_map: dict[int, dict[str, Any]] = {}

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
                if not ch:
                    continue
                delta = ch[0].get("delta") or {}
                if delta.get("content"):
                    step_content.append(delta["content"])
                    final_chunks.append(delta["content"])
                    yield {"type": "delta", "content": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index", 0))
                    entry = tool_calls_map.setdefault(idx, {"id": tc.get("id") or f"call_{step}_{idx}", "type": "function", "function": {"name": "", "arguments": ""}})
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        entry["function"]["arguments"] += fn["arguments"]

        if not tool_calls_map:
            yield {"type": "done", "full_text": "".join(final_chunks)}
            return

        tool_calls = [tool_calls_map[k] for k in sorted(tool_calls_map)]
        conv.append({
            "role": "assistant",
            "content": "".join(step_content) or None,
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            raw_args = tc["function"]["arguments"]
            try:
                parsed_args = json.loads(raw_args) if raw_args else {}
            except Exception:
                parsed_args = {}
            yield {"type": "tool", "name": fn_name, "args": parsed_args}
            result_text, modified_path = execute_tool(ws, fn_name, parsed_args)
            if modified_path:
                yield {"type": "file_changed", "path": modified_path}
            first_ln = result_text.splitlines()[0][:120] if result_text else "OK"
            yield {"type": "tool_result", "name": fn_name, "summary": first_ln}
            conv.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            })

    yield {"type": "done", "full_text": "".join(final_chunks)}
