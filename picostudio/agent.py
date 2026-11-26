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
            "name": "edit_file",
            "description": "Replace exact target text block inside an existing file with replacement text.",
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
            "description": "Create or overwrite a file with full content.",
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
            "name": "run_terminal",
            "description": "Run PowerShell command in project root.",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        },
    },
]


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

        if name == "edit_file":
            rel = str(args.get("path") or "")
            target = str(args.get("target") or "")
            replacement = str(args.get("replacement") or "")
            data = ws.read_file(rel)
            if not target or target not in data["content"]:
                return f"ERROR: Target text not found in {rel}. Read the file first.", None
            new_content = data["content"].replace(target, replacement, 1)
            res = ws.write_file_with_diff(rel, new_content)
            return f"OK: Edited {res['path']} (+{res['added']}/-{res['removed']}).", res

        if name == "write_file":
            rel = str(args.get("path") or "")
            content = str(args.get("content") or "")
            res = ws.write_file_with_diff(rel, content)
            return f"OK: Wrote {res['path']} (+{res['added']}/-{res['removed']}, {res['size']} bytes).", res

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
    url = f"http://{arbiter.llm_host}:{arbiter.llm_port}/v1/chat/completions"

    # Fast mode: direct complete answer using snapshot (NO tools, NO "let me read files" promises!)
    if mode == "fast":
        snapshot = ws.project_context_snapshot(max_chars=2400)
        active_block = ""
        if active_file and active_file.get("path"):
            active_block = f"\nOpen file `{active_file['path']}`:\n```\n{(active_file.get('content') or '')[:2200]}\n```\n"
        fast_sys = (
            "You are PicoStudio, a concise local coding assistant. "
            "No tools in fast mode; ALL project context is below. "
            "Never say 'let me read files first'. Answer directly in the user's language.\n\n"
            f"{snapshot}{active_block}"
        )
        conv_fast: list[dict[str, Any]] = [{"role": "system", "content": fast_sys}] + list(user_messages)
        yield {"type": "status", "text": "Proje bağlamıyla yanıt üretiliyor..."}
        # Only Inkling 2 needs a prefill to skip its <|content_thinking|> block; Qwen streams directly!
        use_prefill = "inkling" in (arbiter.coding_model or "").lower()
        prefill = "### " if use_prefill else ""
        msgs_send = conv_fast + ([{"role": "assistant", "content": prefill}] if use_prefill else [])
        payload = {
            "model": arbiter.coding_model,
            "messages": msgs_send,
            "temperature": 0.3,
            "max_tokens": 1400,
            "stream": True,
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        full = [prefill] if prefill else []
        if prefill:
            yield {"type": "delta", "content": prefill}
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

    # Agent mode: keep initial prompt ultra-compact (~450 tokens) so step 1 starts in ~25-40s instead of 4 min!
    root_items = [x["name"] + ("/" if x["kind"] == "dir" else "") for x in ws.list_tree(max_depth=1, max_items=40)]
    active_hint = f" Open file: `{active_file['path']}`." if (active_file and active_file.get("path")) else ""
    sys_prompt = (
        f"You are PicoStudio local coding agent. Workspace: `{ws.root.name}` "
        f"(root entries: {', '.join(root_items[:25])}).{active_hint} "
        "Use tools (`read_file`, `list_files`, `search_code`, `write_file`, `run_terminal`) directly when needed. "
        "Be brief; reply in the user's language."
    )
    conv: list[dict[str, Any]] = [{"role": "system", "content": sys_prompt}] + list(user_messages)

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
            "max_tokens": 1200,
            "stream": True,
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        step_content: list[str] = []
        tool_calls_map: dict[int, dict[str, Any]] = {}
        r_toks = 0

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
                if delta.get("reasoning_content"):
                    r_toks += 1
                    if r_toks % 15 == 1:
                        yield {"type": "status", "text": f"Ajan düşünüyor (adım {step}/{max_steps} · {r_toks} tok)..."}
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
            result_text, change_info = execute_tool(ws, fn_name, parsed_args)
            if change_info:
                yield {
                    "type": "file_changed",
                    "path": change_info["path"],
                    "added": change_info["added"],
                    "removed": change_info["removed"],
                    "undo_id": change_info["undo_id"],
                    "diff": change_info["diff"],
                }
            first_ln = result_text.splitlines()[0][:120] if result_text else "OK"
            yield {"type": "tool_result", "name": fn_name, "summary": first_ln}
            conv.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            })

    yield {"type": "done", "full_text": "".join(final_chunks)}
