# PicoStudio v0.12.0 — Local IDE Pro, Coding Agent v3, Side-by-Side Review & LTX-2.3 Audio+Video Studio (AMD & NVIDIA)

[![Regression Tests](https://github.com/ffalcon3098-droid/PicoStudio/actions/workflows/tests.yml/badge.svg)](https://github.com/ffalcon3098-droid/PicoStudio/actions/workflows/tests.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> [Türkçe dokümantasyon için README.tr.md](README.tr.md) · **Platform:** Windows 10/11 (x64) · **Zero external Python dependencies** (pure stdlib) · **GPUs:** AMD Radeon (Vulkan) & NVIDIA GeForce GTX/RTX (CUDA 12.4 / Vulkan)

**PicoStudio** unifies your local **Coding Agent v3 ([PicoCode](https://github.com/ffalcon3098-droid/PicoCode) · Qwen3-Coder-30B-A3B MoE, Inkling 2 Mini Vision, Qwen2.5-Coder-7B)** and **Video/Image Studio ([localVid / PicoVid](https://github.com/ffalcon3098-droid/localVid) · LTX-2.3 22B Distilled 1.1 Audio+Video, Wan 2.2 TI2V-5B, Z-Image-Turbo)** into a single zero-dependency **English-first 3-pane Dark/Light Web IDE Pro** (`http://127.0.0.1:7900`), **Terminal Pro**, **Side-by-Side Diff & Multi-File Review**, **Multi-Clip Timeline Editor (`xfade` + stereo `acrossfade`)**, and **Smart Developer CLI** — sharing models zero-copy from sibling `PicoCode` and `localVid` folders with an automatic **4–6 GB VRAM GPU Arbiter**.

---

## Hardware & AMD/NVIDIA Compatibility

| GPU / System Tier | Supported Backend | Recommended Coding + Video Pair |
|---|---|---|
| **AMD Radeon RX** (RX 5500 XT / **RX 5600 XT 6 GB verified** / RX 6600+) | **Vulkan** (`ggml-vulkan`) | Auto-configured; zero ROCm setup required on Windows. |
| **NVIDIA GeForce GTX / RTX** (GTX 1650 / RTX 2060 / 3050 / 3060 / 4060+) | **CUDA 12.4** or **Vulkan** | Auto-detected by `PicoCode` & `localVid` installers; automatic VRAM handoff prevents OOM. |
| **4–6 GB VRAM + 16 GB RAM** *(Entry)* | Vulkan / CUDA | `Qwen2.5-Coder-7B` + `Wan 2.2 TI2V-5B Turbo` / `Z-Image-Turbo` |
| **6 GB+ VRAM + 32 GB RAM** *(Verified Sweet Spot)* | Vulkan / CUDA | `Qwen3-Coder-30B-A3B` / `Inkling 2 Mini Vision` + `LTX-2.3 22B Audio+Video` |

---

## Quick Start (Windows 10/11)

PicoStudio itself requires **only Python 3.10+ (zero `pip` packages)**. Clone the sibling repos side by side so PicoStudio shares their models zero-copy:

```powershell
# 1. Clone side by side in a shared projects folder
git clone https://github.com/ffalcon3098-droid/PicoCode.git
git clone https://github.com/ffalcon3098-droid/localVid.git
git clone https://github.com/ffalcon3098-droid/PicoStudio.git

# 2. Run one-click zero-compile setup in PicoCode (and optionally localVid for Video/Image)
cd PicoCode && .\setup.cmd && cd ..
cd localVid && .\setup.cmd && cd ..

# 3. Launch PicoStudio Local Web IDE (http://127.0.0.1:7900)
cd PicoStudio
.\ide.cmd
# Or open any specific folder directly:
.\picostudio.cmd ide --dir ..\my-project
```

*(You can adjust sibling paths or default port anytime in `configs/studio_config.json`.)*

---

## Highlights

- **English-First IDE, CLI & Agent v3 Review Upgrades (`v0.12.0`):**
  - **100% English Default UI & CLI:** Web IDE (`<html lang="en">`), Command Palette, Git/Diff Review, Terminal Pro, GPU Arbiter, Video Studio, and CLI status/errors now default to clean English while AI responses automatically reply in the user's prompt language.
  - **1-Shot `project_overview` + Rust/Go `symbols.py`:** Instant codebase orientation (manifests, directory/language counts, largest core files) and AST/regex symbol indexing across Python, JS/TS, Rust (`.rs` + `#[tauri::command]`), and Go (`.go`).
  - **KV-Cache Preserving Final Synthesis & Evidence-First Rule:** 10-step read-only Plan/Review mode keeps `tools` identical with `tool_choice="none"` on the final turn (preserving 100% KV prefix cache), caps parallel read-tool output budgets, and requires verifying code with `search_code`/`read_file` before reporting bugs or security findings.
- **Side-by-Side Diff Viewer, Multi-File Review & One-Click Terminal Error Auto-Fix (`v0.10.0`):**
  - **2-Column Line-Numbered Side-by-Side Diff (`◫ Split` / `☰ Unified`):** Horizontally paired old/new lines computed directly in `git_ops.py` (`split_rows`) with dark & light theme support.
  - **Multi-File Changes Review Panel (`📋 Review`):** Step through all staged, unstaged, and untracked files (`◀` / `▶` + file pills) with per-file **Stage (`+`)**, **Unstage**, **Revert (`↺`)**, and **✨ AI Review** code review.
  - **Smart Terminal Error Detector & One-Click Auto-Fix Banner:** Live Terminal Pro SSE stream automatically catches Python tracebacks, `SyntaxError`/`AssertionError`/`FAIL:`/`ERROR:`, and JS errors — surfacing an instant banner with clickable `file:line` jump, **`🔧 Fix with Agent v3`** (auto-launches Agent v3 + Auto-Test with `@file` context), and **`↻ Re-run`**.
- **Coding Agent v3 (`v0.9.0`):**
  - **16-Step Agent Loop + Duplicate Loop Guard:** Multi-file refactors and debugging up to 16 steps (6 steps in read-only Plan Mode) with automatic detection of repeated identical tool calls.
  - **5 New AST, Git & File Tools (11 Total):** `repo_map` (compact AST/symbol outline across Python/JS/TS), `find_symbols` (workspace definition lookup), `git_status`, `git_diff`, and undo-recorded `delete_file`.
  - **Instant Post-Edit Syntax Diagnostics:** Every `edit_file` and `write_file` automatically runs `diagnostics.check_syntax()` (Python AST / JSON) and feeds `[SYNTAX ERROR]` lines back to the agent immediately before tests even run.
  - **Smart Context Compaction & Live 32K Telemetry:** Automatically compacts older bulky tool outputs beyond the latest 6 tool calls while keeping recent reads & diffs verbatim, with a live `ctx: %` pill in the chat bar.
  - **1-Click Turn Checkpoint Rollback (`POST /api/workspace/undo-batch`):** Every multi-file agent turn emits a `turn_checkpoint` button (`↺ Tüm Turu Geri Al`) that cleanly rolls back all edits/deletions in reverse chronological order.
- **LTX-2.3 22B Audio+Video Studio, I2V Upload & Multi-Clip Timeline Editor (`v0.8.0`):**
  - **LTX-2.3 22B Distilled v1.1 (8-Step · 48 kHz Stereo Audio + Video):** T2V, I2V, and Z-Image → LTX-2.3 Studio workflows on 6 GB VRAM (`AMD RX 5600 XT Vulkan` / `NVIDIA CUDA`).
  - **In-IDE I2V Image Upload (`/api/media/upload-init`) & Live Step Progress Bar:** Upload any PNG/JPG/WEBP directly in the Video tab to animate it with synchronized stereo sound, plus live `1/8..8/8` DiT, Video VAE, Audio VAE, and Cinema HD telemetry.
  - **Audio-Preserving Cinema HD (`1280×768 @ 32 fps`):** 2× Vulkan Real-ESRGAN AI Upscale + 32 fps frame interpolation preserving LTX-2.3's 48 kHz Stereo AAC audio.
  - **Multi-Clip Video Timeline & Transitions (`/api/media/timeline`):** Queue multiple clips from the gallery, reorder them, choose smooth transitions (`dissolve`, `fadeblack`, `wipeleft`, `smoothleft`, `circleopen`, `cut`) with synchronized stereo `acrossfade`, and export one unified H.264+AAC MP4.
  - **Qwen3-Coder-30B-A3B Default Coding Engine + Stale `.pyc` Self-Heal Fix (`PYTHONDONTWRITEBYTECODE=1`).**
- **Security Hardening, Native `/infill` FIM & Modular Architecture (`v0.7.0`):**
  - **Localhost Security Shield:** Strict `Host` allowlist (DNS rebinding guard), Same-Origin + `application/json` enforcement, per-session random CSRF token (`X-PicoStudio-Token`), `create_project` boundary guard, and zero inline single-quote XSS (`escJsArg`).
  - **Modular Frontend (`picostudio/static/`):** Decomposed the 2,881-line monolith into clean `index.html`, `style.css`, `app.js`, and a slim ~470-line `web_ide.py`.
  - **Editor Undo (`Ctrl+Z`) & Reliability:** Native undo-preserving `replaceEditorRange()`, unsaved dirty-tab `beforeunload` warning, background tab polling brake (`document.hidden`), and debounced syntax highlighting for huge files.
  - **Atomic GPU Arbiter + Native `/infill` FIM:** Serialized `_op_lock` eliminates GPU start/stop races, port-targeted `llama-server` cleanup never kills unrelated instances, and `Alt+Space` uses `llama-server`'s native `/infill` FIM endpoint!
  - **Safer Coding Agent:** Rejects ambiguous multi-match `edit_file` targets, blocks destructive `run_terminal` commands, and supports real server-side stream cancellation (`POST /api/agent/abort`).
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
