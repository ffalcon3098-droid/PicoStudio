"""
PicoStudio Persistent Per-Project Chat Session Store.

Stores conversation threads inside PicoStudio's own `data/chats/` directory keyed by
project path hash, so target project repositories are NEVER polluted with untracked files.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import time
import uuid
from typing import Any


class ChatSessionStore:
    def __init__(self, base_dir: str | pathlib.Path) -> None:
        self.base_dir = pathlib.Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_root: str | pathlib.Path) -> pathlib.Path:
        norm = str(pathlib.Path(project_root).resolve()).lower()
        key = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]
        d = self.base_dir / key
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_sessions(self, project_root: str | pathlib.Path, limit: int = 25) -> list[dict[str, Any]]:
        d = self._project_dir(project_root)
        items: list[dict[str, Any]] = []
        for fp in d.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
                items.append({
                    "id": data.get("id") or fp.stem,
                    "title": data.get("title") or "Sohbet",
                    "updated_at": float(data.get("updated_at") or fp.stat().st_mtime),
                    "count": len(data.get("messages") or []),
                })
            except Exception:
                continue
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items[:limit]

    def load_session(self, project_root: str | pathlib.Path, session_id: str) -> dict[str, Any] | None:
        sid = "".join(c for c in (session_id or "") if c.isalnum() or c in ("-", "_"))
        if not sid:
            return None
        fp = self._project_dir(project_root) / f"{sid}.json"
        if not fp.is_file():
            return None
        try:
            return json.loads(fp.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return None

    def save_session(
        self,
        project_root: str | pathlib.Path,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        sid = "".join(c for c in (session_id or "") if c.isalnum() or c in ("-", "_")) or f"chat_{uuid.uuid4().hex[:8]}"
        clean_msgs: list[dict[str, Any]] = []
        auto_title = ""
        for m in (messages or [])[-60:]:
            role = str(m.get("role") or "user")
            content = m.get("content")
            # Strip huge inline base64 images when persisting history
            if isinstance(content, list):
                txt_parts = [str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                content = " ".join(txt_parts).strip() or "[Image]"
            else:
                content = str(content or "")
            if role == "user" and not auto_title and content.strip():
                auto_title = content.strip().splitlines()[0][:56]
            clean_msgs.append({"role": role, "content": content[:12000]})

        rec = {
            "id": sid,
            "project": str(pathlib.Path(project_root).resolve()),
            "title": (title or "").strip() or auto_title or "New Chat",
            "updated_at": time.time(),
            "messages": clean_msgs,
        }
        fp = self._project_dir(project_root) / f"{sid}.json"
        fp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"id": sid, "title": rec["title"], "updated_at": rec["updated_at"], "count": len(clean_msgs)}

    def delete_session(self, project_root: str | pathlib.Path, session_id: str) -> bool:
        sid = "".join(c for c in (session_id or "") if c.isalnum() or c in ("-", "_"))
        if not sid:
            return False
        fp = self._project_dir(project_root) / f"{sid}.json"
        if fp.is_file():
            fp.unlink()
            return True
        return False
