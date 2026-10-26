// Pure helpers of the 3D canvas viewer (unit-tested with node: core/tests/test_canvas_js.py).

/** Deterministic PRNG so the galaxy looks the same every visit. */
export function rng(seed = 7) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

/**
 * A spiral galaxy of n particles: positions (x,y,z) and colours (r,g,b), warm core → cyan/violet arms.
 * Logarithmic arms with scatter that grows outward, thin disk. Returns {positions, colors} Float32Arrays.
 */
export function spiralGalaxy(n, { arms = 4, radius = 2300, twist = 2.6, thickness = 70, seed = 7 } = {}) {
  const r = rng(seed);
  const positions = new Float32Array(n * 3);
  const colors = new Float32Array(n * 3);
  const core = [1.0, 0.82, 0.55], mid = [0.45, 0.75, 1.0], edge = [0.62, 0.45, 1.0];
  for (let i = 0; i < n; i++) {
    const d = Math.pow(r(), 1.6);                     // more particles near the core
    const arm = Math.floor(r() * arms);
    const angle = arm * (2 * Math.PI / arms) + d * twist * Math.PI;
    const scatter = (0.12 + d * 0.5) * radius * 0.09;
    const x = Math.cos(angle) * d * radius + (r() - 0.5) * scatter;
    const z = Math.sin(angle) * d * radius + (r() - 0.5) * scatter;
    const y = (r() - 0.5) * thickness * (1 - d * 0.7) * 2;
    positions.set([x, y, z], i * 3);
    const c = d < 0.35 ? mix(core, mid, d / 0.35) : mix(mid, edge, (d - 0.35) / 0.65);
    const glow = 0.55 + r() * 0.45;
    colors.set([c[0] * glow, c[1] * glow, c[2] * glow], i * 3);
  }
  return { positions, colors };
}

export function mix(a, b, t) {
  const k = Math.min(Math.max(t, 0), 1);
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
}

/** Background stars on a huge shell (the space around the galaxy). */
export function starField(n, { inner = 6000, outer = 22000, seed = 11 } = {}) {
  const r = rng(seed);
  const positions = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const u = r() * 2 - 1, th = r() * 2 * Math.PI, rad = inner + r() * (outer - inner);
    const s = Math.sqrt(1 - u * u);
    positions.set([rad * s * Math.cos(th), rad * u, rad * s * Math.sin(th)], i * 3);
  }
  return positions;
}

/** How big a card is drawn at a camera distance: readable near, a star when far (null = draw only the star). */
export function cardScale(distance, size = 1) {
  if (!(distance > 0)) return null;
  const s = (420 / distance) * size;
  if (s < 0.28) return null;
  return Math.min(s, 1.6);
}

/** Cards matching a search, best first (title starts > title contains > subtitle/snippet contains). */
export function matchCards(cards, query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return [];
  const score = (c) => {
    const t = (c.title || '').toLowerCase();
    if (t.startsWith(q)) return 3;
    if (t.includes(q)) return 2;
    if (`${c.subtitle || ''} ${c.snippet || ''}`.toLowerCase().includes(q)) return 1;
    return 0;
  };
  return cards.map((c) => [score(c), c]).filter(([s]) => s > 0).sort((a, b) => b[0] - a[0]).map(([, c]) => c);
}

/** What changed between two card lists: {added, removed, moved, changed} (by id). */
export function diffCards(before, after) {
  const old = new Map(before.map((c) => [c.id, c]));
  const now = new Map(after.map((c) => [c.id, c]));
  const added = after.filter((c) => !old.has(c.id));
  const removed = before.filter((c) => !now.has(c.id));
  const moved = [], changed = [];
  for (const c of after) {
    const o = old.get(c.id);
    if (!o) continue;
    if (o.x !== c.x || o.y !== c.y || o.z !== c.z || o.size !== c.size) moved.push(c);
    if (o.title !== c.title || o.subtitle !== c.subtitle || o.snippet !== c.snippet || o.status !== c.status) changed.push(c);
  }
  return { added, removed, moved, changed };
}

/** Smooth camera flight: eased interpolation 0..1. */
export function ease(t) {
  const k = Math.min(Math.max(t, 0), 1);
  return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
}

/** Context label for the galaxy picker. */
export function contextLabel(c) {
  if (c.context === 'utama') return '🌌 Utama';
  if (c.context.startsWith('company:')) return `🏢 ${c.title}`;
  return `🪐 ${c.title}`;
}

/**
 * The Android app opens the viewer as ".../canvas/#t=<device token>&app=1". Returns the token (if any), whether the viewer
 * is embedded in the app, and the rest of the fragment (deep links such as "#kartu=12" survive). The token lives only in the
 * fragment, which the browser never sends to a server; the viewer removes it from the address right away.
 */
export function takeAppParams(hash) {
  const parts = String(hash || '').replace(/^#/, '').split('&').filter(Boolean);
  let token = '', embedded = false;
  const rest = [];
  for (const p of parts) {
    if (p.startsWith('t=')) token = decodeURIComponent(p.slice(2));
    else if (p === 'app=1') embedded = true;
    else rest.push(p);
  }
  return { token, embedded, rest: rest.length ? `#${rest.join('&')}` : '' };
}

/** Where the fixed desk panels (requests, n8n, storage) hang in the galaxy: a ring around the core, at table height. */
export const PANELS = {
  prompts: { x: -760, y: 140, z: -430, size: 3.6, title: 'Permintaanmu' },
  n8n: { x: 760, y: 140, z: -430, size: 3.6, title: 'Otomasi (n8n)' },
  storage: { x: 0, y: 140, z: 880, size: 3.6, title: 'Simpanan' },
  player: { x: -760, y: 140, z: 430, size: 3.6, title: 'Pemutar' },
  meeting: { x: 760, y: 140, z: 430, size: 3.6, title: 'Rapat' },
};

/**
 * Should the camera fly to a worker station that just showed up? Only for the owner's own task, once, while following is on and the
 * owner is not in the middle of something (touched the screen within the last 4 s) — the desk never grabs the camera from a hand.
 */
export function shouldFollow({ follow, idleMs, kind, status, seen }) {
  return !!follow && !seen && kind === 'owner' && (status === 'queued' || status === 'running') && idleMs > 4000;
}

/** A station whose screenshot changed (a new frame number) must fetch it; the same number never refetches. */
export function frameNeedsFetch(shownSeq, seq, hasFrame) {
  return !!hasFrame && seq > 0 && seq !== shownSeq;
}

/** "5 dtk", "2 mnt" — how long a station has been at work. */
export function ago(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return s < 90 ? `${s} dtk` : s < 5400 ? `${Math.round(s / 60)} mnt` : `${(s / 3600).toFixed(1)} jam`;
}

// ---------- the drafting toolkit (ADR-052): views, projection, commands ----------

/** Standard views as orbit angles: theta around the vertical axis, phi from straight up (0) to straight down (π). */
export const VIEWS = {
  top: { theta: 0, phi: 0.02 }, bottom: { theta: 0, phi: Math.PI - 0.02 },
  front: { theta: 0, phi: Math.PI / 2 }, back: { theta: Math.PI, phi: Math.PI / 2 },
  right: { theta: Math.PI / 2, phi: Math.PI / 2 }, left: { theta: -Math.PI / 2, phi: Math.PI / 2 },
  iso: { theta: Math.PI / 4, phi: 0.955 },
};
export const VIEW_LABEL = { top: 'Atas', bottom: 'Bawah', front: 'Depan', back: 'Belakang', right: 'Kanan', left: 'Kiri', iso: 'Isometrik' };
export const clampPhi = (phi) => Math.min(Math.max(phi, 0.02), Math.PI - 0.02);

/** Smallest turn from angle a to b (so a flight to "back" does not spin the long way round). */
export function shortestAngle(a, b) {
  const d = ((b - a + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
  return a + d;
}

/** Centre and radius of a cloud of points (zoom extents / zoom to selection). */
export function boundsOf(points) {
  if (!points.length) return { x: 0, y: 0, z: 0, radius: 600 };
  const c = points.reduce((s, p) => ({ x: s.x + p.x / points.length, y: s.y + p.y / points.length, z: s.z + p.z / points.length }), { x: 0, y: 0, z: 0 });
  const radius = Math.max(...points.map((p) => Math.hypot(p.x - c.x, p.y - c.y, p.z - c.z)), 120);
  return { ...c, radius };
}

/** Camera distance that fits a sphere of `radius` in view (vertical fov in degrees, with a little margin). */
export function fitDistance(radius, fovDeg, aspect) {
  const v = (fovDeg * Math.PI) / 180, h = 2 * Math.atan(Math.tan(v / 2) * aspect);
  return (radius / Math.sin(Math.min(v, h) / 2)) * 1.12;
}

/** Height of the orthographic frustum that shows the same picture as a perspective camera at distance r. */
export const orthoHeight = (r, fovDeg) => 2 * r * Math.tan((fovDeg * Math.PI) / 360);

export const snapValue = (v, step) => (step > 0 ? Math.round(v / step) * step : v);

export function distance3(a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
  return { dx, dy, dz, d: Math.hypot(dx, dy, dz) };
}

/** CSS matrix3d for the view cube from a camera's matrixWorldInverse (column-major 16 numbers); CSS has y pointing down. */
export function cssCubeMatrix(e) {
  const f = [1, -1, 1];
  const m = [];
  for (let j = 0; j < 3; j++) { for (let i = 0; i < 3; i++) m.push(f[i] * e[j * 4 + i] * f[j]); m.push(0); }
  m.push(0, 0, 0, 1);
  return `matrix3d(${m.map((x) => (Math.abs(x) < 1e-9 ? 0 : +x.toFixed(5))).join(',')})`;
}

const VIEW_WORDS = { top: 'top', atas: 'top', bottom: 'bottom', bawah: 'bottom', front: 'front', depan: 'front', back: 'back', belakang: 'back',
  left: 'left', kiri: 'left', right: 'right', kanan: 'right', iso: 'iso', isometrik: 'iso', isometric: 'iso' };
const TOOL_WORDS = { orbit: 'orbit', putar: 'orbit', pan: 'pan', geser: 'pan', zoom: 'zoom', select: 'select', pilih: 'select',
  measure: 'measure', ukur: 'measure', link: 'link', hubung: 'link', hubungkan: 'link' };

/** The command line (like AutoCAD's): "top", "zoom e", "ortho", "layer tugas off", "view save A", "cari laporan"… → {name, ...}. */
export function parseCommand(text) {
  const t = String(text || '').trim().toLowerCase().replace(/\s+/g, ' ');
  if (!t) return { name: 'none' };
  const [w, ...rest] = t.split(' ');
  const arg = rest.join(' ');
  if (VIEW_WORDS[t]) return { name: 'view', view: VIEW_WORDS[t] };
  if (['home', 'inti'].includes(t)) return { name: 'home' };
  if (['ze', 'extents', 'zoom e', 'zoom extents', 'semua', 'zoom semua'].includes(t)) return { name: 'extents' };
  if (['zs', 'zoom s', 'zoom selection', 'zoom pilihan', 'pilihan'].includes(t)) return { name: 'selection' };
  if (['ortho', 'orto'].includes(t)) return { name: 'projection', mode: 'ortho' };
  if (['persp', 'perspective', 'perspektif'].includes(t)) return { name: 'projection', mode: 'persp' };
  if (['grid', 'kisi'].includes(t)) return { name: 'grid' };
  if (['snap'].includes(t)) return { name: 'snap' };
  if (['help', '?', 'bantuan'].includes(t)) return { name: 'help' };
  if (TOOL_WORDS[t]) return { name: 'tool', tool: TOOL_WORDS[t] };
  if (w === 'layer' || w === 'lapisan') {
    const m = /^(.+?)(?: (on|off|nyala|mati))?$/.exec(arg);
    return m && m[1] ? { name: 'layer', layer: m[1], on: m[2] ? ['on', 'nyala'].includes(m[2]) : null } : { name: 'unknown' };
  }
  if (w === 'view' || w === 'tampilan') {
    const m = /^save (.+)$/.exec(arg) || /^simpan (.+)$/.exec(arg);
    if (m) return { name: 'saveView', as: m[1] };
    return arg ? { name: 'namedView', as: arg } : { name: 'unknown' };
  }
  if (['find', 'cari'].includes(w) && arg) return { name: 'find', query: arg };
  return { name: 'unknown' };
}

// ---------- voice in the browser (ADR-052): resample, voice activity, PCM16 ----------

/** Resample mono Float32 audio by linear interpolation (the microphone runs at 44.1/48 kHz, the server wants 16 kHz). */
export function downsample(input, fromRate, toRate) {
  if (toRate >= fromRate) return Float32Array.from(input);
  const ratio = fromRate / toRate, n = Math.floor(input.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const pos = i * ratio, i0 = Math.floor(pos), i1 = Math.min(i0 + 1, input.length - 1), f = pos - i0;
    out[i] = input[i0] * (1 - f) + input[i1] * f;
  }
  return out;
}

export function floatToPcm16(input) {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) { const s = Math.max(-1, Math.min(1, input[i])); out[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
  return out;
}

export function pcm16ToBase64(pcm) {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

/**
 * Voice activity: feed 16 kHz mono Float32 chunks of any size; push() returns the finished utterance (Int16Array) or null.
 * Adaptive: the start threshold follows the room's noise floor, speech needs a few loud frames in a row, an utterance ends after
 * `hangMs` of quiet, with a short pre-roll so the first syllable is not cut; shorter than `minMs` is dropped as a click.
 */
export class Vad {
  constructor({ rate = 16000, frameMs = 20, startRms = 0.02, hangMs = 700, minMs = 350, maxMs = 15000, preMs = 300, needFrames = 3 } = {}) {
    Object.assign(this, { rate, frame: Math.round((rate * frameMs) / 1000), startRms, hangFrames: Math.round(hangMs / frameMs), minFrames: Math.round(minMs / frameMs),
      maxFrames: Math.round(maxMs / frameMs), preFrames: Math.round(preMs / frameMs), needFrames });
    this.pending = new Float32Array(0); this.pre = []; this.speech = null; this.loud = 0; this.quiet = 0; this.noise = 0.004; this.level = 0;
  }
  get active() { return this.speech !== null; }
  push(chunk) {
    const merged = new Float32Array(this.pending.length + chunk.length);
    merged.set(this.pending); merged.set(chunk, this.pending.length);
    let done = null, at = 0;
    for (; at + this.frame <= merged.length; at += this.frame) done = this.#frame(merged.subarray(at, at + this.frame)) || done;
    this.pending = merged.slice(at);
    return done;
  }
  #frame(f) {
    let e = 0;
    for (let i = 0; i < f.length; i++) e += f[i] * f[i];
    const rms = Math.sqrt(e / f.length);
    this.level = rms;
    const on = rms > Math.max(this.startRms, this.noise * 3);
    if (this.speech === null) {
      if (!on) this.noise = this.noise * 0.95 + rms * 0.05;
      this.pre.push(Float32Array.from(f)); if (this.pre.length > this.preFrames) this.pre.shift();
      this.loud = on ? this.loud + 1 : 0;
      if (this.loud >= this.needFrames) { this.speech = [...this.pre]; this.pre = []; this.quiet = 0; }
      return null;
    }
    this.speech.push(Float32Array.from(f));
    this.quiet = on ? 0 : this.quiet + 1;
    if (this.quiet >= this.hangFrames || this.speech.length >= this.maxFrames) {
      const frames = this.speech.length - this.quiet;
      const keep = this.speech.length - Math.max(0, this.quiet - 10);   // keep 200 ms of the trailing quiet, not the whole hang time
      const out = frames >= this.minFrames ? floatToPcm16(concat(this.speech.slice(0, keep))) : null;
      this.speech = null; this.loud = 0; this.quiet = 0;
      return out;
    }
    return null;
  }
}
function concat(list) { const n = list.reduce((s, a) => s + a.length, 0), out = new Float32Array(n); let o = 0; for (const a of list) { out.set(a, o); o += a.length; } return out; }

/** A live video frame from the server: task id (4 bytes) + frame number (4 bytes), then the JPEG. */
export function parseFrameHeader(buf) {
  const v = new DataView(buf);
  return { task: v.getUint32(0), seq: v.getUint32(4), offset: 8 };
}

// ---------- taking the wheel of a worker's browser (ADR-053) ----------

/** Where on the page, 0–1 each way, a pointer over the video is (the video fills its rectangle exactly). */
export function pageFraction(rect, clientX, clientY) {
  const c = (v) => Math.min(1, Math.max(0, v));
  return { x: c((clientX - rect.left) / (rect.width || 1)), y: c((clientY - rect.top) / (rect.height || 1)) };
}

/** The biggest size, keeping the picture's shape, that fits the stage. */
export function fitSize(stageW, stageH, picW, picH) {
  if (!picW || !picH) return { w: stageW, h: stageH };
  const s = Math.min(stageW / picW, stageH / picH);
  return { w: Math.floor(picW * s), h: Math.floor(picH * s) };
}

const NAMED_KEYS = new Set(['Backspace', 'Tab', 'Enter', 'Escape', 'Delete', 'Home', 'End', 'PageUp', 'PageDown', 'ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown']);

/** A keyboard event → what to send to the page, or null: shortcuts (except select-all), composition and keys a page has no use for
 *  are left alone — pasting and phone keyboards go through text instead. */
export function keyToInput(e) {
  if (e.isComposing || e.key === 'Unidentified' || e.key === 'Process' || e.key === 'Dead') return null;
  if (e.ctrlKey || e.metaKey) return e.key.toLowerCase() === 'a' ? { t: 'key', key: 'a', code: 'KeyA', ctrl: true } : null;
  if (!NAMED_KEYS.has(e.key) && e.key.length !== 1) return null;
  return { t: 'key', key: e.key, code: e.code || '', shift: !!e.shiftKey, alt: !!e.altKey };
}

/** A finger that barely moved and lifted quickly is a tap (a click); anything else drags the page. */
export function touchIntent(dx, dy, ms) {
  return Math.hypot(dx, dy) < 10 && ms < 450 ? 'tap' : 'scroll';
}

/** Screen pixels dragged over the video → page pixels to scroll (the video is smaller or larger than the page). */
export function scrollDelta(screenPx, rectWidth, picWidth) {
  return Math.round(screenPx * ((picWidth || rectWidth) / (rectWidth || 1)));
}

// ---------- feature cards on the desk: player and meeting (ADR-054) ----------

/** 754 → "12:34", 3725 → "1:02:05". */
export function mmss(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const two = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${two(m)}:${two(r)}` : `${two(m)}:${two(r)}`;
}

const YT = /^https:\/\/(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/;

/** What element plays this stage panel: a YouTube video (JARVIS' own embed page), a sound or video file — fetched with the device token when it
 *  lives on JARVIS' server (an <audio> tag cannot send a header) — or nothing we can play here. */
export function playerSource(p) {
  const url = String(p?.url || '');
  const yt = YT.exec(url);
  if (yt) return { kind: 'youtube', id: yt[1] };
  if (!url) return { kind: 'none' };
  const own = url.startsWith('/api/v1/media/');
  if (!own && !url.startsWith('https://')) return { kind: 'none' };
  return { kind: p.panel === 'video' ? 'video' : 'audio', url, auth: own };
}

/** The stop button of a voice command "selesai rapat" reached this viewer: the number only ever goes up. */
export function stopRaised(seen, now) {
  return seen != null && Number.isFinite(now) && now > seen;
}
