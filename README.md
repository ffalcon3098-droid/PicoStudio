# PicoStudio v0.3.0 — Unified Local IDE, Terminal Pro & Multi-Model AI Studio (Coding + Video + Image)

> [Türkçe dokümantasyon için README.tr.md](README.tr.md)

**PicoStudio** unifies your local **Coding Agents (`PicoCode` · Qwen2.5-Coder-7B + Inkling 2 Mini)** and **Video/Image Studio (`PicoVid` · Wan 2.2 TI2V-5B Turbo, Wan 2.2 14B, Z-Image-Turbo)** into a single zero-dependency **3-pane Dark Web IDE** (`http://127.0.0.1:7900`), **Terminal Pro**, and **Smart Developer CLI** — sharing models zero-copy from sibling `PicoCode` and `localVid` folders with an automatic **6 GB VRAM GPU Arbiter**.

---

## Highlights

- **6 GB VRAM GPU Arbiter (`picostudio/arbiter.py`):** Guarantees zero VRAM collisions on 4–6 GB GPUs. Starting Video/Image diffusion automatically unloads the Coding LLM cleanly, streams live logs, and displays the output MP4/PNG inline inside the IDE.
- **Terminal Pro (`v0.3.0`):**
  - **Multi-Tab Real-Time SSE Streaming:** Run dev servers in Tab 1 while running tests/git in Tab 2, with independent working directories (`cd`) and zero-lag `EventSource` streaming.
  - **Interactive `stdin`, History & `Tab` Autocomplete:** Automatically switches to `stdin>` mode while a process runs (`y/n` prompts, `input()`), with `↑`/`↓` per-tab command history and live `Tab` path completion.
  - **Full ANSI Colors + Clickable `file:line` Links:** Colorized terminal output where Python tracebacks and `path/file.py:42` error paths jump straight to that file and line in the Code Editor.
  - **Resizable Split + Maximize / Collapse:** Drag the vertical divider smoothly or toggle maximize (`⤢`) / collapse (`▾`).
  - **Warp-Style `?` Natural-Language AI Commands:** Prefix any prompt with `?` (e.g., `? 7890 portunu dinleyen sureci goster`) to translate Turkish/English requests into PowerShell commands with a safe `Run / Edit / Cancel` preview bar.
- **3-Pane Dark Web IDE (`http://127.0.0.1:7900`):**
  - **Left:** Multi-project switcher, `+ Yeni Proje`, collapsible file explorer, create file, fast project-wide text search.
  - **Center:** Multi-tab code editor (line numbers, `Ctrl+S` save, 1-click Bug/Refactor/Test actions, inline MP4/PNG viewer) + **Terminal Pro**.
  - **Right:** Two unified tabs — **Kod Ajanı (`Qwen2.5-Coder-7B` & `Inkling 2 Mini`)** with live model switching, real tool-calling (`list_files`, `read_file`, `search_code`, `edit_file`, `write_file`, `run_terminal`), Diff + 1-click **Undo (`Geri Al`)**, Abort (`Dur`), Vision image attach; plus **Video & Görsel (`Wan 2.2` + `Z-Image-Turbo`)** with 1-click **Prompt Enhancer** and clickable gallery.
- **Unified Developer CLI (`.\picostudio.cmd`):**
  - `.\ide.cmd` or `.\picostudio.cmd ide` — Open Local Web IDE (`http://127.0.0.1:7900`)
  - `.\picostudio.cmd status` — Live GPU/VRAM telemetry & inventory of all Coding + Video models
  - `.\picostudio.cmd chat` — Interactive terminal agent (`/file`, `/run`, `/video`, `/image`, `/mode fast|think`)
  - `.\picostudio.cmd ask "prompt" --file app.py` — One-shot coding answer
  - `.\picostudio.cmd video "scene prompt" --engine 5b --cinema-hd` — Generate video (auto-frees coding VRAM)
  - `.\picostudio.cmd image "scene prompt"` — Generate image via `Z-Image-Turbo`

---

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
