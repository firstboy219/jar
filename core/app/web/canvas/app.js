// JARVIS — the board (Blueprint v4 Fase 4 → 11, ADR-049/055): the owner's workspace as a 2D infinite paper like Miro / Figma.
// Boards: Utama, each project, each company. Cards are references to real things (tasks, documents, what JARVIS showed, memories, company
// data) plus the owner's own notes, text, shapes and frames; this page lays them out. It can select, place, move, resize, link and take
// cards off the board — it never approves, deletes data, sends or pays.
import { createTakeover } from './takeover.js';
import { PANELS, FEATURE_CARDS, ago, parseFrameHeader, contextLabel, frameNeedsFetch, shouldFollow, takeAppParams } from './lib.js';
import { createBoard } from './board.js';
import { createChrome } from './chrome.js';
import { initDock } from './dock.js';
import { createMeetingCard, createPlayerCard } from './deskcards.js';
import { SHOW_CARDS, createShowCard } from './showcards.js';
import { createGoogleCard } from './googlecard.js';
import { createWorkersCard } from './workerscard.js';
import { createDevTeamCard } from './devteamcard.js';
import { createProjectsCard } from './projectscard.js';
import { openChoice } from './choicepopup.js';

const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { /* private mode */ } return null; };

// Opened by the Android app as "#t=<device token>&app=1": take the token out of the address at once (never sent to a server).
const fromApp = takeAppParams(location.hash);
if (fromApp.embedded || fromApp.token) history.replaceState(null, '', location.pathname + location.search + fromApp.rest);
if (fromApp.embedded) document.documentElement.classList.add('in-app');

const api = {
  get token() { try { return localStorage.getItem('jarvis_canvas_token') || ''; } catch { return ''; } },
  set token(v) { try { v ? localStorage.setItem('jarvis_canvas_token', v) : localStorage.removeItem('jarvis_canvas_token'); } catch { /* private mode */ } },
  async req(method, path, body) {
    const r = await fetch(path, { method, headers: { Authorization: `Bearer ${this.token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined });
    if (r.status === 401) { showLogin(); throw new Error('perlu masuk'); }
    const data = r.headers.get('content-type')?.includes('json') ? await r.json() : null;
    if (!r.ok) throw new Error((data && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))) || `HTTP ${r.status}`);
    return data;
  },
};

function toast(text, bad = false) {
  const t = el('div', `toast${bad ? ' bad' : ''}`, text);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), 4200);
}

function showLogin() { $('#login').hidden = false; $('#password').focus(); }

$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('#login-error').textContent = '';
  try {
    const r = await fetch('/api/v1/devices/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: $('#password').value, device_name: 'Papan (web)' }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'gagal');
    api.token = d.token;
    $('#password').value = '';
    $('#login').hidden = true;
    await loadContexts();
    loadAreas();
  } catch (err) { $('#login-error').textContent = err.message; }
});

$('#admin').href = location.origin.replace('//vis1.', '//jar1.');   // the admin page stays the control point; the board links to it

// ---------- the board ----------
let contexts = [], current = null, lastFocus = null, follow = LS('jarvis_canvas_follow') !== 'off', lastTouch = performance.now();
for (const t of ['pointerdown', 'wheel', 'keydown']) addEventListener(t, () => { lastTouch = performance.now(); }, true);
const liveByRef = new Map();      // ref → {st, shownSeq, fetching}
const seenStations = new Set();
const STATUS_TEXT = { queued: 'menunggu giliran', running: 'bekerja', completed: 'selesai', failed: 'gagal', cancelled: 'dibatalkan', stopped: 'dihentikan' };

// One refresh at a time: the poll and the board's own edits must not overlap and fight over the same card.
let chain = Promise.resolve();
const refresh = (force = false) => { chain = chain.then(() => doRefresh(force)).catch(() => {}); return chain; };

const board = createBoard({
  stage: $('#stage'), api, toast, canvasId: () => current?.id, refresh, embedded: !!fromApp.embedded,
  openUrl,
  contextMenu: (m) => chrome.contextMenu(m),
  decorate: (c) => { const l = liveByRef.get(c.data.ref); if (l) { c.live = l; renderLive(c, l); } },
});
window.__board = board;   // for the owner's own console and the UI tests
const kindsFor = () => {
  const count = {};
  for (const c of board.cards.values()) count[c.data.kind] = (count[c.data.kind] || 0) + 1;
  const known = board.zones.map((z) => ({ kind: z.kind, title: z.title, color: z.color, count: count[z.kind] || 0 }));
  if (count.papan) known.push({ kind: 'papan', title: 'Catatan & bentuk', color: '#94a3b8', count: count.papan });
  return known.filter((k) => k.count);
};
const chrome = createChrome({ board, api, toast, canvasId: () => current?.id, refresh, kindsFor,
  fillFromLibrary: async () => { try { const r = await api.req('POST', `/api/v1/canvases/${current.id}/fill`); toast(r.added ? `${r.added} kartu dari Simpanan ditaruh.` : 'Semua isi Simpanan sudah ada di papan.'); await refresh(true); } catch (err) { toast(err.message, true); } },
  openHistory: () => toggleHistory() });
$('#tb-right').prepend(chrome.inspToggle);
board.insets.top = 64; board.insets.left = matchMedia('(max-width: 700px)').matches ? 52 : 72;

async function openUrl(url) {
  if (!url) return;
  if (url.startsWith('https://')) return void window.open(url, '_blank', 'noopener');
  const r = await fetch(url, { headers: { Authorization: `Bearer ${api.token}` } });
  if (!r.ok) throw new Error(`tidak bisa membuka (${r.status})`);
  window.open(URL.createObjectURL(await r.blob()), '_blank', 'noopener');
}
addEventListener('board:open', (e) => openUrl(e.detail).catch((err) => toast(err.message, true)));

// ---------- data ----------
async function loadContexts() {
  contexts = await api.req('GET', '/api/v1/canvases');
  const pick = $('#galaxy');
  pick.replaceChildren(...contexts.map((c) => { const o = el('option', null, `${contextLabel(c)} (${c.cards})`); o.value = c.context; return o; }), Object.assign(el('option', null, '＋ Papan baru…'), { value: '__new' }));
  const want = LS('jarvis_canvas_context');
  pick.value = contexts.some((c) => c.context === want) ? want : 'utama';
  await openContext(pick.value);
}

async function openContext(context) {
  const c = await api.req('POST', '/api/v1/canvases', { context });
  LS('jarvis_canvas_context', context);
  current = { id: c.id, version: -1, context };
  liveVideo.watch(context);
  board.setContent({ cards: [], edges: [], constellations: [] });
  board.select([]);
  await refresh(true);
}

async function doRefresh(force) {
  if (!current) return;
  const d = await api.req('GET', `/api/v1/canvases/${current.id}${force ? '' : `?since=${current.version}`}`);
  if (d.unchanged) return;
  const first = current.version < 0, before = board.cards.size;
  const diff = board.setContent(d);
  current.version = d.version;
  $('#title').textContent = d.title;
  $('#count').textContent = `${d.cards.length} objek`;
  if (first) {
    const link = /#kartu=(\d+)/.exec(location.hash);   // a link straight to one card (from JARVIS or the app)
    const saved = (() => { try { return JSON.parse(LS(`jarvis_board_view_${current.context}`) || 'null'); } catch { return null; } })();
    if (link && board.cards.get(Number(link[1]))) { board.flyToCard(Number(link[1]), 1, 0); board.select([Number(link[1])]); }
    else if (saved && Number.isFinite(saved.k)) board.setView(saved);
    else board.fitInitial();
  }
  if (d.focus && d.focus !== lastFocus && board.cards.get(d.focus)) { board.flyToCard(d.focus, 1, 800); board.select([d.focus]); }
  lastFocus = d.focus;
  const fresh = diff.added.filter((c) => !c.ref.startsWith('obj:'));
  if (fresh.length && before) toast(`${fresh.length} kartu baru dari JARVIS.`);
}
setInterval(() => { if (!document.hidden && api.token) refresh().catch(() => {}); }, 3000);

let saveTimer = null;
board.on('view', (v) => { clearTimeout(saveTimer); saveTimer = setTimeout(() => { if (current && current.version >= 0) LS(`jarvis_board_view_${current.context}`, JSON.stringify({ cx: Math.round(v.cx), cy: Math.round(v.cy), k: +v.k.toFixed(3) })); }, 600); });

// ---------- top bar ----------
$('#galaxy').addEventListener('change', async (e) => {
  if (e.target.value !== '__new') return openContext(e.target.value).catch((err) => toast(err.message, true));
  const name = prompt('Nama papan baru (proyek):');
  e.target.value = current?.context || 'utama';
  if (!name) return;
  try { const c = await api.req('POST', '/api/v1/canvases', { context: `project:${name}`, title: name }); await loadContexts(); $('#galaxy').value = c.context; await openContext(c.context); }
  catch (err) { toast(err.message, true); }
});
$('#search').addEventListener('click', () => chrome.openPalette('find'));
$('#logout').addEventListener('click', () => { api.token = ''; location.reload(); });
function setFollow(on) {
  follow = on; LS('jarvis_canvas_follow', on ? 'on' : 'off');
  $('#follow').classList.toggle('on', on); $('#follow').title = on ? 'Kamera ikut ke tugas baru yang kamu minta (nyala)' : 'Kamera tidak ikut (mati)';
}
$('#follow').addEventListener('click', () => setFollow(!follow));
setFollow(follow);

function toggleHistory() {
  const panel = $('#history-panel');
  panel.hidden = !panel.hidden;
  if (panel.hidden) return;
  api.req('GET', `/api/v1/canvases/${current.id}/versions`).then((versions) => {
    const close = el('button', 'x', '×'); close.addEventListener('click', () => { panel.hidden = true; });
    panel.replaceChildren(el('h3', null, 'Riwayat tata letak'), close, ...versions.map((v) => {
      const row = el('div', 'version');
      row.append(el('span', null, `v${v.version} · ${new Date(v.at).toLocaleString('id-ID')} · ${v.change} · ${v.cards} kartu`));
      const b = el('button', null, 'Pulihkan');
      b.addEventListener('click', async () => {
        if (!confirm(`Pulihkan tata letak versi ${v.version}?`)) return;
        try { const r = await api.req('POST', `/api/v1/canvases/${current.id}/restore`, { version: v.version }); toast(`Dipulihkan: ${r.cards} kartu${r.dropped ? `, ${r.dropped} sudah tidak ada` : ''}.`); await refresh(true); }
        catch (err) { toast(err.message, true); }
      });
      row.append(b);
      return row;
    }));
  }).catch((err) => toast(err.message, true));
}
$('#history').addEventListener('click', toggleHistory);

// ---------- the desk: what JARVIS is doing, live (ADR-051) ----------
// Every worker task is a station on its card: what it is doing step by step and, when it browses, the page as it is right now.
// n8n, the owner's latest requests, the storage, the player and the meeting recorder are fixed panels around the middle of the board.
const deskPanels = {};

function cardOfRef(ref) { for (const c of board.cards.values()) if (c.data.ref === ref) return c; return null; }

function renderLive(card, l) {
  const st = l.st;
  card.el.classList.add('live');
  let box = card.el.querySelector(':scope > .livebox');
  if (!box) {
    box = el('div', 'livebox nodrag');
    const help = el('div', 'helpline'); help.hidden = true;
    const grab = el('button', 'takebtn', '✋ Intervensi');
    grab.title = 'Kendalikan browser pekerja ini sendiri kapan saja — Jarvis diminta diam sampai Anda selesai';
    grab.addEventListener('click', (ev) => { ev.stopPropagation(); if (l.st) takeover.open(l.st); });
    box.append(el('div', 'livehead'), el('div', 'pageline'), help, el('canvas', 'frame'), grab, el('ul', 'steps'), el('div', 'thought'));
    box.querySelector('canvas').hidden = true;
    if (l.last) drawBitmap(box.querySelector('canvas'), l.last);   // the newest frame we already have
    card.el.insertBefore(box, card.el.querySelector('.actions'));
  }
  const head = box.querySelector('.livehead');
  head.replaceChildren(el('span', `dot ${st.status}`), el('span', null, `${STATUS_TEXT[st.status] || st.status} · ${ago(st.seconds)}${st.browsing ? ' · di browser' : ''}`),
    ...(performance.now() - (l.liveAt || -1e9) < 3000 ? [el('span', 'livebadge', '● LANGSUNG')] : []));
  const help = box.querySelector('.helpline'), grab = box.querySelector('.takebtn');
  help.hidden = !(st.asking || st.controlled);
  help.textContent = st.controlled ? `✋ ${st.control_by || 'Seseorang'} sedang mengendalikan browser ini${st.paused ? ' · Jarvis menunggu' : ''}` : (st.asking ? `❓ Jarvis butuh bantuanmu: ${st.asking}` : '');
  help.classList.toggle('ask', !!st.asking && !st.controlled);
  grab.hidden = !((st.has_frame || st.browsing) && !['completed', 'failed', 'cancelled', 'stopped'].includes(st.status));
  grab.classList.toggle('urgent', !!st.asking && !st.controlled);
  if (st.asking && !l.askToasted && !st.controlled) { l.askToasted = st.asking; toast(`Jarvis butuh bantuanmu di "${st.title}" — klik Intervensi di kartunya.`); }
  if (!st.asking) l.askToasted = '';
  box.querySelector('.pageline').textContent = st.page_title || st.url || '';
  box.querySelector('.pageline').hidden = !(st.page_title || st.url);
  const ul = box.querySelector('.steps');
  ul.replaceChildren(...st.steps.slice(-8).map((s) => el('li', s.status === 'running' ? 'now' : '', `${s.icon} ${s.text}${s.n > 1 ? ` ×${s.n}` : ''}`)));
  box.querySelector('.thought').textContent = st.thought ? `💭 ${st.thought}` : '';
  if (!liveVideo.open() && frameNeedsFetch(l.shownSeq, st.frame_seq, st.has_frame)) fetchFrame(card, l);   // snapshots only while the live video is down
}

async function drawBitmap(cv, blobOrBuf) {
  const bmp = await createImageBitmap(blobOrBuf instanceof Blob ? blobOrBuf : new Blob([blobOrBuf], { type: 'image/jpeg' }));
  if (cv.width !== bmp.width || cv.height !== bmp.height) { cv.width = bmp.width; cv.height = bmp.height; }
  cv.getContext('2d').drawImage(bmp, 0, 0);
  bmp.close();
  cv.hidden = false;
}

/** The fallback while the live video is down: one picture per poll. */
async function fetchFrame(card, l) {
  if (l.fetching) return;
  l.fetching = true;
  try {
    const r = await fetch(`/api/v1/canvas/live/${l.st.task_id}/frame?context=${encodeURIComponent(current.context)}`, { headers: { Authorization: `Bearer ${api.token}` } });
    if (r.ok) {
      const blob = await r.blob(), cv = card.el.querySelector('.livebox canvas');
      l.last = blob;
      if (cv) await drawBitmap(cv, blob);
      l.shownSeq = Number(r.headers.get('X-Frame-Seq')) || l.st.frame_seq;
    }
  } catch { /* the next poll tries again */ } finally { l.fetching = false; }
}

/** Live video of the stations: the server pushes every frame its browser makes (about 10–30 a second while something moves). */
const liveVideo = (() => {
  let ws = null, retry = 0, want = '';
  const open = () => ws?.readyState === 1 && ws.ready;
  function watch(context) {
    want = context;
    if (ws?.readyState === 1 && ws.ready) ws.send(JSON.stringify({ type: 'watch', context }));
  }
  function connect() {
    if (!api.token || (ws && ws.readyState <= 1)) return;
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/canvas/live/ws`);
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: api.token }));
    ws.onmessage = (m) => {
      if (typeof m.data === 'string') {
        const msg = JSON.parse(m.data);
        if (msg.type === 'auth_ok') { ws.ready = true; retry = 0; if (want) watch(want); }
        else if (msg.type === 'control') takeover.reply(msg);
        return;
      }
      const h = parseFrameHeader(m.data);
      const l = [...liveByRef.values()].find((x) => x.st.task_id === h.task);
      if (!l) return;
      const frame = new Blob([m.data.slice(h.offset)], { type: 'image/jpeg' });
      if (takeover.task() === h.task) takeover.frame(h.task, frame);
      l.last = frame; l.shownSeq = h.seq; l.liveAt = performance.now();
      const card = cardOfRef(l.st.ref), cv = card?.el.querySelector('.livebox canvas');
      if (cv && !l.drawing && !card.el.classList.contains('off')) { l.drawing = true; drawBitmap(cv, frame).catch(() => {}).finally(() => { l.drawing = false; }); }
    };
    ws.onclose = () => { if (ws) ws.ready = false; setTimeout(connect, Math.min(1000 * 2 ** retry++, 15000)); };
    ws.onerror = () => ws.close();
  }
  /** Tell the server something (taking the wheel, an input); false when the video link is down. */
  const sendJson = (obj) => { if (!open()) return false; ws.send(JSON.stringify(obj)); return true; };
  return { open, watch, connect, send: sendJson };
})();
const takeover = createTakeover({
  send: (obj) => { if (!liveVideo.send(obj) && obj.type !== 'input') toast('Siaran langsung belum tersambung — coba lagi sebentar.', true); },
  toast,
});
setInterval(() => liveVideo.connect(), 2000);

function clearLive(ref) {
  const card = cardOfRef(ref);
  if (card) {
    card.live = null;
    card.el.classList.remove('live');
    card.el.querySelector(':scope > .livebox')?.remove();
    card.autoH = null;
  }
  liveByRef.delete(ref);
}

function panelFor(name) {
  if (deskPanels[name]) return deskPanels[name];
  const e = el('div', 'card panel');
  e.style.setProperty('--c', '#67e8f9');
  board.setWidget(name, e, PANELS[name]);
  if (areaLayout[name]) board.setArea(name, areaLayout[name]);
  return (deskPanels[name] = { el: e, ...PANELS[name] });
}

// The areas' sizes and locks (ADR-062) are the owner's, kept on the server so the phone and the browser show the same desk.
let areaLayout = {};
async function loadAreas() {
  try { areaLayout = (await api.req('GET', '/api/v1/canvas/areas')).areas || {}; } catch { return; }
  for (const [name, layout] of Object.entries(areaLayout)) if (deskPanels[name]) board.setArea(name, layout);
}
const areaSaves = {};
board.on('widget', (a) => {
  areaLayout[a.name] = { w: a.w, h: a.h, locked: a.locked };
  clearTimeout(areaSaves[a.name]);
  areaSaves[a.name] = setTimeout(() => api.req('PUT', `/api/v1/canvas/areas/${a.name}`, areaLayout[a.name]).catch((err) => toast(err.message, true)), 400);
  if (a.reason === 'lock') toast(a.locked ? 'Area dikunci — ukurannya tidak bisa diubah.' : 'Kunci dibuka — geser tepi area untuk mengubah ukurannya.');
});
// full screen: in the phone app the app hides its own bars and buttons too, so the area really fills the screen
board.on('fullscreen', (name) => {
  try { window.JarvisHost?.fullscreen?.(!!name); } catch { /* an older app */ }
  if (!window.JarvisHost?.fullscreen) {
    try { if (name && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {}); else if (!name && document.fullscreenElement) document.exitFullscreen?.(); } catch { /* not allowed here */ }
  }
});
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && board.fullArea) board.closeFull(); });
window.__jarvisAreaExit = () => { if (board.fullArea) board.closeFull(); };   // the phone's Back button

// The player and the meeting recorder (ADR-054): feature cards at fixed places; the camera flies to one when it shows up.
let dockApi = null, playerCard = null, meetingCard = null, videoCard = null, googleCard = null, workersCard = null, devteamCard = null, projectsCard = null;
const showCards = {};
const arrived = {};   // card → the key of what it last showed (undefined until the first poll after loading)

function renderFeatureCards(d) {
  if (!('player' in d) || current.context !== 'utama') return;   // only the main board is the desk; a company board has neither
  const pp = panelFor('player'), mp = panelFor('meeting');
  const send = (o) => dockApi?.raw(o);
  playerCard ||= createPlayerCard({ box: pp.el, api, send, toast, label: 'musik', hint: 'Bilang: "putar lagu …" — lagunya diputar di sini.' });
  meetingCard ||= createMeetingCard({ box: mp.el, api, toast, embedded: !!fromApp.embedded });
  pp.el.hidden = !playerCard.update(d.player);
  const m = meetingCard.update(d.meeting, d.now);
  mp.el.hidden = !m.show;
  const arrive = (name, key, pn) => {
    const first = arrived[name] === undefined, fresh = key != null && arrived[name] !== key;
    arrived[name] = key;
    if (fresh && !first && follow && performance.now() - lastTouch > 2500) board.focusRect({ x: pn.x, y: pn.y, w: pn.w, h: 320 }, 1, 900);
  };
  arrive('player', d.player?.id ?? null, pp);
  arrive('meeting', m.show && ['waiting', 'recording'].includes(d.meeting?.state) ? m.key : null, mp);
  const cards = d.cards || {}, vp = panelFor('video');
  videoCard ||= createPlayerCard({ box: vp.el, api, send, toast, label: 'video', hint: 'Bilang: "putar video …" atau "putar YouTube …" — videonya diputar di sini.' });
  vp.el.hidden = !videoCard.update(cards.video);
  arrive('video', cards.video?.id ?? null, vp);
  for (const slot of Object.keys(SHOW_CARDS)) {
    const pn = panelFor(slot);
    showCards[slot] ||= createShowCard({ box: pn.el, api, slot, send, toast, embedded: !!fromApp.embedded });
    pn.el.hidden = false;
    arrive(slot, showCards[slot].update(cards[slot]), pn);
  }
  googleCard ||= createGoogleCard({ box: panelFor('google').el, api, toast, embedded: !!fromApp.embedded });
  panelFor('google').el.hidden = !googleCard.allowed;
  workersCard ||= createWorkersCard({ box: panelFor('workers').el, api, toast });
  workersCard.update(d.workers);
  // ADR-079: a project asks the owner to pick — the popup (in the phone app its native dialog does this instead)
  if (!fromApp.embedded) for (const c of d.choices || []) if (!seenChoices.has(c.id)) { seenChoices.add(c.id); openChoice({ api, toast }, c, () => projectsCard?.reload()); }
  panelFor('workers').el.hidden = false;
  projectsCard ||= createProjectsCard({ box: panelFor('projects').el, api, toast, onShowTask: (id) => {
    const c = cardOfRef(`task:${id}`);
    if (c) { board.flyToCard(c.data.id, 0.9, 900); board.select([c.data.id]); } else toast('Kartunya belum ada di papan — sebentar lagi muncul.');
  } });
  panelFor('projects').el.hidden = false;
  devteamCard ||= createDevTeamCard({ box: panelFor('devteam').el, api, toast });
  devteamCard.update(d.devteam, d.stations);
  panelFor('devteam').el.hidden = !d.devteam;   // only the owner's own device sees it
}

// "🕘 Terakhir" (ADR-072): the camera goes where the owner's latest request left its mark, and that card glows for a moment
const seenChoices = new Set();
let lastActivity = null;
function flash(node) { if (!node) return; node.classList.remove('flash'); void node.offsetWidth; node.classList.add('flash'); setTimeout(() => node.classList.remove('flash'), 2600); }
$('#projectsbtn').addEventListener('click', () => {   // "Proyek": straight to the projects area, full screen
  if (current?.context !== 'utama') { toast('Proyek ada di papan utama — pilih "Utama" dulu.'); return; }
  if (deskPanels.projects) board.openFull('projects');
});
$('#lastact').addEventListener('click', async () => {
  if (current?.context !== 'utama') { toast('Aktivitas terakhir ada di papan utama — pilih "Utama" dulu.'); return; }
  const a = lastActivity;
  const said = a?.asked ? `Permintaan terakhir: "${a.asked}"` : '';
  if (!a || a.where === 'none') { toast(said ? `${said} — jawabannya ada di chat.` : 'Belum ada aktivitas.'); return; }
  if (a.where === 'card' && board.cards.get(a.node)) {
    board.flyToCard(a.node, 1, 900); board.select([a.node]); flash(board.cards.get(a.node).el);
  } else if (a.where === 'panel' && PANELS[a.panel]) {
    const p = PANELS[a.panel], w = board.widgets.get(a.panel);
    board.focusRect(w ? board.widgetRect(w) : { x: p.x, y: p.y, w: p.w, h: 360 }, 1, 900); flash(deskPanels[a.panel]?.el);
  } else { toast(said ? `${said} — jawabannya ada di chat.` : 'Kartunya sudah tidak ada di papan.'); return; }
  toast([said, `→ ${a.what}: ${a.title}`].filter(Boolean).join(' '));
});

function renderPanels(d) {
  if ('last_activity' in d) lastActivity = d.last_activity;
  const desk = current.context === 'utama';   // the panels around the middle belong to the main board only
  renderFeatureCards(d);
  const show = (name, on) => { if (on && desk) panelFor(name).el.hidden = false; else if (deskPanels[name]) deskPanels[name].el.hidden = true; };
  show('n8n', !!d.n8n); show('storage', !!d.storage);
  if (!desk) { for (const n of FEATURE_CARDS) if (deskPanels[n]) deskPanels[n].el.hidden = true; return; }
  if (d.n8n) {
    const e = panelFor('n8n').el;
    e.replaceChildren(el('div', 'kind', 'meja · otomasi'), el('div', 'title', 'Yang dijalankan n8n'));
    if (!d.n8n.length) e.append(el('div', 'snippet', 'Belum ada eksekusi (atau n8n belum terhubung).'));
    for (const x of d.n8n.slice(0, 8)) { const row = el('div', 'deskrow'); row.append(el('span', `dot ${x.status === 'success' ? 'completed' : x.status === 'error' ? 'failed' : 'running'}`), el('b', null, ` ${x.workflow}`), el('span', null, ` · ${x.status}`)); e.append(row); }
  }
  if (d.storage) {
    const e = panelFor('storage').el;
    e.replaceChildren(el('div', 'kind', 'meja · simpanan'), el('div', 'title', `Simpanan — ${d.storage.total} item`));
    const chips = el('div', 'chips');
    for (const [k, n] of Object.entries(d.storage.counts)) chips.append(el('span', 'chip', `${k} ${n}`));
    e.append(chips);
    for (const i of d.storage.latest) e.append(el('div', 'deskrow', `${i.kept ? '⭐ ' : ''}${i.title} · ${i.kind}`));
    const b = el('button', null, 'Taruh semua di papan ini'); b.dataset.gesture = 'ok';
    b.addEventListener('click', async (ev) => { ev.stopPropagation(); try { const r = await api.req('POST', `/api/v1/canvases/${current.id}/fill`); toast(`${r.added} kartu dari Simpanan ditaruh.`); await refresh(true); } catch (err) { toast(err.message, true); } });
    e.append(b);
  }
}

let pollingLive = false;
async function pollLive() {
  if (!current || document.hidden || !api.token || pollingLive) return;
  pollingLive = true;
  try {
    const d = await api.req('GET', `/api/v1/canvas/live?context=${encodeURIComponent(current.context)}`);
    const now = new Set(d.stations.map((s) => s.ref));
    for (const ref of [...liveByRef.keys()]) if (!now.has(ref)) clearLive(ref);
    for (const st of d.stations) {
      const l = liveByRef.get(st.ref) || { shownSeq: 0 };
      l.st = st; liveByRef.set(st.ref, l);
      const card = cardOfRef(st.ref);
      if (!card) { if (!l.asked) { l.asked = true; refresh(true).catch(() => {}); } continue; }   // its card is on the way
      card.live = l;
      renderLive(card, l);
      takeover.update(st);
      const first = !seenStations.has(st.task_id);
      seenStations.add(st.task_id);
      if (first && shouldFollow({ follow, idleMs: performance.now() - lastTouch, kind: st.kind, status: st.status, seen: false })) {
        board.flyToCard(card.data.id, 0.9, 1000);
        toast(`Jarvis mengerjakan: ${st.title}`);
      }
    }
    renderPanels(d);
  } catch { /* offline: the next poll tries again */ } finally { pollingLive = false; }
}
setInterval(pollLive, 1300);

// ---------- hand gestures (on-device; navigation only) ----------
let tracker = null;
$('#gesture').addEventListener('click', async () => {
  if (tracker) { tracker.stop(); tracker = null; document.body.classList.remove('gesture-on'); $('#gesture').classList.remove('on'); return; }
  try {
    $('#gesture').classList.add('busy');
    const { startHandTracking } = await import('./gestures.js');
    tracker = await startHandTracking($('#camera'), onGesture, (s, m) => {
      $('#gesture-hud').textContent = `${m.active ? (m.paused ? 'JEDA (tahan telapak 1 dtk)' : 'AKTIF') : 'tahan telapak terbuka 1 dtk untuk mulai'} · ${s.fps.toFixed(0)} fps · ${s.latencyMs.toFixed(0)} ms`;
    });
    document.body.classList.add('gesture-on'); $('#gesture').classList.add('on');
  } catch (err) { toast(`Gestur tidak bisa dimulai: ${err.message}`, true); } finally { $('#gesture').classList.remove('busy'); }
});

const cursor = $('#cursor');
let gDown = false, gPos = { x: 0, y: 0 };
function onGesture(e) {
  const x = (e.x ?? 0) * innerWidth, y = (e.y ?? 0) * innerHeight;
  if (e.type === 'cursor') { cursor.hidden = false; cursor.style.transform = `translate(${x}px, ${y}px)`; gPos = { x, y }; if (gDown) board.pointerEvent('pointermove', x, y); }
  if (e.type === 'press') { gDown = true; cursor.classList.add('down'); board.pointerEvent('pointerdown', x, y); }
  if (e.type === 'release') { if (gDown) board.pointerEvent('pointerup', gPos.x, gPos.y); gDown = false; cursor.classList.remove('down'); }
  if (e.type === 'click') {
    const target = document.elementFromPoint(x, y);
    const ok = target?.closest('[data-gesture="ok"]');   // only navigation buttons; never "Lepas"/confirm dialogs
    if (ok) ok.click();
  }
  if (e.type === 'zoom') board.zoomBy(Math.min(Math.max(e.factor, 0.8), 1.25), x, y);
  if (e.type === 'scroll') board.panBy(-e.dx * innerWidth, -e.dy * innerHeight);
  if (e.type === 'pause' || (e.type === 'lock' && !e.active)) { cursor.hidden = true; gDown = false; }
}

// ---------- the docks (ADR-052) ----------
dockApi = initDock({ api, toast, embedded: !!fromApp.embedded });
addEventListener('keydown', (e) => { if (e.key === 'Home' && !e.target.closest('input, textarea, select')) board.fitAll(480); });
if (fromApp.token) api.token = fromApp.token;
if (api.token) { loadContexts().catch((err) => toast(err.message, true)); loadAreas(); } else showLogin();
