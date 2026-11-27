# PicoStudio v0.12.0 — Yerel IDE Pro, Kod Ajanı v3, Yan Yana Diff İnceleme & LTX-2.3 Ses+Video Stüdyosu (AMD & NVIDIA)

[![Regression Tests](https://github.com/ffalcon3098-droid/PicoStudio/actions/workflows/tests.yml/badge.svg)](https://github.com/ffalcon3098-droid/PicoStudio/actions/workflows/tests.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> [For English documentation, see README.md](README.md) · **Platform:** Windows 10/11 (x64) · **Sıfır harici Python bağımlılığı** (saf stdlib) · **GPU Desteği:** AMD Radeon (Vulkan) & NVIDIA GeForce GTX/RTX (CUDA 12.4 / Vulkan)

**PicoStudio**, elinizdeki yerel **Kod Ajanı v3'ü ([PicoCode](https://github.com/ffalcon3098-droid/PicoCode) · Qwen3-Coder-30B-A3B MoE, Inkling 2 Mini Vision, Qwen2.5-Coder-7B)** ve **Video/Görsel Motorlarını ([localVid / PicoVid](https://github.com/ffalcon3098-droid/localVid) · LTX-2.3 22B Distilled 1.1 Ses+Video, Wan 2.2 TI2V-5B, Z-Image-Turbo)** tek bir sıfır bağımlılıklı **İngilizce varsayılan 3 panelli Web IDE Pro** (`http://127.0.0.1:7900`), **Terminal Pro**, **Yan Yana (Side-by-Side) Diff & Çok Dosyalı İnceleme**, **Çoklu Klip Zaman Çizelgesi (`xfade` + stereo `acrossfade`)** ve **akıllı CLI** altında birleştirir. Modelleri kopyalamaz; komşu `PicoCode` ve `localVid` klasörlerinden sıfır ekstra disk kullanımıyla ve otomatik **4–6 GB VRAM GPU Nöbetçisi** ile çalıştırır.

---

## Donanım & AMD/NVIDIA Uyumluluğu

| GPU / Sistem Katmanı | Desteklenen Backend | Önerilen Kod + Video İkilisi |
|---|---|---|
| **AMD Radeon RX** (RX 5500 XT / **RX 5600 XT 6 GB doğrulandı** / RX 6600+) | **Vulkan** (`ggml-vulkan`) | Windows'ta ROCm gerekmeden otomatik çalışır. |
| **NVIDIA GeForce GTX / RTX** (GTX 1650 / RTX 2060 / 3050 / 3060 / 4060+) | **CUDA 12.4** veya **Vulkan** | `PicoCode` ve `localVid` kurulumları tarafından otomatik algılanır; otomatik VRAM devri OOM'u önler. |
| **4–6 GB VRAM + 16 GB RAM** *(Giriş)* | Vulkan / CUDA | `Qwen2.5-Coder-7B` + `Wan 2.2 TI2V-5B Turbo` / `Z-Image-Turbo` |
| **6 GB+ VRAM + 32 GB RAM** *(Doğrulanmış İdeal)* | Vulkan / CUDA | `Qwen3-Coder-30B-A3B` / `Inkling 2 Mini Vision` + `LTX-2.3 22B Ses+Video` |

---

## Hızlı Başlangıç (Windows 10/11)

PicoStudio'nun kendisi **yalnızca Python 3.10+ gerektirir (sıfır `pip` paketi)**. Modelleri sıfır kopyayla paylaşmak için 3 repoyu aynı üst klasörde yan yana klonlayın:

```powershell
# 1. Aynı proje klasöründe yan yana klonlayın
git clone https://github.com/ffalcon3098-droid/PicoCode.git
git clone https://github.com/ffalcon3098-droid/localVid.git
git clone https://github.com/ffalcon3098-droid/PicoStudio.git

# 2. PicoCode (ve video/görsel için opsiyonel localVid) içinde tek tıkla kurulumu çalıştırın
cd PicoCode; .\setup.cmd; cd ..
cd localVid; .\setup.cmd; cd ..

# 3. PicoStudio Yerel Web IDE'yi başlatın (http://127.0.0.1:7900)
cd PicoStudio
.\ide.cmd
# Veya doğrudan belirli bir proje klasörünü açın:
.\picostudio.cmd ide --dir ..\my-project
```

---

## Öne Çıkan Özellikler

- **İngilizce Varsayılan Arayüz/CLI & Ajan v3 İnceleme İyileştirmeleri (`v0.12.0`):**
  - **%100 İngilizce Varsayılan IDE & CLI:** Web IDE (`<html lang="en">`), Komut Paleti, Git/Diff İnceleme, Terminal Pro, GPU Nöbetçisi, Video Stüdyosu ve CLI durum/hata mesajları temiz İngilizce varsayılanına geçirildi (AI yanıtları kullanıcının yazdığı dilde — örn. Türkçe soruya Türkçe — yanıt vermeye devam eder).
  - **Tek Adımlı `project_overview` + Rust/Go `symbols.py`:** Proje yapısını tek araç çağrısında özetleyen `project_overview` ile Python, JS/TS, Rust (`.rs` + `#[tauri::command]`) ve Go (`.go`) sembol desteği.
  - **KV-Cache Korumalı Final Sentez & Kanıt Kuralı:** 10 adımlı salt-okunur Plan/İnceleme modu final turda `tools` şemasını koruyup `tool_choice="none"` ile %100 KV önbelleğini korur; paralel araç çıktısı bütçesini dengeler ve hata/güvenlik iddiası öncesi kodu `search_code`/`read_file` ile doğrulama kuralı uygular.

- **Yan Yana (Side-by-Side) Diff, Çok Dosyalı İnceleme & Terminal Tek Tık Hata Düzeltici (`v0.10.0`):**
  - **2 Sütunlu Satır Numaralı Side-by-Side Diff (`◫ Yan Yana` / `☰ Tek Sütun`):** `git_ops.py` içinde yatay eşleştirilen eski/yeni satırlar (`split_rows`) ile koyu ve açık tema uyumlu karşılaştırma.
  - **Çok Dosyalı Değişiklik İnceleme Paneli (`📋 İncele`):** Tüm staged, unstaged ve yeni dosyalar arasında `◀` / `▶` ve dosya etiketleriyle gezinin; her dosya için **Stage (`+`)**, **Unstage**, **Geri Al (`↺`)** ve **✨ AI İncele** çalıştırın.
  - **Akıllı Terminal Hata Yakalayıcı & Tek Tık Düzeltme Çubuğu:** Canlı Terminal Pro SSE akışındaki Python traceback, `SyntaxError`/`AssertionError`/`FAIL:`/`ERROR:` ve JS hatalarını otomatik yakalar; tıklanabilir `dosya:satır` atlaması, **`🔧 Ajan v3 ile Düzelt`** (otomatik `@dosya` + `Oto-Test` tetikleyici) ve **`↻ Tekrar Koş`** butonları sunar.
- **Kod Ajanı v3 (`v0.9.0`):**
  - **16 Adımlı Ajan Döngüsü + Tekrar Koruması:** Çok dosyalı refactor ve hata ayıklama için 16 adıma kadar otonom çalışma (Plan modunda 6 adım) ve aynı araç çağrısının sonsuz döngüye girmesini önleyen koruma.
  - **5 Yeni AST, Git & Dosya Aracı (Toplam 11 Araç):** `repo_map` (Python/JS/TS AST sembol haritası), `find_symbols` (proje çapı sembol arama), `git_status`, `git_diff` ve geri alınabilir `delete_file`.
  - **Anlık Düzenleme Sonrası Sözdizimi Denetimi:** Her `edit_file` ve `write_file` çağrısı anında `diagnostics.check_syntax()` (Python AST / JSON) çalıştırır; sözdizimi hatası varsa testi bile beklemeden `[SYNTAX ERROR]` olarak ajana bildirir.
  - **Akıllı Bağlam Sıkıştırma & Canlı 32K Telemetri:** Son 6 araç çıktısını ve tüm diff'leri eksiksiz koruyup eski hacimli çıktıları otomatik sıkıştırır; sohbet üst çubuğunda canlı `ctx: %` göstergesi sunar.
  - **Tek Tık Tur Kayıt Noktası (`POST /api/workspace/undo-batch`):** Birden fazla dosya değiştiren her ajan turunun sonunda **"↺ Tüm Turu Geri Al"** butonu ile tüm değişiklikler ve silmeler ters sırayla temiz biçimde geri alınır.
- **LTX-2.3 22B Ses+Video Stüdyosu, I2V Yükleme & Çoklu Klip Zaman Çizelgesi (`v0.8.0`):**
  - **LTX-2.3 22B Distilled v1.1 (8 Adım · 48 kHz Stereo Ses + Video):** 6 GB VRAM'li kartlarda (`AMD RX 5600 XT Vulkan` / `NVIDIA CUDA`) T2V, I2V ve Z-Image → LTX-2.3 Stüdyo akışı.
  - **IDE İçi I2V Görsel Yükleme (`/api/media/upload-init`) & Canlı İlerleme Çubuğu:** Video sekmesinden doğrudan PNG/JPG/WEBP yükleyip sesli videoya çevirin; `1/8..8/8` DiT, Video VAE, Ses VAE ve Sinema HD aşamalarını canlı izleyin.
  - **Ses Korumalı Sinema HD (`1280×768 @ 32 fps`):** 2× Vulkan Real-ESRGAN + 32 fps akıcılık uygulanırken LTX-2.3'ün 48 kHz Stereo AAC sesi eksiksiz korunur.
  - **Çoklu Klip Zaman Çizelgesi & Geçişler (`/api/media/timeline`):** Galerideki klipleri sıraya dizin, geçiş efektini (`dissolve`, `fadeblack`, `wipeleft`, `smoothleft`, `circleopen`, `cut`) ve süresini seçip senkronize stereo `acrossfade` ile tek MP4'te birleştirin.
  - **Qwen3-Coder-30B-A3B Varsayılan Kodlama Motoru + `Oto-Test` Bayat `.pyc` Önbellek Düzeltmesi (`PYTHONDONTWRITEBYTECODE=1`).**
- **Güvenlik Zırhı, Natif `/infill` FIM & Modüler Mimari (`v0.7.0`):**
  - **Localhost Güvenlik Kalkanı:** Katı `Host` kontrolü (DNS rebinding koruması), Same-Origin + `application/json` zorunluluğu, oturum bazlı rastgele CSRF token (`X-PicoStudio-Token`), `create_project` sınır koruması ve sıfır tek-tırnak `onclick` XSS (`escJsArg`).
  - **Modüler Ön Yüz (`picostudio/static/`):** `2.881` satırlık monolit temiz `index.html`, `style.css`, `app.js` ve ~470 satırlık `web_ide.py` olarak ayrıştırıldı.
  - **Editör `Ctrl+Z` & Güvenilirlik:** Tarayıcı geri alma yığınını koruyan `replaceEditorRange()`, kaydedilmemiş sekme çıkışı uyarısı (`beforeunload`), arka plan sekme polling freni (`document.hidden`) ve büyük dosyalarda debounce renklendirme.
  - **Atomik GPU Nöbetçisi + Natif `/infill` FIM:** `_op_lock` ile sıfır VRAM yarış durumu, sadece kendi port/PID'ini kapatan güvenli `llama-server` temizliği ve `Alt+Space` için natif `llama-server /infill` FIM tamamlama.
  - **Daha Güvenli Kod Ajanı:** Belirsiz çoklu eşleşmeli `edit_file` reddi, yıkıcı `run_terminal` komut engeli ve gerçek sunucu tarafı iptal (`POST /api/agent/abort`).
- **Akıllı Gezinme, `Alt+Space` AI Tamamlama & Proje Değiştirme (`v0.6.0`):**
  - **Sembol Gezgini (`Ctrl+Shift+O`) & `F12` Tanıma Git (`picostudio/symbols.py`):** Python AST + JS/TS sembol çıkarıcı ile dosya içi Outline, `#` ile proje geneli sembol arama ve imleçteki fonksiyona `F12` ile anında atlama.
  - **İsteğe Bağlı `Alt+Space` AI Kod Tamamlama (FIM):** İmleç öncesi/sonrası bağlamla yerel modelden tamamlama önerisi (`Tab` ile kabul, `Esc` ile iptal).
  - **Proje Çapında Bul & Değiştir (`⇄`):** Önizlemeli ve geri alınabilir çok dosyalı değiştirme + her arama sonucunda doğrudan ilgili satıra atlama.
  - **Otomatik Proje AI Kuralları (`.picostudio.md` / `AGENTS.md`) + Hızlı Ajan Çipleri (`/review`, `/bug`, `/test`, `/refactor`, `/doc`, `/plan`).**
- **Cursor Tarzı `Ctrl+K` Satır İçi AI & Anlık Kod Tanılama (`v0.5.0`):**
  - Editörde herhangi bir kod bloğunu seçip **`Ctrl+K`** tuşlayın; yerel AI canlı unified diff önizlemesi ve tek tık **Uygula** ile kodu yerinde düzenlesin.
  - Dosya açarken/kaydederken sıfır gecikmeli **Python (`ast.parse`) & JSON sözdizimi hata çubuğu** (`Satıra Git` ve `AI ile Düzelt`).
  - **Sürüklenebilir 3 Panel (`Ctrl+B` yan panel aç/kapa), `Ctrl+Shift+P` Komut Paleti, 3 Tema (`Midnight` / `Obsidian` / `Light`) & Yazı Boyutu (`A-/A+`)** kalıcı olarak saklanır.
  - **Proje Bazlı Kalıcı Sohbet Geçmişi** (hedef repoları kirletmeden `data/chats/` altında) + sohbette **`@dosya` Otomatik Bağlam Tamamlama**.
- **Kod Editörü Pro (`v0.4.0`):**
  - Sıfır bağımlılıklı gerçek sözdizimi renklendirme (Python, JS/TS/JSX/TSX, JSON, HTML, CSS, PowerShell/Bash, Markdown).
  - Enter'da otomatik girinti, otomatik parantez/tırnak tamamlama (`() [] {} "" ''`), `Shift+Tab` girinti azaltma, `Ctrl+/` yorum satırı aç/kapat, canlı satır/sütun/dil göstergesi.
  - `Ctrl+F` / `Ctrl+H` dosya içi Bul & Değiştir (vurgulu eşleşmelerle) ve VS Code tarzı `Ctrl+P` Hızlı Dosya Açma paleti.
- **Git & Görsel Diff Paneli (`v0.4.0`):**
  - Sol panelde canlı değişen dosya sayaçlı `Git` sekmesi, aktif dal (`branch`) ve son commit geçmişi.
  - Orta panelde satır bazlı renkli görsel Diff görüntüleyici (yeni/izlenmeyen dosyalar dahil), tek tık **Stage (`+`)**, **Unstage (`-`)**, **Geri Al (`↺`)**, **Commit** ve **✨ AI Commit Mesajı** üretici.
- **Kod Ajanı v2 (`v0.4.0`):**
  - **Planla + Onayla Modu:** Ajan önce salt-okunur inceleme yapıp çok dosyalı uygulama planı çıkarır; onay kartından sonra uygular.
  - **Oto-Test + Kendi Düzeltme Döngüsü:** Dosya değişikliklerinden sonra proje testlerini (`unittest` / `npm test`) otomatik koşar; hata çıkarsa izini okuyup kodu kendi düzeltir.
- **Terminal Pro (`v0.3.0`):**
  - **Çok Sekmeli Canlı SSE Akışı:** Bir sekmede sunucu çalışırken diğer sekmede test veya `git` çalıştırın; her sekmenin bağımsız `cd` dizini ve sıfır gecikmeli `EventSource` canlı log akışı vardır.
  - **İnteraktif `stdin`, Komut Geçmişi & `Tab` Tamamlama:** Komut çalışırken giriş satırı otomatik `stdin>` moduna geçer (`y/n`, `input()` cevapları için), `↑`/`↓` geçmişi ve `Tab` ile dosya/klasör yolu tamamlama sunar.
  - **Tam ANSI Renk Desteği + Tıklanabilir `dosya:satır` Bağlantıları:** Renkli terminal çıktısında Python traceback ve `dosya.py:42` hata satırlarına tıklayınca editörde doğrudan o dosya ve satıra atlar.
  - **Sürüklenebilir Bölme + Büyüt / Daralt:** Editör ve terminal arasındaki tutamacı sürükleyerek yüksekliği ayarlayın veya `⤢` / `▾` ile büyütüp daraltın.
  - **Warp Tarzı `?` Doğal Dil → PowerShell AI Çevirici:** Komut satırına `?` ile başlayan Türkçe/İngilizce bir istek yazın (örn. `? 7890 portunu dinleyen sureci goster`), yerel AI komutu güvenli önizleme çubuğu (`Çalıştır` / `Düzenle` / `İptal`) ile hazırlasın.
- **3 Panelli Karanlık Lokal IDE (`http://127.0.0.1:7900`):**
  - **Sol Panel:** Proje değiştirici (`PicoCode`, `localVid`, `PicoStudio`, kendi projeleriniz), `+ New Project`, daraltılabilir dosya ağacı, `+ New`, proje içi arama.
  - **Orta Panel:** Sekmeli kod editörü (satır numaraları, `Ctrl+S` kaydet, tek tık *Bug Bul / Refactor / Test Yaz*, gömülü MP4/PNG oynatıcı) + **Terminal Pro**.
  - **Sağ Panel:** İki birleşik sekme — **Kod Ajanı (`Qwen2.5-Coder-7B` & `Inkling 2 Mini`)** (canlı model değiştirme, gerçek tool-calling dosya okuma/yazma/düzenleme/terminal çalıştırma, Diff + tek tık **Geri Al**, **Dur**, ekran görüntüsü ekleme) + **Video & Görsel (`Wan 2.2` + `Z-Image-Turbo`)** (tek tık **Sinematikleştir** + canlı galeri).
- **Birleşik Geliştirici CLI (`.\picostudio.cmd`):**

```powershell
# Lokal Web IDE'yi aç (http://127.0.0.1:7900)
.\ide.cmd

# GPU/VRAM ve kurulu tüm Kod + Video modellerini gör
.\picostudio.cmd status

# Terminalden interaktif Kod + Video ajanı (/file, /run, /video, /image)
.\picostudio.cmd chat

# Tek seferlik kod sorusu (dosya bağlamlı)
.\picostudio.cmd ask "Find potential bugs in this file" --file ..\my-app\app.py

# Terminalden doğrudan video / görsel üret (VRAM'i otomatik yönetir)
.\picostudio.cmd video "Golden hour drone shot over Istanbul Bosphorus" --engine 5b --cinema-hd
.\picostudio.cmd image "Cyberpunk robotics workshop, cinematic lighting"
```

---

## Lisans

[Apache License, Version 2.0](LICENSE) altında lisanslanmıştır.
