"""
PicoStudio Safe Local Git & Visual Diff Engine.

Provides zero-dependency git status, line-by-line structured diff (including untracked files),
stage/unstage, safe path-validated revert, commit, and commit history for the active workspace.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import difflib
import pathlib
import re
import subprocess
from typing import Any

from picostudio.workspace import Workspace


def _run_git(cwd: pathlib.Path, args: list[str], timeout: int = 15) -> tuple[int, str, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
        )
        return res.returncode, res.stdout or "", res.stderr or ""
    except FileNotFoundError:
        return 127, "", "git bulunamadi (PATH icinde degil)."
    except subprocess.TimeoutExpired:
        return 124, "", "git komutu zaman asimina ugradi."


def is_git_repo(ws: Workspace) -> bool:
    rc, out, _ = _run_git(ws.root, ["rev-parse", "--is-inside-work-tree"])
    return rc == 0 and out.strip().lower() == "true"


def get_status(ws: Workspace) -> dict[str, Any]:
    if not is_git_repo(ws):
        return {
            "is_repo": False,
            "branch": "",
            "ahead": 0,
            "behind": 0,
            "staged": [],
            "unstaged": [],
            "untracked": [],
            "total_changes": 0,
        }

    rc, out, err = _run_git(ws.root, ["status", "--porcelain=v1", "-b", "-uall"])
    if rc != 0:
        return {
            "is_repo": False,
            "error": err.strip(),
            "branch": "",
            "ahead": 0,
            "behind": 0,
            "staged": [],
            "unstaged": [],
            "untracked": [],
            "total_changes": 0,
        }

    branch = ""
    ahead = 0
    behind = 0
    staged: list[dict[str, str]] = []
    unstaged: list[dict[str, str]] = []
    untracked: list[dict[str, str]] = []

    for line in out.splitlines():
        if line.startswith("## "):
            hdr = line[3:].strip()
            m_b = re.match(r"^(?:No commits yet on )?([^\s.]+)", hdr)
            if m_b:
                branch = m_b.group(1)
            m_a = re.search(r"ahead (\d+)", hdr)
            m_d = re.search(r"behind (\d+)", hdr)
            ahead = int(m_a.group(1)) if m_a else 0
            behind = int(m_d.group(1)) if m_d else 0
            continue
        if len(line) < 4:
            continue
        x, y = line[0], line[1]
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        raw_path = raw_path.strip('"')
        if x == "?" and y == "?":
            untracked.append({"path": raw_path, "code": "??"})
        else:
            if x != " ":
                staged.append({"path": raw_path, "code": x})
            if y != " ":
                unstaged.append({"path": raw_path, "code": y})

    return {
        "is_repo": True,
        "branch": branch or "HEAD",
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "total_changes": len(staged) + len(unstaged) + len(untracked),
    }


def _parse_unified_diff(diff_text: str) -> dict[str, Any]:
    lines: list[dict[str, str]] = []
    added = 0
    removed = 0
    for ln in diff_text.splitlines()[:800]:
        if ln.startswith("@@"):
            lines.append({"type": "hunk", "text": ln})
        elif ln.startswith("+++") or ln.startswith("---") or ln.startswith("diff --git") or ln.startswith("index "):
            lines.append({"type": "meta", "text": ln})
        elif ln.startswith("+"):
            added += 1
            lines.append({"type": "add", "text": ln})
        elif ln.startswith("-"):
            removed += 1
            lines.append({"type": "del", "text": ln})
        else:
            lines.append({"type": "ctx", "text": ln})
    return {"added": added, "removed": removed, "lines": lines, "raw": diff_text[:20000]}


def get_diff(ws: Workspace, rel_path: str = "", staged: bool = False) -> dict[str, Any]:
    if not is_git_repo(ws):
        return {"error": "Bu klasor bir Git reposu degil.", "added": 0, "removed": 0, "lines": [], "raw": ""}

    rel_clean = (rel_path or "").strip()
    if rel_clean:
        p = ws.safe_path(rel_clean)
        rel_clean = p.relative_to(ws.root).as_posix()

    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if rel_clean:
        args += ["--", rel_clean]

    rc, out, _ = _run_git(ws.root, args)
    if rc == 0 and out.strip():
        return {"path": rel_clean or "(tum degisiklikler)", "staged": staged, **_parse_unified_diff(out)}

    # Handle untracked file preview by diffing against empty content
    if rel_clean and not staged:
        p = ws.safe_path(rel_clean)
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace").splitlines()
                u = "\n".join(
                    difflib.unified_diff([], content, fromfile="/dev/null", tofile=f"b/{rel_clean}", lineterm="")
                )
                return {"path": rel_clean, "staged": False, "untracked": True, **_parse_unified_diff(u)}
            except OSError:
                pass

    return {"path": rel_clean or "(tum degisiklikler)", "staged": staged, "added": 0, "removed": 0, "lines": [], "raw": ""}


def stage_path(ws: Workspace, rel_path: str | None = None) -> tuple[bool, str]:
    if not is_git_repo(ws):
        return False, "Git reposu bulunamadi."
    if rel_path and rel_path.strip():
        p = ws.safe_path(rel_path)
        rel = p.relative_to(ws.root).as_posix()
        rc, _, err = _run_git(ws.root, ["add", "--", rel])
    else:
        rc, _, err = _run_git(ws.root, ["add", "-A"])
    return (rc == 0), (err.strip() or "OK")


def unstage_path(ws: Workspace, rel_path: str | None = None) -> tuple[bool, str]:
    if not is_git_repo(ws):
        return False, "Git reposu bulunamadi."
    if rel_path and rel_path.strip():
        p = ws.safe_path(rel_path)
        rel = p.relative_to(ws.root).as_posix()
        rc, _, err = _run_git(ws.root, ["reset", "HEAD", "--", rel])
        if rc != 0:
            rc, _, err = _run_git(ws.root, ["rm", "--cached", "--", rel])
    else:
        rc, _, err = _run_git(ws.root, ["reset", "HEAD"])
    return (rc == 0), (err.strip() or "OK")


def revert_path(ws: Workspace, rel_path: str) -> tuple[bool, str]:
    if not is_git_repo(ws):
        return False, "Git reposu bulunamadi."
    p = ws.safe_path(rel_path)
    rel = p.relative_to(ws.root).as_posix()
    # Check if file is tracked in git
    rc_ls, out_ls, _ = _run_git(ws.root, ["ls-files", "--", rel])
    if rc_ls == 0 and out_ls.strip():
        rc, _, err = _run_git(ws.root, ["checkout", "--", rel])
        return (rc == 0), (err.strip() or f"{rel} geri yuklendi.")
    # Untracked file inside workspace -> safe delete
    if p.exists() and p.is_file():
        p.unlink()
        return True, f"Izlenmeyen dosya silindi: {rel}"
    return False, f"Dosya bulunamadi: {rel}"


def commit_changes(ws: Workspace, message: str) -> dict[str, Any]:
    if not is_git_repo(ws):
        return {"ok": False, "error": "Git reposu bulunamadi."}
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "error": "Commit mesaji bos olamaz."}
    rc, out, err = _run_git(ws.root, ["commit", "-m", msg])
    if rc != 0:
        return {"ok": False, "error": (err or out).strip() or "Commit basarisiz."}
    _, h_out, _ = _run_git(ws.root, ["rev-parse", "--short", "HEAD"])
    return {"ok": True, "hash": h_out.strip(), "summary": out.strip().splitlines()[0] if out.strip() else "Committed"}


def get_log(ws: Workspace, limit: int = 12) -> list[dict[str, str]]:
    if not is_git_repo(ws):
        return []
    rc, out, _ = _run_git(ws.root, ["log", f"-n{max(1, min(30, limit))}", "--pretty=format:%h|%an|%ar|%s"])
    if rc != 0:
        return []
    items: list[dict[str, str]] = []
    for ln in out.splitlines():
        parts = ln.split("|", 3)
        if len(parts) == 4:
            items.append({"hash": parts[0], "author": parts[1], "when": parts[2], "subject": parts[3]})
    return items
