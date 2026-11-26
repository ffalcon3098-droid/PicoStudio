"""
PicoStudio Local Web IDE (Zero-Dependency 3-Pane Dark IDE + Terminal + Coding Agent + Video Studio).

Runs at http://127.0.0.1:7900 — unifies:
  - Project Explorer & Multi-Tab Code Editor (save, search, create/delete files)
  - Embedded PowerShell Terminal with persistent `cd` & 1-click "Send Error to AI"
  - Inkling 2 Mini Local Coding Agent (Fast Direct Code vs Deep Think, Vision, Apply-to-Editor)
  - PicoVid Video & Image Studio (Wan 2.2 5B / 14B + Z-Image-Turbo) with automatic 6 GB VRAM handoff

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import json
import mimetypes
import pathlib
import threading
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from picostudio.agent import run_agent_stream
from picostudio.arbiter import GPUArbiter, load_config
from picostudio.terminal import TerminalSession
from picostudio.workspace import Workspace


IDE_HTML = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>PicoStudio IDE — Yerel Kodlama, Terminal &amp; Video Stüdyosu</title>
<style>
  :root {
    --bg:#0b0f17; --p1:#111724; --p2:#171f31; --p3:#1d2740; --b:#26324d;
    --txt:#e6edf7; --mut:#8fa2c2; --acc:#38bdf8; --acc2:#818cf8;
    --ok:#22c55e; --warn:#f59e0b; --err:#ef4444; --code:#080c13;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--txt);font-family:"Segoe UI",system-ui,sans-serif;overflow:hidden}
  body{display:flex;flex-direction:column}
  header{display:flex;align-items:center;gap:10px;padding:7px 14px;background:var(--p1);border-bottom:1px solid var(--b);flex-wrap:wrap}
  .brand{font-weight:700;font-size:15px;display:flex;align-items:center;gap:8px;white-space:nowrap}
  .pill{font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(56,189,248,.14);color:var(--acc);border:1px solid rgba(56,189,248,.35);white-space:nowrap}
  .pill.ok{background:rgba(34,197,94,.14);color:var(--ok);border-color:rgba(34,197,94,.35)}
  .pill.warn{background:rgba(245,158,11,.15);color:var(--warn);border-color:rgba(245,158,11,.35)}
  .pill.err{background:rgba(239,68,68,.15);color:var(--err);border-color:rgba(239,68,68,.35)}
  .pill.vid{background:rgba(168,85,247,.16);color:#c084fc;border-color:rgba(168,85,247,.4)}
  .hdr-right{margin-left:auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--mut)}
  .meter{display:flex;flex-direction:column;gap:2px;min-width:128px}
  .mbar{height:5px;background:#1e293b;border-radius:4px;overflow:hidden}
  .mfill{height:100%;background:linear-gradient(90deg,var(--acc),var(--acc2));width:0;transition:width .35s}
  .mfill.warn{background:var(--warn)} .mfill.err{background:var(--err)}
  select,input,textarea{background:var(--bg);color:var(--txt);border:1px solid var(--b);border-radius:6px;padding:5px 8px;font-size:12.5px;font-family:inherit}
  button{background:var(--p3);color:var(--txt);border:1px solid var(--b);border-radius:6px;padding:5px 10px;font-size:12px;font-weight:600;cursor:pointer}
  button:hover{border-color:var(--acc);background:#243252}
  button.primary{background:linear-gradient(135deg,#0284c7,#4f46e5);border-color:transparent;color:#fff}
  button.purple{background:linear-gradient(135deg,#7c3aed,#db2777);border-color:transparent;color:#fff}
  button.danger{background:rgba(239,68,68,.15);border-color:rgba(239,68,68,.45);color:#fca5a5}
  button.sm{padding:3px 7px;font-size:11px}
  button:disabled{opacity:.45;cursor:not-allowed}

  .workbench{flex:1;display:grid;grid-template-columns:235px 1fr 410px;min-height:0}
  .pane{display:flex;flex-direction:column;min-height:0;border-right:1px solid var(--b);background:var(--p1)}
  .pane:last-child{border-right:none}
  .pane-hdr{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;border-bottom:1px solid var(--b);font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--mut);gap:6px}

  /* Left Explorer */
  .search-box{padding:7px 8px;border-bottom:1px solid var(--b);display:flex;gap:5px}
  .search-box input{flex:1;min-width:0}
  .tree{flex:1;overflow-y:auto;padding:5px 0;font-size:12.5px}
  .titem{padding:4px 10px;cursor:pointer;display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#cbd5e1}
  .titem:hover{background:var(--p2)}
  .titem.active{background:rgba(56,189,248,.14);color:var(--acc)}
  .titem.dir{color:var(--mut);font-weight:600}
  .search-hits{border-top:1px solid var(--b);max-height:170px;overflow-y:auto;background:var(--code);font-size:11.5px;display:none}
  .hit{padding:5px 9px;border-bottom:1px solid #162033;cursor:pointer}
  .hit:hover{background:var(--p2)}

  /* Center Editor + Terminal */
  .center-col{display:grid;grid-template-rows:1fr 225px;min-height:0;background:var(--bg);border-right:1px solid var(--b)}
  .editor-area{display:flex;flex-direction:column;min-height:0}
  .tabbar{display:flex;align-items:center;background:var(--p1);border-bottom:1px solid var(--b);overflow-x:auto;gap:2px;padding:0 6px}
  .etab{display:flex;align-items:center;gap:6px;padding:7px 11px;font-size:12px;color:var(--mut);cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
  .etab.active{color:var(--txt);border-bottom-color:var(--acc);background:var(--bg)}
  .etab .x{font-size:11px;opacity:.65;padding:0 3px;border-radius:3px}
  .etab .x:hover{background:#334155;opacity:1}
  .etoolbar{display:flex;align-items:center;gap:6px;padding:5px 10px;background:var(--p2);border-bottom:1px solid var(--b);font-size:11.5px;color:var(--mut);flex-wrap:wrap}
  .code-host{flex:1;display:flex;min-height:0;background:var(--code);position:relative}
  .gutter{width:46px;background:#0a0f18;color:#475569;font-family:"Cascadia Code",Consolas,monospace;font-size:13px;line-height:1.5;padding:10px 6px;text-align:right;overflow:hidden;user-select:none;border-right:1px solid #172033}
  #codeEditor{flex:1;background:transparent;color:#e2e8f0;border:none;outline:none;resize:none;padding:10px 12px;font-family:"Cascadia Code",Consolas,monospace;font-size:13px;line-height:1.5;white-space:pre;overflow:auto;tab-size:4}
  #mediaViewer{display:none;flex:1;align-items:center;justify-content:center;flex-direction:column;gap:10px;padding:16px;background:#05080f}
  #mediaViewer video,#mediaViewer img{max-width:100%;max-height:78%;border-radius:8px;border:1px solid var(--b)}

  /* Embedded Terminal */
  .term-area{display:flex;flex-direction:column;min-height:0;border-top:2px solid var(--b);background:#070a10}
  .term-out{flex:1;overflow-y:auto;padding:8px 11px;font-family:"Cascadia Code",Consolas,monospace;font-size:12px;line-height:1.45;color:#cbd5e1;white-space:pre-wrap;word-break:break-word}
  .term-inp{display:flex;align-items:center;gap:6px;padding:6px 10px;border-top:1px solid #1b253a;background:var(--p1)}
  .term-inp span{font-family:Consolas,monospace;font-size:12px;color:var(--acc)}
  .term-inp input{flex:1;font-family:Consolas,monospace;font-size:12.5px}

  /* Right AI & Media Pane */
  .rtabs{display:flex;background:var(--p1);border-bottom:1px solid var(--b)}
  .rtab{flex:1;padding:9px 8px;text-align:center;font-size:12.5px;font-weight:700;color:var(--mut);cursor:pointer;border-bottom:2px solid transparent}
  .rtab.active{color:var(--acc);border-bottom-color:var(--acc);background:var(--p2)}
  .rtab.active.vid{color:#c084fc;border-bottom-color:#c084fc}
  .rbody{flex:1;display:flex;flex-direction:column;min-height:0;overflow:hidden}
  .chat-feed{flex:1;overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:10px}
  .msg{border-radius:8px;padding:9px 11px;font-size:12.8px;line-height:1.5;border:1px solid var(--b);background:var(--p2)}
  .msg.user{background:#182744;border-color:#2b4372}
  .msg-hdr{font-size:10.5px;color:var(--mut);display:flex;justify-content:space-between;margin-bottom:5px}
  .code-blk{margin:7px 0;border:1px solid #26314a;border-radius:7px;overflow:hidden;background:var(--code)}
  .code-blk-h{display:flex;justify-content:space-between;align-items:center;padding:4px 8px;background:#101726;font-size:11px;color:var(--mut);gap:5px}
  .code-blk pre{margin:0;padding:8px;overflow-x:auto;font-family:"Cascadia Code",Consolas,monospace;font-size:11.8px;color:#dbeafe}
  .chat-ctrl{padding:9px;border-top:1px solid var(--b);background:var(--p1);display:flex;flex-direction:column;gap:7px}
  .chat-opts{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11.5px;color:var(--mut)}
  .media-scroll{flex:1;overflow-y:auto;padding:11px;display:flex;flex-direction:column;gap:10px}
  .mcard{background:var(--p2);border:1px solid var(--b);border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:7px}
  .row{display:flex;gap:7px;align-items:center}
  .logbox{font-family:Consolas,monospace;font-size:11px;background:var(--code);border:1px solid var(--b);border-radius:6px;padding:7px;max-height:130px;overflow-y:auto;white-space:pre-wrap;color:#9fb3d1}
  .gallery{display:grid;grid-template-columns:1fr 1fr;gap:7px}
  .gitem{background:var(--code);border:1px solid var(--b);border-radius:7px;padding:6px;cursor:pointer;font-size:11px;overflow:hidden}
  .gitem:hover{border-color:#c084fc}
  .gitem .gname{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--txt);margin-top:4px}
  .gitem .gmeta{color:var(--mut);font-size:10px}
  @media(max-width:1100px){.workbench{grid-template-columns:190px 1fr 340px}}
</style>
</head>
<body>
<header>
  <div class="brand">
    <span>PicoStudio IDE</span>
    <span class="pill">v0.2.0</span>
    <span id="gpuOwnerPill" class="pill">GPU: Boşta</span>
  </div>
  <div class="row">
    <span style="font-size:12px;color:var(--mut)">Proje:</span>
    <select id="projSel" onchange="switchProject(this.value)"></select>
    <button class="sm" onclick="newProjectPrompt()" title="Yeni proje klasörü oluştur veya aç">+ Yeni Proje</button>
  </div>
  <div class="hdr-right">
    <select id="modelSel" onchange="switchCodingModel(this.value)" title="Aktif Kodlama Modeli"></select>
    <div class="meter"><div id="vramTxt">VRAM: --</div><div class="mbar"><div id="vramFill" class="mfill"></div></div></div>
    <div class="meter"><div id="ramTxt">RAM: --</div><div class="mbar"><div id="ramFill" class="mfill"></div></div></div>
    <button id="llmBtn" class="sm primary" onclick="toggleCodingEngine()">Kodlama AI Başlat</button>
    <button class="sm danger" onclick="stopAllGpu()">GPU Boşalt</button>
  </div>
</header>

<div class="workbench">
  <!-- LEFT: EXPLORER -->
  <section class="pane">
    <div class="pane-hdr">
      <span>Dosyalar</span>
      <div class="row" style="gap:4px">
        <button class="sm" onclick="newFilePrompt()">+ Yeni</button>
        <button class="sm" onclick="loadTree()">↻</button>
      </div>
    </div>
    <div class="search-box">
      <input id="searchInp" placeholder="Projede ara..." onkeydown="if(event.key==='Enter')searchProject()" />
      <button class="sm" onclick="searchProject()">Ara</button>
    </div>
    <div id="searchHits" class="search-hits"></div>
    <div id="fileTree" class="tree"></div>
  </section>

  <!-- CENTER: EDITOR + TERMINAL -->
  <section class="center-col">
    <div class="editor-area">
      <div id="tabBar" class="tabbar"></div>
      <div class="etoolbar">
        <span id="activeFileLbl">Dosya seçilmedi</span>
        <div style="margin-left:auto;display:flex;gap:5px;flex-wrap:wrap">
          <button class="sm primary" onclick="saveActiveFile()">Kaydet (Ctrl+S)</button>
          <button class="sm" onclick="askAiAboutFile('Bu dosyadaki olasi buglari ve iyilestirmeleri bul:')">Bug Bul</button>
          <button class="sm" onclick="askAiAboutFile('Bu dosya icin temiz bir refactor onerisi ve tam kodu ver:')">Refactor</button>
          <button class="sm" onclick="askAiAboutFile('Bu dosya icin unittest birim testleri yaz:')">Test Yaz</button>
          <button class="sm" onclick="closeMediaViewer()">Editöre Dön</button>
        </div>
      </div>
      <div class="code-host">
        <div id="gutter" class="gutter">1</div>
        <textarea id="codeEditor" spellcheck="false" placeholder="Sol panelden bir dosya açın veya + Yeni ile oluşturun..."></textarea>
        <div id="mediaViewer"></div>
      </div>
    </div>

    <div class="term-area">
      <div class="pane-hdr" style="padding:5px 10px">
        <span>Terminal <span id="termCwd" style="font-weight:400;text-transform:none;color:var(--acc)"></span></span>
        <div class="row" style="gap:5px">
          <button class="sm" onclick="runTerm('py -m unittest discover -s tests -v')">Test Koş</button>
          <button class="sm" onclick="runTerm('git status -s')">git status</button>
          <button class="sm" onclick="sendTermErrorToAi()">Hatayı AI'ya Gönder</button>
          <button class="sm danger" onclick="stopTerm()">Durdur</button>
          <button class="sm" onclick="clearTerm()">Temizle</button>
        </div>
      </div>
      <div id="termOut" class="term-out"></div>
      <div class="term-inp">
        <span>PS&gt;</span>
        <input id="termInp" placeholder="Komut yazın (Enter ile çalıştırın; cd desteklenir)..." onkeydown="if(event.key==='Enter'){runTerm(this.value);this.value='';}" />
        <button class="sm primary" onclick="const i=document.getElementById('termInp');runTerm(i.value);i.value='';">Çalıştır</button>
      </div>
    </div>
  </section>

  <!-- RIGHT: AI CODING AGENT + VIDEO/IMAGE STUDIO -->
  <section class="pane">
    <div class="rtabs">
      <div id="rtabCode" class="rtab active" onclick="switchRightTab('code')">Kod Ajanı (Inkling 2)</div>
      <div id="rtabVid" class="rtab" onclick="switchRightTab('media')">Video &amp; Görsel (Wan 2.2)</div>
    </div>

    <!-- TAB 1: CODING AGENT -->
    <div id="rightCode" class="rbody">
      <div id="chatFeed" class="chat-feed">
        <div class="msg">
          <div class="msg-hdr"><span>PicoStudio Ajan</span><span>6 GB VRAM Hazır</span></div>
          <b>Inkling 2 Mini</b> burada açık dosyayı okuyabilir, kod üretebilir ve ürettiği kod bloğunu tek tıkla <b>Editöre Uygula</b> ile kaydedebilir. Video üretmek istediğinde <b>GPU Nöbetçisi</b> VRAM'i otomatik devreder.
        </div>
      </div>
      <div class="chat-ctrl">
        <div class="chat-opts">
          <label><input type="checkbox" id="chkIncludeFile" checked /> Proje + açık dosya</label>
          <select id="agentMode" title="Proje Ajanı dosya okuyup yazabilir; Hızlı mod anında yanıtlar">
            <option value="fast" selected>Hızlı (Proje Bağlamlı)</option>
            <option value="agent">Ajan (Dosya Oku/Yaz + Araçlar)</option>
          </select>
          <label style="cursor:pointer"><span class="pill">+ Görsel</span><input id="chatImg" type="file" accept="image/*" style="display:none" onchange="onChatImg(event)" /></label>
          <span id="chatImgTag" style="display:none" class="pill ok">Görsel eklendi</span>
          <button class="sm" style="margin-left:auto" onclick="clearChat()">Temizle</button>
        </div>
        <div class="row" style="align-items:flex-end">
          <textarea id="chatInp" rows="2" style="flex:1;resize:vertical" placeholder="Kod görevinizi yazın (Ctrl+Enter)..." onkeydown="if(event.ctrlKey&&event.key==='Enter')sendAgent()"></textarea>
          <button id="chatSendBtn" class="primary" style="height:48px;min-width:68px" onclick="sendAgent()">Gönder</button>
          <button id="chatAbortBtn" class="danger" style="height:48px;display:none" onclick="abortAgent()">Dur</button>
        </div>
      </div>
    </div>

    <!-- TAB 2: VIDEO & IMAGE STUDIO -->
    <div id="rightMedia" class="rbody" style="display:none">
      <div class="media-scroll">
        <div class="mcard">
          <div style="font-size:11.5px;color:#c084fc;font-weight:700">6 GB VRAM Otomatik Devir Aktif</div>
          <div style="font-size:11.5px;color:var(--mut)">Video/Görsel başlatıldığında çalışan kodlama modeli otomatik kapanır, 6 GB VRAM güvenle PicoVid'e aktarılır.</div>
          <textarea id="vidPrompt" rows="3" placeholder="Sahne açıklamanızı yazın (Türkçe veya İngilizce)..."></textarea>
          <div class="row">
            <button class="sm" style="flex:1" onclick="enhanceVideoPrompt()">Inkling 2 ile Sinematikleştir</button>
          </div>
          <div class="row">
            <select id="vidPreset" style="flex:1">
              <option value="5b|t2v|640|384|81">Wan 2.2 TI2V-5B Turbo (5sn · 640×384 → HD)</option>
              <option value="5b|t2v|832|480|81">Wan 2.2 TI2V-5B Natif (5sn · 832×480)</option>
              <option value="14b|t2v|640|384|33">Wan 2.2 14B T2V (Sinematik 2.1sn)</option>
              <option value="5b|t2i|1024|1024|1">Z-Image-Turbo (Hızlı Görsel · 1024×1024)</option>
            </select>
          </div>
          <div class="row" style="font-size:12px;color:var(--mut)">
            <label><input type="checkbox" id="chkCinemaHd" checked /> Sinema HD + 32fps</label>
            <label><input type="checkbox" id="chkFastPrev" /> Hızlı Önizleme (~2sn)</label>
          </div>
          <div class="row">
            <button id="vidStartBtn" class="purple" style="flex:1" onclick="startMedia()">Üretimi Başlat</button>
            <button class="danger" onclick="stopMedia()">Durdur</button>
          </div>
        </div>

        <div class="mcard">
          <div style="font-size:11.5px;color:var(--mut);font-weight:700">Canlı Üretim Logu</div>
          <div id="mediaLogBox" class="logbox">Henüz üretim başlatılmadı.</div>
        </div>

        <div class="mcard">
          <div class="row" style="justify-content:space-between">
            <span style="font-size:11.5px;color:var(--mut);font-weight:700">Son Çıktılar (Tıkla &amp; IDE'de İzle)</span>
            <button class="sm" onclick="loadMediaGallery()">Yenile</button>
          </div>
          <div id="mediaGallery" class="gallery"></div>
        </div>
      </div>
    </div>
  </section>
</div>

<script>
const openTabs = {}; // path -> {content, saved}
let activeTab = null;
let chatHistory = [];
let chatImgData = null;
let lastStatus = null;
let codeBlockStore = {};
let agentAbortCtrl = null;
const collapsedDirs = new Set();

const editor = document.getElementById('codeEditor');
const gutter = document.getElementById('gutter');

function escHtml(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

function updateGutter(){
  const n = Math.max(1, editor.value.split('\n').length);
  let s=''; for(let i=1;i<=n;i++) s += i+'\n';
  gutter.textContent = s;
  gutter.scrollTop = editor.scrollTop;
}
editor.addEventListener('input', ()=>{
  if(activeTab && openTabs[activeTab]){ openTabs[activeTab].content = editor.value; renderTabs(); }
  updateGutter();
});
editor.addEventListener('scroll', ()=>{ gutter.scrollTop = editor.scrollTop; });
editor.addEventListener('keydown', e=>{
  if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='s'){ e.preventDefault(); saveActiveFile(); }
  if(e.key==='Tab'){
    e.preventDefault();
    const s=editor.selectionStart, end=editor.selectionEnd;
    editor.value = editor.value.slice(0,s)+'    '+editor.value.slice(end);
    editor.selectionStart = editor.selectionEnd = s+4;
    editor.dispatchEvent(new Event('input'));
  }
});

async function loadProjects(){
  const r = await fetch('/api/workspace/projects').then(x=>x.json());
  const sel = document.getElementById('projSel');
  sel.innerHTML = '';
  for(const p of r.projects){
    const o = document.createElement('option');
    o.value = p.path; o.textContent = p.name;
    if(p.path === r.current) o.selected = true;
    sel.appendChild(o);
  }
}

async function switchProject(path){
  await fetch('/api/workspace/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  for(const k of Object.keys(openTabs)) delete openTabs[k];
  activeTab = null; editor.value = ''; updateGutter(); renderTabs();
  document.getElementById('activeFileLbl').textContent = 'Dosya seçilmedi';
  loadTree(); pollTerminal();
}

async function loadCodingModels(){
  const inv = await fetch('/api/inventory').then(x=>x.json());
  const sel = document.getElementById('modelSel');
  sel.innerHTML = '';
  for(const m of (inv.coding_models||[])){
    const o = document.createElement('option');
    o.value = m.id;
    const tag = m.id==='qwen25-coder-7b' ? '⚡ %100 GPU' : (m.id==='inkling2-mini' ? '🧠 Derin+Vision' : 'MoE');
    o.textContent = `${m.id} (${tag})${m.installed?'':' [Eksik]'}`;
    o.disabled = !m.installed;
    if(lastStatus && lastStatus.coding_model===m.id) o.selected = true;
    sel.appendChild(o);
  }
}

async function switchCodingModel(modelId){
  if(!modelId) return;
  const r = await fetch('/api/gpu/start-coding',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model: modelId})
  });
  const j = await r.json();
  if(!r.ok) alert(j.message||j.error||'Model baslatilamadi');
  pollStatus();
}

async function loadTree(){
  const r = await fetch('/api/workspace/tree').then(x=>x.json());
  const box = document.getElementById('fileTree');
  box.innerHTML = '';
  for(const it of r.items){
    // Hide items inside collapsed parent directories
    let hidden = false;
    for(const cd of collapsedDirs){
      if(it.path.startsWith(cd + '/')){ hidden = true; break; }
    }
    if(hidden) continue;
    const div = document.createElement('div');
    div.className = 'titem ' + (it.kind==='dir'?'dir':'') + (it.path===activeTab?' active':'');
    div.style.paddingLeft = (10 + it.depth*14) + 'px';
    if(it.kind==='dir'){
      const isCol = collapsedDirs.has(it.path);
      div.textContent = (isCol ? '▸ ' : '▾ ') + it.name;
      div.onclick = ()=>{ isCol ? collapsedDirs.delete(it.path) : collapsedDirs.add(it.path); loadTree(); };
    }else{
      div.innerHTML = `<span style="flex:1;overflow:hidden;text-overflow:ellipsis">${escHtml(it.name)}</span><span class="x" title="Sil" style="opacity:.45;font-size:11px;padding:0 4px" onclick="event.stopPropagation();deleteWorkspaceFile('${escHtml(it.path)}')">×</span>`;
      div.onclick = ()=>openFile(it.path);
    }
    box.appendChild(div);
  }
}

async function deleteWorkspaceFile(path){
  if(!confirm(path + ' dosyasını silmek istiyor musunuz?')) return;
  const r = await fetch('/api/workspace/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  if(r.ok){ closeTab(path); loadTree(); }
}

async function openFile(path){
  closeMediaViewer();
  if(!openTabs[path]){
    const r = await fetch('/api/workspace/file?path='+encodeURIComponent(path));
    const j = await r.json();
    if(!r.ok){ alert(j.error||'Acilamadi'); return; }
    openTabs[path] = {content: j.content, saved: j.content};
  }
  activeTab = path;
  editor.value = openTabs[path].content;
  document.getElementById('activeFileLbl').textContent = path;
  updateGutter(); renderTabs(); loadTree();
}

function renderTabs(){
  const bar = document.getElementById('tabBar');
  bar.innerHTML = '';
  for(const [p, st] of Object.entries(openTabs)){
    const dirty = st.content !== st.saved ? ' ●' : '';
    const t = document.createElement('div');
    t.className = 'etab' + (p===activeTab?' active':'');
    t.innerHTML = `<span>${escHtml(p.split('/').pop())}${dirty}</span><span class="x" onclick="event.stopPropagation();closeTab('${escHtml(p)}')">×</span>`;
    t.onclick = ()=>openFile(p);
    bar.appendChild(t);
  }
}

function closeTab(p){
  delete openTabs[p];
  if(activeTab===p){
    const keys = Object.keys(openTabs);
    activeTab = keys.length ? keys[0] : null;
    editor.value = activeTab ? openTabs[activeTab].content : '';
    document.getElementById('activeFileLbl').textContent = activeTab || 'Dosya seçilmedi';
    updateGutter();
  }
  renderTabs();
}

async function saveActiveFile(){
  if(!activeTab || !openTabs[activeTab]) return;
  const r = await fetch('/api/workspace/file',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path:activeTab, content:openTabs[activeTab].content})
  });
  if(r.ok){ openTabs[activeTab].saved = openTabs[activeTab].content; renderTabs(); }
}

async function newProjectPrompt(){
  const p = prompt('Yeni proje adı veya tam klasör yolu (örnek: araban veya C:\\Users\\ROBONENTA\\Desktop\\Projects\\araban):');
  if(!p || !p.trim()) return;
  const r = await fetch('/api/workspace/create-project',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path:p.trim()})
  });
  const j = await r.json();
  if(!r.ok){ alert(j.error||'Proje oluşturulamadı'); return; }
  for(const k of Object.keys(openTabs)) delete openTabs[k];
  activeTab = null; editor.value = ''; updateGutter(); renderTabs();
  document.getElementById('activeFileLbl').textContent = 'Dosya seçilmedi';
  await loadProjects(); await loadTree(); pollTerminal();
}

async function newFilePrompt(){
  const p = prompt('Aktif proje içinde yeni dosya adı/yolu (örnek: main.py veya src/app.py):');
  if(!p || !p.trim()) return;
  const r = await fetch('/api/workspace/file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:p.trim(), content:''})});
  const j = await r.json();
  if(!r.ok){ alert(j.error||'Dosya oluşturulamadı'); return; }
  await loadTree(); openFile(j.path || p.trim());
}

async function searchProject(){
  const q = document.getElementById('searchInp').value.trim();
  const box = document.getElementById('searchHits');
  if(!q){ box.style.display='none'; return; }
  const r = await fetch('/api/workspace/search?q='+encodeURIComponent(q)).then(x=>x.json());
  box.style.display = 'block';
  box.innerHTML = r.hits.length ? r.hits.map(h=>`<div class="hit" onclick="openFile('${escHtml(h.path)}')"><b>${escHtml(h.path)}:${h.line}</b><div style="color:var(--mut)">${escHtml(h.text)}</div></div>`).join('') : '<div class="hit">Sonuç bulunamadı</div>';
}

/* Terminal */
async function runTerm(cmd){
  if(!cmd || !cmd.trim()) return;
  await fetch('/api/terminal/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmd})});
  pollTerminal();
}
async function stopTerm(){ await fetch('/api/terminal/stop',{method:'POST'}); pollTerminal(); }
async function clearTerm(){ await fetch('/api/terminal/clear',{method:'POST'}); pollTerminal(); }
async function pollTerminal(){
  try{
    const j = await fetch('/api/terminal/status').then(x=>x.json());
    document.getElementById('termCwd').textContent = '· ' + j.cwd;
    const el = document.getElementById('termOut');
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    el.textContent = (j.lines||[]).join('\n');
    if(atBottom) el.scrollTop = el.scrollHeight;
  }catch(e){}
}
function sendTermErrorToAi(){
  const txt = document.getElementById('termOut').textContent.slice(-1800);
  switchRightTab('code');
  document.getElementById('chatInp').value = "Terminaldeki su hatayi analiz et ve duzeltilmis kodu ver:\n\n```\n" + txt + "\n```";
  document.getElementById('chatInp').focus();
}

/* Right tabs & GPU Arbiter */
function switchRightTab(tab){
  document.getElementById('rightCode').style.display = tab==='code'?'flex':'none';
  document.getElementById('rightMedia').style.display = tab==='media'?'flex':'none';
  document.getElementById('rtabCode').className = 'rtab' + (tab==='code'?' active':'');
  document.getElementById('rtabVid').className = 'rtab' + (tab==='media'?' active vid':'');
  if(tab==='media') loadMediaGallery();
}

async function toggleCodingEngine(){
  if(lastStatus?.owner==='coding' || lastStatus?.owner==='coding_starting'){
    await fetch('/api/gpu/stop-coding',{method:'POST'});
  }else{
    const m = document.getElementById('modelSel')?.value || null;
    await fetch('/api/gpu/start-coding',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:m})});
  }
  pollStatus();
}
async function stopAllGpu(){ await fetch('/api/gpu/stop-all',{method:'POST'}); pollStatus(); }

async function pollStatus(){
  try{
    const st = await fetch('/api/status').then(x=>x.json());
    lastStatus = st;
    const p = document.getElementById('gpuOwnerPill');
    const btn = document.getElementById('llmBtn');
    if(st.owner==='coding'){ p.className='pill ok'; p.textContent='GPU: KOD · '+st.coding_model; btn.textContent='Kodlama AI Durdur'; }
    else if(st.owner==='coding_starting'){ p.className='pill warn'; p.textContent='GPU: Yükleniyor...'; btn.textContent='Yükleniyor...'; }
    else if(st.owner==='media'){ p.className='pill vid'; p.textContent='GPU: VIDEO · '+(st.media_job?.engine||'5b').toUpperCase(); btn.textContent='Kodlama AI Başlat'; }
    else { p.className='pill'; p.textContent='GPU: Boşta'; btn.textContent='Kodlama AI Başlat'; }

    const hw = st.hardware||{};
    const msel = document.getElementById('modelSel');
    if(msel && st.coding_model && Array.from(msel.options).some(o=>o.value===st.coding_model && !o.disabled)){
      msel.value = st.coding_model;
    }
    if(hw.vram_used_ded_gib!=null && hw.vram_total_gib){
      const pct = Math.min(100, hw.vram_used_ded_gib/hw.vram_total_gib*100);
      const sh = hw.vram_used_shr_gib!=null?` · Sh:${hw.vram_used_shr_gib.toFixed(1)}`:'';
      document.getElementById('vramTxt').textContent = `VRAM ${hw.vram_used_ded_gib.toFixed(2)}/${hw.vram_total_gib.toFixed(1)}G${sh}`;
      const f = document.getElementById('vramFill'); f.style.width = pct.toFixed(0)+'%';
      f.className = 'mfill' + (pct>85?' err':pct>70?' warn':'');
    }
    if(hw.ram_used_gib!=null && hw.ram_total_gib){
      const pct = Math.min(100, hw.ram_used_gib/hw.ram_total_gib*100);
      document.getElementById('ramTxt').textContent = `RAM ${hw.ram_used_gib.toFixed(1)}/${hw.ram_total_gib.toFixed(1)}G`;
      document.getElementById('ramFill').style.width = pct.toFixed(0)+'%';
    }
    if(st.media_logs && st.media_logs.length){
      const ml = document.getElementById('mediaLogBox');
      ml.textContent = st.media_logs.join('\n');
      ml.scrollTop = ml.scrollHeight;
    }
  }catch(e){}
}

/* Coding Agent */
function onChatImg(ev){
  const f = ev.target.files[0]; if(!f) return;
  const rd = new FileReader();
  rd.onload = ()=>{ chatImgData = rd.result; document.getElementById('chatImgTag').style.display='inline-block'; };
  rd.readAsDataURL(f);
}
function clearChat(){ chatHistory=[]; document.getElementById('chatFeed').innerHTML=''; }
function askAiAboutFile(prefix){
  if(!activeTab){ alert('Once soldan bir dosya acin.'); return; }
  switchRightTab('code');
  document.getElementById('chkIncludeFile').checked = true;
  document.getElementById('chatInp').value = prefix;
  sendAgent();
}

function renderAgentMarkdown(txt){
  const parts = txt.split(/```(\w*)\n([\s\S]*?)```/g);
  let html = '';
  for(let i=0;i<parts.length;i+=3){
    html += escHtml(parts[i]||'').replace(/`([^`]+)`/g,'<code style="background:#0f172a;padding:1px 4px;border-radius:3px">$1</code>').replace(/\n/g,'<br>');
    if(i+2 < parts.length){
      const lang = parts[i+1] || 'code';
      const code = (parts[i+2] || '').trimEnd();
      if(!code.trim()) continue;
      const id = 'cb_' + Math.random().toString(36).slice(2,9);
      codeBlockStore[id] = code;
      const isShell = /^(sh|bash|powershell|ps1|cmd)$/i.test(lang);
      const actBtn = isShell
        ? `<button class="sm primary" onclick="runTerm(codeBlockStore['${id}'])">Terminalde Çalıştır</button>`
        : `<button class="sm primary" onclick="applyCodeToEditor('${id}')">Editöre Uygula</button>`;
      html += `<div class="code-blk"><div class="code-blk-h"><span>${escHtml(lang)}</span><div class="row" style="gap:4px">${actBtn}<button class="sm" onclick="navigator.clipboard.writeText(codeBlockStore['${id}'])">Kopyala</button></div></div><pre>${escHtml(code)}</pre></div>`;
    }
  }
  return html;
}

function applyCodeToEditor(id){
  const code = codeBlockStore[id]; if(!code) return;
  if(!activeTab){
    const p = prompt('Kodu hangi dosyaya kaydedelim? (ornek: yeni_dosya.py)');
    if(!p) return;
    openTabs[p] = {content: code, saved: ''};
    activeTab = p;
  }else{
    openTabs[activeTab].content = code;
  }
  editor.value = code;
  document.getElementById('activeFileLbl').textContent = activeTab;
  updateGutter(); renderTabs(); saveActiveFile();
}

function abortAgent(){
  if(agentAbortCtrl){ agentAbortCtrl.abort(); agentAbortCtrl = null; }
}

async function undoAgentEdit(undoId, btnEl){
  const r = await fetch('/api/workspace/undo',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({undo_id: undoId})
  });
  const j = await r.json();
  if(r.ok){
    btnEl.textContent = 'Geri Alındı'; btnEl.disabled = true;
    loadTree();
    if(j.deleted){ closeTab(j.path); }
    else if(openTabs[j.path]){ delete openTabs[j.path]; openFile(j.path); }
  }else{
    alert(j.error||'Geri alinamadi');
  }
}

async function sendAgent(){
  const inp = document.getElementById('chatInp');
  const text = inp.value.trim();
  if(!text && !chatImgData) return;
  inp.value = '';
  const feed = document.getElementById('chatFeed');

  let uContent = text;
  if(chatImgData){
    uContent = [{type:'text',text:text||'Bu ekran goruntusunu incele.'},{type:'image_url',image_url:{url:chatImgData}}];
    chatImgData = null; document.getElementById('chatImg').value=''; document.getElementById('chatImgTag').style.display='none';
  }
  chatHistory.push({role:'user', content:uContent});

  const uDiv = document.createElement('div');
  uDiv.className='msg user';
  uDiv.innerHTML=`<div class="msg-hdr"><span>Sen</span><span>${activeTab?escHtml(activeTab):'Proje'}</span></div><div>${escHtml(text)}</div>`;
  feed.appendChild(uDiv);

  const activeModelName = document.getElementById('modelSel')?.value || 'AI';
  const aDiv = document.createElement('div');
  aDiv.className='msg';
  aDiv.innerHTML=`<div class="msg-hdr"><span>${escHtml(activeModelName)}</span><span class="st">Proje taranıyor...</span></div><div class="tools" style="display:flex;flex-direction:column;gap:4px;margin-bottom:6px"></div><div class="bd">...</div>`;
  feed.appendChild(aDiv);
  feed.scrollTop = feed.scrollHeight;

  const btn = document.getElementById('chatSendBtn'); btn.disabled=true;
  const abtn = document.getElementById('chatAbortBtn'); abtn.style.display='inline-block';
  agentAbortCtrl = new AbortController();
  const mode = document.getElementById('agentMode').value;
  const activePayload = (document.getElementById('chkIncludeFile').checked && activeTab && openTabs[activeTab])
    ? {path: activeTab, content: openTabs[activeTab].content}
    : null;
  let full = ''; let toks = 0; const t0 = performance.now();
  try{
    const resp = await fetch('/api/agent/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},
      signal: agentAbortCtrl.signal,
      body:JSON.stringify({messages: chatHistory, mode, active_file: activePayload})
    });
    if(!resp.ok){
      const err = await resp.json().catch(()=>({error:resp.statusText}));
      aDiv.querySelector('.bd').textContent = 'Hata: ' + (err.error||resp.status);
      return;
    }
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf='';
    const toolsEl = aDiv.querySelector('.tools');
    while(true){
      const {done, value} = await reader.read(); if(done) break;
      buf += dec.decode(value,{stream:true});
      const lines = buf.split('\n'); buf = lines.pop()||'';
      for(const ln of lines){
        if(!ln.startsWith('data:')) continue;
        const ds = ln.slice(5).trim();
        if(!ds || ds==='[DONE]') continue;
        try{
          const ev = JSON.parse(ds);
          if(ev.type==='status'){
            aDiv.querySelector('.st').textContent = ev.text;
          }else if(ev.type==='tool'){
            const d = document.createElement('div');
            d.className = 'pill';
            d.style.borderRadius = '6px';
            d.textContent = `⚙ ${ev.name}(${JSON.stringify(ev.args||{}).slice(0,80)})`;
            toolsEl.appendChild(d);
          }else if(ev.type==='tool_result'){
            const d = document.createElement('div');
            d.style.cssText = 'font-size:11px;color:var(--mut);padding-left:6px';
            d.textContent = `↳ ${ev.summary}`;
            toolsEl.appendChild(d);
          }else if(ev.type==='file_changed'){
            loadTree();
            if(openTabs[ev.path]){ delete openTabs[ev.path]; openFile(ev.path); }
            const dc = document.createElement('div');
            dc.className = 'code-blk';
            dc.innerHTML = `<div class="code-blk-h"><span>✏ ${escHtml(ev.path)} <b style="color:var(--ok)">+${ev.added||0}</b> <b style="color:var(--err)">-${ev.removed||0}</b></span><div class="row" style="gap:4px"><button class="sm" onclick="openFile('${escHtml(ev.path)}')">Aç</button>${ev.undo_id?`<button class="sm danger" onclick="undoAgentEdit('${escHtml(ev.undo_id)}',this)">Geri Al</button>`:''}</div></div>${ev.diff?`<pre style="max-height:110px;font-size:10.8px">${escHtml(ev.diff)}</pre>`:''}`;
            toolsEl.appendChild(dc);
          }else if(ev.type==='delta' && ev.content){
            full += ev.content; toks++;
            const sec = (performance.now()-t0)/1000;
            aDiv.querySelector('.st').textContent = `${toks} tok · ${(toks/Math.max(0.2,sec)).toFixed(1)} t/s`;
            aDiv.querySelector('.bd').innerHTML = renderAgentMarkdown(full);
          }else if(ev.type==='error'){
            aDiv.querySelector('.bd').textContent = 'Hata: ' + ev.error;
          }
          feed.scrollTop = feed.scrollHeight;
        }catch(e){}
      }
    }
    chatHistory.push({role:'assistant', content:full});
  }catch(e){
    aDiv.querySelector('.bd').textContent = (e.name==='AbortError') ? 'Durduruldu.' : ('Bağlantı hatası: ' + e);
  }finally{
    btn.disabled = false; abtn.style.display='none'; agentAbortCtrl = null;
  }
}

/* Video & Image Studio */
async function enhanceVideoPrompt(){
  const box = document.getElementById('vidPrompt');
  const raw = box.value.trim();
  if(!raw){ alert('Once kisa bir sahne fikri yazin.'); return; }
  const r = await fetch('/api/media/enhance-prompt',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({prompt:raw})
  });
  const j = await r.json();
  if(r.ok && j.enhanced) box.value = j.enhanced;
  else alert(j.error||'Gelistirilemedi');
}

async function startMedia(){
  const prompt = document.getElementById('vidPrompt').value.trim();
  if(!prompt){ alert('Sahne promptu bos olamaz.'); return; }
  const [engine, mode, w, h, f] = document.getElementById('vidPreset').value.split('|');
  const r = await fetch('/api/media/start',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      prompt, engine, mode, width:+w, height:+h, frames:+f,
      cinema_hd: document.getElementById('chkCinemaHd').checked,
      fast_preview: document.getElementById('chkFastPrev').checked,
    })
  });
  const j = await r.json();
  if(!r.ok) alert(j.error||'Baslatilamadi');
  pollStatus();
}
async function stopMedia(){ await fetch('/api/media/stop',{method:'POST'}); pollStatus(); }

async function loadMediaGallery(){
  const items = await fetch('/api/media/outputs').then(x=>x.json());
  const g = document.getElementById('mediaGallery');
  g.innerHTML = items.length ? items.map(it=>`
    <div class="gitem" onclick="previewMedia('${escHtml(it.name)}','${it.kind}')">
      <div style="color:${it.kind==='video'?'#c084fc':'var(--acc)'};font-weight:700">${it.kind==='video'?'▶ MP4':'🖼 PNG'} · ${it.size_mb} MB</div>
      <div class="gname">${escHtml(it.name)}</div>
    </div>`).join('') : '<div style="color:var(--mut);font-size:12px">Henüz çıktı yok.</div>';
}

function previewMedia(name, kind){
  const mv = document.getElementById('mediaViewer');
  editor.style.display='none'; gutter.style.display='none'; mv.style.display='flex';
  const url = '/api/media/file?name=' + encodeURIComponent(name);
  mv.innerHTML = (kind==='video'
    ? `<video src="${url}" controls autoplay loop></video>`
    : `<img src="${url}" />`)
    + `<div class="row"><span style="font-size:12px;color:var(--mut)">${escHtml(name)}</span><button class="sm" onclick="closeMediaViewer()">Editöre Dön</button></div>`;
}
function closeMediaViewer(){
  document.getElementById('mediaViewer').style.display='none';
  editor.style.display='block'; gutter.style.display='block';
}

loadProjects(); loadCodingModels(); loadTree(); pollStatus(); pollTerminal();
setInterval(pollStatus, 2500);
setInterval(pollTerminal, 1500);
</script>
</body>
</html>
"""


def make_handler(arbiter: GPUArbiter, ws: Workspace, term: TerminalSession) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _json(self, data: Any, status: int = 200) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body_json(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(n) if n > 0 else b"{}"
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                return {}

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = dict(urllib.parse.parse_qsl(parsed.query))

            if path in ("/", "/index.html"):
                raw = IDE_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/status":
                self._json(arbiter.get_status())
                return
            if path == "/api/inventory":
                self._json(arbiter.get_inventory())
                return
            if path == "/api/workspace/projects":
                self._json({"current": str(ws.root), "projects": ws.list_projects()})
                return
            if path == "/api/workspace/tree":
                self._json({"root": str(ws.root), "items": ws.list_tree()})
                return
            if path == "/api/workspace/file":
                try:
                    self._json(ws.read_file(qs.get("path", "")))
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                except Exception as exc:
                    self._json({"error": str(exc)}, status=404)
                return
            if path == "/api/workspace/search":
                self._json({"hits": ws.search(qs.get("q", ""))})
                return
            if path == "/api/terminal/status":
                self._json(term.snapshot())
                return
            if path == "/api/media/outputs":
                self._json(arbiter.list_media_outputs())
                return
            if path == "/api/media/file":
                name = pathlib.Path(qs.get("name", "")).name
                fpath = arbiter.picovid_dir / "outputs" / name
                if not fpath.exists() or not fpath.is_file():
                    self._json({"error": "Bulunamadi"}, status=404)
                    return
                data = fpath.read_bytes()
                ctype = mimetypes.guess_type(fpath.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            self._json({"error": "Not found"}, status=404)

        def do_POST(self) -> None:
            path = urllib.parse.urlparse(self.path).path
            body = self._body_json()

            if path == "/api/workspace/select":
                try:
                    new_root = ws.set_root(str(body.get("path") or ""))
                    term.set_cwd(new_root)
                    self._json({"ok": True, "root": str(new_root)})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return

            if path == "/api/workspace/create-project":
                try:
                    new_root = ws.create_project(str(body.get("path") or ""))
                    term.set_cwd(new_root)
                    self._json({"ok": True, "root": str(new_root)})
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return

            if path == "/api/workspace/file":
                try:
                    res = ws.write_file(str(body.get("path") or ""), str(body.get("content") or ""))
                    self._json({"ok": True, **res})
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return

            if path == "/api/workspace/delete":
                try:
                    ok = ws.delete_file(str(body.get("path") or ""))
                    self._json({"ok": ok}, status=200 if ok else 404)
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return

            if path == "/api/workspace/undo":
                try:
                    res = ws.undo_edit(str(body.get("undo_id") or ""))
                    self._json({"ok": True, **res})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return

            if path == "/api/terminal/run":
                ok, msg = term.run_command(str(body.get("command") or ""))
                self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/terminal/stop":
                self._json({"ok": term.stop()})
                return
            if path == "/api/terminal/clear":
                term.clear()
                self._json({"ok": True})
                return

            if path == "/api/gpu/start-coding":
                ok, msg = arbiter.start_coding(body.get("model"))
                self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/gpu/stop-coding":
                arbiter.stop_coding()
                self._json({"ok": True})
                return
            if path == "/api/gpu/stop-all":
                arbiter.stop_all()
                self._json({"ok": True})
                return

            if path == "/api/media/start":
                ok, msg, out_path = arbiter.start_media(
                    prompt=str(body.get("prompt") or ""),
                    engine=str(body.get("engine") or "5b"),
                    mode=str(body.get("mode") or "t2v"),
                    width=int(body.get("width") or 640),
                    height=int(body.get("height") or 384),
                    frames=int(body.get("frames") or 81),
                    cinema_hd=bool(body.get("cinema_hd", True)),
                    fast_preview=bool(body.get("fast_preview", False)),
                )
                self._json({"ok": ok, "message": msg, "output": out_path}, status=200 if ok else 400)
                return

            if path == "/api/media/stop":
                arbiter.stop_media()
                self._json({"ok": True})
                return

            if path == "/api/media/enhance-prompt":
                if arbiter.owner != "coding":
                    ok, msg = arbiter.start_coding(wait_ready=True)
                    if not ok:
                        self._json({"error": msg}, status=503)
                        return
                raw_p = str(body.get("prompt") or "").strip()
                payload = {
                    "model": arbiter.coding_model,
                    "messages": [
                        {"role": "system", "content": "You rewrite short scene ideas into one rich, photorealistic English cinematic video prompt (camera motion, lighting, lens, detail, 2-3 sentences). Output ONLY the prompt."},
                        {"role": "user", "content": raw_p},
                        {"role": "assistant", "content": "Cinematic shot of "},
                    ],
                    "temperature": 0.6,
                    "max_tokens": 180,
                }
                req = urllib.request.Request(
                    f"http://{arbiter.llm_host}:{arbiter.llm_port}/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        res = json.loads(resp.read().decode("utf-8", errors="replace"))
                    txt = "Cinematic shot of " + (res["choices"][0]["message"].get("content") or "").strip()
                    self._json({"enhanced": txt})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=502)
                return

            if path == "/api/agent/chat":
                if arbiter.owner == "media":
                    self._json({"error": "Su an Video/Gorsel uretimi GPU'yu kullaniyor. Once bitmesini bekleyin veya durdurun."}, status=409)
                    return
                if arbiter.owner != "coding":
                    ok, msg = arbiter.start_coding(wait_ready=True)
                    if not ok:
                        self._json({"error": msg}, status=503)
                        return

                msgs = list(body.get("messages") or [])
                mode = str(body.get("mode") or "fast")
                active_file = body.get("active_file")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for ev in run_agent_stream(arbiter, ws, msgs, active_file=active_file, mode=mode):
                        line = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8")
                        self.wfile.write(line)
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except Exception as exc:
                    err_line = f"data: {json.dumps({'type': 'error', 'error': str(exc)}, ensure_ascii=False)}\n\n".encode("utf-8")
                    self.wfile.write(err_line)
                    self.wfile.flush()
                return

            self._json({"error": "Not found"}, status=404)

    return Handler


class PicoStudioHTTPServer(ThreadingHTTPServer):
    """Disable SO_REUSEADDR on Windows so two IDE instances never silently share port 7900."""
    allow_reuse_address = False


def run_ide(
    *,
    host: str | None = None,
    port: int | None = None,
    workspace_dir: str | None = None,
    open_browser: bool = True,
) -> int:
    cfg = load_config()
    h = host or cfg.get("ide_host", "127.0.0.1")
    p = int(port or cfg.get("ide_port", 7900))
    ws_path = workspace_dir or cfg.get("default_workspace") or str(pathlib.Path.cwd())

    arbiter = GPUArbiter(cfg)
    ws = Workspace(ws_path, projects_root=cfg.get("projects_root"))
    term = TerminalSession(ws.root)

    httpd = PicoStudioHTTPServer((h, p), make_handler(arbiter, ws, term))
    url = f"http://{h}:{p}/"
    print("============================================================")
    print(f"  PicoStudio Local IDE  -> {url}")
    print(f"  Aktif Proje           -> {ws.root}")
    print(f"  Kodlama Motoru        -> {arbiter.picocode_dir}")
    print(f"  Video/Gorsel Motoru   -> {arbiter.picovid_dir}")
    print("  Kapatmak icin Ctrl+C")
    print("============================================================", flush=True)
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        term.stop()
        arbiter.stop_all()
        httpd.server_close()
    return 0
