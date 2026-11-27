/* PicoStudio v0.7.0 Security Shield: Auto-attach per-session CSRF token + JSON header on all /api/ POSTs */
const PS_CSRF_TOKEN = document.querySelector('meta[name="ps-csrf"]')?.getAttribute('content') || '';
const _origFetch = window.fetch.bind(window);
window.fetch = function(input, init){
  const url = typeof input === 'string' ? input : (input?.url || '');
  const opts = init ? {...init} : {};
  if((opts.method || 'GET').toUpperCase() === 'POST' && (url.startsWith('/api/') || url.includes('/api/'))){
    const hdrs = new Headers(opts.headers || {});
    if(PS_CSRF_TOKEN) hdrs.set('X-PicoStudio-Token', PS_CSRF_TOKEN);
    if(!hdrs.has('Content-Type')) hdrs.set('Content-Type', 'application/json');
    opts.headers = hdrs;
    if(opts.body === undefined) opts.body = '{}';
  }
  return _origFetch(input, opts);
};

const openTabs = {}; // path -> {content, saved}
let activeTab = null;
let chatHistory = [];
let chatImgData = null;
let lastStatus = null;
let codeBlockStore = {};
let agentAbortCtrl = null;
let activeAgentReqId = null;
let allWorkspaceFiles = [];
let hlTimer = null;
const collapsedDirs = new Set();

const editor = document.getElementById('codeEditor');
const gutter = document.getElementById('gutter');
const codeHL = document.getElementById('codeHighlight');
const codeStage = document.getElementById('codeStage');

function escHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function escJsArg(s){return escHtml(JSON.stringify(String(s??'')))}
function hasDirtyTabs(){return Object.values(openTabs).some(t=>t && t.content !== t.saved);}

window.addEventListener('beforeunload', e=>{
  if(hasDirtyTabs()){ e.preventDefault(); e.returnValue = ''; }
});

/* Native Ctrl+Z / Ctrl+Y preserving editor edit helper */
function replaceEditorRange(start, end, text, selStart=null, selEnd=null){
  editor.focus();
  editor.setSelectionRange(start, end);
  let usedExec = false;
  try{
    usedExec = document.execCommand('insertText', false, text);
  }catch(e){ usedExec = false; }
  if(!usedExec){
    editor.setRangeText(text, start, end, 'end');
    editor.dispatchEvent(new Event('input'));
  }
  const ns = (selStart !== null) ? selStart : (start + text.length);
  const ne = (selEnd !== null) ? selEnd : ns;
  editor.setSelectionRange(ns, ne);
}

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

function scheduleHighlight(){
  if((editor.value || '').length > 35000){
    clearTimeout(hlTimer);
    hlTimer = setTimeout(renderHighlight, 55);
  }else{
    renderHighlight();
  }
}

function updateGutter(){
  const n = Math.max(1, editor.value.split('\n').length);
  let s=''; for(let i=1;i<=n;i++) s += i+'\n';
  gutter.textContent = s;
  gutter.scrollTop = editor.scrollTop;
  scheduleHighlight();
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
    replaceEditorRange(lineStart, blkEnd, next, lineStart, lineStart + next.length);
    return;
  }
  if(e.key==='F12'){ e.preventDefault(); gotoDefinitionAtCursor(); return; }
  if(e.altKey && e.code==='Space'){ e.preventDefault(); triggerFimComplete(); return; }
  if(e.key==='Tab' && pendingFimText){ e.preventDefault(); acceptFim(); return; }
  if(e.key==='Tab'){
    e.preventDefault();
    if(e.shiftKey){
      const lineStart = val.lastIndexOf('\n', s - 1) + 1;
      const lineEnd = val.indexOf('\n', end);
      const blkEnd = lineEnd === -1 ? val.length : lineEnd;
      const next = val.slice(lineStart, blkEnd).split('\n').map(l => l.replace(/^ {1,4}|\t/, '')).join('\n');
      replaceEditorRange(lineStart, blkEnd, next, lineStart, lineStart + next.length);
    }else if(s !== end && val.slice(s, end).includes('\n')){
      const lineStart = val.lastIndexOf('\n', s - 1) + 1;
      const lineEnd = val.indexOf('\n', end);
      const blkEnd = lineEnd === -1 ? val.length : lineEnd;
      const next = val.slice(lineStart, blkEnd).split('\n').map(l => '    ' + l).join('\n');
      replaceEditorRange(lineStart, blkEnd, next, lineStart, lineStart + next.length);
    }else{
      replaceEditorRange(s, end, '    ', s + 4, s + 4);
    }
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
      replaceEditorRange(s, end, ins, s + 1 + indent.length + 4, s + 1 + indent.length + 4);
    }else{
      const ins = '\n' + indent + extra;
      replaceEditorRange(s, end, ins, s + ins.length, s + ins.length);
    }
    return;
  }
  if(e.key==='Backspace' && s===end && s>0 && PAIRS[val[s-1]]===val[s]){
    e.preventDefault();
    replaceEditorRange(s - 1, s + 1, '', s - 1, s - 1);
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
    replaceEditorRange(s, end, e.key + sel + closeCh, s + 1, end + 1);
  }
});

/* Global Shortcuts: Ctrl+P Quick Open, Ctrl+Shift+P Command Palette, Ctrl+Shift+O Symbols, Ctrl+K Inline Edit, Ctrl+B Sidebar */
window.addEventListener('keydown', e=>{
  if((e.ctrlKey||e.metaKey) && e.shiftKey && e.key.toLowerCase()==='p'){
    e.preventDefault(); openCmdPalette();
  }else if((e.ctrlKey||e.metaKey) && e.shiftKey && e.key.toLowerCase()==='o'){
    e.preventDefault(); openSymbolPalette(false);
  }else if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='p'){
    e.preventDefault(); openQuickOpen();
  }else if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'){
    e.preventDefault(); openInlineEditBar();
  }else if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='b'){
    e.preventDefault(); togglePane(e.shiftKey ? 'rightPane' : 'leftPane');
  }else if(e.key==='Escape'){
    if(document.getElementById('symBackdrop').style.display==='flex') closeSymbolPalette();
    else if(document.getElementById('cmdPaletteBackdrop').style.display==='flex') closeCmdPalette();
    else if(document.getElementById('quickOpenBackdrop').style.display==='flex') closeQuickOpen();
    else if(document.getElementById('fimBar').style.display==='flex') hideFim();
    else if(document.getElementById('inlineKBar').style.display==='flex') closeInlineEditBar();
    else if(document.getElementById('findBar').style.display==='flex') toggleFindBar(false);
  }
});

/* ========== V0.5.0 POWER FEATURES: THEMES, FONT, RESIZERS, CMD PALETTE, CTRL+K, DIAGNOSTICS, CHAT SESSIONS, @FILE ========== */
const THEMES = ['midnight', 'obsidian', 'light'];
let currentTheme = localStorage.getItem('ps_theme') || 'midnight';
let editorFontPx = parseInt(localStorage.getItem('ps_font_px') || '13', 10) || 13;
let currentChatId = null;
let inlineEditState = null;

function applyTheme(t){
  currentTheme = THEMES.includes(t) ? t : 'midnight';
  document.body.classList.remove('theme-obsidian', 'theme-light');
  if(currentTheme === 'obsidian') document.body.classList.add('theme-obsidian');
  if(currentTheme === 'light') document.body.classList.add('theme-light');
  localStorage.setItem('ps_theme', currentTheme);
}
function cycleTheme(){
  const idx = (THEMES.indexOf(currentTheme) + 1) % THEMES.length;
  applyTheme(THEMES[idx]);
}
function applyFontSize(px){
  editorFontPx = Math.max(11, Math.min(20, px));
  const sz = editorFontPx + 'px';
  editor.style.fontSize = sz; codeHL.style.fontSize = sz; gutter.style.fontSize = sz;
  localStorage.setItem('ps_font_px', String(editorFontPx));
}
function adjustFontSize(delta){ applyFontSize(editorFontPx + delta); }

function togglePane(id){
  const el = document.getElementById(id);
  if(el) el.classList.toggle('hidden-pane');
}

(function initHorizontalResizers(){
  function bind(resizerId, paneId, fromRight, storageKey){
    const bar = document.getElementById(resizerId);
    const pane = document.getElementById(paneId);
    const saved = parseInt(localStorage.getItem(storageKey) || '0', 10);
    if(saved >= 165 && saved <= 640) pane.style.width = saved + 'px';
    let drag = false, sx = 0, sw = 0;
    bar.addEventListener('mousedown', e=>{
      drag = true; sx = e.clientX; sw = pane.offsetWidth;
      bar.classList.add('drag'); document.body.style.userSelect = 'none';
    });
    window.addEventListener('mousemove', e=>{
      if(!drag) return;
      const dx = fromRight ? (sx - e.clientX) : (e.clientX - sx);
      const nw = Math.max(165, Math.min(640, sw + dx));
      pane.style.width = nw + 'px';
      localStorage.setItem(storageKey, String(nw));
    });
    window.addEventListener('mouseup', ()=>{
      if(!drag) return; drag = false; bar.classList.remove('drag'); document.body.style.userSelect = '';
    });
  }
  bind('leftResizer', 'leftPane', false, 'ps_left_w');
  bind('rightResizer', 'rightPane', true, 'ps_right_w');
})();

/* Command Palette (Ctrl+Shift+P) */
const IDE_COMMANDS = [
  {label:'Dosya: Hızlı Aç (Ctrl+P)', run:()=>openQuickOpen()},
  {label:'Gezinme: Dosya Sembolleri / Outline (Ctrl+Shift+O)', run:()=>openSymbolPalette(false)},
  {label:'Gezinme: Tüm Proje Sembollerinde Ara (#)', run:()=>openSymbolPalette(true)},
  {label:'Gezinme: İmleçteki Sembol Tanımına Git (F12)', run:()=>gotoDefinitionAtCursor()},
  {label:'Editör: AI Kod Tamamlama (Alt+Space)', run:()=>triggerFimComplete()},
  {label:'Editör: Satır İçi AI Düzenle (Ctrl+K)', run:()=>openInlineEditBar()},
  {label:'Editör: Dosya İçi Bul & Değiştir (Ctrl+F)', run:()=>toggleFindBar(true)},
  {label:'Editör: Aktif Dosyayı Kaydet (Ctrl+S)', run:()=>saveActiveFile()},
  {label:'Editör: Yazı Boyutunu Büyüt (A+)', run:()=>adjustFontSize(1)},
  {label:'Editör: Yazı Boyutunu Küçült (A-)', run:()=>adjustFontSize(-1)},
  {label:'Görünüm: Tema Değiştir (Midnight / Obsidian / Light)', run:()=>cycleTheme()},
  {label:'Görünüm: Sol Paneli Gizle/Göster (Ctrl+B)', run:()=>togglePane('leftPane')},
  {label:'Görünüm: Sağ AI Panelini Gizle/Göster (Ctrl+Shift+B)', run:()=>togglePane('rightPane')},
  {label:'Git: Git & Diff Paneline Geç', run:()=>switchLeftTab('git')},
  {label:'Git: Çok Dosyalı Değişiklik İnceleme Paneli (Side-by-Side)', run:()=>openMultiFileReview()},
  {label:'Git: Tüm Değişikliklerin Diff Önizlemesi', run:()=>openGitDiff('', false)},
  {label:'Terminal: Yeni Sekme Aç', run:()=>createTerminalTab()},
  {label:'Terminal: Proje Testlerini Çalıştır', run:()=>runTerm('py -m unittest discover -s tests -v')},
  {label:'Terminal: Son Hatayı AI Ajan v3 ile Düzelt', run:()=>autoFixTerminalError()},
  {label:'Terminal: Büyüt / Küçült', run:()=>toggleTermMax()},
  {label:'Ajan: Yeni Sohbet Başlat', run:()=>newChatSession()},
  {label:'Ajan: Planla + Onayla Moduna Geç', run:()=>{document.getElementById('agentMode').value='plan';}},
  {label:'GPU: Kodlama AI Başlat/Durdur', run:()=>toggleCodingEngine()},
  {label:'GPU: Tüm GPU Belleğini Boşalt', run:()=>stopAllGpu()},
];
let cmdFiltered = []; let cmdSel = 0;
function openCmdPalette(){
  document.getElementById('cmdPaletteBackdrop').style.display = 'flex';
  const inp = document.getElementById('cmdPaletteInp');
  inp.value = ''; inp.focus(); cmdSel = 0; renderCmdPalette();
}
function closeCmdPalette(){ document.getElementById('cmdPaletteBackdrop').style.display = 'none'; }
function renderCmdPalette(){
  const q = document.getElementById('cmdPaletteInp').value.trim();
  cmdFiltered = IDE_COMMANDS.map(c=>({cmd:c, s:fuzzyScore(c.label, q)})).filter(x=>x.s>=0).sort((a,b)=>b.s-a.s);
  if(cmdSel >= cmdFiltered.length) cmdSel = 0;
  document.getElementById('cmdPaletteList').innerHTML = cmdFiltered.map((x,i)=>
    `<div class="qo-item${i===cmdSel?' sel':''}" onclick="execCmdIdx(${i})"><span>${escHtml(x.cmd.label)}</span></div>`
  ).join('') || '<div style="padding:12px 14px;color:var(--mut);font-size:12px">Komut bulunamadı.</div>';
}
function execCmdIdx(i){
  const item = cmdFiltered[i]; closeCmdPalette();
  if(item) item.cmd.run();
}
function onCmdPaletteKey(ev){
  if(ev.key==='ArrowDown'){ ev.preventDefault(); cmdSel = Math.min(cmdFiltered.length-1, cmdSel+1); renderCmdPalette(); }
  else if(ev.key==='ArrowUp'){ ev.preventDefault(); cmdSel = Math.max(0, cmdSel-1); renderCmdPalette(); }
  else if(ev.key==='Enter' && cmdFiltered[cmdSel]){ ev.preventDefault(); execCmdIdx(cmdSel); }
  else if(ev.key==='Escape'){ closeCmdPalette(); }
}

/* Instant Syntax Diagnostics (Problems Bar) */
function renderDiagnostics(diags){
  const bar = document.getElementById('diagBar');
  if(!diags || !diags.length){ bar.style.display='none'; bar.innerHTML=''; return; }
  const d = diags[0];
  bar.style.display = 'flex';
  bar.innerHTML = `<b>⚠ Satır ${d.line}:${d.col}</b><span style="flex:1">${escHtml(d.message)}</span>`
    + `<button class="sm" onclick="gotoEditorLine(${d.line})">Satıra Git</button>`
    + `<button class="sm primary" onclick="askAiFixDiag(${d.line}, ${escJsArg(d.message)})">AI ile Düzelt</button>`;
}
async function checkActiveDiagnostics(){
  if(!activeTab) { renderDiagnostics([]); return; }
  try{
    const r = await fetch('/api/editor/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:activeTab, content:editor.value})}).then(x=>x.json());
    renderDiagnostics(r.diagnostics || []);
  }catch(e){}
}
function askAiFixDiag(line, msg){
  switchRightTab('code');
  document.getElementById('agentMode').value = 'agent';
  document.getElementById('chatInp').value = `@${activeTab} dosyasının ${line}. satırındaki şu sözdizimi hatasını düzelt: ${msg}`;
  sendAgent();
}

/* Cursor-Style Ctrl+K Inline Edit */
function openInlineEditBar(){
  if(!activeTab){ alert('Önce bir dosya açın.'); return; }
  const s = editor.selectionStart, end = editor.selectionEnd;
  inlineEditState = {
    start: s, end: end,
    selection: editor.value.slice(s, end),
    replacement: null,
  };
  const bar = document.getElementById('inlineKBar');
  bar.style.display = 'flex';
  document.getElementById('inlineKPreview').style.display = 'none';
  const inp = document.getElementById('inlineKInp');
  inp.value = '';
  inp.placeholder = inlineEditState.selection
    ? `Seçili ${inlineEditState.selection.split('\n').length} satıra ne yapılsın?...`
    : 'Aktif dosyaya ne yapılsın? (seçim yoksa tüm dosya düzenlenir)...';
  inp.focus();
}
function closeInlineEditBar(){
  document.getElementById('inlineKBar').style.display = 'none';
  inlineEditState = null; editor.focus();
}
async function runInlineEdit(){
  if(!inlineEditState || !activeTab) return;
  const instr = document.getElementById('inlineKInp').value.trim();
  if(!instr) return;
  const btn = document.getElementById('inlineKRunBtn');
  btn.disabled = true; btn.textContent = 'Üretiliyor...';
  try{
    const r = await fetch('/api/editor/inline-edit',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        path: activeTab, content: editor.value,
        selection: inlineEditState.selection, instruction: instr,
        start: inlineEditState.start, end: inlineEditState.end,
      })
    });
    const j = await r.json();
    if(!r.ok || j.replacement == null){ alert(j.error || 'Düzenleme üretilemedi.'); return; }
    inlineEditState.replacement = j.replacement;
    document.getElementById('inlineKDiff').textContent = j.diff || j.replacement;
    document.getElementById('inlineKStats').textContent = `+${j.added||0} / -${j.removed||0} satır`;
    document.getElementById('inlineKPreview').style.display = 'flex';
  }finally{
    btn.disabled = false; btn.textContent = 'Önizle';
  }
}
function applyInlineEdit(){
  if(!inlineEditState || inlineEditState.replacement == null) return;
  if(inlineEditState.selection){
    replaceEditorRange(inlineEditState.start, inlineEditState.end, inlineEditState.replacement, inlineEditState.start, inlineEditState.start + inlineEditState.replacement.length);
  }else{
    replaceEditorRange(0, editor.value.length, inlineEditState.replacement, 0, 0);
  }
  closeInlineEditBar();
  saveActiveFile();
}

/* Persistent Per-Project Chat Sessions + @file Autocomplete */
let atMatches = []; let atSel = 0; let atStartPos = -1;
function onChatInpChange(){
  const inp = document.getElementById('chatInp');
  const pos = inp.selectionStart || 0;
  const before = inp.value.slice(0, pos);
  const m = before.match(/(?:^|\s)@([A-Za-z0-9_.\-\/]*)$/);
  const menu = document.getElementById('atMenu');
  if(!m){ menu.style.display='none'; atStartPos=-1; return; }
  atStartPos = pos - m[1].length - 1;
  const q = m[1];
  atMatches = allWorkspaceFiles.map(p=>({p, s:fuzzyScore(p, q)})).filter(x=>x.s>=0).sort((a,b)=>b.s-a.s).slice(0,10);
  if(!atMatches.length){ menu.style.display='none'; return; }
  atSel = 0;
  menu.style.display = 'block';
  renderAtMenu();
}
function renderAtMenu(){
  const menu = document.getElementById('atMenu');
  menu.innerHTML = atMatches.map((x,i)=>`<div class="at-item${i===atSel?' sel':''}" onclick="pickAtFile(${escJsArg(x.p)})">@${escHtml(x.p)}</div>`).join('');
}
function pickAtFile(path){
  const inp = document.getElementById('chatInp');
  const pos = inp.selectionStart || inp.value.length;
  if(atStartPos >= 0){
    inp.value = inp.value.slice(0, atStartPos) + '@' + path + ' ' + inp.value.slice(pos);
    const np = atStartPos + path.length + 2;
    inp.selectionStart = inp.selectionEnd = np;
  }
  document.getElementById('atMenu').style.display = 'none';
  atStartPos = -1; inp.focus();
}
function onChatInpKey(ev){
  const menu = document.getElementById('atMenu');
  if(menu.style.display==='block' && atMatches.length){
    if(ev.key==='ArrowDown'){ ev.preventDefault(); atSel = (atSel+1)%atMatches.length; renderAtMenu(); return; }
    if(ev.key==='ArrowUp'){ ev.preventDefault(); atSel = (atSel-1+atMatches.length)%atMatches.length; renderAtMenu(); return; }
    if(ev.key==='Tab' || (ev.key==='Enter' && !ev.ctrlKey)){ ev.preventDefault(); pickAtFile(atMatches[atSel].p); return; }
    if(ev.key==='Escape'){ menu.style.display='none'; return; }
  }
  if(ev.ctrlKey && ev.key==='Enter'){ ev.preventDefault(); sendAgent(); }
}

async function loadChatSessions(){
  try{
    const r = await fetch('/api/chat/sessions').then(x=>x.json());
    const sel = document.getElementById('chatSessSel');
    const items = r.sessions || [];
    sel.innerHTML = `<option value="">— Mevcut Sohbet —</option>` + items.map(s=>
      `<option value="${escHtml(s.id)}"${s.id===currentChatId?' selected':''}>${escHtml(s.title)} (${s.count})</option>`
    ).join('');
  }catch(e){}
}
async function persistCurrentChat(){
  if(!chatHistory.length) return;
  try{
    const r = await fetch('/api/chat/sessions/save',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id: currentChatId, messages: chatHistory})
    }).then(x=>x.json());
    if(r && r.id){ currentChatId = r.id; loadChatSessions(); }
  }catch(e){}
}
async function selectChatSession(sid){
  abortAgent();
  if(!sid){ newChatSession(); return; }
  const r = await fetch('/api/chat/session?id='+encodeURIComponent(sid)).then(x=>x.json());
  if(!r || !r.messages) return;
  codeBlockStore = {};
  for(const k of Object.keys(turnCheckpointStore)) delete turnCheckpointStore[k];
  currentChatId = r.id;
  chatHistory = r.messages;
  const feed = document.getElementById('chatFeed');
  feed.innerHTML = '';
  let idx = 0;
  for(const m of chatHistory){
    idx++;
    const d = document.createElement('div');
    d.className = 'msg' + (m.role==='user' ? ' user' : '');
    const who = m.role==='user' ? 'Sen' : 'Ajan';
    d.innerHTML = `<div class="msg-hdr"><span>${who}</span><span>Kayıtlı</span></div><div>${m.role==='user'?escHtml(m.content):renderAgentMarkdown(m.content, 's'+idx)}</div>`;
    feed.appendChild(d);
  }
  feed.scrollTop = feed.scrollHeight;
}
function newChatSession(){
  abortAgent();
  currentChatId = null; chatHistory = []; codeBlockStore = {};
  for(const k of Object.keys(turnCheckpointStore)) delete turnCheckpointStore[k];
  const cp = document.getElementById('agentCtxPill');
  if(cp){ cp.textContent = 'ctx: 0%'; cp.className = 'pill'; }
  document.getElementById('chatFeed').innerHTML = '';
  loadChatSessions();
}
async function deleteCurrentChatSession(){
  const sid = document.getElementById('chatSessSel').value || currentChatId;
  if(!sid){ newChatSession(); return; }
  await fetch('/api/chat/sessions/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:sid})});
  newChatSession();
}

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
    return `<div class="qo-item${i===qoSel?' sel':''}" onclick="closeQuickOpen();openFile(${escJsArg(it.path)})"><span>${escHtml(name)}</span><span class="qo-dir">${escHtml(dir)}</span></div>`;
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
      html += st.staged.map(f=>`<div class="gfile" onclick="openGitDiff(${escJsArg(f.path)},true)"><span class="gcode A">${escHtml(f.code)}</span><span class="gp" title="${escHtml(f.path)}">${escHtml(f.path)}</span><button class="sm" title="Unstage" onclick="event.stopPropagation();gitUnstage(${escJsArg(f.path)})">-</button></div>`).join('');
    }
    const chg = [...st.unstaged, ...st.untracked];
    html += `<div class="git-sec"><span>Değişenler (${chg.length})</span></div>`;
    if(chg.length){
      html += chg.map(f=>{
        const cls = f.code==='??'?'U':(f.code==='D'?'D':'M');
        return `<div class="gfile" onclick="openGitDiff(${escJsArg(f.path)},false)"><span class="gcode ${cls}">${escHtml(f.code)}</span><span class="gp" title="${escHtml(f.path)}">${escHtml(f.path)}</span><button class="sm" title="Stage" onclick="event.stopPropagation();gitStage(${escJsArg(f.path)})">+</button><button class="sm danger" title="Geri Al (Revert)" onclick="event.stopPropagation();gitRevert(${escJsArg(f.path)})">↺</button></div>`;
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

let diffViewMode = localStorage.getItem('ps_diff_mode') || 'split';
let lastDiffArgs = null;
let reviewFiles = [];
let reviewIdx = 0;

function toggleDiffViewMode(){
  diffViewMode = (diffViewMode === 'split') ? 'unified' : 'split';
  localStorage.setItem('ps_diff_mode', diffViewMode);
  if(lastDiffArgs) openGitDiff(lastDiffArgs.path, lastDiffArgs.staged, lastDiffArgs.inReview);
}

function renderSplitDiff(rows){
  if(!rows || !rows.length) return '<div style="padding:16px;color:var(--mut)">Gösterilecek fark yok.</div>';
  const trs = rows.map(row=>{
    if(row.kind === 'hunk') return `<tr><td colspan="4" class="shunk">${escHtml(row.text)}</td></tr>`;
    if(row.kind === 'meta') return `<tr><td colspan="4" class="smeta">${escHtml(row.text)}</td></tr>`;
    const lLn = row.left_ln != null ? row.left_ln : '';
    const rLn = row.right_ln != null ? row.right_ln : '';
    return `<tr><td class="sln">${lLn}</td><td class="${row.left_type||'ctx'}">${escHtml(row.left_text)||' '}</td><td class="sln sdiv">${rLn}</td><td class="${row.right_type||'ctx'}">${escHtml(row.right_text)||' '}</td></tr>`;
  }).join('');
  return `<table class="split-tbl"><tbody>${trs}</tbody></table>`;
}

async function openMultiFileReview(startPath=''){
  const st = await fetch('/api/git/status').then(x=>x.json()).catch(()=>null);
  if(!st || !st.is_repo){ alert('Bu proje henüz bir Git reposu değil.'); return; }
  const seen = new Set();
  reviewFiles = [];
  for(const f of (st.staged||[])){
    const key = 'S:' + f.path;
    if(!seen.has(key)){ seen.add(key); reviewFiles.push({path:f.path, code:f.code, staged:true}); }
  }
  for(const f of [...(st.unstaged||[]), ...(st.untracked||[])]){
    const key = 'W:' + f.path;
    if(!seen.has(key)){ seen.add(key); reviewFiles.push({path:f.path, code:f.code, staged:false}); }
  }
  if(!reviewFiles.length){ alert('İncelenecek Git değişikliği bulunamadı (çalışma dizini temiz).'); return; }
  reviewIdx = startPath ? Math.max(0, reviewFiles.findIndex(x=>x.path===startPath)) : 0;
  const cur = reviewFiles[reviewIdx];
  openGitDiff(cur.path, cur.staged, true);
}

function reviewJump(idx){
  if(!reviewFiles.length) return;
  reviewIdx = (idx + reviewFiles.length) % reviewFiles.length;
  const cur = reviewFiles[reviewIdx];
  openGitDiff(cur.path, cur.staged, true);
}

function askAiReviewDiff(path, staged){
  switchRightTab('code');
  document.getElementById('agentMode').value = 'plan';
  const ref = path ? `@${path} dosyasındaki` : 'projedeki';
  document.getElementById('chatInp').value = `git_diff aracını kullanarak ${ref} ${staged?'staged ':''}değişiklikleri bug, güvenlik ve temiz kod açısından incele; en önemli bulguları listele.`;
  sendAgent();
}

async function openGitDiff(path, staged, inReview=false){
  lastDiffArgs = {path, staged, inReview};
  const r = await fetch(`/api/git/diff?path=${encodeURIComponent(path)}&staged=${staged?1:0}`).then(x=>x.json());
  const dv = document.getElementById('diffViewer');
  document.getElementById('mediaViewer').style.display = 'none';
  codeStage.style.display = 'none'; gutter.style.display = 'none';
  dv.style.display = 'flex';
  let reviewBarHtml = '';
  if(inReview && reviewFiles.length){
    const pills = reviewFiles.map((f, i)=>{
      const cls = f.code==='??'?'U':(f.code==='D'?'D':(f.staged?'A':'M'));
      const base = f.path.split('/').pop();
      return `<div class="rpill${i===reviewIdx?' active':''}" title="${escHtml(f.path)}" onclick="reviewJump(${i})"><span class="gcode ${cls}">${escHtml(f.code)}</span><span>${escHtml(base)}</span>${f.staged?'<span style="font-size:9.5px;color:var(--ok)">S</span>':''}</div>`;
    }).join('');
    reviewBarHtml = `<div class="review-strip"><span style="font-size:11px;color:var(--mut);font-weight:700;white-space:nowrap">📋 İnceleme (${reviewIdx+1}/${reviewFiles.length})</span><button class="sm" onclick="reviewJump(${reviewIdx-1})">◀</button><button class="sm" onclick="reviewJump(${reviewIdx+1})">▶</button>${pills}</div>`;
  }
  const modeLbl = diffViewMode === 'split' ? '☰ Tek Sütun' : '◫ Yan Yana';
  const actBtn = path
    ? (staged
      ? `<button class="sm" onclick="gitUnstage(${escJsArg(path)}).then(()=>${inReview?'openMultiFileReview('+escJsArg(path)+')':'openGitDiff('+escJsArg(path)+',false)'})">Unstage</button>`
      : `<button class="sm primary" onclick="gitStage(${escJsArg(path)}).then(()=>${inReview?'openMultiFileReview('+escJsArg(path)+')':'openGitDiff('+escJsArg(path)+',true)'})">Stage (+)</button><button class="sm danger" onclick="gitRevert(${escJsArg(path)}).then(()=>${inReview?'openMultiFileReview()':'closeCenterOverlays()'})">↺</button>`)
      + `<button class="sm" onclick="openFile(${escJsArg(path)})">Dosyayı Aç</button>`
    : '';
  const bodyHtml = (diffViewMode === 'split' && r.split_rows && r.split_rows.length)
    ? renderSplitDiff(r.split_rows)
    : ((r.lines && r.lines.length)
      ? r.lines.map(ln=>`<div class="dln ${ln.type}">${escHtml(ln.text)||' '}</div>`).join('')
      : '<div style="padding:16px;color:var(--mut)">Gösterilecek fark yok.</div>');
  dv.innerHTML = `${reviewBarHtml}<div class="diff-hdr"><b>${escHtml(r.path||path)}</b><span class="pill">${staged?'Staged':'Working Tree'}</span><span style="color:var(--ok);font-weight:700">+${r.added||0}</span><span style="color:var(--err);font-weight:700">-${r.removed||0}</span><div style="margin-left:auto;display:flex;gap:5px;flex-wrap:wrap"><button class="sm" onclick="toggleDiffViewMode()">${modeLbl}</button><button class="sm" onclick="askAiReviewDiff(${escJsArg(path)},${staged?1:0})">✨ AI İncele</button>${actBtn}<button class="sm" onclick="closeCenterOverlays()">Editöre Dön</button></div></div><div class="diff-body">${bodyHtml}</div>`;
}
async function gitStage(path){ await fetch('/api/git/stage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})}); await loadGitStatus(true); }
async function gitStageAll(){ await fetch('/api/git/stage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:''})}); await loadGitStatus(true); }
async function gitUnstage(path){ await fetch('/api/git/unstage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})}); await loadGitStatus(true); }
async function gitRevert(path){
  if(!confirm(path + ' dosyasındaki değişiklikleri geri almak istiyor musunuz?')) return false;
  const r = await fetch('/api/git/revert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  if(r.ok){
    if(openTabs[path]){ delete openTabs[path]; openFile(path); }
    loadTree(); loadGitStatus(true);
    return true;
  }
  return false;
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
  if(hasDirtyTabs() && !confirm('Kaydedilmemiş değişiklikler var. Yine de proje değiştirilsin mi?')){
    loadProjects(); return;
  }
  await fetch('/api/workspace/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  for(const k of Object.keys(openTabs)) delete openTabs[k];
  activeTab = null; editor.value = ''; updateGutter(); renderTabs();
  document.getElementById('activeFileLbl').textContent = 'Dosya seçilmedi';
  closeCenterOverlays(); renderDiagnostics([]); newChatSession(); loadTree(); pollTerminal(); loadGitStatus(true);
}

async function loadCodingModels(){
  const inv = await fetch('/api/inventory').then(x=>x.json());
  const sel = document.getElementById('modelSel');
  sel.innerHTML = '';
  for(const m of (inv.coding_models||[])){
    const o = document.createElement('option');
    o.value = m.id;
    const tag = m.id==='qwen3-coder-30b' ? '🚀 30B/3B MoE · Kod' : (m.id==='inkling2-mini' ? '🧠 Derin+Vision' : '⚡ 7B GPU');
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
      div.innerHTML = `<span style="flex:1;overflow:hidden;text-overflow:ellipsis">${escHtml(it.name)}</span><span class="x" title="Sil" style="opacity:.45;font-size:11px;padding:0 4px" onclick="event.stopPropagation();deleteWorkspaceFile(${escJsArg(it.path)})">×</span>`;
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
  updateGutter(); renderTabs(); loadTree(); checkActiveDiagnostics();
}

function renderTabs(){
  const bar = document.getElementById('tabBar');
  bar.innerHTML = '';
  for(const [p, st] of Object.entries(openTabs)){
    const dirty = st.content !== st.saved ? ' ●' : '';
    const t = document.createElement('div');
    t.className = 'etab' + (p===activeTab?' active':'');
    t.innerHTML = `<span>${escHtml(p.split('/').pop())}${dirty}</span><span class="x" onclick="event.stopPropagation();closeTab(${escJsArg(p)})">×</span>`;
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
  if(r.ok){
    const j = await r.json().catch(()=>({}));
    openTabs[activeTab].saved = openTabs[activeTab].content;
    renderTabs(); loadGitStatus(false);
    renderDiagnostics(j.diagnostics || []);
  }
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
  box.innerHTML = r.hits.length ? r.hits.map(h=>`<div class="hit" onclick="openFileAtLine(${escJsArg(h.path)},${h.line})"><b>${escHtml(h.path)}:${h.line}</b><div style="color:var(--mut)">${escHtml(h.text)}</div></div>`).join('') : '<div class="hit">Sonuç bulunamadı</div>';
}

async function openFileAtLine(path, line){
  await openFile(path);
  gotoEditorLine(line);
}

function toggleProjReplace(){
  const row = document.getElementById('projReplaceRow');
  row.style.display = (row.style.display === 'flex') ? 'none' : 'flex';
  if(row.style.display === 'flex') document.getElementById('projReplaceInp').focus();
}

async function replaceInProject(){
  const q = document.getElementById('searchInp').value;
  const rep = document.getElementById('projReplaceInp').value;
  if(!q){ alert('Önce aranacak metni yazın.'); return; }
  const prev = await fetch('/api/workspace/replace',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query:q, replacement:rep, dry_run:true})
  }).then(x=>x.json());
  if(!prev.ok || !prev.total_replacements){ alert('Eşleşme bulunamadı.'); return; }
  const summary = prev.files.slice(0,8).map(f=>`${f.path} (${f.count})`).join('\n');
  if(!confirm(`${prev.files.length} dosyada toplam ${prev.total_replacements} eşleşme değiştirilecek:\n\n${summary}\n\nDevam edilsin mi?`)) return;
  const res = await fetch('/api/workspace/replace',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query:q, replacement:rep, dry_run:false})
  }).then(x=>x.json());
  if(res.ok){
    for(const f of (res.files||[])){
      if(openTabs[f.path]){ delete openTabs[f.path]; if(activeTab===f.path) openFile(f.path); }
    }
    searchProject(); loadGitStatus(false);
    alert(`✓ ${res.files.length} dosyada ${res.total_replacements} değişiklik uygulandı.`);
  }
}

/* ========== V0.6.0: SYMBOLS OUTLINE (Ctrl+Shift+O), F12 GO-TO-DEF, ALT+SPACE FIM & QUICK CHIPS ========== */
let symItems = []; let symSel = 0; let symFileCache = [];
async function openSymbolPalette(workspaceWide=false){
  document.getElementById('symBackdrop').style.display = 'flex';
  const inp = document.getElementById('symInp');
  inp.value = workspaceWide ? '#' : '';
  inp.focus(); symSel = 0;
  symFileCache = [];
  if(activeTab){
    const r = await fetch('/api/editor/symbols',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:activeTab, content:editor.value})
    }).then(x=>x.json()).catch(()=>({symbols:[]}));
    symFileCache = (r.symbols||[]).map(s=>({...s, path:activeTab}));
  }
  renderSymbolPalette();
}
function closeSymbolPalette(){ document.getElementById('symBackdrop').style.display = 'none'; }
async function renderSymbolPalette(){
  const raw = document.getElementById('symInp').value.trim();
  if(raw.startsWith('#')){
    const q = raw.slice(1).trim();
    const r = await fetch('/api/workspace/symbols?q='+encodeURIComponent(q)).then(x=>x.json()).catch(()=>({symbols:[]}));
    symItems = r.symbols || [];
  }else{
    symItems = symFileCache
      .map(s=>({s, sc:fuzzyScore(s.name + ' ' + (s.detail||''), raw)}))
      .filter(x=>x.sc>=0).sort((a,b)=>b.sc-a.sc).map(x=>x.s);
  }
  if(symSel >= symItems.length) symSel = 0;
  document.getElementById('symList').innerHTML = symItems.length ? symItems.slice(0,30).map((s,i)=>
    `<div class="qo-item${i===symSel?' sel':''}" onclick="jumpSymbolIdx(${i})"><span><span class="sym-kind">${escHtml(s.kind)}</span>${escHtml(s.name)}</span><span class="qo-dir">${escHtml(s.path||'')}:${s.line}</span></div>`
  ).join('') : '<div style="padding:12px 14px;color:var(--mut);font-size:12px">Sembol bulunamadı (tüm proje için # ile arayın).</div>';
}
async function jumpSymbolIdx(i){
  const s = symItems[i]; closeSymbolPalette();
  if(!s) return;
  if(s.path && s.path !== activeTab) await openFile(s.path);
  gotoEditorLine(s.line);
}
function onSymbolKey(ev){
  if(ev.key==='ArrowDown'){ ev.preventDefault(); symSel = Math.min(symItems.length-1, symSel+1); renderSymbolPalette(); }
  else if(ev.key==='ArrowUp'){ ev.preventDefault(); symSel = Math.max(0, symSel-1); renderSymbolPalette(); }
  else if(ev.key==='Enter' && symItems[symSel]){ ev.preventDefault(); jumpSymbolIdx(symSel); }
  else if(ev.key==='Escape'){ closeSymbolPalette(); }
}

function getWordAtCursor(){
  const val = editor.value, pos = editor.selectionStart || 0;
  let a = pos, b = pos;
  while(a > 0 && /[A-Za-z0-9_$]/.test(val[a-1])) a--;
  while(b < val.length && /[A-Za-z0-9_$]/.test(val[b])) b++;
  return val.slice(a, b);
}
async function gotoDefinitionAtCursor(){
  const word = getWordAtCursor();
  if(!word) return;
  // 1) Check current file first
  if(activeTab){
    const r = await fetch('/api/editor/symbols',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:activeTab, content:editor.value})
    }).then(x=>x.json()).catch(()=>({symbols:[]}));
    const localHit = (r.symbols||[]).find(s=>s.name===word || s.short===word);
    if(localHit){ gotoEditorLine(localHit.line); return; }
  }
  // 2) Search across whole workspace
  const wr = await fetch('/api/workspace/symbols?exact=1&q='+encodeURIComponent(word)).then(x=>x.json()).catch(()=>({symbols:[]}));
  const hit = (wr.symbols||[])[0];
  if(hit){ await openFileAtLine(hit.path, hit.line); }
}

/* On-Demand Alt+Space AI Code Completion (FIM) */
let pendingFimText = '';
let pendingFimPos = 0;
async function triggerFimComplete(){
  if(!activeTab){ alert('Önce bir dosya açın.'); return; }
  const pos = editor.selectionStart || 0;
  pendingFimPos = pos; pendingFimText = '';
  const bar = document.getElementById('fimBar');
  bar.style.display = 'flex';
  document.getElementById('fimStatus').textContent = 'Yerel AI imleç için tamamlama üretiyor...';
  document.getElementById('fimCode').textContent = '...';
  try{
    const r = await fetch('/api/editor/complete',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        path: activeTab,
        prefix: editor.value.slice(Math.max(0, pos - 1800), pos),
        suffix: editor.value.slice(pos, pos + 600),
      })
    });
    const j = await r.json();
    if(!r.ok || !j.completion){
      document.getElementById('fimStatus').textContent = j.error || 'Tamamlama üretilemedi.';
      document.getElementById('fimCode').textContent = '';
      return;
    }
    pendingFimText = j.completion;
    document.getElementById('fimStatus').textContent = 'Hazır — Tab veya ✓ Kabul ile ekleyin';
    document.getElementById('fimCode').textContent = pendingFimText;
  }catch(e){
    document.getElementById('fimStatus').textContent = 'Hata: ' + e;
  }
}
function acceptFim(){
  if(!pendingFimText) return;
  replaceEditorRange(pendingFimPos, pendingFimPos, pendingFimText);
  hideFim();
}
function hideFim(){
  pendingFimText = '';
  document.getElementById('fimBar').style.display = 'none';
  editor.focus();
}

const QUICK_CHIP_PROMPTS = {
  '/review': 'Aktif dosyayı güvenlik, performans ve okunabilirlik açısından incele, en önemli 3 iyileştirmeyi listele.',
  '/bug': 'Aktif dosyadaki olası bug ve kenar durum hatalarını tespit edip düzelt.',
  '/test': 'Aktif dosya için kapsamlı unittest birim testleri yaz ve çalıştır.',
  '/refactor': 'Aktif dosyayı daha temiz, modüler ve okunabilir olacak şekilde refactor et.',
  '/doc': 'Aktif dosyadaki fonksiyon ve sınıflara kısa, net docstring ve tip anotasyonları ekle.',
  '/plan': 'Bu değişiklik için önce çok dosyalı bir uygulama planı hazırla: ',
};
function useQuickChip(cmd){
  const inp = document.getElementById('chatInp');
  if(cmd === '/plan'){
    document.getElementById('agentMode').value = 'plan';
    inp.value = QUICK_CHIP_PROMPTS[cmd];
    inp.focus();
    return;
  }
  const ref = activeTab ? `@${activeTab} ` : '';
  inp.value = ref + (QUICK_CHIP_PROMPTS[cmd] || cmd);
  inp.focus();
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
let lastTermCommand = '';
let termRecentLines = [];
let detectedTermErr = null;

const ANSI_COLORS = {
  30:'#475569',31:'#f87171',32:'#4ade80',33:'#fbbf24',34:'#60a5fa',35:'#c084fc',36:'#38bdf8',37:'#e2e8f0',
  90:'#64748b',91:'#fca5a5',92:'#86efac',93:'#fde047',94:'#93c5fd',95:'#d8b4fe',96:'#67e8f9',97:'#ffffff'
};

function linkifyPaths(safeHtml){
  // 1) Python traceback: File "C:\...\foo.py", line 42
  safeHtml = safeHtml.replace(/File &quot;([^&]+?)&quot;, line (\d+)/g, (m, p, ln)=>{
    const clean = p.replace(/\\/g, '/');
    return `File "<span class="tlink" onclick="jumpFromTerm(${escJsArg(clean)},${ln})">${p}</span>", line ${ln}`;
  });
  // 2) Generic path:line (e.g. pulsemonitor/server.py:62 or apps/client/src/Drive.tsx:128)
  safeHtml = safeHtml.replace(/(^|[\s(])([A-Za-z0-9_.\-/\\]+\.(?:py|ts|tsx|js|jsx|html|css|json|md)):(\d+)/g, (m, pre, p, ln)=>{
    const clean = p.replace(/\\/g, '/');
    return `${pre}<span class="tlink" onclick="jumpFromTerm(${escJsArg(clean)},${ln})">${p}:${ln}</span>`;
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

function stripAnsi(s){ return String(s||'').replace(/\x1b\[[0-9;]*m/g, ''); }

function detectTerminalError(recent){
  const clean = recent.map(stripAnsi);
  // If the latest command finished cleanly with exit code 0, suppress stale error banners
  for(let i = clean.length - 1; i >= Math.max(0, clean.length - 4); i--){
    if(/\[çıkış kodu:\s*0\]/i.test(clean[i])) return null;
  }
  const errRe = /(Traceback \(most recent call last\):|\b(?:SyntaxError|NameError|TypeError|ValueError|AttributeError|ImportError|ModuleNotFoundError|AssertionError|KeyError|IndexError|ZeroDivisionError|RuntimeError|ReferenceError|RangeError):[^\n]*|^FAIL:\s+\S+|^ERROR:\s+\S+|FAILED \(|exit_code=[1-9]\d*|\[exit [1-9]\d*\]|\[çıkış kodu:\s*[1-9]\d*\])/i;
  let lastHitIdx = -1;
  let headline = '';
  for(let i = clean.length - 1; i >= 0; i--){
    const m = clean[i].match(errRe);
    if(m){
      lastHitIdx = i;
      headline = clean[i].trim().slice(0, 120);
      break;
    }
  }
  if(lastHitIdx === -1) return null;
  // Find nearest file:line reference inside the last ~35 lines around the error
  let errFile = ''; let errLine = 0;
  const winStart = Math.max(0, lastHitIdx - 25);
  const win = clean.slice(winStart);
  for(let i = win.length - 1; i >= 0; i--){
    const mPy = win[i].match(/File "([^"]+)", line (\d+)/);
    if(mPy){ errFile = mPy[1].replace(/\\/g, '/'); errLine = parseInt(mPy[2], 10); break; }
    const mGen = win[i].match(/([A-Za-z0-9_.\-/\\]+\.(?:py|js|ts|tsx|jsx)):(\d+)/);
    if(mGen){ errFile = mGen[1].replace(/\\/g, '/'); errLine = parseInt(mGen[2], 10); break; }
  }
  const snippet = win.slice(-28).join('\n').slice(-1800);
  return {headline, file: errFile, line: errLine, snippet};
}

function renderTermErrBanner(){
  const bar = document.getElementById('termErrBar');
  if(!bar) return;
  if(!detectedTermErr){ bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = 'flex';
  const locBtn = (detectedTermErr.file && detectedTermErr.line)
    ? `<button class="sm" onclick="jumpFromTerm(${escJsArg(detectedTermErr.file)},${detectedTermErr.line})">📄 ${escHtml(detectedTermErr.file.split('/').pop())}:${detectedTermErr.line}</button>`
    : '';
  const rerunBtn = lastTermCommand
    ? `<button class="sm" onclick="runTerm(${escJsArg(lastTermCommand)})">↻ Tekrar Koş</button>`
    : '';
  bar.innerHTML = `<span style="font-weight:700">⚠ Hata Yakalandı</span><span class="err-msg" title="${escHtml(detectedTermErr.headline)}">${escHtml(detectedTermErr.headline)}</span>${locBtn}<button class="sm primary" onclick="autoFixTerminalError()">🔧 Ajan v3 ile Düzelt</button>${rerunBtn}<button class="sm" onclick="dismissTermErr()">×</button>`;
}

function dismissTermErr(){
  detectedTermErr = null;
  renderTermErrBanner();
}

function autoFixTerminalError(){
  const err = detectedTermErr;
  const txt = err ? err.snippet : document.getElementById('termOut').innerText.slice(-1800);
  if(!txt.trim()){ alert('Terminalde analiz edilecek çıktı bulunamadı.'); return; }
  let atRef = '';
  if(err && err.file){
    let rel = err.file;
    const projRoot = (document.getElementById('projSel')?.value || '').replace(/\\/g, '/').replace(/\/$/, '');
    if(projRoot && rel.toLowerCase().startsWith(projRoot.toLowerCase() + '/')) rel = rel.slice(projRoot.length + 1);
    if(!/^[A-Za-z]:\//.test(rel)) atRef = `@${rel} `;
  }
  switchRightTab('code');
  document.getElementById('agentMode').value = 'agent';
  const chk = document.getElementById('chkAutoVerify');
  if(chk) chk.checked = true;
  document.getElementById('chatInp').value = `${atRef}Terminaldeki şu hatayı tespit edip doğrudan düzelt ve testle doğrula:\n\n\`\`\`\n${txt}\n\`\`\``;
  sendAgent();
}

function appendTermLines(lines, reset=false){
  const el = document.getElementById('termOut');
  const atBottom = reset || (el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  if(reset){ el.innerHTML = ''; termRecentLines = []; dismissTermErr(); }
  const frag = document.createDocumentFragment();
  for(const ln of (lines||[])){
    termRecentLines.push(ln);
    const div = document.createElement('div');
    div.innerHTML = renderAnsiLine(ln) || '&nbsp;';
    frag.appendChild(div);
  }
  if(termRecentLines.length > 80) termRecentLines = termRecentLines.slice(-80);
  el.appendChild(frag);
  while(el.childNodes.length > 450) el.removeChild(el.firstChild);
  if(atBottom) el.scrollTop = el.scrollHeight;
  if(!reset && lines && lines.length){
    const found = detectTerminalError(termRecentLines);
    if(found){ detectedTermErr = found; renderTermErrBanner(); }
    else if(lines.some(l=>/\[çıkış kodu:\s*0\]/i.test(stripAnsi(l)))){ dismissTermErr(); }
  }
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
    t.innerHTML = `${s.running?'<span class="dot"></span>':''}<span>${escHtml(s.name)}</span><span style="opacity:.55;padding-left:3px" onclick="event.stopPropagation();closeTerminalTab(${escJsArg(s.id)})">×</span>`;
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
  lastTermCommand = clean;
  termRecentLines = [];
  dismissTermErr();
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
      cb.innerHTML = r.matches.slice(0,12).map(m=>`<span style="cursor:pointer;padding:1px 5px;background:#162238;border-radius:4px" onclick="applyCompletion(${escJsArg(m)})">${escHtml(m)}</span>`).join('');
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
  termRecentLines = []; dismissTermErr();
}
function sendTermErrorToAi(){
  if(detectedTermErr){ autoFixTerminalError(); return; }
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
      updateMediaProgress(st);
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

let msgSeqCounter = 0;

function renderAgentMarkdown(txt, msgKey='m0'){
  const parts = txt.split(/```(\w*)\n([\s\S]*?)```/g);
  let html = '';
  let blkIdx = 0;
  for(let i=0;i<parts.length;i+=3){
    html += escHtml(parts[i]||'').replace(/`([^`]+)`/g,'<code style="background:#0f172a;padding:1px 4px;border-radius:3px">$1</code>').replace(/\n/g,'<br>');
    if(i+2 < parts.length){
      const lang = parts[i+1] || 'code';
      const code = (parts[i+2] || '').trimEnd();
      if(!code.trim()) continue;
      const id = `cb_${msgKey}_${blkIdx++}`;
      codeBlockStore[id] = code;
      const isShell = /^(sh|bash|powershell|ps1|cmd)$/i.test(lang);
      const actBtn = isShell
        ? `<button class="sm primary" onclick="if(confirm('Bu kabuk komutunu terminalde calistirmak istiyor musunuz?\\n\\n'+codeBlockStore['${id}']))runTerm(codeBlockStore['${id}'])">Terminalde Çalıştır</button>`
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
  if(activeAgentReqId){
    fetch('/api/agent/abort',{method:'POST',body:JSON.stringify({req_id: activeAgentReqId})}).catch(()=>{});
  }
  if(agentAbortCtrl){ agentAbortCtrl.abort(); agentAbortCtrl = null; }
}

const turnCheckpointStore = {};

async function undoAgentEdit(undoId, btnEl){
  const r = await fetch('/api/workspace/undo',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({undo_id: undoId})
  });
  const j = await r.json();
  if(r.ok){
    btnEl.textContent = 'Geri Alındı'; btnEl.disabled = true;
    loadTree(); loadGitStatus(false);
    if(j.deleted){ closeTab(j.path); }
    else if(openTabs[j.path]){ delete openTabs[j.path]; openFile(j.path); }
  }else{
    alert(j.error||'Geri alinamadi');
  }
}

async function undoTurnCheckpoint(cpId, btnEl){
  const ids = turnCheckpointStore[cpId];
  if(!ids || !ids.length) return;
  if(!confirm(`Bu turdaki ${ids.length} dosya değişikliğini topluca geri almak istiyor musunuz?`)) return;
  btnEl.disabled = true;
  try{
    const r = await fetch('/api/workspace/undo-batch',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({undo_ids: ids})
    });
    const j = await r.json();
    if(r.ok && j.ok){
      btnEl.textContent = `✓ Tur Geri Alındı (${j.count})`;
      delete turnCheckpointStore[cpId];
      loadTree(); loadGitStatus(false);
      for(const dp of (j.deleted_paths||[])){ closeTab(dp); }
      for(const rp of (j.restored_paths||[])){
        if(openTabs[rp]){ delete openTabs[rp]; openFile(rp); }
      }
    }else{
      btnEl.disabled = false;
      alert(j.error||'Tur geri alinamadi');
    }
  }catch(e){
    btnEl.disabled = false;
    alert('Hata: ' + e);
  }
}

function updateAgentCtxPill(ev){
  const el = document.getElementById('agentCtxPill');
  if(!el || !ev) return;
  const toks = ev.est_ctx_tokens || 0;
  const lim = ev.ctx_limit || 32768;
  const pct = Math.min(100, Math.round((toks / lim) * 100));
  const kStr = toks >= 1000 ? (toks / 1000).toFixed(1) + 'k' : String(toks);
  el.textContent = `ctx: ${kStr} (${pct}%)${ev.compacted ? ' ⚡' : ''}`;
  el.className = 'pill' + (pct >= 85 ? ' err' : (pct >= 65 ? ' warn' : ''));
  el.title = `Adım ${ev.step||1}/${ev.max_steps||16} · ~${toks} / ${lim} tok${ev.compacted ? ' (eski araç çıktıları sıkıştırıldı)' : ''}`;
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
  activeAgentReqId = 'req_' + Math.random().toString(36).slice(2, 10);
  const mode = document.getElementById('agentMode').value;
  const autoVerify = !!document.getElementById('chkAutoVerify')?.checked;
  const activePayload = (document.getElementById('chkIncludeFile').checked && activeTab && openTabs[activeTab])
    ? (mode === 'fast' ? {path: activeTab, content: openTabs[activeTab].content} : {path: activeTab})
    : null;
  const msgKey = 'm' + (++msgSeqCounter);
  let full = ''; let toks = 0; const t0 = performance.now();
  let rafPending = false;
  const flushMd = ()=>{
    rafPending = false;
    aDiv.querySelector('.bd').innerHTML = renderAgentMarkdown(full, msgKey);
    feed.scrollTop = feed.scrollHeight;
  };
  let completedOk = false;
  try{
    const resp = await fetch('/api/agent/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},
      signal: agentAbortCtrl.signal,
      body:JSON.stringify({req_id: activeAgentReqId, messages: chatHistory, mode, auto_verify: autoVerify, active_file: activePayload})
    });
    if(!resp.ok){
      const err = await resp.json().catch(()=>({error:resp.statusText}));
      aDiv.querySelector('.bd').textContent = 'Hata: ' + (err.error||resp.status);
      chatHistory.pop();
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
          }else if(ev.type==='metrics'){
            updateAgentCtxPill(ev);
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
            if(ev.deleted){
              closeTab(ev.path);
            }else if(openTabs[ev.path]){
              delete openTabs[ev.path]; openFile(ev.path);
            }
            const dc = document.createElement('div');
            dc.className = 'code-blk';
            const ico = ev.deleted ? '🗑' : '✏';
            const openBtn = ev.deleted ? '' : `<button class="sm" onclick="openFile(${escJsArg(ev.path)})">Aç</button>`;
            dc.innerHTML = `<div class="code-blk-h"><span>${ico} ${escHtml(ev.path)} <b style="color:var(--ok)">+${ev.added||0}</b> <b style="color:var(--err)">-${ev.removed||0}</b></span><div class="row" style="gap:4px">${openBtn}${ev.undo_id?`<button class="sm danger" onclick="undoAgentEdit(${escJsArg(ev.undo_id)},this)">Geri Al</button>`:''}</div></div>${ev.diff?`<pre style="max-height:110px;font-size:10.8px">${escHtml(ev.diff)}</pre>`:''}`;
            toolsEl.appendChild(dc);
          }else if(ev.type==='turn_checkpoint'){
            const cpId = 'cp_' + Math.random().toString(36).slice(2, 9);
            turnCheckpointStore[cpId] = ev.undo_ids || [];
            const nFiles = (ev.files || []).length;
            const nEdits = ev.count || turnCheckpointStore[cpId].length;
            const cpc = document.createElement('div');
            cpc.className = 'row';
            cpc.style.cssText = 'margin-top:8px;padding-top:6px;border-top:1px solid var(--b);justify-content:space-between;font-size:11.5px;color:var(--mut)';
            cpc.innerHTML = `<span>📌 Tur Kayıt Noktası: ${nFiles} dosya · ${nEdits} değişiklik</span><button class="sm danger" onclick="undoTurnCheckpoint(${escJsArg(cpId)},this)">↺ Tüm Turu Geri Al</button>`;
            aDiv.appendChild(cpc);
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
            if(!rafPending){ rafPending = true; requestAnimationFrame(flushMd); }
          }else if(ev.type==='error'){
            aDiv.querySelector('.bd').textContent = 'Hata: ' + ev.error;
          }
          feed.scrollTop = feed.scrollHeight;
        }catch(e){}
      }
    }
    if(full) flushMd();
    completedOk = true;
    chatHistory.push({role:'assistant', content:full});
    persistCurrentChat();
  }catch(e){
    if(!completedOk) chatHistory.pop();
    aDiv.querySelector('.bd').textContent = (e.name==='AbortError') ? 'Durduruldu.' : ('Bağlantı hatası: ' + e);
  }finally{
    btn.disabled = false; abtn.style.display='none'; agentAbortCtrl = null; activeAgentReqId = null;
  }
}

/* Video & Image Studio */
let mediaInitImgPath = null;

async function uploadMediaInitImg(ev){
  const f = ev.target.files && ev.target.files[0]; if(!f) return;
  const rd = new FileReader();
  rd.onload = async ()=>{
    const r = await fetch('/api/media/upload-init',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:f.name, data_url:rd.result})
    });
    const j = await r.json();
    if(r.ok && j.ok){
      mediaInitImgPath = j.path;
      document.getElementById('vidInitTag').textContent = '✓ ' + f.name;
      document.getElementById('vidInitClear').style.display = 'inline-block';
      const sel = document.getElementById('vidPreset');
      if(sel && !sel.value.includes('|i2v|')) sel.value = 'ltx23|i2v|640|384|81';
    } else alert(j.error||'Gorsel yuklenemedi');
  };
  rd.readAsDataURL(f);
}

function clearMediaInitImg(){
  mediaInitImgPath = null;
  document.getElementById('vidInitFile').value = '';
  document.getElementById('vidInitTag').textContent = 'Seçili değil (T2V)';
  document.getElementById('vidInitClear').style.display = 'none';
}

function updateMediaProgress(st){
  const fill = document.getElementById('mediaProgFill');
  const lbl = document.getElementById('mediaProgLbl');
  if(!fill || !lbl) return;
  const job = st.media_job;
  if(!job){ fill.style.width='0%'; lbl.textContent='Hazır'; return; }
  if(job.status==='done'){ fill.style.width='100%'; lbl.textContent='✓ Tamamlandı'; return; }
  if(job.status==='error'){ lbl.textContent='✗ Hata'; return; }
  if(job.status==='stopped'){ lbl.textContent='Durduruldu'; return; }
  const txt = (st.media_logs||[]).join('\n');
  let pct = 8, stage = 'Model / Gemma-3 yükleniyor...';
  const stepMatches = [...txt.matchAll(/\|\s*(\d+)\/(\d+)\s*-\s*([\d.]+s\/it|[\d.]+it\/s)/g)];
  if(txt.includes('Sinema HD') || txt.includes('AI Upscale')){ pct = 92; stage = 'Sinema HD (1280×768 · 32fps · Ses)...'; }
  else if(txt.includes('audio vae decode completed')){ pct = 88; stage = 'Ses + H.264 MP4 paketleniyor...'; }
  else if(txt.includes('sampling completed')){ pct = 72; stage = 'Video & Ses VAE Decode...'; }
  else if(stepMatches.length){
    const last = stepMatches[stepMatches.length-1];
    const cur = +last[1], tot = Math.max(1, +last[2]);
    pct = Math.round(12 + (cur/tot)*58);
    stage = `LTX-2.3 Adım ${cur}/${tot} (${last[3]})`;
  }
  fill.style.width = pct + '%';
  lbl.textContent = `${stage} · ${pct}%`;
}

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
  let [engine, mode, w, h, f] = document.getElementById('vidPreset').value.split('|');
  if(mode==='i2v' && !mediaInitImgPath){ alert('I2V modu icin once bir gorsel secin.'); return; }
  if(mode==='t2v' && mediaInitImgPath) mode = 'i2v';
  const r = await fetch('/api/media/start',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      prompt, engine, mode, width:+w, height:+h, frames:+f,
      init_img: mode==='i2v' ? mediaInitImgPath : null,
      cinema_hd: document.getElementById('chkCinemaHd').checked,
      fast_preview: document.getElementById('chkFastPrev').checked,
    })
  });
  const j = await r.json();
  if(!r.ok) alert(j.error||'Baslatilamadi');
  pollStatus();
}
async function stopMedia(){ await fetch('/api/media/stop',{method:'POST'}); pollStatus(); }

let ideTimeline = [];
function addToIdeTimeline(name, label, ev){
  if(ev) ev.stopPropagation();
  ideTimeline.push({name, label: label || name});
  renderIdeTimelineList();
}
function moveIdeTimeline(i, d){
  const j = i + d;
  if(j < 0 || j >= ideTimeline.length) return;
  const t = ideTimeline[i]; ideTimeline[i] = ideTimeline[j]; ideTimeline[j] = t;
  renderIdeTimelineList();
}
function removeIdeTimeline(i){ ideTimeline.splice(i, 1); renderIdeTimelineList(); }
function clearIdeTimeline(){ ideTimeline = []; renderIdeTimelineList(); const st=document.getElementById('ideTlStatus'); if(st) st.textContent=''; }
function renderIdeTimelineList(){
  const el = document.getElementById('ideTlList'); if(!el) return;
  if(!ideTimeline.length){ el.innerHTML='Aşağıdaki galeriden <b>+</b> ile klipleri sıraya ekleyin.'; return; }
  el.innerHTML = ideTimeline.map((c,i)=>`
    <div class="row" style="gap:4px;background:var(--bg);border:1px solid var(--b);border-radius:6px;padding:3px 6px">
      <span style="color:#c084fc;font-weight:700">#${i+1}</span>
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--tx)" title="${escHtml(c.name)}">${escHtml(c.label)}</span>
      <button class="sm" onclick="moveIdeTimeline(${i},-1)">▲</button>
      <button class="sm" onclick="moveIdeTimeline(${i},1)">▼</button>
      <button class="sm danger" onclick="removeIdeTimeline(${i})">×</button>
    </div>`).join('');
}
async function renderIdeTimeline(){
  if(!ideTimeline.length){ alert('Once zaman cizelgesine klip ekleyin.'); return; }
  const btn = document.getElementById('ideTlBtn');
  const st = document.getElementById('ideTlStatus');
  btn.disabled = true; st.textContent = 'Kurgu birlestiriliyor (xfade + stereo ses)...';
  try{
    const r = await fetch('/api/media/timeline',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        clips: ideTimeline.map(c=>({name:c.name})),
        transition: document.getElementById('ideTlTrans').value,
        transition_sec: parseFloat(document.getElementById('ideTlDur').value),
      })
    });
    const j = await r.json();
    if(r.ok && j.ok){
      st.textContent = `✓ Hazır: ${j.name} (${j.duration_sec}s · ${j.size_mb} MB)`;
      loadMediaGallery();
      previewMedia(j.name, 'video');
    } else st.textContent = 'Hata: ' + (j.error||'Kurgu basarisiz');
  }finally{ btn.disabled = false; }
}

async function loadMediaGallery(){
  const items = await fetch('/api/media/outputs').then(x=>x.json());
  const g = document.getElementById('mediaGallery');
  g.innerHTML = items.length ? items.map(it=>`
    <div class="gitem" onclick="previewMedia(${escJsArg(it.name)},${escJsArg(it.kind)})">
      <div class="row" style="justify-content:space-between;gap:4px">
        <span style="color:${it.kind==='video'?'#c084fc':'var(--acc)'};font-weight:700">${it.kind==='video'?'▶ MP4':'🖼 PNG'} · ${it.size_mb} MB</span>
        ${it.kind==='video'?`<button class="sm" title="Zaman çizelgesine ekle" onclick="addToIdeTimeline(${escJsArg(it.name)},${escJsArg(it.label||it.name)},event)">+</button>`:''}
      </div>
      <div class="gname" title="${escHtml(it.name)}">${escHtml(it.label||it.name)}</div>
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

applyTheme(currentTheme); applyFontSize(editorFontPx);
loadProjects(); loadCodingModels(); loadTree(); loadGitStatus(false); loadChatSessions(); pollStatus(); pollTerminal();
setInterval(()=>{ if(!document.hidden) pollStatus(); }, 2500);
setInterval(()=>{ if(!document.hidden) loadTermSessions(); }, 3500);
setInterval(()=>{ if(!document.hidden) loadGitStatus(false); }, 6000);
document.addEventListener('visibilitychange', ()=>{ if(!document.hidden){ pollStatus(); loadGitStatus(false); } });
