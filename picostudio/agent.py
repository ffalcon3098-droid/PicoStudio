"""
PicoStudio Local Coding Agent v2 (Tool-Calling + Plan/Approval + Auto-Test Self-Heal).

Gives local coding models (Qwen2.5-Coder-7B, Inkling 2 Mini) real IDE superpowers:
  - Fast Mode: instant project-snapshot response without tool overhead
  - Plan + Approval Mode: read-only codebase inspection -> structured multi-file plan card -> user approval
  - Agent Mode + Auto-Verify Self-Heal:
      * list_files, read_file, search_code, edit_file, write_file, run_terminal
      * Automatically detects and runs workspace tests after edits
      * Feeds test failures back into the agent for automatic self-healing fix rounds
  - Streams structured SSE events (status, tool, tool_result, file_changed, plan_ready, verify, delta, done, error).

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import urllib.request
from typing import Any, Iterator

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

READONLY_TOOL_NAMES = {"list_files", "read_file", "search_code"}
READONLY_AGENT_TOOLS = [t for t in AGENT_TOOLS if t["function"]["name"] in READONLY_TOOL_NAMES]
KNOWN_TOOL_NAMES = {t["function"]["name"] for t in AGENT_TOOLS}


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


def run_workspace_tests(ws: Workspace, custom_cmd: str | None = None, timeout: int = 45) -> dict[str, Any]:
    """Execute workspace tests and return structured pass/fail diagnostics."""
    cmd = (custom_cmd or "").strip() or detect_test_command(ws)
    if not cmd:
        return {"ran": False, "passed": True, "command": "", "exit_code": 0, "output": "Projede otomatik test komutu bulunamadi."}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ws.root) + (os.pathsep + existing_pp if existing_pp else "")
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


def _extract_fallback_tool_calls(text: str, step: int, allowed: set[str] | None = None) -> list[dict[str, Any]]:
    """Parse JSON tool calls emitted in content by models without native OpenAI tool_calls (e.g. Qwen2.5)."""
    import re
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
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", re.I),
    re.compile(r"\bremove-item\b[^\n]*-recurse[^\n]*-force|\bremove-item\b[^\n]*-force[^\n]*-recurse", re.I),
    re.compile(r"\b(del|erase|rmdir|rd)\b[^\n]*(/[sqf]\s*){2,}", re.I),
    re.compile(r"\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*f|\bgit\s+push\s+[^\n]*--force\b", re.I),
    re.compile(r"\b(invoke-expression|iex)\b|\|\s*(sh|bash|powershell|pwsh)\b", re.I),
    re.compile(r"\b(format-volume|diskpart|shutdown|stop-computer|reg\s+delete)\b", re.I),
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

        if name == "edit_file":
            rel = str(args.get("path") or "")
            target = str(args.get("target") or "")
            replacement = str(args.get("replacement") or "")
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
            danger = is_dangerous_command(cmd)
            if danger:
                return f"ERROR: {danger}", None
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
    import re
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
    max_steps: int = 6,
    auto_verify: bool = False,
    test_cmd: str | None = None,
    max_heal_rounds: int = 2,
    cancel_event: threading.Event | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Generator yielding structured IDE events:
      {"type": "status", "text": "..."}
      {"type": "tool", "name": "...", "args": {...}}
      {"type": "tool_result", "name": "...", "summary": "..."}
      {"type": "file_changed", "path": "...", "added": N, "removed": M, "undo_id": "...", "diff": "..."}
      {"type": "plan_ready", "plan": "..."}
      {"type": "verify", "passed": bool, "command": "...", "exit_code": int, "output": "...", "round": int}
      {"type": "delta", "content": "..."}
      {"type": "done", "full_text": "..."}
      {"type": "error", "error": "..."}
    """
    url = f"http://{arbiter.llm_host}:{arbiter.llm_port}/v1/chat/completions"
    at_context = extract_at_file_context(ws, user_messages)
    project_rules = load_project_rules(ws)

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
        yield {"type": "status", "text": "Proje bağlamıyla yanıt üretiliyor..."}
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

    # 2) Plan Mode (read-only inspection -> approval card) vs Full Agent Mode (with optional Auto-Verify Self-Heal)
    is_plan_mode = (mode == "plan")
    tools_spec = READONLY_AGENT_TOOLS if is_plan_mode else AGENT_TOOLS
    allowed_names = READONLY_TOOL_NAMES if is_plan_mode else KNOWN_TOOL_NAMES
    effective_steps = min(max_steps, 4) if is_plan_mode else max_steps

    root_items = [x["name"] + ("/" if x["kind"] == "dir" else "") for x in ws.list_tree(max_depth=1, max_items=40)]
    active_hint = f" Open file: `{active_file['path']}`." if (active_file and active_file.get("path")) else ""
    if is_plan_mode:
        sys_prompt = (
            f"You are PicoStudio Planning Agent. Workspace: `{ws.root.name}` "
            f"(root entries: {', '.join(root_items[:25])}).{active_hint} "
            "You are in READ-ONLY PLAN MODE. Do NOT modify files. "
            "Use `list_files`, `read_file`, or `search_code` if needed, then produce a clear, numbered multi-file "
            "implementation plan (1. Hedef Dosyalar, 2. Yapılacak Değişiklikler, 3. Test/Doğrulama) in the user's language."
            f"{project_rules}{at_context}"
        )
    else:
        sys_prompt = (
            f"You are PicoStudio local coding agent. Workspace: `{ws.root.name}` "
            f"(root entries: {', '.join(root_items[:25])}).{active_hint} "
            "Use tools (`read_file`, `list_files`, `search_code`, `edit_file`, `write_file`, `run_terminal`) directly when needed. "
            "Prefer `edit_file` for targeted changes. Be brief; reply in the user's language."
            f"{project_rules}{at_context}"
        )

    conv: list[dict[str, Any]] = [{"role": "system", "content": sys_prompt}] + list(user_messages)
    final_chunks: list[str] = []
    modified_files: list[str] = []
    heal_round = 0
    step = 0

    while step < effective_steps:
        if cancel_event is not None and cancel_event.is_set():
            yield {"type": "status", "text": "İptal edildi."}
            yield {"type": "done", "full_text": "".join(final_chunks)}
            return
        step += 1
        phase_lbl = "Plan hazırlanıyor" if is_plan_mode else "Ajan düşünüyor"
        yield {"type": "status", "text": f"{phase_lbl} (adım {step}/{effective_steps})..."}
        payload = {
            "model": arbiter.coding_model,
            "messages": conv,
            "tools": tools_spec,
            "tool_choice": "auto",
            "temperature": 0.25,
            "max_tokens": 4096,
            "stream": True,
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        step_content: list[str] = []
        tool_calls_map: dict[int, dict[str, Any]] = {}
        r_toks = 0

        with urllib.request.urlopen(req, timeout=360) as resp:
            for raw in resp:
                if cancel_event is not None and cancel_event.is_set():
                    yield {"type": "status", "text": "İptal edildi."}
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
                            effective_steps = max(effective_steps, step + 3)
                            yield {"type": "status", "text": f"Test başarısız — ajan otomatik düzeltiyor (tur {heal_round}/{max_heal_rounds})..."}
                            continue

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
            if parse_err:
                result_text = f"ERROR: Tool '{fn_name}' JSON arguments were invalid or truncated ({parse_err}). Retry with valid JSON or write one file at a time."
                change_info = None
            elif is_plan_mode and fn_name not in READONLY_TOOL_NAMES:
                result_text = f"ERROR: Plan modunda '{fn_name}' engellendi. Sadece okuma araclarini kullanin."
                change_info = None
            else:
                yield {"type": "tool", "name": fn_name, "args": parsed_args}
                result_text, change_info = execute_tool(ws, fn_name, parsed_args)
            if change_info:
                modified_files.append(change_info["path"])
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

    if is_plan_mode:
        plan_txt = "".join(final_chunks).strip()
        yield {"type": "plan_ready", "plan": plan_txt}
    yield {"type": "done", "full_text": "".join(final_chunks)}
