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

from picostudio import git_ops
from picostudio.agent import run_agent_stream
from picostudio.arbiter import GPUArbiter, load_config
from picostudio.terminal import TerminalManager, TerminalSession
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

  /* Left Explorer + Git Panel */
  .ltabs{display:flex;background:var(--p1);border-bottom:1px solid var(--b)}
  .ltab{flex:1;padding:7px 6px;text-align:center;font-size:11.5px;font-weight:700;color:var(--mut);cursor:pointer;border-bottom:2px solid transparent;display:flex;align-items:center;justify-content:center;gap:5px}
  .ltab.active{color:var(--acc);border-bottom-color:var(--acc);background:var(--p2)}
  .gbadge{background:var(--acc);color:#06121f;font-size:10px;font-weight:800;padding:0 5px;border-radius:999px;display:none}
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
  .git-panel{flex:1;display:none;flex-direction:column;min-height:0;overflow:hidden}
  .git-box{padding:8px;border-bottom:1px solid var(--b);display:flex;flex-direction:column;gap:6px}
  .git-scroll{flex:1;overflow-y:auto;padding:4px 0;font-size:12px}
  .git-sec{padding:5px 10px 3px;font-size:10.5px;font-weight:700;color:var(--mut);text-transform:uppercase;display:flex;justify-content:space-between;align-items:center}
  .gfile{padding:4px 9px;display:flex;align-items:center;gap:5px;cursor:pointer;color:#cbd5e1}
  .gfile:hover{background:var(--p2)}
  .gfile .gp{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
  .gcode{font-family:Consolas,monospace;font-size:10.5px;font-weight:700;width:18px;text-align:center;flex-shrink:0}
  .gcode.M{color:var(--warn)} .gcode.A,.gcode.U{color:var(--ok)} .gcode.D{color:var(--err)}
  .glog{padding:5px 10px;border-bottom:1px solid #162033;font-size:11px;color:var(--mut)}
  .glog b{color:var(--acc);font-family:Consolas,monospace}

  /* Center Editor Pro + Visual Diff + Resizable Terminal Pro */
  .center-col{display:flex;flex-direction:column;min-height:0;background:var(--bg);border-right:1px solid var(--b);overflow:hidden}
  .editor-area{flex:1;display:flex;flex-direction:column;min-height:90px;overflow:hidden}
  .tabbar{display:flex;align-items:center;background:var(--p1);border-bottom:1px solid var(--b);overflow-x:auto;gap:2px;padding:0 6px}
  .etab{display:flex;align-items:center;gap:6px;padding:7px 11px;font-size:12px;color:var(--mut);cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
  .etab.active{color:var(--txt);border-bottom-color:var(--acc);background:var(--bg)}
  .etab .x{font-size:11px;opacity:.65;padding:0 3px;border-radius:3px}
  .etab .x:hover{background:#334155;opacity:1}
  .etoolbar{display:flex;align-items:center;gap:6px;padding:5px 10px;background:var(--p2);border-bottom:1px solid var(--b);font-size:11.5px;color:var(--mut);flex-wrap:wrap}
  .find-bar{display:none;align-items:center;gap:6px;padding:5px 10px;background:#101a2e;border-bottom:1px solid #26395e;font-size:12px;flex-wrap:wrap}
  .find-bar input{width:170px;padding:3px 7px;font-size:12px}
  .code-host{flex:1;display:flex;min-height:0;background:var(--code);position:relative;overflow:hidden}
  .gutter{width:46px;background:#0a0f18;color:#475569;font-family:"Cascadia Code",Consolas,monospace;font-size:13px;line-height:1.5;padding:10px 6px;text-align:right;overflow:hidden;user-select:none;border-right:1px solid #172033;flex-shrink:0}
  .code-stage{flex:1;position:relative;min-width:0;min-height:0;overflow:hidden;background:var(--code)}
  .code-hl{position:absolute;inset:0;margin:0;padding:10px 12px;font-family:"Cascadia Code",Consolas,monospace;font-size:13px;line-height:1.5;white-space:pre;overflow:hidden;pointer-events:none;color:#e2e8f0;tab-size:4}
  #codeEditor{position:absolute;inset:0;width:100%;height:100%;margin:0;background:transparent;color:transparent;caret-color:#38bdf8;border:none;outline:none;resize:none;padding:10px 12px;font-family:"Cascadia Code",Consolas,monospace;font-size:13px;line-height:1.5;white-space:pre;overflow:auto;tab-size:4;-webkit-text-fill-color:transparent}
  #codeEditor::placeholder{-webkit-text-fill-color:#475569;color:#475569}
  #codeEditor::selection{background:rgba(56,189,248,.28)}
  .tok-kw{color:#c084fc;font-weight:600} .tok-fn{color:#60a5fa} .tok-str{color:#86efac}
  .tok-num{color:#fbbf24} .tok-com{color:#64748b;font-style:italic} .tok-dec{color:#f472b6}
  .tok-key{color:#38bdf8} .tok-tag{color:#f87171} .tok-var{color:#fb923c}
  mark.hl-match{background:rgba(250,204,21,.28);color:inherit;border-radius:2px}
  mark.hl-match.cur{background:rgba(250,204,21,.62);outline:1px solid #facc15}
  #diffViewer{display:none;flex:1;flex-direction:column;min-height:0;background:var(--code);overflow:hidden}
  .diff-hdr{display:flex;align-items:center;gap:8px;padding:7px 12px;background:#0f172a;border-bottom:1px solid var(--b);font-size:12px;flex-wrap:wrap}
  .diff-body{flex:1;overflow:auto;padding:8px 0;font-family:"Cascadia Code",Consolas,monospace;font-size:12px;line-height:1.48}
  .dln{padding:0 12px;white-space:pre;min-height:18px}
  .dln.add{background:rgba(34,197,94,.14);color:#86efac}
  .dln.del{background:rgba(239,68,68,.15);color:#fca5a5}
  .dln.hunk{background:rgba(56,189,248,.12);color:#7dd3fc;font-weight:600;margin-top:4px}
  .dln.meta{color:#64748b}
  .dln.ctx{color:#cbd5e1}
  #mediaViewer{display:none;flex:1;align-items:center;justify-content:center;flex-direction:column;gap:10px;padding:16px;background:#05080f}
  #mediaViewer video,#mediaViewer img{max-width:100%;max-height:78%;border-radius:8px;border:1px solid var(--b)}

  /* Quick Open Ctrl+P Modal */
  .qo-backdrop{display:none;position:fixed;inset:0;background:rgba(4,7,14,.68);z-index:900;align-items:flex-start;justify-content:center;padding-top:11vh}
  .qo-modal{width:540px;max-width:92vw;background:var(--p1);border:1px solid #334a73;border-radius:10px;box-shadow:0 20px 55px rgba(0,0,0,.65);overflow:hidden;display:flex;flex-direction:column}
  .qo-modal input{border:none;border-bottom:1px solid var(--b);border-radius:0;padding:11px 14px;font-size:14px;background:#0c1322;outline:none}
  .qo-list{max-height:320px;overflow-y:auto;padding:4px 0}
  .qo-item{padding:7px 14px;cursor:pointer;display:flex;justify-content:space-between;font-size:12.5px;color:#cbd5e1}
  .qo-item.sel,.qo-item:hover{background:rgba(56,189,248,.16);color:#fff}
  .qo-item .qo-dir{color:var(--mut);font-size:11px}

  /* Agent v2 Plan & Auto-Verify Cards */
  .plan-card{margin-top:8px;padding:9px 10px;border-radius:8px;background:#101c33;border:1px solid #2c4c7e;display:flex;flex-direction:column;gap:7px}
  .verify-card{margin-top:6px;border-radius:7px;border:1px solid var(--b);overflow:hidden;background:var(--code)}
  .verify-card.ok{border-color:rgba(34,197,94,.45)}
  .verify-card.fail{border-color:rgba(239,68,68,.5)}
  .verify-card .vh{padding:5px 8px;font-size:11.5px;font-weight:700;display:flex;justify-content:space-between;align-items:center}
  .verify-card.ok .vh{background:rgba(34,197,94,.14);color:#86efac}
  .verify-card.fail .vh{background:rgba(239,68,68,.16);color:#fca5a5}
  .verify-card pre{margin:0;padding:7px 8px;font-size:10.8px;max-height:110px;overflow:auto;color:#cbd5e1;font-family:Consolas,monospace}

  /* Terminal Pro Resizer, Multi-Tab, ANSI & Warp AI Bar */
  .resizer{height:5px;background:var(--b);cursor:row-resize;flex-shrink:0;transition:background .15s}
  .resizer:hover,.resizer.drag{background:var(--acc)}
  .term-area{height:255px;min-height:36px;display:flex;flex-direction:column;background:#070a10;flex-shrink:0}
  .term-area.collapsed{height:36px !important}
  .term-area.collapsed .term-body{display:none}
  .term-body{flex:1;display:flex;flex-direction:column;min-height:0}
  .ttabbar{display:flex;align-items:center;gap:4px;padding:4px 8px;background:var(--p1);border-bottom:1px solid var(--b);overflow-x:auto;flex-shrink:0}
  .ttab{display:flex;align-items:center;gap:6px;padding:3px 9px;border-radius:6px;font-size:11.5px;color:var(--mut);cursor:pointer;background:transparent;border:1px solid transparent;white-space:nowrap}
  .ttab.active{color:var(--txt);background:var(--p2);border-color:var(--b)}
  .ttab .dot{width:7px;height:7px;border-radius:50%;background:var(--ok);display:inline-block;animation:pulse 1.1s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
  .term-out{flex:1;overflow-y:auto;padding:8px 11px;font-family:"Cascadia Code",Consolas,monospace;font-size:12px;line-height:1.45;color:#cbd5e1;white-space:pre-wrap;word-break:break-word}
  .tlink{color:#38bdf8;text-decoration:underline;cursor:pointer}
  .tlink:hover{color:#7dd3fc}
  .nl-bar{display:none;align-items:center;gap:8px;padding:6px 10px;background:#101c31;border-top:1px solid #2b4570;font-size:12px;flex-wrap:wrap}
  .nl-bar code{background:#070c16;padding:3px 7px;border-radius:5px;color:#7dd3fc;font-family:"Cascadia Code",Consolas,monospace;font-size:12px}
  .comp-bar{display:none;gap:5px;padding:4px 10px;background:#0b1220;border-top:1px solid #1b2740;flex-wrap:wrap;font-size:11px;font-family:Consolas,monospace;color:#93c5fd}
  .term-inp{display:flex;align-items:center;gap:6px;padding:6px 10px;border-top:1px solid #1b253a;background:var(--p1)}
  .term-inp .prompt-tag{font-family:Consolas,monospace;font-size:12px;font-weight:700;color:var(--acc);white-space:nowrap}
  .term-inp .prompt-tag.stdin{color:var(--warn)}
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
    <span class="pill">v0.4.0</span>
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
  <!-- LEFT: EXPLORER + GIT -->
  <section class="pane">
    <div class="ltabs">
      <div id="ltabFiles" class="ltab active" onclick="switchLeftTab('files')">Dosyalar</div>
      <div id="ltabGit" class="ltab" onclick="switchLeftTab('git')">Git <span id="gitBadge" class="gbadge">0</span></div>
    </div>

    <div id="leftFiles" style="flex:1;display:flex;flex-direction:column;min-height:0">
      <div class="pane-hdr">
        <span>Gezgin</span>
        <div class="row" style="gap:4px">
          <button class="sm" onclick="openQuickOpen()" title="Hızlı dosya aç (Ctrl+P)">Ctrl+P</button>
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
    </div>

    <div id="leftGit" class="git-panel">
      <div class="pane-hdr">
        <span id="gitBranchLbl">⎇ Git</span>
        <div class="row" style="gap:4px">
          <button class="sm" onclick="gitStageAll()" title="Tüm değişiklikleri stage et">+ Tümü</button>
          <button class="sm" onclick="loadGitStatus(true)">↻</button>
        </div>
      </div>
      <div class="git-box">
        <textarea id="gitCommitMsg" rows="2" placeholder="Commit mesajı yazın..."></textarea>
        <div class="row" style="gap:5px">
          <button class="sm primary" style="flex:1" onclick="gitCommit()">Commit</button>
          <button id="gitAiBtn" class="sm" onclick="gitAiMessage()" title="Yerel AI ile diff'ten commit mesajı üret">✨ AI</button>
          <button class="sm" onclick="openGitDiff('',false)" title="Tüm çalışma diff'ini gör">Diff</button>
        </div>
      </div>
      <div id="gitScroll" class="git-scroll"></div>
    </div>
  </section>

  <!-- CENTER: EDITOR PRO + VISUAL DIFF + TERMINAL PRO -->
  <section class="center-col">
    <div class="editor-area">
      <div id="tabBar" class="tabbar"></div>
      <div class="etoolbar">
        <span id="activeFileLbl">Dosya seçilmedi</span>
        <span id="cursorStatus" style="font-size:11px;color:#64748b"></span>
        <div style="margin-left:auto;display:flex;gap:5px;flex-wrap:wrap">
          <button class="sm" onclick="toggleFindBar(true)" title="Dosya içi bul / değiştir (Ctrl+F)">Bul (Ctrl+F)</button>
          <button class="sm primary" onclick="saveActiveFile()">Kaydet (Ctrl+S)</button>
          <button class="sm" onclick="askAiAboutFile('Bu dosyadaki olasi buglari ve iyilestirmeleri bul:')">Bug Bul</button>
          <button class="sm" onclick="askAiAboutFile('Bu dosya icin temiz bir refactor onerisi ve tam kodu ver:')">Refactor</button>
          <button class="sm" onclick="askAiAboutFile('Bu dosya icin unittest birim testleri yaz:')">Test Yaz</button>
          <button class="sm" onclick="closeCenterOverlays()">Editöre Dön</button>
        </div>
      </div>
      <div id="findBar" class="find-bar">
        <input id="findInp" placeholder="Bul..." oninput="updateFindMatches()" onkeydown="onFindKey(event)" />
        <input id="replaceInp" placeholder="Değiştir..." onkeydown="if(event.key==='Enter')replaceOne()" />
        <span id="findCount" style="color:var(--mut);font-size:11px;min-width:46px">0/0</span>
        <button class="sm" onclick="jumpFind(-1)">▲</button>
        <button class="sm" onclick="jumpFind(1)">▼</button>
        <button class="sm" onclick="replaceOne()">Değiştir</button>
        <button class="sm" onclick="replaceAll()">Tümü</button>
        <button class="sm" onclick="toggleFindBar(false)">×</button>
      </div>
      <div class="code-host">
        <div id="gutter" class="gutter">1</div>
        <div id="codeStage" class="code-stage">
          <pre id="codeHighlight" class="code-hl" aria-hidden="true"></pre>
          <textarea id="codeEditor" spellcheck="false" placeholder="Sol panelden bir dosya açın, Ctrl+P ile hızlı açın veya + Yeni ile oluşturun..."></textarea>
        </div>
        <div id="diffViewer"></div>
        <div id="mediaViewer"></div>
      </div>
    </div>

    <div id="termResizer" class="resizer" title="Terminali boyutlandırmak için sürükleyin"></div>
    <div id="termArea" class="term-area">
      <div class="ttabbar">
        <div id="termTabs" class="row" style="gap:4px"></div>
        <button class="sm" onclick="createTerminalTab()" title="Yeni terminal sekmesi">+</button>
        <span id="termCwd" style="font-size:11px;color:var(--acc);margin-left:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:280px"></span>
        <div class="row" style="margin-left:auto;gap:4px">
          <button class="sm" onclick="runTerm('py -m unittest discover -s tests -v')">Test Koş</button>
          <button class="sm" onclick="runTerm('git status -s')">git</button>
          <button class="sm" onclick="sendTermErrorToAi()" title="Terminal çıktısını AI'ya gönder">AI Çöz</button>
          <button class="sm danger" onclick="stopTerm()">Durdur</button>
          <button class="sm" onclick="clearTerm()">Temizle</button>
          <button class="sm" onclick="toggleTermMax()" title="Büyüt/Küçült">⤢</button>
          <button class="sm" onclick="toggleTermCollapse()" title="Daralt/Aç">▾</button>
        </div>
      </div>
      <div class="term-body">
        <div id="termOut" class="term-out"></div>
        <div id="compBar" class="comp-bar"></div>
        <div id="nlCmdBar" class="nl-bar">
          <span class="pill">AI Komut</span>
          <code id="nlCmdCode"></code>
          <span id="nlCmdDesc" style="color:var(--mut);font-size:11.5px;flex:1"></span>
          <button class="sm primary" onclick="acceptNlCmd(true)">Çalıştır</button>
          <button class="sm" onclick="acceptNlCmd(false)">Düzenle</button>
          <button class="sm danger" onclick="hideNlBar()">İptal</button>
        </div>
        <div class="term-inp">
          <span id="termPromptTag" class="prompt-tag">PS&gt;</span>
          <input id="termInp" autocomplete="off" placeholder="Komut yazın (↑↓ geçmiş · Tab tamamla · ? ile Türkçe AI komut)..." onkeydown="onTermKey(event)" />
          <button id="termRunBtn" class="sm primary" onclick="submitTermInput()">Çalıştır</button>
        </div>
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
          <label><input type="checkbox" id="chkIncludeFile" checked /> Proje + dosya</label>
          <select id="agentMode" title="Hızlı anında yanıtlar; Planla+Onayla önce plan çıkarır; Ajan doğrudan dosya okuyup yazar">
            <option value="fast">Hızlı (Proje Bağlamlı)</option>
            <option value="plan">Planla + Onayla (Çok Dosyalı)</option>
            <option value="agent" selected>Ajan v2 (Dosya + Araçlar)</option>
          </select>
          <label title="Ajan dosya düzenledikten sonra proje testlerini otomatik koşar; hata çıkarsa kendi düzeltir"><input type="checkbox" id="chkAutoVerify" checked /> Oto-Test</label>
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

<!-- QUICK OPEN MODAL (Ctrl+P) -->
<div id="quickOpenBackdrop" class="qo-backdrop" onclick="if(event.target===this)closeQuickOpen()">
  <div class="qo-modal">
    <input id="quickOpenInp" placeholder="Dosya adına göre hızlı aç (Ctrl+P)..." oninput="renderQuickOpen()" onkeydown="onQuickOpenKey(event)" />
    <div id="quickOpenList" class="qo-list"></div>
  </div>
</div>

<script>
const openTabs = {}; // path -> {content, saved}
let activeTab = null;
let chatHistory = [];
let chatImgData = null;
let lastStatus = null;
let codeBlockStore = {};
let agentAbortCtrl = null;
let allWorkspaceFiles = [];
const collapsedDirs = new Set();

const editor = document.getElementById('codeEditor');
const gutter = document.getElementById('gutter');
const codeHL = document.getElementById('codeHighlight');
const codeStage = document.getElementById('codeStage');

function escHtml(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

/* ========== CODE EDITOR PRO (Syntax Highlight, Auto-Indent/Pairs, Ctrl+F/H, Ctrl+P) ========== */
let findMatches = [];
let findIdx = -1;
const PAIRS = {'(':')','[':']','{':'}','"':'"',"'":"'"};

function detectLang(path){
  const ext = (path||'').split('.').pop().toLowerCase();
  if(ext==='py') return 'python';
  if(['js','mjs','cjs','ts','tsx','jsx'].includes(ext)) return 'js';
  if(ext==='json') return 'json';
  if(['html','htm','xml','svg'].includes(ext)) return 'html';
  if(ext==='css') return 'css';
  if(['ps1','sh','bash','cmd','bat'].includes(ext)) return 'shell';
  if(ext==='md') return 'md';
  return 'plain';
}

function highlightCode(src, path){
  const lang = detectLang(path);
  let re;
  if(lang==='python'){
    re = /(#[^\n]*|"{3}[\s\S]*?"{3}|'{3}[\s\S]*?'{3}|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|@[A-Za-z_]\w*|\b(?:def|class|import|from|return|if|elif|else|for|while|try|except|finally|with|as|yield|async|await|lambda|pass|break|continue|raise|in|not|and|or|is|None|True|False|global|nonlocal|assert|del)\b|\b\d+(?:\.\d+)?\b)/g;
  }else if(lang==='js'){
    re = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|\b(?:const|let|var|function|class|return|if|else|for|while|switch|case|break|continue|try|catch|finally|throw|async|await|import|export|from|default|new|this|typeof|instanceof|type|interface|extends|implements|true|false|null|undefined|void)\b|\b\d+(?:\.\d+)?\b)/g;
  }else if(lang==='json'){
    re = /("(?:\\.|[^"\\\n])*"\s*:|"(?:\\.|[^"\\\n])*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)/g;
  }else if(lang==='html'){
    re = /(<!--[\s\S]*?-->|<\/?[A-Za-z][A-Za-z0-9-]*|\s[A-Za-z-:]+(?==)|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')/g;
  }else if(lang==='css'){
    re = /(\/\*[\s\S]*?\*\/|@[a-z-]+|\.[A-Za-z_-][\w-]*|#[0-9a-fA-F]{3,8}\b|[a-z-]+(?=\s*:)|"(?:\\.|[^"\\\n])*"|\b\d+(?:\.\d+)?(?:px|rem|em|vh|vw|%|s|ms)?\b)/g;
  }else if(lang==='shell'){
    re = /(#[^\n]*|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|\$[A-Za-z_]\w*|\b(?:if|else|elseif|for|foreach|while|function|return|try|catch|Set-Location|Get-ChildItem|Where-Object|ForEach-Object|echo|cd|exit)\b)/g;
  }else if(lang==='md'){
    re = /(^#{1,6}\s[^\n]*|`[^`\n]+`|\*\*[^*\n]+\*\*)/gm;
  }else{
    return escHtml(src);
  }
  let out = ''; let last = 0; let m;
  while((m = re.exec(src)) !== null){
    if(m.index > last) out += escHtml(src.slice(last, m.index));
    const t = m[0];
    let cls = '';
    if((lang==='python'||lang==='shell') && t.startsWith('#')) cls='tok-com';
    else if((lang==='js'||lang==='css') && (t.startsWith('//')||t.startsWith('/*'))) cls='tok-com';
    else if(lang==='html' && t.startsWith('<!--')) cls='tok-com';
    else if(lang==='json' && t.endsWith(':')) cls='tok-key';
    else if(t.startsWith('"')||t.startsWith("'")||t.startsWith('`')) cls='tok-str';
    else if(t.startsWith('@')) cls='tok-dec';
    else if(t.startsWith('$')) cls='tok-var';
    else if(lang==='html' && t.startsWith('<')) cls='tok-tag';
    else if(lang==='html' && t.startsWith(' ')) cls='tok-key';
    else if(lang==='md' && t.startsWith('#')) cls='tok-fn';
    else if(lang==='md' && t.startsWith('`')) cls='tok-str';
    else if(/^-?\d/.test(t)) cls='tok-num';
    else if(lang==='css' && t.startsWith('.')) cls='tok-fn';
    else if(lang==='css' && t.startsWith('#')) cls='tok-num';
    else if(lang==='css' && /^[a-z-]+$/.test(t)) cls='tok-key';
    else cls='tok-kw';
    out += cls ? `<span class="${cls}">${escHtml(t)}</span>` : escHtml(t);
    last = re.lastIndex;
  }
  if(last < src.length) out += escHtml(src.slice(last));
  return out;
}

function applyFindMarks(raw, q){
  if(!q) return highlightCode(raw, activeTab);
  const ql = q.toLowerCase(), rl = raw.toLowerCase();
  let html = ''; let pos = 0; let idx = 0;
  while(true){
    const hit = rl.indexOf(ql, pos);
    if(hit === -1){ html += highlightCode(raw.slice(pos), activeTab); break; }
    html += highlightCode(raw.slice(pos, hit), activeTab);
    const curCls = (idx === findIdx) ? ' cur' : '';
    html += `<mark class="hl-match${curCls}">${escHtml(raw.slice(hit, hit + q.length))}</mark>`;
    pos = hit + q.length; idx++;
  }
  return html;
}

function renderHighlight(){
  const val = editor.value || '';
  const q = (document.getElementById('findBar').style.display === 'flex') ? document.getElementById('findInp').value : '';
  codeHL.innerHTML = (q ? applyFindMarks(val, q) : highlightCode(val, activeTab)) + '\n';
  codeHL.scrollTop = editor.scrollTop;
  codeHL.scrollLeft = editor.scrollLeft;
}

function updateCursorStatus(){
  const pos = editor.selectionStart || 0;
  const before = editor.value.slice(0, pos);
  const lines = before.split('\n');
  const ln = lines.length, col = lines[lines.length - 1].length + 1;
  const lang = detectLang(activeTab);
  document.getElementById('cursorStatus').textContent = activeTab ? `Sat ${ln}, Süt ${col} · ${lang.toUpperCase()}` : '';
}

function updateGutter(){
  const n = Math.max(1, editor.value.split('\n').length);
  let s=''; for(let i=1;i<=n;i++) s += i+'\n';
  gutter.textContent = s;
  gutter.scrollTop = editor.scrollTop;
  renderHighlight();
  updateCursorStatus();
}

editor.addEventListener('input', ()=>{
  if(activeTab && openTabs[activeTab]){ openTabs[activeTab].content = editor.value; renderTabs(); }
  updateGutter();
  if(document.getElementById('findBar').style.display === 'flex') updateFindMatches(false);
});
editor.addEventListener('scroll', ()=>{
  gutter.scrollTop = editor.scrollTop;
  codeHL.scrollTop = editor.scrollTop;
  codeHL.scrollLeft = editor.scrollLeft;
});
editor.addEventListener('click', updateCursorStatus);
editor.addEventListener('keyup', updateCursorStatus);

editor.addEventListener('keydown', e=>{
  const s = editor.selectionStart, end = editor.selectionEnd, val = editor.value;
  if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='s'){ e.preventDefault(); saveActiveFile(); return; }
  if((e.ctrlKey||e.metaKey) && (e.key.toLowerCase()==='f' || e.key.toLowerCase()==='h')){
    e.preventDefault(); toggleFindBar(true); return;
  }
  if((e.ctrlKey||e.metaKey) && e.key==='/'){
    e.preventDefault();
    const pref = (detectLang(activeTab)==='python'||detectLang(activeTab)==='shell') ? '# ' : '// ';
    const lineStart = val.lastIndexOf('\n', s - 1) + 1;
    const lineEnd = val.indexOf('\n', end);
    const blkEnd = lineEnd === -1 ? val.length : lineEnd;
    const lines = val.slice(lineStart, blkEnd).split('\n');
    const allCom = lines.every(l => !l.trim() || l.trimStart().startsWith(pref.trim()));
    const next = lines.map(l => {
      if(!l.trim()) return l;
      if(allCom) return l.replace(new RegExp('^(\\s*)'+pref.trim().replace('/','\\/')+'\\s?'), '$1');
      return l.replace(/^(\s*)/, '$1' + pref);
    }).join('\n');
    editor.value = val.slice(0, lineStart) + next + val.slice(blkEnd);
    editor.selectionStart = lineStart; editor.selectionEnd = lineStart + next.length;
    editor.dispatchEvent(new Event('input'));
    return;
  }
  if(e.key==='Tab'){
    e.preventDefault();
    if(e.shiftKey){
      const lineStart = val.lastIndexOf('\n', s - 1) + 1;
      const lineEnd = val.indexOf('\n', end);
      const blkEnd = lineEnd === -1 ? val.length : lineEnd;
      const next = val.slice(lineStart, blkEnd).split('\n').map(l => l.replace(/^ {1,4}|\t/, '')).join('\n');
      editor.value = val.slice(0, lineStart) + next + val.slice(blkEnd);
      editor.selectionStart = lineStart; editor.selectionEnd = lineStart + next.length;
    }else if(s !== end && val.slice(s, end).includes('\n')){
      const lineStart = val.lastIndexOf('\n', s - 1) + 1;
      const lineEnd = val.indexOf('\n', end);
      const blkEnd = lineEnd === -1 ? val.length : lineEnd;
      const next = val.slice(lineStart, blkEnd).split('\n').map(l => '    ' + l).join('\n');
      editor.value = val.slice(0, lineStart) + next + val.slice(blkEnd);
      editor.selectionStart = lineStart; editor.selectionEnd = lineStart + next.length;
    }else{
      editor.value = val.slice(0, s) + '    ' + val.slice(end);
      editor.selectionStart = editor.selectionEnd = s + 4;
    }
    editor.dispatchEvent(new Event('input'));
    return;
  }
  if(e.key==='Enter'){
    e.preventDefault();
    const lineStart = val.lastIndexOf('\n', s - 1) + 1;
    const curLine = val.slice(lineStart, s);
    const indent = (curLine.match(/^\s*/) || [''])[0];
    const trimmed = curLine.trimEnd();
    const extra = /[:{(\[]$/.test(trimmed) ? '    ' : '';
    const nextCh = val[end] || '';
    const prevCh = val[s - 1] || '';
    if((prevCh==='{'&&nextCh==='}') || (prevCh==='['&&nextCh===']') || (prevCh==='('&&nextCh===')')){
      const ins = '\n' + indent + '    \n' + indent;
      editor.value = val.slice(0, s) + ins + val.slice(end);
      editor.selectionStart = editor.selectionEnd = s + 1 + indent.length + 4;
    }else{
      const ins = '\n' + indent + extra;
      editor.value = val.slice(0, s) + ins + val.slice(end);
      editor.selectionStart = editor.selectionEnd = s + ins.length;
    }
    editor.dispatchEvent(new Event('input'));
    return;
  }
  if(e.key==='Backspace' && s===end && s>0 && PAIRS[val[s-1]]===val[s]){
    e.preventDefault();
    editor.value = val.slice(0, s - 1) + val.slice(s + 1);
    editor.selectionStart = editor.selectionEnd = s - 1;
    editor.dispatchEvent(new Event('input'));
    return;
  }
  if(Object.values(PAIRS).includes(e.key) && s===end && val[s]===e.key && !['"',"'"].includes(e.key)){
    e.preventDefault();
    editor.selectionStart = editor.selectionEnd = s + 1;
    return;
  }
  if(PAIRS[e.key] && !e.ctrlKey && !e.altKey && !e.metaKey){
    const closeCh = PAIRS[e.key];
    if((e.key==='"' || e.key==="'") && s===end && val[s]===e.key){
      e.preventDefault(); editor.selectionStart = editor.selectionEnd = s + 1; return;
    }
    e.preventDefault();
    const sel = val.slice(s, end);
    editor.value = val.slice(0, s) + e.key + sel + closeCh + val.slice(end);
    editor.selectionStart = s + 1;
    editor.selectionEnd = end + 1;
    editor.dispatchEvent(new Event('input'));
  }
});

/* Global Shortcuts: Ctrl+P Quick Open, Ctrl+F Find */
window.addEventListener('keydown', e=>{
  if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='p'){
    e.preventDefault(); openQuickOpen();
  }else if(e.key==='Escape'){
    if(document.getElementById('quickOpenBackdrop').style.display==='flex') closeQuickOpen();
    else if(document.getElementById('findBar').style.display==='flex') toggleFindBar(false);
  }
});

/* In-File Find & Replace */
function toggleFindBar(show){
  const bar = document.getElementById('findBar');
  bar.style.display = show ? 'flex' : 'none';
  if(show){
    const inp = document.getElementById('findInp');
    const sel = editor.value.slice(editor.selectionStart, editor.selectionEnd);
    if(sel && !sel.includes('\n')) inp.value = sel;
    inp.focus(); inp.select();
    updateFindMatches(true);
  }else{
    findMatches = []; findIdx = -1; renderHighlight(); editor.focus();
  }
}
function updateFindMatches(jumpFirst=true){
  const q = document.getElementById('findInp').value;
  findMatches = [];
  if(q){
    const ql = q.toLowerCase(), txt = editor.value.toLowerCase();
    let pos = 0;
    while(true){
      const idx = txt.indexOf(ql, pos);
      if(idx === -1) break;
      findMatches.push({start: idx, end: idx + q.length});
      pos = idx + q.length;
    }
  }
  findIdx = findMatches.length ? (jumpFirst ? 0 : Math.min(Math.max(0, findIdx), findMatches.length - 1)) : -1;
  document.getElementById('findCount').textContent = findMatches.length ? `${findIdx+1}/${findMatches.length}` : '0/0';
  renderHighlight();
  if(jumpFirst && findIdx >= 0) scrollEditorToPos(findMatches[findIdx].start);
}
function scrollEditorToPos(pos){
  const lnIdx = editor.value.slice(0, pos).split('\n').length - 1;
  editor.scrollTop = Math.max(0, lnIdx * 19.5 - editor.clientHeight / 3);
  gutter.scrollTop = editor.scrollTop; codeHL.scrollTop = editor.scrollTop;
}
function jumpFind(delta){
  if(!findMatches.length) return;
  findIdx = (findIdx + delta + findMatches.length) % findMatches.length;
  document.getElementById('findCount').textContent = `${findIdx+1}/${findMatches.length}`;
  const m = findMatches[findIdx];
  scrollEditorToPos(m.start);
  editor.setSelectionRange(m.start, m.end);
  renderHighlight();
}
function onFindKey(ev){
  if(ev.key==='Enter'){ ev.preventDefault(); jumpFind(ev.shiftKey ? -1 : 1); }
  else if(ev.key==='Escape'){ toggleFindBar(false); }
}
function replaceOne(){
  if(findIdx < 0 || !findMatches[findIdx]) return;
  const rep = document.getElementById('replaceInp').value;
  const m = findMatches[findIdx];
  editor.value = editor.value.slice(0, m.start) + rep + editor.value.slice(m.end);
  editor.dispatchEvent(new Event('input'));
  updateFindMatches(false);
}
function replaceAll(){
  const q = document.getElementById('findInp').value;
  if(!q) return;
  const rep = document.getElementById('replaceInp').value;
  const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  editor.value = editor.value.replace(re, rep);
  editor.dispatchEvent(new Event('input'));
  updateFindMatches(false);
}

/* Quick Open Ctrl+P Modal */
let qoItems = []; let qoSel = 0;
function openQuickOpen(){
  document.getElementById('quickOpenBackdrop').style.display = 'flex';
  const inp = document.getElementById('quickOpenInp');
  inp.value = ''; inp.focus();
  qoSel = 0; renderQuickOpen();
}
function closeQuickOpen(){ document.getElementById('quickOpenBackdrop').style.display = 'none'; }
function fuzzyScore(text, query){
  if(!query) return 1;
  const t = text.toLowerCase(), q = query.toLowerCase();
  if(t.includes(q)) return 100 - t.indexOf(q) * 0.1;
  let ti = 0, score = 0;
  for(const ch of q){
    const f = t.indexOf(ch, ti);
    if(f === -1) return -1;
    score += (f === ti ? 3 : 1);
    ti = f + 1;
  }
  return score;
}
function renderQuickOpen(){
  const q = document.getElementById('quickOpenInp').value.trim();
  qoItems = allWorkspaceFiles
    .map(p => ({path: p, score: fuzzyScore(p, q)}))
    .filter(x => x.score >= 0)
    .sort((a,b) => b.score - a.score)
    .slice(0, 30);
  if(qoSel >= qoItems.length) qoSel = 0;
  const list = document.getElementById('quickOpenList');
  list.innerHTML = qoItems.length ? qoItems.map((it, i)=>{
    const parts = it.path.split('/');
    const name = parts.pop(); const dir = parts.join('/');
    return `<div class="qo-item${i===qoSel?' sel':''}" onclick="closeQuickOpen();openFile('${escHtml(it.path)}')"><span>${escHtml(name)}</span><span class="qo-dir">${escHtml(dir)}</span></div>`;
  }).join('') : '<div style="padding:12px 14px;color:var(--mut);font-size:12px">Eşleşen dosya yok.</div>';
}
function onQuickOpenKey(ev){
  if(ev.key==='ArrowDown'){ ev.preventDefault(); qoSel = Math.min(qoItems.length - 1, qoSel + 1); renderQuickOpen(); }
  else if(ev.key==='ArrowUp'){ ev.preventDefault(); qoSel = Math.max(0, qoSel - 1); renderQuickOpen(); }
  else if(ev.key==='Enter' && qoItems[qoSel]){ ev.preventDefault(); const p = qoItems[qoSel].path; closeQuickOpen(); openFile(p); }
  else if(ev.key==='Escape'){ closeQuickOpen(); }
}

/* ========== GIT & VISUAL DIFF PANEL ========== */
function switchLeftTab(tab){
  document.getElementById('leftFiles').style.display = tab==='files' ? 'flex' : 'none';
  document.getElementById('leftGit').style.display = tab==='git' ? 'flex' : 'none';
  document.getElementById('ltabFiles').className = 'ltab' + (tab==='files' ? ' active' : '');
  document.getElementById('ltabGit').className = 'ltab' + (tab==='git' ? ' active' : '');
  if(tab==='git') loadGitStatus(true);
}

async function loadGitStatus(renderList=false){
  try{
    const st = await fetch('/api/git/status').then(x=>x.json());
    const badge = document.getElementById('gitBadge');
    if(st.is_repo && st.total_changes > 0){
      badge.style.display = 'inline-block'; badge.textContent = st.total_changes;
    }else{
      badge.style.display = 'none';
    }
    if(!renderList && document.getElementById('leftGit').style.display !== 'flex') return;
    const hdr = document.getElementById('gitBranchLbl');
    const box = document.getElementById('gitScroll');
    if(!st.is_repo){
      hdr.textContent = '⎇ Git Yok';
      box.innerHTML = '<div style="padding:12px;color:var(--mut);font-size:12px">Bu proje henüz bir Git reposu değil.</div>';
      return;
    }
    const ab = (st.ahead?` ↑${st.ahead}`:'') + (st.behind?` ↓${st.behind}`:'');
    hdr.textContent = `⎇ ${st.branch}${ab}`;
    let html = '';
    if(st.staged.length){
      html += `<div class="git-sec"><span>Hazır / Staged (${st.staged.length})</span><button class="sm" onclick="gitUnstage('')">- Tümü</button></div>`;
      html += st.staged.map(f=>`<div class="gfile" onclick="openGitDiff('${escHtml(f.path)}',true)"><span class="gcode A">${escHtml(f.code)}</span><span class="gp" title="${escHtml(f.path)}">${escHtml(f.path)}</span><button class="sm" title="Unstage" onclick="event.stopPropagation();gitUnstage('${escHtml(f.path)}')">-</button></div>`).join('');
    }
    const chg = [...st.unstaged, ...st.untracked];
    html += `<div class="git-sec"><span>Değişenler (${chg.length})</span></div>`;
    if(chg.length){
      html += chg.map(f=>{
        const cls = f.code==='??'?'U':(f.code==='D'?'D':'M');
        return `<div class="gfile" onclick="openGitDiff('${escHtml(f.path)}',false)"><span class="gcode ${cls}">${escHtml(f.code)}</span><span class="gp" title="${escHtml(f.path)}">${escHtml(f.path)}</span><button class="sm" title="Stage" onclick="event.stopPropagation();gitStage('${escHtml(f.path)}')">+</button><button class="sm danger" title="Geri Al (Revert)" onclick="event.stopPropagation();gitRevert('${escHtml(f.path)}')">↺</button></div>`;
      }).join('');
    }else{
      html += '<div style="padding:6px 10px;color:var(--mut);font-size:11.5px">Çalışma dizini temiz ✓</div>';
    }
    const logs = await fetch('/api/git/log').then(x=>x.json()).catch(()=>[]);
    if(logs && logs.length){
      html += `<div class="git-sec" style="margin-top:8px"><span>Son Commitler</span></div>`;
      html += logs.slice(0, 8).map(l=>`<div class="glog"><b>${escHtml(l.hash)}</b> ${escHtml(l.subject)}<div style="font-size:10px;opacity:.75">${escHtml(l.author)} · ${escHtml(l.when)}</div></div>`).join('');
    }
    box.innerHTML = html;
  }catch(e){}
}

async function openGitDiff(path, staged){
  const r = await fetch(`/api/git/diff?path=${encodeURIComponent(path)}&staged=${staged?1:0}`).then(x=>x.json());
  const dv = document.getElementById('diffViewer');
  document.getElementById('mediaViewer').style.display = 'none';
  codeStage.style.display = 'none'; gutter.style.display = 'none';
  dv.style.display = 'flex';
  const actBtn = path
    ? (staged
      ? `<button class="sm" onclick="gitUnstage('${escHtml(path)}').then(()=>openGitDiff('${escHtml(path)}',false))">Unstage</button>`
      : `<button class="sm primary" onclick="gitStage('${escHtml(path)}').then(()=>openGitDiff('${escHtml(path)}',true))">Stage (+)</button>`)
      + `<button class="sm" onclick="openFile('${escHtml(path)}')">Dosyayı Aç</button>`
    : '';
  const bodyHtml = (r.lines && r.lines.length)
    ? r.lines.map(ln=>`<div class="dln ${ln.type}">${escHtml(ln.text)||' '}</div>`).join('')
    : '<div style="padding:16px;color:var(--mut)">Gösterilecek fark yok.</div>';
  dv.innerHTML = `<div class="diff-hdr"><b>${escHtml(r.path||path)}</b><span class="pill">${staged?'Staged':'Working Tree'}</span><span style="color:var(--ok);font-weight:700">+${r.added||0}</span><span style="color:var(--err);font-weight:700">-${r.removed||0}</span><div style="margin-left:auto;display:flex;gap:5px">${actBtn}<button class="sm" onclick="closeCenterOverlays()">Editöre Dön</button></div></div><div class="diff-body">${bodyHtml}</div>`;
}
async function gitStage(path){ await fetch('/api/git/stage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})}); await loadGitStatus(true); }
async function gitStageAll(){ await fetch('/api/git/stage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:''})}); await loadGitStatus(true); }
async function gitUnstage(path){ await fetch('/api/git/unstage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})}); await loadGitStatus(true); }
async function gitRevert(path){
  if(!confirm(path + ' dosyasındaki değişiklikleri geri almak istiyor musunuz?')) return;
  const r = await fetch('/api/git/revert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  if(r.ok){
    if(openTabs[path]){ delete openTabs[path]; openFile(path); }
    loadTree(); loadGitStatus(true);
  }
}
async function gitCommit(){
  const inp = document.getElementById('gitCommitMsg');
  const msg = inp.value.trim();
  if(!msg){ alert('Önce bir commit mesajı yazın.'); return; }
  const r = await fetch('/api/git/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
  const j = await r.json();
  if(r.ok && j.ok){ inp.value = ''; await loadGitStatus(true); }
  else alert(j.error || 'Commit başarısız (önce dosyaları + ile stage edin).');
}
async function gitAiMessage(){
  const btn = document.getElementById('gitAiBtn');
  btn.disabled = true; btn.textContent = '...';
  try{
    const r = await fetch('/api/git/ai-message',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const j = await r.json();
    if(r.ok && j.message) document.getElementById('gitCommitMsg').value = j.message;
    else alert(j.error || 'Commit mesajı üretilemedi.');
  }finally{ btn.disabled = false; btn.textContent = '✨ AI'; }
}
function closeCenterOverlays(){
  document.getElementById('mediaViewer').style.display = 'none';
  document.getElementById('diffViewer').style.display = 'none';
  codeStage.style.display = 'block'; gutter.style.display = 'block';
  renderHighlight();
}

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
  closeCenterOverlays(); loadTree(); pollTerminal(); loadGitStatus(true);
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
  allWorkspaceFiles = (r.items||[]).filter(x=>x.kind==='file').map(x=>x.path);
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
  closeCenterOverlays();
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
  if(r.ok){ openTabs[activeTab].saved = openTabs[activeTab].content; renderTabs(); loadGitStatus(false); }
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
  await loadProjects(); await loadTree(); pollTerminal(); loadGitStatus(true);
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

/* ========== TERMINAL PRO (Multi-Tab, Live SSE, ANSI, Clickable Links, Stdin, Tab-Complete, ? AI) ========== */
let activeTermId = null;
let termRunning = false;
let termEventSrc = null;
let termHistory = [];
let termHistIdx = -1;
let pendingNlCmd = '';
let termSavedHeight = 255;
let termMaximized = false;

const ANSI_COLORS = {
  30:'#475569',31:'#f87171',32:'#4ade80',33:'#fbbf24',34:'#60a5fa',35:'#c084fc',36:'#38bdf8',37:'#e2e8f0',
  90:'#64748b',91:'#fca5a5',92:'#86efac',93:'#fde047',94:'#93c5fd',95:'#d8b4fe',96:'#67e8f9',97:'#ffffff'
};

function linkifyPaths(safeHtml){
  // 1) Python traceback: File "C:\...\foo.py", line 42
  safeHtml = safeHtml.replace(/File &quot;([^&]+?)&quot;, line (\d+)/g, (m, p, ln)=>{
    const clean = p.replace(/\\/g, '/');
    return `File "<span class="tlink" onclick="jumpFromTerm('${escHtml(clean)}',${ln})">${p}</span>", line ${ln}`;
  });
  // 2) Generic path:line (e.g. pulsemonitor/server.py:62 or apps/client/src/Drive.tsx:128)
  safeHtml = safeHtml.replace(/(^|[\s(])([A-Za-z0-9_.\-/\\]+\.(?:py|ts|tsx|js|jsx|html|css|json|md)):(\d+)/g, (m, pre, p, ln)=>{
    const clean = p.replace(/\\/g, '/');
    return `${pre}<span class="tlink" onclick="jumpFromTerm('${escHtml(clean)}',${ln})">${p}:${ln}</span>`;
  });
  return safeHtml;
}

function renderAnsiLine(raw){
  const re = /\x1b\[([0-9;]*)m/g;
  let out = ''; let last = 0; let m;
  let color = null; let bold = false; let dim = false;
  while((m = re.exec(raw)) !== null){
    if(m.index > last){
      const chunk = linkifyPaths(escHtml(raw.slice(last, m.index)));
      const st = (color?`color:${color};`:'') + (bold?'font-weight:700;':'') + (dim?'opacity:.65;':'');
      out += st ? `<span style="${st}">${chunk}</span>` : chunk;
    }
    const codes = (m[1]||'0').split(';').map(x=>parseInt(x||'0',10));
    for(const c of codes){
      if(c===0){ color=null; bold=false; dim=false; }
      else if(c===1) bold=true;
      else if(c===2) dim=true;
      else if(ANSI_COLORS[c]) color = ANSI_COLORS[c];
    }
    last = re.lastIndex;
  }
  if(last < raw.length){
    const chunk = linkifyPaths(escHtml(raw.slice(last)));
    const st = (color?`color:${color};`:'') + (bold?'font-weight:700;':'') + (dim?'opacity:.65;':'');
    out += st ? `<span style="${st}">${chunk}</span>` : chunk;
  }
  return out;
}

async function jumpFromTerm(filePath, lineNum){
  let rel = filePath.replace(/\\/g, '/');
  const projRoot = (document.getElementById('projSel')?.value || '').replace(/\\/g, '/').replace(/\/$/, '');
  if(projRoot && rel.toLowerCase().startsWith(projRoot.toLowerCase() + '/')){
    rel = rel.slice(projRoot.length + 1);
  }
  await openFile(rel);
  gotoEditorLine(lineNum);
}

function gotoEditorLine(lineNum){
  const lines = editor.value.split('\n');
  const idx = Math.max(0, Math.min(lines.length - 1, lineNum - 1));
  let pos = 0;
  for(let i=0;i<idx;i++) pos += lines[i].length + 1;
  editor.focus();
  editor.setSelectionRange(pos, pos + (lines[idx]?.length || 0));
  const lineH = 19.5;
  editor.scrollTop = Math.max(0, idx * lineH - editor.clientHeight / 3);
  gutter.scrollTop = editor.scrollTop;
}

function appendTermLines(lines, reset=false){
  const el = document.getElementById('termOut');
  const atBottom = reset || (el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  if(reset) el.innerHTML = '';
  const frag = document.createDocumentFragment();
  for(const ln of (lines||[])){
    const div = document.createElement('div');
    div.innerHTML = renderAnsiLine(ln) || '&nbsp;';
    frag.appendChild(div);
  }
  el.appendChild(frag);
  while(el.childNodes.length > 450) el.removeChild(el.firstChild);
  if(atBottom) el.scrollTop = el.scrollHeight;
}

function setTermRunningState(running){
  termRunning = !!running;
  const tag = document.getElementById('termPromptTag');
  const inp = document.getElementById('termInp');
  const btn = document.getElementById('termRunBtn');
  if(termRunning){
    tag.textContent = 'stdin>'; tag.className = 'prompt-tag stdin';
    inp.placeholder = 'Çalışan işleme girdi gönderin (y/n veya metin + Enter)...';
    btn.textContent = 'Gönder';
  }else{
    tag.textContent = 'PS>'; tag.className = 'prompt-tag';
    inp.placeholder = 'Komut yazın (↑↓ geçmiş · Tab tamamla · ? ile Türkçe AI komut)...';
    btn.textContent = 'Çalıştır';
  }
}

async function loadTermSessions(){
  const r = await fetch('/api/terminal/sessions').then(x=>x.json());
  const box = document.getElementById('termTabs');
  box.innerHTML = '';
  if(!activeTermId && r.sessions.length) activeTermId = r.sessions[0].id;
  if(activeTermId && !r.sessions.some(s=>s.id===activeTermId) && r.sessions.length){
    activeTermId = r.sessions[0].id;
  }
  for(const s of r.sessions){
    const t = document.createElement('div');
    t.className = 'ttab' + (s.id===activeTermId?' active':'');
    t.innerHTML = `${s.running?'<span class="dot"></span>':''}<span>${escHtml(s.name)}</span><span style="opacity:.55;padding-left:3px" onclick="event.stopPropagation();closeTerminalTab('${s.id}')">×</span>`;
    t.onclick = ()=>selectTerminalTab(s.id);
    box.appendChild(t);
  }
}

async function createTerminalTab(){
  const r = await fetch('/api/terminal/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(x=>x.json());
  activeTermId = r.id;
  await loadTermSessions();
  connectTermStream(activeTermId);
}

async function closeTerminalTab(sid){
  await fetch('/api/terminal/sessions/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:sid})});
  if(activeTermId===sid) activeTermId = null;
  await loadTermSessions();
  if(activeTermId) connectTermStream(activeTermId);
}

async function selectTerminalTab(sid){
  activeTermId = sid;
  await loadTermSessions();
  connectTermStream(sid);
}

async function connectTermStream(sid){
  if(termEventSrc){ termEventSrc.close(); termEventSrc = null; }
  const snap = await fetch('/api/terminal/status?id='+encodeURIComponent(sid)).then(x=>x.json());
  document.getElementById('termCwd').textContent = '· ' + snap.cwd;
  termHistory = snap.history || [];
  termHistIdx = termHistory.length;
  setTermRunningState(snap.running);
  appendTermLines(snap.lines || [], true);

  termEventSrc = new EventSource(`/api/terminal/stream?id=${encodeURIComponent(sid)}&after=${snap.seq||0}`);
  termEventSrc.onmessage = (e)=>{
    try{
      const ev = JSON.parse(e.data);
      if(ev.type==='output'){
        appendTermLines(ev.lines || [], false);
        document.getElementById('termCwd').textContent = '· ' + ev.cwd;
        if(ev.running !== termRunning){ setTermRunningState(ev.running); loadTermSessions(); }
      }else if(ev.type==='state'){
        document.getElementById('termCwd').textContent = '· ' + ev.cwd;
        if(ev.running !== termRunning){ setTermRunningState(ev.running); loadTermSessions(); }
      }
    }catch(err){}
  };
}

async function pollTerminal(){
  await loadTermSessions();
  if(activeTermId && !termEventSrc) connectTermStream(activeTermId);
}

async function runTerm(cmd){
  if(!cmd || !cmd.trim()) return;
  const clean = cmd.trim();
  if(!termHistory.length || termHistory[termHistory.length-1] !== clean) termHistory.push(clean);
  termHistIdx = termHistory.length;
  document.getElementById('compBar').style.display = 'none';
  await fetch('/api/terminal/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:activeTermId, command:clean})});
  loadTermSessions();
}

async function submitTermInput(){
  const inp = document.getElementById('termInp');
  const val = inp.value;
  if(!val.trim()) return;
  inp.value = '';
  document.getElementById('compBar').style.display = 'none';
  if(termRunning){
    await fetch('/api/terminal/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:activeTermId, text:val})});
    return;
  }
  if(val.trim().startsWith('?')){
    const q = val.trim().slice(1).trim();
    if(q) requestNlCmd(q);
    return;
  }
  runTerm(val);
}

async function onTermKey(ev){
  const inp = ev.target;
  if(ev.key==='Enter'){ ev.preventDefault(); submitTermInput(); return; }
  if(ev.key==='ArrowUp' && !termRunning){
    ev.preventDefault();
    if(termHistIdx > 0){ termHistIdx--; inp.value = termHistory[termHistIdx] || ''; }
    return;
  }
  if(ev.key==='ArrowDown' && !termRunning){
    ev.preventDefault();
    if(termHistIdx < termHistory.length - 1){ termHistIdx++; inp.value = termHistory[termHistIdx] || ''; }
    else { termHistIdx = termHistory.length; inp.value = ''; }
    return;
  }
  if(ev.key==='Tab' && !termRunning){
    ev.preventDefault();
    const r = await fetch('/api/terminal/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:activeTermId, line:inp.value})}).then(x=>x.json());
    inp.value = r.completed || inp.value;
    const cb = document.getElementById('compBar');
    if(r.matches && r.matches.length > 1){
      cb.style.display = 'flex';
      cb.innerHTML = r.matches.slice(0,12).map(m=>`<span style="cursor:pointer;padding:1px 5px;background:#162238;border-radius:4px" onclick="applyCompletion('${escHtml(m)}')">${escHtml(m)}</span>`).join('');
    }else{
      cb.style.display = 'none';
    }
  }
}

function applyCompletion(choice){
  const inp = document.getElementById('termInp');
  const parts = inp.value.split(' ');
  parts[parts.length - 1] = choice;
  inp.value = parts.join(' ');
  document.getElementById('compBar').style.display = 'none';
  inp.focus();
}

async function requestNlCmd(query){
  const bar = document.getElementById('nlCmdBar');
  bar.style.display = 'flex';
  document.getElementById('nlCmdCode').textContent = 'AI çeviriyor...';
  document.getElementById('nlCmdDesc').textContent = query;
  pendingNlCmd = '';
  const r = await fetch('/api/terminal/nl2cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:activeTermId, query})});
  const j = await r.json();
  if(r.ok && j.command){
    pendingNlCmd = j.command;
    document.getElementById('nlCmdCode').textContent = j.command;
    document.getElementById('nlCmdDesc').textContent = j.explanation || '';
  }else{
    document.getElementById('nlCmdCode').textContent = 'Hata';
    document.getElementById('nlCmdDesc').textContent = j.error || 'Çevrilemedi';
  }
}
function acceptNlCmd(execNow){
  const cmd = pendingNlCmd; hideNlBar();
  if(!cmd) return;
  if(execNow) runTerm(cmd);
  else { const i = document.getElementById('termInp'); i.value = cmd; i.focus(); }
}
function hideNlBar(){ document.getElementById('nlCmdBar').style.display='none'; pendingNlCmd=''; }

async function stopTerm(){ await fetch('/api/terminal/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:activeTermId})}); loadTermSessions(); }
async function clearTerm(){
  await fetch('/api/terminal/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:activeTermId})});
  document.getElementById('termOut').innerHTML = '';
}
function sendTermErrorToAi(){
  const txt = document.getElementById('termOut').innerText.slice(-1800);
  switchRightTab('code');
  document.getElementById('chatInp').value = "Terminaldeki şu hatayı analiz et ve düzeltilmiş kodu ver:\n\n```\n" + txt + "\n```";
  document.getElementById('chatInp').focus();
}

/* Draggable Resize + Collapse + Maximize */
(function initTermResizer(){
  const bar = document.getElementById('termResizer');
  const area = document.getElementById('termArea');
  let dragging = false, startY = 0, startH = 0;
  bar.addEventListener('mousedown', e=>{
    dragging = true; startY = e.clientY; startH = area.offsetHeight;
    bar.classList.add('drag'); area.classList.remove('collapsed'); termMaximized = false;
    document.body.style.userSelect = 'none';
  });
  window.addEventListener('mousemove', e=>{
    if(!dragging) return;
    const h = Math.max(90, Math.min(window.innerHeight * 0.78, startH + (startY - e.clientY)));
    area.style.height = h + 'px'; termSavedHeight = h;
  });
  window.addEventListener('mouseup', ()=>{
    if(!dragging) return;
    dragging = false; bar.classList.remove('drag'); document.body.style.userSelect = '';
  });
})();
function toggleTermCollapse(){
  const area = document.getElementById('termArea');
  area.classList.toggle('collapsed');
}
function toggleTermMax(){
  const area = document.getElementById('termArea');
  area.classList.remove('collapsed');
  termMaximized = !termMaximized;
  area.style.height = (termMaximized ? Math.round(window.innerHeight * 0.68) : termSavedHeight) + 'px';
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
  const autoVerify = !!document.getElementById('chkAutoVerify')?.checked;
  const activePayload = (document.getElementById('chkIncludeFile').checked && activeTab && openTabs[activeTab])
    ? {path: activeTab, content: openTabs[activeTab].content}
    : null;
  let full = ''; let toks = 0; const t0 = performance.now();
  try{
    const resp = await fetch('/api/agent/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},
      signal: agentAbortCtrl.signal,
      body:JSON.stringify({messages: chatHistory, mode, auto_verify: autoVerify, active_file: activePayload})
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
            loadTree(); loadGitStatus(false);
            if(openTabs[ev.path]){ delete openTabs[ev.path]; openFile(ev.path); }
            const dc = document.createElement('div');
            dc.className = 'code-blk';
            dc.innerHTML = `<div class="code-blk-h"><span>✏ ${escHtml(ev.path)} <b style="color:var(--ok)">+${ev.added||0}</b> <b style="color:var(--err)">-${ev.removed||0}</b></span><div class="row" style="gap:4px"><button class="sm" onclick="openFile('${escHtml(ev.path)}')">Aç</button>${ev.undo_id?`<button class="sm danger" onclick="undoAgentEdit('${escHtml(ev.undo_id)}',this)">Geri Al</button>`:''}</div></div>${ev.diff?`<pre style="max-height:110px;font-size:10.8px">${escHtml(ev.diff)}</pre>`:''}`;
            toolsEl.appendChild(dc);
          }else if(ev.type==='verify'){
            const vc = document.createElement('div');
            vc.className = 'verify-card ' + (ev.passed ? 'ok' : 'fail');
            const ttl = ev.passed
              ? `✓ Oto-Test Geçti (Tur ${ev.round||1}) · ${ev.command}`
              : `✗ Oto-Test Başarısız (exit ${ev.exit_code}) · Ajan düzeltiyor (Tur ${ev.round||1})`;
            vc.innerHTML = `<div class="vh"><span>${escHtml(ttl)}</span></div>${ev.output?`<pre>${escHtml(ev.output.slice(-900))}</pre>`:''}`;
            toolsEl.appendChild(vc);
          }else if(ev.type==='plan_ready'){
            const pc = document.createElement('div');
            pc.className = 'plan-card';
            pc.innerHTML = `<div style="font-size:11.5px;color:var(--acc);font-weight:700">📋 Plan Hazır — Onay Bekliyor</div><div style="font-size:11.5px;color:var(--mut)">Onayladığınızda ajan planı çok dosyalı olarak uygular ve proje testlerini otomatik çalıştırır.</div><div class="row" style="gap:6px"><button class="sm primary" onclick="approvePlanAndRun(this)">✓ Planı Onayla ve Uygula (Oto-Test)</button><button class="sm danger" onclick="this.closest('.plan-card').remove()">İptal</button></div>`;
            aDiv.appendChild(pc);
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
  document.getElementById('diffViewer').style.display='none';
  codeStage.style.display='none'; gutter.style.display='none'; mv.style.display='flex';
  const url = '/api/media/file?name=' + encodeURIComponent(name);
  mv.innerHTML = (kind==='video'
    ? `<video src="${url}" controls autoplay loop></video>`
    : `<img src="${url}" />`)
    + `<div class="row"><span style="font-size:12px;color:var(--mut)">${escHtml(name)}</span><button class="sm" onclick="closeCenterOverlays()">Editöre Dön</button></div>`;
}
function closeMediaViewer(){ closeCenterOverlays(); }

function approvePlanAndRun(btnEl){
  const card = btnEl.closest('.plan-card');
  if(card){ card.innerHTML = '<div style="font-size:11.5px;color:var(--ok);font-weight:700">✓ Plan Onaylandı — Ajan uyguluyor...</div>'; }
  document.getElementById('agentMode').value = 'agent';
  const chk = document.getElementById('chkAutoVerify');
  if(chk) chk.checked = true;
  document.getElementById('chatInp').value = 'Plan onaylandı. Şimdi tüm değişiklikleri adım adım uygula ve doğrula.';
  sendAgent();
}

loadProjects(); loadCodingModels(); loadTree(); loadGitStatus(false); pollStatus(); pollTerminal();
setInterval(pollStatus, 2500);
setInterval(loadTermSessions, 3500);
setInterval(()=>loadGitStatus(false), 6000);
</script>
</body>
</html>
"""


def make_handler(arbiter: GPUArbiter, ws: Workspace, term_mgr: TerminalManager | TerminalSession) -> type[BaseHTTPRequestHandler]:
    if isinstance(term_mgr, TerminalSession):
        mgr = TerminalManager(term_mgr.cwd)
        mgr.sessions = {term_mgr.id: term_mgr}
        mgr.active_id = term_mgr.id
        term_mgr = mgr

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
            if path == "/api/git/status":
                self._json(git_ops.get_status(ws))
                return
            if path == "/api/git/diff":
                try:
                    self._json(git_ops.get_diff(ws, qs.get("path", ""), staged=(qs.get("staged") in ("1", "true", "True"))))
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/git/log":
                self._json(git_ops.get_log(ws, limit=int(qs.get("limit", "12") or "12")))
                return
            if path == "/api/terminal/sessions":
                self._json({"sessions": term_mgr.list_sessions()})
                return
            if path == "/api/terminal/status":
                self._json(term_mgr.get(qs.get("id")).snapshot())
                return
            if path == "/api/terminal/stream":
                sess = term_mgr.get(qs.get("id"))
                after = int(qs.get("after", "0") or "0")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for ev in sess.subscribe(after_seq=after, heartbeat_s=4.0):
                        chunk = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8")
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
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
                    term_mgr.set_cwd_all(new_root)
                    self._json({"ok": True, "root": str(new_root)})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=400)
                return

            if path == "/api/workspace/create-project":
                try:
                    new_root = ws.create_project(str(body.get("path") or ""))
                    term_mgr.set_cwd_all(new_root)
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

            if path == "/api/git/stage":
                try:
                    ok, msg = git_ops.stage_path(ws, body.get("path"))
                    self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/git/unstage":
                try:
                    ok, msg = git_ops.unstage_path(ws, body.get("path"))
                    self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/git/revert":
                try:
                    ok, msg = git_ops.revert_path(ws, str(body.get("path") or ""))
                    self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                except PermissionError as exc:
                    self._json({"error": str(exc)}, status=403)
                return
            if path == "/api/git/commit":
                res = git_ops.commit_changes(ws, str(body.get("message") or ""))
                self._json(res, status=200 if res.get("ok") else 400)
                return
            if path == "/api/git/ai-message":
                if arbiter.owner == "media":
                    self._json({"error": "GPU su an Video/Gorsel uretiminde."}, status=409)
                    return
                diff_info = git_ops.get_diff(ws, "", staged=True)
                if not diff_info.get("raw"):
                    diff_info = git_ops.get_diff(ws, "", staged=False)
                raw_diff = (diff_info.get("raw") or "")[:3200]
                if not raw_diff:
                    self._json({"error": "Diff bos; once bir degisiklik yapin."}, status=400)
                    return
                if arbiter.owner != "coding":
                    ok, msg = arbiter.start_coding(wait_ready=True)
                    if not ok:
                        self._json({"error": msg}, status=503)
                        return
                payload = {
                    "model": arbiter.coding_model,
                    "messages": [
                        {"role": "system", "content": "Write ONE concise Conventional Commit message line (e.g. 'feat: add syntax highlighting') for the git diff below. Output ONLY the single line, no quotes or markdown."},
                        {"role": "user", "content": raw_diff},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 60,
                }
                req = urllib.request.Request(
                    f"http://{arbiter.llm_host}:{arbiter.llm_port}/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=90) as resp:
                        res = json.loads(resp.read().decode("utf-8", errors="replace"))
                    msg_txt = (res["choices"][0]["message"].get("content") or "").strip().splitlines()[0].strip("`\"' ")
                    self._json({"message": msg_txt})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=502)
                return

            if path == "/api/terminal/sessions":
                s = term_mgr.create_session(name=body.get("name"), cwd=body.get("cwd"))
                self._json({"ok": True, "id": s.id, "name": s.name, "cwd": str(s.cwd)})
                return
            if path == "/api/terminal/sessions/close":
                ok = term_mgr.close_session(str(body.get("id") or ""))
                self._json({"ok": ok})
                return
            if path == "/api/terminal/run":
                sess = term_mgr.get(body.get("id"))
                ok, msg = sess.run_command(str(body.get("command") or ""))
                self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/terminal/input":
                sess = term_mgr.get(body.get("id"))
                ok, msg = sess.send_input(str(body.get("text") or ""))
                self._json({"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/terminal/complete":
                sess = term_mgr.get(body.get("id"))
                self._json(sess.complete_path(str(body.get("line") or "")))
                return
            if path == "/api/terminal/stop":
                sess = term_mgr.get(body.get("id"))
                self._json({"ok": sess.stop()})
                return
            if path == "/api/terminal/clear":
                sess = term_mgr.get(body.get("id"))
                sess.clear()
                self._json({"ok": True})
                return
            if path == "/api/terminal/nl2cmd":
                if arbiter.owner == "media":
                    self._json({"error": "GPU su an Video/Gorsel uretiminde."}, status=409)
                    return
                if arbiter.owner != "coding":
                    ok, msg = arbiter.start_coding(wait_ready=True)
                    if not ok:
                        self._json({"error": msg}, status=503)
                        return
                sess = term_mgr.get(body.get("id"))
                query = str(body.get("query") or "").strip()
                payload = {
                    "model": arbiter.coding_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f"Convert the user's request into ONE safe Windows PowerShell command for cwd `{sess.cwd}`. "
                                'Return ONLY valid JSON: {"command": "...", "explanation": "brief Turkish 1-line explanation"}.'
                            ),
                        },
                        {"role": "user", "content": query},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 180,
                }
                req = urllib.request.Request(
                    f"http://{arbiter.llm_host}:{arbiter.llm_port}/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=90) as resp:
                        res = json.loads(resp.read().decode("utf-8", errors="replace"))
                    txt = (res["choices"][0]["message"].get("content") or "").strip()
                    import re as _re
                    txt_clean = _re.sub(r"^```(?:json|powershell|ps1)?\s*|\s*```$", "", txt, flags=_re.I).strip()
                    m = _re.search(r"\{[\s\S]*\}", txt_clean)
                    parsed: dict[str, Any] = {}
                    if m:
                        raw_j = m.group(0)
                        try:
                            parsed = json.loads(raw_j)
                        except json.JSONDecodeError:
                            # Handle unescaped Windows backslashes inside JSON strings
                            try:
                                parsed = json.loads(_re.sub(r'(?<!\\)\\(?![\\/"bfnrtu])', r'\\\\', raw_j))
                            except Exception:
                                parsed = {}
                    if not parsed.get("command"):
                        parsed = {"command": txt_clean.strip("` \n"), "explanation": ""}
                    self._json({"command": str(parsed.get("command") or "").strip(), "explanation": str(parsed.get("explanation") or "").strip()})
                except Exception as exc:
                    self._json({"error": str(exc)}, status=502)
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
                mode = str(body.get("mode") or "agent")
                auto_verify = bool(body.get("auto_verify", False))
                test_cmd = body.get("test_cmd")
                active_file = body.get("active_file")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for ev in run_agent_stream(
                        arbiter, ws, msgs, active_file=active_file, mode=mode,
                        auto_verify=auto_verify, test_cmd=test_cmd,
                    ):
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
    daemon_threads = True


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
    term_mgr = TerminalManager(ws.root)

    httpd = PicoStudioHTTPServer((h, p), make_handler(arbiter, ws, term_mgr))
    url = f"http://{h}:{p}/"
    print("============================================================")
    print(f"  PicoStudio Local IDE v0.4.0 -> {url}")
    print(f"  Aktif Proje                 -> {ws.root}")
    print(f"  Kodlama Motoru              -> {arbiter.picocode_dir}")
    print(f"  Video/Gorsel Motoru         -> {arbiter.picovid_dir}")
    print("  Kapatmak icin Ctrl+C")
    print("============================================================", flush=True)
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        term_mgr.stop_all()
        arbiter.stop_all()
        httpd.server_close()
    return 0
