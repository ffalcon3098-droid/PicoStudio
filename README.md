# PicoStudio v0.1.0 — Unified Local IDE, Terminal & Multi-Model AI Studio (Coding + Video + Image)

> [Türkçe dokümantasyon için README.tr.md](README.tr.md)

**PicoStudio** unifies your local **Coding Agent (`PicoCode` · Inkling 2 Mini)** and **Video/Image Studio (`PicoVid` · Wan 2.2 TI2V-5B Turbo, Wan 2.2 14B, Z-Image-Turbo)** into a single zero-dependency **3-pane Dark Web IDE** (`http://127.0.0.1:7900`), **Embedded Terminal**, and **Smart Developer CLI** — sharing models zero-copy from sibling `PicoCode` and `localVid` folders with an automatic **6 GB VRAM GPU Arbiter**.

---

## Highlights

- **6 GB VRAM GPU Arbiter (`picostudio/arbiter.py`):** Guarantees zero VRAM collisions on 4–6 GB GPUs. Starting Video/Image diffusion automatically unloads the Coding LLM cleanly, streams live logs, and displays the output MP4/PNG inline inside the IDE.
- **3-Pane Dark Web IDE (`http://127.0.0.1:7900`):**
  - **Left:** Multi-project switcher, file explorer, create file, fast project-wide text search.
  - **Center:** Multi-tab code editor (line numbers, `Ctrl+S` save, 1-click Bug/Refactor/Test actions, inline MP4/PNG viewer) + **Embedded PowerShell Terminal** (`cd` persistence, 1-click `Test Koş`, `git status`, and *"Send Error to AI"*).
  - **Right:** Two unified tabs — **Kod Ajanı (`Inkling 2 Mini`)** with *Fast Direct Code* vs *Deep Think* toggle, Vision image attach, and 1-click **Apply to Editor / Run in Terminal**; plus **Video & Görsel (`Wan 2.2` + `Z-Image-Turbo`)** with 1-click **Inkling 2 Cinematic Prompt Enhancer** and clickable gallery.
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
