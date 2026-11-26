# PicoStudio v0.7.0 — Zırhlı & Modüler Yerel IDE Pro, Natif FIM, Terminal Pro, Git & Çoklu AI Stüdyosu

> [For English documentation, see README.md](README.md)

**PicoStudio**, elinizdeki yerel **Kodlama Ajanlarını (`PicoCode` · Qwen2.5-Coder-7B + Inkling 2 Mini)** ve **Video/Görsel Motorlarını (`PicoVid` · Wan 2.2 TI2V-5B Turbo, Wan 2.2 14B, Z-Image-Turbo)** tek bir sıfır bağımlılıklı **3 panelli Web IDE Pro** (`http://127.0.0.1:7900`), **Terminal Pro**, **Git & Görsel Diff** ve **akıllı CLI** altında birleştirir. Modelleri kopyalamaz; komşu `PicoCode` ve `localVid` klasörlerinden sıfır ekstra disk kullanımıyla ortak çalıştırır.

---

## Öne Çıkan Özellikler

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
  - **Sol Panel:** Proje değiştirici (`PulseMonitor`, `MiniLedger`, `PicoCode`, `localVid`, `PicoStudio` vb.), `+ Yeni Proje`, daraltılabilir dosya ağacı, `+ Yeni Dosya`, proje içi arama.
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
.\picostudio.cmd ask "Bu dosyadaki bugları bul" --file ..\MiniLedger\app.py

# Terminalden doğrudan video / görsel üret (VRAM'i otomatik yönetir)
.\picostudio.cmd video "Golden hour drone shot over Istanbul Bosphorus" --engine 5b --cinema-hd
.\picostudio.cmd image "Cyberpunk robotics workshop, cinematic lighting"
```

---

## Lisans

[Apache License, Version 2.0](LICENSE) altında lisanslanmıştır.
