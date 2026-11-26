# PicoStudio v0.1.0 — Birleşik Yerel IDE, Terminal & Çoklu AI Stüdyosu (Kod + Video + Görsel)

> [For English documentation, see README.md](README.md)

**PicoStudio**, elinizdeki yerel **Kodlama Ajanını (`PicoCode` · Inkling 2 Mini)** ve **Video/Görsel Motorlarını (`PicoVid` · Wan 2.2 TI2V-5B Turbo, Wan 2.2 14B, Z-Image-Turbo)** tek bir sıfır bağımlılıklı **3 panelli karanlık Web IDE** (`http://127.0.0.1:7900`), **gömülü Terminal** ve **akıllı CLI** altında birleştirir. Modelleri kopyalamaz; komşu `PicoCode` ve `localVid` klasörlerinden sıfır ekstra disk kullanımıyla ortak çalıştırır.

---

## Öne Çıkan Özellikler

- **6 GB VRAM GPU Nöbetçisi (`picostudio/arbiter.py`):** Kodlama ve Video modellerinin 6 GB VRAM'de çakışmasını engeller. Video/Görsel başlattığınızda `Inkling 2 Mini` otomatik kapanıp VRAM'i boşaltır; çıktı MP4/PNG doğrudan IDE içinde oynatılır.
- **3 Panelli Karanlık Lokal IDE (`http://127.0.0.1:7900`):**
  - **Sol Panel:** Proje değiştirici (`MiniLedger`, `PicoCode`, `localVid`, `PicoStudio` vb.), dosya ağacı, `+ Yeni Dosya`, proje içi arama.
  - **Orta Panel:** Sekmeli kod editörü (satır numaraları, `Ctrl+S` kaydet, tek tık *Bug Bul / Refactor / Test Yaz*, gömülü MP4/PNG oynatıcı) + **Gömülü PowerShell Terminali** (`cd` desteği, `Test Koş`, `git status`, *"Hatayı AI'ya Gönder"*).
  - **Sağ Panel:** İki birleşik sekme — **Kod Ajanı (`Inkling 2 Mini`)** (*Hızlı Kod* / *Derin Analiz* geçişi, ekran görüntüsü ekleme, tek tık **Editöre Uygula** ve **Terminalde Çalıştır**) + **Video & Görsel (`Wan 2.2` + `Z-Image-Turbo`)** (tek tık **Inkling 2 ile Sinematikleştir** çapraz model köprüsü + canlı galeri).
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
