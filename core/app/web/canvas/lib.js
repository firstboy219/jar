// Pure helpers of the 2D board viewer (unit-tested with node: app/web/canvas/tests).

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
    if (o.x !== c.x || o.y !== c.y || o.z !== c.z || o.size !== c.size || o.w !== c.w || o.h !== c.h) moved.push(c);
    if (o.title !== c.title || o.subtitle !== c.subtitle || o.snippet !== c.snippet || o.status !== c.status || o.pinned !== c.pinned
      || JSON.stringify(o.props || null) !== JSON.stringify(c.props || null)) changed.push(c);
  }
  return { added, removed, moved, changed };
}

/** Smooth flight: eased interpolation 0..1. */
export function ease(t) {
  const k = Math.min(Math.max(t, 0), 1);
  return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
}

/** Context label for the board picker. */
export function contextLabel(c) {
  if (c.context === 'utama') return 'Utama';
  if (c.context.startsWith('company:')) return `🏢 ${c.title}`;
  return c.title;
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

/** Where the fixed desk panels (requests, n8n, storage, player, meeting) sit on the board: a ring around the middle (the server's x and z). */
export const PANELS = {
  prompts: { x: -760, y: -430, w: 330, title: 'Permintaanmu' },
  n8n: { x: 440, y: -430, w: 330, title: 'Otomasi (n8n)' },
  storage: { x: -165, y: 700, w: 330, title: 'Simpanan' },
  player: { x: -1130, y: 110, w: 330, title: 'Pemutar' },
  meeting: { x: 800, y: 110, w: 330, title: 'Rapat' },
  // ADR-056: one card for every other thing JARVIS shows — a row above and a row below the middle
  video: { x: -1400, y: -1180, w: 480, title: 'Video' },
  image: { x: -860, y: -1180, w: 400, title: 'Gambar' },
  doc: { x: -400, y: -1180, w: 420, title: 'Dokumen' },
  map: { x: 80, y: -1180, w: 440, title: 'Peta' },
  web: { x: -860, y: 1300, w: 380, title: 'Halaman web' },
  text: { x: -420, y: 1300, w: 400, title: 'Catatan' },
  draft: { x: 40, y: 1300, w: 400, title: 'Draf balasan' },
  google: { x: 860, y: -430, w: 340, title: 'Akun Google' },   // ADR-057
};
/** The feature cards (ADR-054/056): what each of them is called on the server's desk poll. */
export const FEATURE_CARDS = ['player', 'video', 'image', 'doc', 'map', 'web', 'text', 'draft', 'meeting', 'google'];

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

// ---------- the 2D board (ADR-055): world ↔ screen, fitting, snapping, alignment, connectors ----------
// view = {cx, cy, k}: the world point at the middle of the viewport, and the scale. vp = {w, h} is the viewport in pixels.
// A rect is {x, y, w, h} in world units (x to the right, y down — the server's x and z).

export const MIN_ZOOM = 0.04, MAX_ZOOM = 4;
export const clampZoom = (k) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, k));
export const toScreen = (v, vp, x, y) => ({ x: (x - v.cx) * v.k + vp.w / 2, y: (y - v.cy) * v.k + vp.h / 2 });
export const toWorld = (v, vp, sx, sy) => ({ x: (sx - vp.w / 2) / v.k + v.cx, y: (sy - vp.h / 2) / v.k + v.cy });

/** Zoom by a factor so the world point under (sx, sy) stays under it — what the wheel and a pinch do. */
export function zoomAt(v, vp, factor, sx, sy) {
  const k = clampZoom(v.k * factor);
  const before = toWorld(v, vp, sx, sy), after = toWorld({ ...v, k }, vp, sx, sy);
  return { k, cx: v.cx + before.x - after.x, cy: v.cy + before.y - after.y };
}

/** Drag the paper by (dx, dy) screen pixels. */
export const panBy = (v, dx, dy) => ({ ...v, cx: v.cx - dx / v.k, cy: v.cy - dy / v.k });

export function rectsBounds(rects) {
  if (!rects.length) return null;
  const x0 = Math.min(...rects.map((r) => r.x)), y0 = Math.min(...rects.map((r) => r.y));
  const x1 = Math.max(...rects.map((r) => r.x + r.w)), y1 = Math.max(...rects.map((r) => r.y + r.h));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

/** The view that shows a rect with room around it; `inset` keeps it clear of floating panels. */
export function fitRect(r, vp, { pad = 72, maxK = 1.25, inset = {} } = {}) {
  const l = inset.left || 0, rt = inset.right || 0, t = inset.top || 0, b = inset.bottom || 0;
  const aw = Math.max(vp.w - l - rt - 2 * pad, 80), ah = Math.max(vp.h - t - b - 2 * pad, 80);
  const k = clampZoom(Math.min(aw / Math.max(r.w, 1), ah / Math.max(r.h, 1), maxK));
  // the middle of the free area, not of the whole viewport
  const mx = l + (vp.w - l - rt) / 2, my = t + (vp.h - t - b) / 2;
  return { k, cx: r.x + r.w / 2 + (vp.w / 2 - mx) / k, cy: r.y + r.h / 2 + (vp.h / 2 - my) / k };
}

/** Mouse wheel (zoom) or trackpad two-finger scroll (pan)? Pinch on a trackpad arrives as a ctrl+wheel (zoom). */
export function wheelIntent(e) {
  if (e.ctrlKey || e.metaKey) return 'zoom';
  if (e.deltaMode === 1) return 'zoom';                          // lines: a notched mouse wheel
  const dy = Math.abs(e.deltaY), dx = Math.abs(e.deltaX);
  if (dx > 0 || (dy > 0 && dy % 1 !== 0)) return 'pan';          // sideways or fractional: a trackpad
  return dy >= 50 ? 'zoom' : 'pan';                              // whole big steps: a mouse wheel
}

export const snapValue = (v, step) => (step > 0 ? Math.round(v / step) * step : v);

export const rectsIntersect = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
export const rectContains = (outer, inner) => inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.w <= outer.x + outer.w && inner.y + inner.h <= outer.y + outer.h;

/**
 * Smart guides: how far (dx, dy) to nudge a moving rect so one of its edges / middle lines meets one of the others', when closer than
 * `tol` world units, and the guide lines to draw. Pure.
 */
export function snapRect(m, others, tol) {
  const xs = [m.x, m.x + m.w / 2, m.x + m.w], ys = [m.y, m.y + m.h / 2, m.y + m.h];
  let bx = null, by = null;
  for (const o of others) {
    const ox = [o.x, o.x + o.w / 2, o.x + o.w], oy = [o.y, o.y + o.h / 2, o.y + o.h];
    for (const a of xs) for (const b of ox) { const d = b - a; if (Math.abs(d) <= tol && (!bx || Math.abs(d) < Math.abs(bx.d))) bx = { d, at: b, o }; }
    for (const a of ys) for (const b of oy) { const d = b - a; if (Math.abs(d) <= tol && (!by || Math.abs(d) < Math.abs(by.d))) by = { d, at: b, o }; }
  }
  const dx = bx ? bx.d : 0, dy = by ? by.d : 0;
  const moved = { x: m.x + dx, y: m.y + dy, w: m.w, h: m.h };
  const guides = [];
  if (bx) guides.push({ axis: 'x', at: bx.at, from: Math.min(moved.y, bx.o.y), to: Math.max(moved.y + moved.h, bx.o.y + bx.o.h) });
  if (by) guides.push({ axis: 'y', at: by.at, from: Math.min(moved.x, by.o.x), to: Math.max(moved.x + moved.w, by.o.x + by.o.w) });
  return { dx, dy, guides };
}

/** Align rects to their group's edge / middle. Returns the same rects with new x / y. Pure. */
export function alignRects(rects, mode) {
  const b = rectsBounds(rects);
  if (!b) return [];
  return rects.map((r) => {
    switch (mode) {
      case 'left': return { ...r, x: b.x };
      case 'hcenter': return { ...r, x: b.x + (b.w - r.w) / 2 };
      case 'right': return { ...r, x: b.x + b.w - r.w };
      case 'top': return { ...r, y: b.y };
      case 'vcenter': return { ...r, y: b.y + (b.h - r.h) / 2 };
      case 'bottom': return { ...r, y: b.y + b.h - r.h };
      default: return r;
    }
  });
}

/** Even gaps between three or more rects along an axis ('h' or 'v'); the outer two stay put. Pure. */
export function distributeRects(rects, axis) {
  if (rects.length < 3) return rects;
  const pos = axis === 'h' ? 'x' : 'y', size = axis === 'h' ? 'w' : 'h';
  const order = [...rects].sort((a, b) => a[pos] - b[pos]);
  const first = order[0], last = order[order.length - 1];
  const gap = (last[pos] + last[size] - first[pos] - order.reduce((s, r) => s + r[size], 0)) / (order.length - 1);
  let at = first[pos];
  const placed = new Map();
  for (const r of order) { placed.set(r, { ...r, [pos]: at }); at += r[size] + gap; }
  return rects.map((r) => placed.get(r));
}

/** Drag a handle ('n','ne','e','se','s','sw','w','nw') by (dx, dy) world units. `ratio` keeps the shape; `center` grows from the middle. */
export function resizeRect(r, handle, dx, dy, { min = [60, 40], ratio = false, center = false } = {}) {
  let { x, y, w, h } = r;
  const east = handle.includes('e'), west = handle.includes('w'), south = handle.includes('s'), north = handle.includes('n');
  const f = center ? 2 : 1;
  if (east) w += dx * f; if (west) w -= dx * f;
  if (south) h += dy * f; if (north) h -= dy * f;
  if (ratio && r.w > 0 && r.h > 0) {
    const k = (east || west) && (north || south) ? Math.max(w / r.w, h / r.h) : (east || west) ? w / r.w : h / r.h;
    w = r.w * k; h = r.h * k;
  }
  w = Math.max(w, min[0]); h = Math.max(h, min[1]);
  x = center ? r.x + (r.w - w) / 2 : west ? r.x + r.w - w : r.x;
  y = center ? r.y + (r.h - h) / 2 : north ? r.y + r.h - h : r.y;
  return { x, y, w, h };
}

const SIDES = { e: [1, 0], w: [-1, 0], s: [0, 1], n: [0, -1] };
export function sidePoint(r, side) {
  return side === 'e' ? { x: r.x + r.w, y: r.y + r.h / 2 } : side === 'w' ? { x: r.x, y: r.y + r.h / 2 }
    : side === 's' ? { x: r.x + r.w / 2, y: r.y + r.h } : { x: r.x + r.w / 2, y: r.y };
}

/** The curve from card a to card b (rects), leaving and entering through the sides that face each other. */
export function connectorPath(a, b) {
  const ac = { x: a.x + a.w / 2, y: a.y + a.h / 2 }, bc = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
  const dx = bc.x - ac.x, dy = bc.y - ac.y;
  const horizontal = Math.abs(dx) * (a.h + b.h) >= Math.abs(dy) * (a.w + b.w);
  const sa = horizontal ? (dx >= 0 ? 'e' : 'w') : (dy >= 0 ? 's' : 'n');
  const sb = horizontal ? (dx >= 0 ? 'w' : 'e') : (dy >= 0 ? 'n' : 's');
  const p = sidePoint(a, sa), q = sidePoint(b, sb);
  const pull = Math.max(40, Math.hypot(q.x - p.x, q.y - p.y) * 0.4);
  const c1 = { x: p.x + SIDES[sa][0] * pull, y: p.y + SIDES[sa][1] * pull }, c2 = { x: q.x + SIDES[sb][0] * pull, y: q.y + SIDES[sb][1] * pull };
  const t = 0.5, u = 1 - t;
  const mid = { x: u ** 3 * p.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t ** 3 * q.x, y: u ** 3 * p.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t ** 3 * q.y };
  return {
    d: `M ${p.x} ${p.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${q.x} ${q.y}`, from: p, to: q, mid,
    startAngle: Math.atan2(p.y - c1.y, p.x - c1.x), endAngle: Math.atan2(q.y - c2.y, q.x - c2.x),   // the direction an arrow at each end points
  };
}

/** The minimap: world bounds → a box of `size` pixels, and back. */
export function miniMapFit(bounds, size, pad = 200) {
  const w = bounds.w + 2 * pad, h = bounds.h + 2 * pad;
  const s = Math.min(size.w / w, size.h / h);
  return { s, ox: (size.w - w * s) / 2 - (bounds.x - pad) * s, oy: (size.h - h * s) / 2 - (bounds.y - pad) * s };
}
