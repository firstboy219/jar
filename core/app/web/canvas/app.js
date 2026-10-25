// JARVIS — the 3D canvas: the owner's workspace as a galaxy (Blueprint v4 Fase 4, ADR-049).
// One galaxy per context (Utama, each project, each company). Cards are references to real things (tasks, documents,
// what JARVIS showed, memories, company data); this page only lays them out in space. It can fly, select, place, move,
// link and take cards off the canvas — it never approves, deletes data, sends or pays.
import * as THREE from './vendor/three.module.min.js';
import { cardScale, contextLabel, diffCards, ease, matchCards, spiralGalaxy, starField } from './lib.js';

const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const small = window.matchMedia('(max-width: 700px)').matches;

// ---------- API (device token from pairing with the admin password; kept only in this browser) ----------
const api = {
  get token() { try { return localStorage.getItem('jarvis_canvas_token') || ''; } catch { return ''; } },
  set token(v) { try { v ? localStorage.setItem('jarvis_canvas_token', v) : localStorage.removeItem('jarvis_canvas_token'); } catch { /* private mode */ } },
  async req(method, path, body) {
    const r = await fetch(path, { method, headers: { Authorization: `Bearer ${this.token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined });
    if (r.status === 401) { showLogin(); throw new Error('perlu masuk'); }
    const data = r.headers.get('content-type')?.includes('json') ? await r.json() : null;
    if (!r.ok) throw new Error((data && data.detail) || `HTTP ${r.status}`);
    return data;
  },
};

function toast(text, bad = false) {
  const t = el('div', `toast${bad ? ' bad' : ''}`, text);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), 4200);
}

function showLogin() {
  $('#login').hidden = false;
  $('#password').focus();
}

$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('#login-error').textContent = '';
  try {
    const r = await fetch('/api/v1/devices/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: $('#password').value, device_name: 'Kanvas 3D (web)' }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'gagal');
    api.token = d.token;
    $('#password').value = '';
    $('#login').hidden = true;
    await loadContexts();
  } catch (err) { $('#login-error').textContent = err.message; }
});

// ---------- scene ----------
const renderer = new THREE.WebGLRenderer({ antialias: !small, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, small ? 1.5 : 2));
renderer.setClearColor(0x02030a);
$('#space').append(renderer.domElement);
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x02030a, 0.000035);
const camera = new THREE.PerspectiveCamera(60, 1, 1, 80000);

function glowTexture(inner = 'rgba(255,255,255,1)', outer = 'rgba(255,255,255,0)') {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d'); const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, inner); grd.addColorStop(0.25, 'rgba(255,255,255,0.55)'); grd.addColorStop(1, outer);
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const GLOW = glowTexture();

const galaxyData = spiralGalaxy(small ? 14000 : 30000);
const galaxyGeo = new THREE.BufferGeometry();
galaxyGeo.setAttribute('position', new THREE.BufferAttribute(galaxyData.positions, 3));
galaxyGeo.setAttribute('color', new THREE.BufferAttribute(galaxyData.colors, 3));
const galaxy = new THREE.Points(galaxyGeo, new THREE.PointsMaterial({ size: 11, map: GLOW, vertexColors: true, transparent: true,
  depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.95 }));
scene.add(galaxy);

const starsGeo = new THREE.BufferGeometry();
starsGeo.setAttribute('position', new THREE.BufferAttribute(starField(small ? 3000 : 7000), 3));
scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({ size: 26, map: GLOW, color: 0xbfd7ff, transparent: true, depthWrite: false,
  blending: THREE.AdditiveBlending, opacity: 0.7, fog: false })));

const core = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: 0xffc98a, transparent: true, opacity: 0.6, depthWrite: false, blending: THREE.AdditiveBlending }));
core.scale.set(620, 620, 1);
scene.add(core);

const constellationGroup = new THREE.Group();
scene.add(constellationGroup);
const cardStarGeo = new THREE.BufferGeometry();
const cardStars = new THREE.Points(cardStarGeo, new THREE.PointsMaterial({ size: 46, map: GLOW, vertexColors: true, transparent: true,
  depthWrite: false, blending: THREE.AdditiveBlending }));
scene.add(cardStars);
const edgeGeo = new THREE.BufferGeometry();
const edges = new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ color: 0x67e8f9, transparent: true, opacity: 0.45 }));
scene.add(edges);

// ---------- camera: orbit around a target that can go anywhere (the space is infinite) ----------
const view = { target: new THREE.Vector3(), r: 3600, theta: 0.6, phi: 0.95 };
let flight = null;
function placeCamera() {
  const { target, r, theta, phi } = view;
  camera.position.set(target.x + r * Math.sin(phi) * Math.sin(theta), target.y + r * Math.cos(phi), target.z + r * Math.sin(phi) * Math.cos(theta));
  camera.lookAt(target);
}
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function flyTo(pos, r = 520, ms = 900) {
  if (reducedMotion) { flight = null; view.target.set(pos.x, pos.y, pos.z); view.r = r; return; }   // jump, no flight
  flight = { from: view.target.clone(), to: new THREE.Vector3(pos.x, pos.y, pos.z), r0: view.r, r1: r, t0: performance.now(), ms };
}
function home() { flyTo({ x: 0, y: 0, z: 0 }, small ? 4600 : 3600, 1100); view.phi = 0.95; }
function orbit(dx, dy) { view.theta -= dx * 0.005; view.phi = Math.min(Math.max(view.phi - dy * 0.005, 0.08), Math.PI - 0.08); }
function pan(dx, dy) {
  const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
  const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
  const k = view.r / 900;
  view.target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
}
function dolly(f) { view.r = Math.min(Math.max(view.r * f, 60), 30000); }

// ---------- state ----------
const KIND_COLOR = {};
let contexts = [], current = null, cards = new Map(), canvasEdges = [], selected = null, linkFrom = null, gestureMode = false;

function hex(c) { return new THREE.Color(c); }

function rebuildStars() {
  const list = [...cards.values()];
  const pos = new Float32Array(list.length * 3), col = new Float32Array(list.length * 3);
  list.forEach((c, i) => {
    pos.set([c.data.x, c.data.y, c.data.z], i * 3);
    const k = hex(KIND_COLOR[c.data.kind] || '#ffffff');
    col.set([k.r, k.g, k.b], i * 3);
  });
  cardStarGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  cardStarGeo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  cardStarGeo.computeBoundingSphere();
  const seg = [];
  for (const e of canvasEdges) {
    const a = cards.get(e.a), b = cards.get(e.b);
    if (a && b) seg.push(a.data.x, a.data.y, a.data.z, b.data.x, b.data.y, b.data.z);
  }
  edgeGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(seg), 3));
  edgeGeo.computeBoundingSphere();
}

function buildConstellations(list) {
  constellationGroup.clear();
  $('#labels').replaceChildren();
  for (const c of list) {
    KIND_COLOR[c.kind] = c.color;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: hex(c.color), transparent: true, opacity: 0.55,
      depthWrite: false, blending: THREE.AdditiveBlending }));
    s.scale.set(300, 300, 1);
    s.position.set(...c.center);
    constellationGroup.add(s);
    const label = el('div', 'constellation', c.title);
    label.style.setProperty('--c', c.color);
    label.dataset.x = c.center[0]; label.dataset.y = c.center[1]; label.dataset.z = c.center[2];
    label.dataset.gesture = 'ok';
    label.addEventListener('click', () => flyTo({ x: c.center[0], y: c.center[1], z: c.center[2] }, 900));
    $('#labels').append(label);
  }
}

function cardElement(d) {
  const e = el('div', 'card');
  e.dataset.id = d.id;
  e.style.setProperty('--c', KIND_COLOR[d.kind] || '#fff');
  fillCard(e, d);
  e.addEventListener('pointerdown', (ev) => startCardDrag(ev, d.id));
  e.addEventListener('dblclick', () => { const c = cards.get(d.id); flyTo(c.data, 420); });
  $('#cards').append(e);
  return e;
}

function fillCard(e, d) {
  e.replaceChildren();
  e.append(el('div', 'kind', `${d.kind}${d.subtitle ? ' · ' + d.subtitle : ''}`), el('div', 'title', d.title || '(tanpa judul)'));
  if (d.snippet) e.append(el('div', 'snippet', d.snippet));
  if (d.image) { const img = el('img'); img.src = d.image; img.loading = 'lazy'; img.alt = ''; e.append(img); }
  const acts = el('div', 'actions');
  const btn = (label, act, cls = '') => { const b = el('button', cls, label); b.dataset.act = act; if (act !== 'hide') b.dataset.gesture = 'ok'; b.addEventListener('click', (ev) => { ev.stopPropagation(); cardAction(d.id, act); }); acts.append(b); };
  if (d.url) btn('Buka', 'open');
  btn('Terbang ke', 'fly');
  btn(linkFrom === d.id ? 'Batal hubung' : 'Hubungkan', 'link');
  btn(d.pinned ? 'Lepas pin' : 'Pin', 'pin');
  btn('Lepas dari kanvas', 'hide', 'danger');
  e.append(acts);
  e.classList.toggle('pinned', !!d.pinned);
}

async function cardAction(id, act) {
  const c = cards.get(id);
  if (!c) return;
  try {
    if (act === 'fly') flyTo(c.data, 420);
    if (act === 'open') await openUrl(c.data.url);
    if (act === 'pin') await api.req('PATCH', `/api/v1/canvas/cards/${id}`, { pinned: !c.data.pinned });
    if (act === 'link') {
      if (linkFrom === id) { linkFrom = null; toast('Batal menghubungkan.'); }
      else if (linkFrom) { await api.req('POST', `/api/v1/canvases/${current.id}/edges`, { a: linkFrom, b: id }); linkFrom = null; toast('Dua kartu terhubung.'); }
      else { linkFrom = id; toast('Pilih kartu kedua, lalu "Hubungkan".'); }
      cards.forEach((x) => fillCard(x.el, x.data));
    }
    if (act === 'hide') {
      if (gestureMode) return toast('Melepas kartu tidak bisa lewat gestur.', true);
      if (!confirm('Lepas kartu ini dari kanvas? Isinya (tugas/dokumen/dll) tidak dihapus.')) return;
      await api.req('DELETE', `/api/v1/canvas/cards/${id}`);
    }
    await refresh(true);
  } catch (err) { toast(err.message, true); }
}

async function openUrl(url) {
  if (!url) return;
  if (url.startsWith('https://')) return void window.open(url, '_blank', 'noopener');
  const r = await fetch(url, { headers: { Authorization: `Bearer ${api.token}` } });
  if (!r.ok) throw new Error(`tidak bisa membuka (${r.status})`);
  window.open(URL.createObjectURL(await r.blob()), '_blank', 'noopener');
}

function select(id) {
  selected = id;
  cards.forEach((c, k) => c.el.classList.toggle('selected', k === id));
}

// ---------- data ----------
async function loadContexts() {
  contexts = await api.req('GET', '/api/v1/canvases');
  const pick = $('#galaxy');
  pick.replaceChildren(...contexts.map((c) => { const o = el('option', null, `${contextLabel(c)} (${c.cards})`); o.value = c.context; return o; }));
  const want = (() => { try { return localStorage.getItem('jarvis_canvas_context'); } catch { return null; } })();
  pick.value = contexts.some((c) => c.context === want) ? want : 'utama';
  await openContext(pick.value);
}

async function openContext(context) {
  const c = await api.req('POST', '/api/v1/canvases', { context });
  try { localStorage.setItem('jarvis_canvas_context', context); } catch { /* ignore */ }
  current = { id: c.id, version: -1, context };
  cards.forEach((x) => x.el.remove());
  cards = new Map();
  selected = null; linkFrom = null;
  await refresh(true);
  const link = /#kartu=(\d+)/.exec(location.hash);   // a link straight to one card (from JARVIS or the app)
  const target = link && cards.get(Number(link[1]));
  if (target) { view.r = 3600; flyTo(target.data, 420, 1600); select(target.data.id); } else home();
}

let lastFocus = null;
async function refresh(force = false) {
  if (!current) return;
  const d = await api.req('GET', `/api/v1/canvases/${current.id}${force ? '' : `?since=${current.version}`}`);
  if (d.unchanged) return;
  if (current.version < 0) buildConstellations(d.constellations);
  const before = [...cards.values()].map((c) => c.data);
  const diff = diffCards(before, d.cards);
  for (const c of diff.removed) { cards.get(c.id)?.el.remove(); cards.delete(c.id); }
  for (const c of d.cards) {
    const had = cards.get(c.id);
    if (had) { had.data = c; fillCard(had.el, c); } else cards.set(c.id, { data: c, el: cardElement(c) });
  }
  canvasEdges = d.edges;
  current.version = d.version;
  $('#title').textContent = d.title;
  $('#count').textContent = `${d.cards.length} kartu`;
  rebuildStars();
  if (d.focus && d.focus !== lastFocus && cards.get(d.focus)) { flyTo(cards.get(d.focus).data, 420); select(d.focus); }
  lastFocus = d.focus;
  if (diff.added.length && before.length) toast(`${diff.added.length} kartu baru dari JARVIS.`);
}

setInterval(() => { if (!document.hidden && api.token) refresh().catch(() => {}); }, 3000);

// ---------- pointer: orbit / pan / zoom, and dragging cards through space ----------
const pointers = new Map();
let gesture = null;   // {mode: 'orbit'|'pan'|'card', ...}
const raycaster = new THREE.Raycaster();

function ndc(x, y) { return new THREE.Vector2((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1); }

function startCardDrag(ev, id) {
  if (ev.target.closest('button')) return;
  ev.stopPropagation();
  const c = cards.get(id);
  const normal = camera.getWorldDirection(new THREE.Vector3());
  gesture = { mode: 'card', id, plane: new THREE.Plane().setFromNormalAndCoplanarPoint(normal, new THREE.Vector3(c.data.x, c.data.y, c.data.z)),
    sx: ev.clientX, sy: ev.clientY, moved: false };
  if (ev.pointerId != null) ev.target.setPointerCapture?.(ev.pointerId);
}

function moveCard(x, y) {
  const c = cards.get(gesture.id);
  raycaster.setFromCamera(ndc(x, y), camera);
  const hit = raycaster.ray.intersectPlane(gesture.plane, new THREE.Vector3());
  if (!hit) return;
  if (Math.hypot(x - gesture.sx, y - gesture.sy) > 6) gesture.moved = true;
  if (gesture.moved) { c.data = { ...c.data, x: hit.x, y: hit.y, z: hit.z }; rebuildStars(); }
}

async function endCardDrag() {
  const g = gesture; gesture = null;
  const c = cards.get(g.id);
  if (!g.moved) return select(selected === g.id ? null : g.id);
  try { await api.req('PATCH', `/api/v1/canvas/cards/${g.id}`, { x: c.data.x, y: c.data.y, z: c.data.z }); await refresh(true); }
  catch (err) { toast(err.message, true); }
}

const surface = renderer.domElement;
surface.addEventListener('pointerdown', (e) => {
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  surface.setPointerCapture(e.pointerId);
  if (pointers.size === 1) gesture = { mode: e.button === 2 || e.shiftKey ? 'pan' : 'orbit', x: e.clientX, y: e.clientY };
  else gesture = { mode: 'pinch', d: pinchDistance(), c: pinchCenter() };
});
window.addEventListener('pointermove', (e) => {
  if (gesture?.mode === 'card') return moveCard(e.clientX, e.clientY);
  if (!pointers.has(e.pointerId)) return;
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (!gesture) return;
  if (gesture.mode === 'pinch' && pointers.size === 2) {
    const d = pinchDistance(), c = pinchCenter();
    dolly(gesture.d / d); pan(c.x - gesture.c.x, c.y - gesture.c.y);
    gesture.d = d; gesture.c = c; return;
  }
  const dx = e.clientX - gesture.x, dy = e.clientY - gesture.y;
  gesture.x = e.clientX; gesture.y = e.clientY;
  if (gesture.mode === 'orbit') orbit(dx, dy); else if (gesture.mode === 'pan') pan(dx, dy);
});
window.addEventListener('pointerup', (e) => {
  pointers.delete(e.pointerId);
  if (gesture?.mode === 'card') return void endCardDrag();
  if (pointers.size === 0) gesture = null;
});
surface.addEventListener('contextmenu', (e) => e.preventDefault());
surface.addEventListener('wheel', (e) => { e.preventDefault(); dolly(Math.exp(e.deltaY * 0.0012)); }, { passive: false });
surface.addEventListener('dblclick', () => select(null));
function pinchDistance() { const [a, b] = [...pointers.values()]; return Math.hypot(a.x - b.x, a.y - b.y) || 1; }
function pinchCenter() { const [a, b] = [...pointers.values()]; return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }

const keys = new Set();
window.addEventListener('keydown', (e) => { if (e.target.closest('input, select')) return; keys.add(e.key.toLowerCase()); if (e.key === 'Home') home(); });
window.addEventListener('keyup', (e) => keys.delete(e.key.toLowerCase()));
function flyKeys(dt) {
  const f = camera.getWorldDirection(new THREE.Vector3());
  const right = new THREE.Vector3().crossVectors(f, camera.up).normalize();
  const v = view.r * 0.0009 * dt;
  if (keys.has('w')) view.target.addScaledVector(f, v);
  if (keys.has('s')) view.target.addScaledVector(f, -v);
  if (keys.has('a')) view.target.addScaledVector(right, -v);
  if (keys.has('d')) view.target.addScaledVector(right, v);
  if (keys.has('q')) view.target.y -= v;
  if (keys.has('e')) view.target.y += v;
  if (keys.has('arrowleft')) orbit(-dt * 0.4, 0);
  if (keys.has('arrowright')) orbit(dt * 0.4, 0);
  if (keys.has('arrowup')) dolly(1 - dt * 0.0012);
  if (keys.has('arrowdown')) dolly(1 + dt * 0.0012);
}

// ---------- toolbar ----------
$('#galaxy').addEventListener('change', (e) => openContext(e.target.value).catch((err) => toast(err.message, true)));
$('#home').addEventListener('click', home);
$('#new-project').addEventListener('click', async () => {
  const name = prompt('Nama proyek (galaksi baru):');
  if (!name) return;
  try { const c = await api.req('POST', '/api/v1/canvases', { context: `project:${name}`, title: name }); await loadContexts(); $('#galaxy').value = c.context; await openContext(c.context); }
  catch (err) { toast(err.message, true); }
});
$('#find').addEventListener('input', (e) => {
  const found = matchCards([...cards.values()].map((c) => c.data), e.target.value);
  const list = $('#find-results');
  list.replaceChildren(...found.slice(0, 8).map((c) => { const b = el('button', null, c.title); b.dataset.gesture = 'ok'; b.addEventListener('click', () => { flyTo(c, 420); select(c.id); list.replaceChildren(); }); return b; }));
});
$('#add').addEventListener('click', () => { $('#add-panel').hidden = !$('#add-panel').hidden; if (!$('#add-panel').hidden) $('#add-q').focus(); });
$('#add-q').addEventListener('input', debounce(async (e) => {
  if (!current) return;
  const items = await api.req('GET', `/api/v1/canvases/${current.id}/search?q=${encodeURIComponent(e.target.value)}`).catch(() => []);
  $('#add-results').replaceChildren(...items.map((it) => {
    const b = el('button', null, `${it.kind} · ${it.title}`);
    b.addEventListener('click', async () => {
      try { const n = await api.req('POST', `/api/v1/canvases/${current.id}/cards`, { ref: it.ref }); await refresh(true); const c = cards.get(n.id); if (c) { flyTo(c.data, 420); select(n.id); } }
      catch (err) { toast(err.message, true); }
    });
    return b;
  }));
}, 300));
$('#history').addEventListener('click', async () => {
  const panel = $('#history-panel');
  panel.hidden = !panel.hidden;
  if (panel.hidden) return;
  const versions = await api.req('GET', `/api/v1/canvases/${current.id}/versions`);
  panel.replaceChildren(el('h3', null, 'Riwayat tata letak'), ...versions.map((v) => {
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
});
$('#logout').addEventListener('click', () => { api.token = ''; location.reload(); });
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ---------- hand gestures (on-device; navigation only) ----------
let tracker = null;
$('#gesture').addEventListener('click', async () => {
  if (tracker) { tracker.stop(); tracker = null; gestureMode = false; document.body.classList.remove('gesture-on'); $('#gesture').textContent = 'Gestur'; return; }
  try {
    $('#gesture').textContent = 'Memuat…';
    const { startHandTracking } = await import('./gestures.js');
    tracker = await startHandTracking($('#camera'), onGesture, (s, m) => {
      $('#gesture-hud').textContent = `${m.active ? (m.paused ? 'JEDA (tahan telapak 1 dtk)' : 'AKTIF') : 'tahan telapak terbuka 1 dtk untuk mulai'} · ${s.fps.toFixed(0)} fps · ${s.latencyMs.toFixed(0)} ms`;
    });
    gestureMode = true;
    document.body.classList.add('gesture-on');
    $('#gesture').textContent = 'Matikan gestur';
  } catch (err) { $('#gesture').textContent = 'Gestur'; toast(`Gestur tidak bisa dimulai: ${err.message}`, true); }
});

const cursor = $('#cursor');
let gDrag = null;
function onGesture(e) {
  const x = (e.x ?? 0) * innerWidth, y = (e.y ?? 0) * innerHeight;
  if (e.type === 'cursor') { cursor.hidden = false; cursor.style.transform = `translate(${x}px, ${y}px)`; if (gDrag?.mode === 'card') moveCard(x, y); }
  if (e.type === 'press') {
    const target = document.elementFromPoint(x, y);
    const card = target?.closest('.card');
    if (card && !target.closest('button')) { startCardDrag({ target: card, clientX: x, clientY: y, stopPropagation() {} }, Number(card.dataset.id)); gDrag = { mode: 'card' }; }
    else gDrag = { mode: 'orbit', x, y };
    cursor.classList.add('down');
  }
  if (e.type === 'drag' && gDrag?.mode === 'orbit') { orbit(x - gDrag.x, y - gDrag.y); gDrag.x = x; gDrag.y = y; }
  if (e.type === 'release') { if (gDrag?.mode === 'card' && gesture?.mode === 'card') endCardDrag(); gDrag = null; cursor.classList.remove('down'); }
  if (e.type === 'click') {
    const target = document.elementFromPoint(x, y);
    const ok = target?.closest('[data-gesture="ok"]');   // only navigation buttons; never "Lepas"/confirm dialogs
    if (ok) ok.click();
  }
  if (e.type === 'zoom') dolly(1 / Math.min(Math.max(e.factor, 0.8), 1.25));
  if (e.type === 'scroll') pan(e.dx * innerWidth, e.dy * innerHeight);
  if (e.type === 'pause' || (e.type === 'lock' && !e.active)) { cursor.hidden = true; gDrag = null; }
}

// ---------- frame ----------
const tmp = new THREE.Vector3();
let lastT = performance.now();
function frame(t) {
  const dt = Math.min(t - lastT, 50); lastT = t;
  if (flight) {
    const k = ease((t - flight.t0) / flight.ms);
    view.target.lerpVectors(flight.from, flight.to, k);
    view.r = flight.r0 + (flight.r1 - flight.r0) * k;
    if (k >= 1) flight = null;
  }
  flyKeys(dt);
  galaxy.rotation.y += dt * 0.000004;
  placeCamera();
  renderer.render(scene, camera);
  // HTML cards follow their 3D positions; the 140 nearest are drawn as cards, the rest are stars
  const list = [...cards.values()].map((c) => {
    tmp.set(c.data.x, c.data.y, c.data.z);
    return { c, d: camera.position.distanceTo(tmp), p: tmp.clone().project(camera) };
  }).sort((a, b) => a.d - b.d);
  list.forEach(({ c, d, p }, i) => {
    const s = cardScale(d, c.data.size);
    const visible = i < 140 && s && p.z < 1 && Math.abs(p.x) < 1.2 && Math.abs(p.y) < 1.2;
    c.el.hidden = !visible;
    if (!visible) return;
    const x = (p.x + 1) / 2 * innerWidth, y = (1 - p.y) / 2 * innerHeight;
    c.el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px) scale(${s})`;
    c.el.style.zIndex = String(10000 - Math.round(d));
    c.el.style.opacity = String(Math.min(1, s * 1.6));
  });
  for (const label of $('#labels').children) {
    tmp.set(+label.dataset.x, +label.dataset.y + 230, +label.dataset.z).project(camera);
    const vis = tmp.z < 1 && Math.abs(tmp.x) < 1.1 && Math.abs(tmp.y) < 1.1;
    label.hidden = !vis;
    if (vis) label.style.transform = `translate(-50%, -50%) translate(${(tmp.x + 1) / 2 * innerWidth}px, ${(1 - tmp.y) / 2 * innerHeight}px)`;
  }
  $('#hud').textContent = `jarak ${Math.round(view.r)} · pusat ${Math.round(view.target.x)}, ${Math.round(view.target.y)}, ${Math.round(view.target.z)}`;
  requestAnimationFrame(frame);
}

function resize() { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); }
window.addEventListener('resize', resize);
resize();
placeCamera();
requestAnimationFrame(frame);
if (api.token) loadContexts().catch((err) => toast(err.message, true)); else showLogin();
