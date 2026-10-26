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
  prompts: { x: -760, y: 140, z: -430, size: 1.9, title: 'Permintaanmu' },
  n8n: { x: 760, y: 140, z: -430, size: 1.9, title: 'Otomasi (n8n)' },
  storage: { x: 0, y: 140, z: 880, size: 1.9, title: 'Simpanan' },
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
