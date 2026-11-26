# PicoStudio v0.6.0 — Unified Local IDE Pro, Symbols & F12, Alt+Space AI FIM, Ctrl+K, Terminal Pro & Git

> [Türkçe dokümantasyon için README.tr.md](README.tr.md)

**PicoStudio** unifies your local **Coding Agents (`PicoCode` · Qwen2.5-Coder-7B + Inkling 2 Mini)** and **Video/Image Studio (`PicoVid` · Wan 2.2 TI2V-5B Turbo, Wan 2.2 14B, Z-Image-Turbo)** into a single zero-dependency **3-pane Dark/Light Web IDE Pro** (`http://127.0.0.1:7900`), **Terminal Pro**, **Git & Visual Diff**, and **Smart Developer CLI** — sharing models zero-copy from sibling `PicoCode` and `localVid` folders with an automatic **6 GB VRAM GPU Arbiter**.

---

## Highlights

- **Smart Navigation, `Alt+Space` AI Autocomplete & Project Replace (`v0.6.0`):**
  - **Symbol Outline (`Ctrl+Shift+O`) & `F12` Go-to-Definition (`picostudio/symbols.py`):** Python AST + JS/TS symbol indexer for current-file outline, workspace-wide `#symbol` search, and instant `F12` jump-to-definition.
  - **On-Demand `Alt+Space` AI Code Completion (FIM):** Prefix/suffix-aware local LLM completion bar with `Tab` to accept and `Esc` to dismiss.
  - **Project-Wide Search & Replace (`⇄`):** Safe dry-run previewed multi-file replace with undo snapshots + exact line jump on every search hit.
  - **Auto Project AI Rules (`.picostudio.md` / `AGENTS.md`) + Quick Prompt Chips (`/review`, `/bug`, `/test`, `/refactor`, `/doc`, `/plan`).**
- **Cursor-Style `Ctrl+K` Inline AI Edit & Instant Diagnostics (`v0.5.0`):**
  - Select any code block and press **`Ctrl+K`** to instruct the local LLM with a live unified diff preview and 1-click **Apply**.
  - Instant zero-dependency **Python (`ast.parse`) & JSON syntax diagnostics** banner on open/save with 1-click *Go to Line* and *Fix with AI*.
  - **Resizable 3-Pane Layout (`Ctrl+B` sidebar toggle), `Ctrl+Shift+P` Command Palette, 3 Themes (`Midnight` / `Obsidian` / `Light`) & Font Size (`A-/A+`)** persisted in `localStorage`.
  - **Persistent Per-Project Chat History** (`data/chats/`, never polluting target repos) + live **`@file` Context Autocomplete** in chat.
- **Code Editor Pro (`v0.4.0`):**
  - Real zero-dependency syntax highlighting (Python, JS/TS/JSX/TSX, JSON, HTML, CSS, PowerShell/Bash, Markdown).
  - Auto-indent on Enter, auto-closing brackets & quotes (`() [] {} "" ''`), `Shift+Tab` dedent, `Ctrl+/` comment toggle, live cursor line/col/language status.
  - `Ctrl+F` / `Ctrl+H` in-file Find & Replace with live match highlighting, plus VS Code-style `Ctrl+P` Quick Open fuzzy file palette.
- **Git & Visual Diff Panel (`v0.4.0`):**
  - Dedicated left-pane `Git` tab with live changed-file badge, branch & ahead/behind status, and recent commit log.
  - Visual line-by-line colored Diff Viewer (including untracked file preview), 1-click **Stage (`+`)**, **Unstage (`-`)**, **Revert (`↺`)**, **Commit**, and **✨ AI Commit Message** generator.
- **Coding Agent v2 (`v0.4.0`):**
  - **Plan + Approval Mode (`Planla + Onayla`):** Read-only codebase inspection followed by an interactive Plan Approval Card before any file is modified.
  - **Auto-Test & Self-Heal Loop (`Oto-Test`):** Automatically runs the workspace's test suite (`unittest` / `npm test`) after edits and feeds failures back into the agent to repair automatically.
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
