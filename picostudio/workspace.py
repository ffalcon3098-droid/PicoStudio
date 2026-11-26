"""
PicoStudio Safe Local Workspace & File Engine.

Provides path-traversal-safe file browsing, reading, saving, creation, deletion,
and fast text search across any local project folder.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import pathlib
from typing import Any

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "models", "engine", "build", "dist", ".pytest_cache", ".mypy_cache",
}
TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md",
    ".txt", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".cmd", ".bat", ".ps1",
    ".sh", ".sql", ".csv", ".xml", ".c", ".cpp", ".h", ".hpp", ".rs", ".go",
    ".gitignore", ".env",
}
MAX_READ_BYTES = 512 * 1024


class Workspace:
    def __init__(self, root: str | pathlib.Path, projects_root: str | pathlib.Path | None = None) -> None:
        self.root = pathlib.Path(root).resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
        self.projects_root = pathlib.Path(projects_root).resolve() if projects_root else self.root.parent

    def set_root(self, new_root: str | pathlib.Path) -> pathlib.Path:
        cand = pathlib.Path(new_root)
        if not cand.is_absolute():
            cand = self.projects_root / cand
        cand = cand.resolve()
        if not cand.exists() or not cand.is_dir():
            raise FileNotFoundError(f"Klasor bulunamadi: {cand}")
        self.root = cand
        return self.root

    def list_projects(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if self.projects_root.exists():
            for d in sorted(self.projects_root.iterdir(), key=lambda x: x.name.lower()):
                if d.is_dir() and not d.name.startswith("."):
                    out.append({"name": d.name, "path": str(d.resolve())})
        return out

    def safe_path(self, rel_path: str) -> pathlib.Path:
        rel_clean = (rel_path or "").replace("\\", "/").lstrip("/")
        target = (self.root / rel_clean).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError(f"Calisma alani disina erisim engellendi: {rel_path}") from exc
        return target

    def list_tree(self, max_depth: int = 4, max_items: int = 400) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        def _walk(cur: pathlib.Path, depth: int) -> None:
            if depth > max_depth or len(items) >= max_items:
                return
            try:
                entries = sorted(cur.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError:
                return
            for entry in entries:
                if len(items) >= max_items:
                    return
                if entry.is_dir():
                    if entry.name in IGNORE_DIRS or entry.name.startswith("."):
                        continue
                    rel = entry.relative_to(self.root).as_posix()
                    items.append({"path": rel, "name": entry.name, "kind": "dir", "depth": depth})
                    _walk(entry, depth + 1)
                else:
                    rel = entry.relative_to(self.root).as_posix()
                    try:
                        sz = entry.stat().st_size
                    except OSError:
                        sz = 0
                    items.append({"path": rel, "name": entry.name, "kind": "file", "depth": depth, "size": sz})

        _walk(self.root, 0)
        return items

    def read_file(self, rel_path: str) -> dict[str, Any]:
        p = self.safe_path(rel_path)
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"Dosya bulunamadi: {rel_path}")
        sz = p.stat().st_size
        if sz > MAX_READ_BYTES:
            raise ValueError(f"Dosya editor icin cok buyuk ({sz // 1024} KB > 512 KB)")
        content = p.read_text(encoding="utf-8", errors="replace")
        return {"path": p.relative_to(self.root).as_posix(), "content": content, "size": sz}

    def write_file(self, rel_path: str, content: str) -> dict[str, Any]:
        p = self.safe_path(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": p.relative_to(self.root).as_posix(), "size": p.stat().st_size}

    def delete_file(self, rel_path: str) -> bool:
        p = self.safe_path(rel_path)
        if p == self.root or not p.exists() or p.is_dir():
            return False
        p.unlink()
        return True

    def search(self, query: str, max_hits: int = 50) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        hits: list[dict[str, Any]] = []
        for item in self.list_tree(max_depth=5, max_items=600):
            if item["kind"] != "file" or item["size"] > MAX_READ_BYTES:
                continue
            p = self.root / item["path"]
            if p.suffix.lower() not in TEXT_EXTS and p.name not in ("LICENSE", "Makefile", "Dockerfile"):
                continue
            try:
                for idx, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if q in line.lower():
                        hits.append({"path": item["path"], "line": idx, "text": line.strip()[:160]})
                        if len(hits) >= max_hits:
                            return hits
            except OSError:
                continue
        return hits
