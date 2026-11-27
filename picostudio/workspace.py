"""
PicoStudio Safe Local Workspace & File Engine.

Provides path-traversal-safe file browsing, reading, saving, creation, deletion,
and fast text search across any local project folder.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import difflib
import pathlib
import threading
import uuid
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
        self._initial_root = self.root
        self._lock = threading.RLock()
        self._undo_store: dict[str, dict[str, Any]] = {}

    def set_root(self, new_root: str | pathlib.Path) -> pathlib.Path:
        cand = pathlib.Path(new_root)
        if not cand.is_absolute():
            cand = self.projects_root / cand
        cand = cand.resolve()
        if not cand.is_relative_to(self.projects_root) and cand != self._initial_root:
            raise PermissionError(
                f"Proje kok dizini disina gecis engellendi: {cand} (izinli kok: {self.projects_root})"
            )
        if not cand.exists() or not cand.is_dir():
            raise FileNotFoundError(f"Klasor bulunamadi: {cand}")
        with self._lock:
            self.root = cand
        return cand

    def create_project(self, name_or_path: str) -> pathlib.Path:
        raw = (name_or_path or "").strip().strip('"').strip("'")
        if not raw:
            raise ValueError("Proje adi bos olamaz.")
        cand = pathlib.Path(raw)
        if not cand.is_absolute():
            if ".." in cand.parts:
                raise PermissionError("Gecersiz proje adi.")
            cand = self.projects_root / cand
        cand = cand.resolve()
        # Security boundary: prevent creating/pivoting projects outside projects_root
        try:
            cand.relative_to(self.projects_root)
        except ValueError as exc:
            raise PermissionError(
                f"Proje kok dizini disinda proje olusturulamaz: {cand} (izinli kok: {self.projects_root})"
            ) from exc
        cand.mkdir(parents=True, exist_ok=True)
        self.root = cand
        return self.root

    def list_projects(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        if self.projects_root.exists():
            for d in sorted(self.projects_root.iterdir(), key=lambda x: x.name.lower()):
                if d.is_dir() and not d.name.startswith("."):
                    rp = str(d.resolve())
                    out.append({"name": d.name, "path": rp})
                    seen.add(rp)
        cur = str(self.root.resolve())
        if cur not in seen:
            out.append({"name": self.root.name, "path": cur})
        return out

    def safe_path(self, rel_path: str) -> pathlib.Path:
        raw = (rel_path or "").strip()
        cand = pathlib.Path(raw)
        if cand.is_absolute():
            target = cand.resolve()
        else:
            rel_clean = raw.replace("\\", "/").lstrip("/")
            target = (self.root / rel_clean).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError(
                f"Calisma alani disina erisim engellendi: {rel_path} "
                f"(Yeni proje klasoru olusturmak icin ustteki '+ Yeni Proje' butonunu kullanin)"
            ) from exc
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
        raw = p.read_bytes()
        if b"\x00" in raw[:8192]:
            raise ValueError(f"Ikili (binary) dosya metin editorunde acilamaz: {rel_path}")
        content = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
        return {"path": p.relative_to(self.root).as_posix(), "content": content, "size": sz}

    def write_file(self, rel_path: str, content: str) -> dict[str, Any]:
        p = self.safe_path(rel_path)
        orig_eol = "\r\n" if (p.is_file() and b"\r\n" in p.read_bytes()[:65536]) else "\n"
        norm = content.replace("\r\n", "\n")
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline=orig_eol) as fh:
            fh.write(norm)
        return {"path": p.relative_to(self.root).as_posix(), "size": p.stat().st_size}

    def write_file_with_diff(self, rel_path: str, content: str) -> dict[str, Any]:
        """Write file while recording a byte-exact undo snapshot and unified diff stats."""
        p = self.safe_path(rel_path)
        existed = p.exists() and p.is_file()
        old_bytes = p.read_bytes() if existed else b""
        if existed and b"\x00" in old_bytes[:8192]:
            raise ValueError(f"Ikili (binary) dosya metin olarak duzenlenemez: {rel_path}")
        old_text = old_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n") if existed else ""
        res = self.write_file(rel_path, content)
        undo_id = uuid.uuid4().hex[:10]
        with self._lock:
            self._undo_store[undo_id] = {
                "abs_path": str(p),
                "rel_path": res["path"],
                "existed": existed,
                "old_bytes": old_bytes,
            }
            if len(self._undo_store) > 120:
                oldest = next(iter(self._undo_store))
                del self._undo_store[oldest]
        diff_lines = list(
            difflib.unified_diff(
                old_text.splitlines(),
                content.replace("\r\n", "\n").splitlines(),
                fromfile=f"a/{res['path']}",
                tofile=f"b/{res['path']}",
                n=2,
                lineterm="",
            )
        )
        added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))
        return {
            **res,
            "undo_id": undo_id,
            "added": added,
            "removed": removed,
            "diff": "\n".join(diff_lines[:80]),
        }

    def undo_edit(self, undo_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._undo_store.pop(undo_id, None)
        if not rec:
            raise KeyError("Geri alma kaydi bulunamadi veya zaten geri alindi.")
        p = pathlib.Path(rec["abs_path"])
        if rec["existed"]:
            p.parent.mkdir(parents=True, exist_ok=True)
            if "old_bytes" in rec:
                p.write_bytes(rec["old_bytes"])
            else:
                p.write_text(rec.get("old_content", ""), encoding="utf-8")
            return {"restored": True, "deleted": False, "path": rec["rel_path"]}
        if p.exists():
            p.unlink()
        return {"restored": False, "deleted": True, "path": rec["rel_path"]}

    def undo_batch(self, undo_ids: list[str]) -> dict[str, Any]:
        """Revert multiple recorded edits in reverse chronological order (turn checkpoint rollback)."""
        restored: list[str] = []
        deleted: list[str] = []
        count = 0
        for uid in reversed(list(undo_ids or [])):
            with self._lock:
                present = uid in self._undo_store
            if not present:
                continue
            res = self.undo_edit(uid)
            count += 1
            if res["deleted"]:
                if res["path"] not in deleted:
                    deleted.append(res["path"])
            elif res["path"] not in restored:
                restored.append(res["path"])
        if count == 0:
            raise KeyError("Geri alinacak gecerli kayit bulunamadi veya zaten geri alindi.")
        return {"count": count, "restored_paths": restored, "deleted_paths": deleted}

    def delete_file(self, rel_path: str) -> bool:
        p = self.safe_path(rel_path)
        if p == self.root or not p.exists() or p.is_dir():
            return False
        p.unlink()
        return True

    def delete_file_with_undo(self, rel_path: str) -> dict[str, Any]:
        """Delete a file while recording a byte-exact undo snapshot so the deletion can be reverted."""
        p = self.safe_path(rel_path)
        if p == self.root or not p.exists() or p.is_dir():
            raise FileNotFoundError(f"Silinecek dosya bulunamadi: {rel_path}")
        rel = p.relative_to(self.root).as_posix()
        old_bytes = p.read_bytes()
        old_text = old_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n")
        p.unlink()
        undo_id = uuid.uuid4().hex[:10]
        with self._lock:
            self._undo_store[undo_id] = {
                "abs_path": str(p),
                "rel_path": rel,
                "existed": True,
                "old_bytes": old_bytes,
            }
            if len(self._undo_store) > 120:
                oldest = next(iter(self._undo_store))
                del self._undo_store[oldest]
        diff_lines = list(
            difflib.unified_diff(
                old_text.splitlines(),
                [],
                fromfile=f"a/{rel}",
                tofile="/dev/null",
                n=0,
                lineterm="",
            )
        )
        removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))
        return {
            "path": rel,
            "undo_id": undo_id,
            "added": 0,
            "removed": removed,
            "deleted": True,
            "diff": "\n".join(diff_lines[:60]),
        }

    def project_context_snapshot(self, max_chars: int = 3600) -> str:
        """Build a compact, high-signal project overview (tree + key config/README files) for the AI agent."""
        lines: list[str] = [f"Project root: {self.root.name} ({self.root})"]
        lines.append("\nDirectory tree:")
        tree = self.list_tree(max_depth=3, max_items=100)
        binary_dirs: dict[str, int] = {}
        tree_chars = 0
        for item in tree:
            p = item["path"]
            if item["kind"] == "file" and pathlib.Path(p).suffix.lower() in (".glb", ".gltf", ".png", ".jpg", ".mp4", ".wav", ".mp3", ".sqlite", ".sqlite-wal", ".sqlite-shm", ".bin", ".gguf", ".safetensors"):
                parent = pathlib.Path(p).parent.as_posix()
                binary_dirs[parent] = binary_dirs.get(parent, 0) + 1
                continue
            if tree_chars < 1100:
                ln = f"  {'  ' * item['depth']}{item['name']}{'/' if item['kind'] == 'dir' else ''}"
                lines.append(ln)
                tree_chars += len(ln) + 1
        if binary_dirs:
            lines.append("Binary/asset folders:")
            for d, cnt in sorted(binary_dirs.items()):
                lines.append(f"  {d}/ ({cnt} files)")

        # Reserve ample budget for actual README / package.json / PRD contents
        key_candidates = [
            "README.md", "README.tr.md", "package.json", "pyproject.toml", "tsconfig.json",
            "requirements.txt", "apps/client/package.json", "apps/server/package.json", "docs/PRD.md",
        ]
        used = sum(len(x) + 1 for x in lines)
        for rel in key_candidates:
            fp = self.root / rel
            if not fp.exists() or not fp.is_file():
                continue
            budget = max_chars - used
            if budget < 250:
                break
            try:
                txt = fp.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            snippet = txt[: min(1100, budget - 60)]
            block = f"\n--- {rel} ---\n{snippet}"
            lines.append(block)
            used += len(block)

        # If no standard manifest existed (e.g. small Python folder), peek first 2 small source files
        if used < 1200:
            for item in tree:
                if item["kind"] != "file" or item["size"] > 12000:
                    continue
                fp = self.root / item["path"]
                if fp.suffix.lower() not in (".py", ".ts", ".tsx", ".js", ".html"):
                    continue
                budget = max_chars - used
                if budget < 250:
                    break
                try:
                    txt = fp.read_text(encoding="utf-8", errors="replace").strip()[: min(1100, budget - 60)]
                    block = f"\n--- {item['path']} ---\n{txt}"
                    lines.append(block)
                    used += len(block)
                except OSError:
                    continue
        return "\n".join(lines)[:max_chars]

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

    def replace_in_project(self, query: str, replacement: str, *, dry_run: bool = False, max_files: int = 80) -> dict[str, Any]:
        """Case-sensitive safe multi-file search & replace across workspace text files (with undo snapshots)."""
        q = query or ""
        if not q:
            return {"ok": False, "error": "Aranacak metin bos olamaz.", "files": [], "total_replacements": 0}
        changed: list[dict[str, Any]] = []
        total = 0
        for item in self.list_tree(max_depth=5, max_items=600):
            if item["kind"] != "file" or item["size"] > MAX_READ_BYTES:
                continue
            p = self.root / item["path"]
            if p.suffix.lower() not in TEXT_EXTS and p.name not in ("LICENSE", "Makefile", "Dockerfile"):
                continue
            try:
                old_text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            cnt = old_text.count(q)
            if cnt <= 0:
                continue
            total += cnt
            entry: dict[str, Any] = {"path": item["path"], "count": cnt}
            if not dry_run:
                new_text = old_text.replace(q, replacement)
                res = self.write_file_with_diff(item["path"], new_text)
                entry["undo_id"] = res["undo_id"]
            changed.append(entry)
            if len(changed) >= max_files:
                break
        return {"ok": True, "dry_run": dry_run, "files": changed, "total_replacements": total}
