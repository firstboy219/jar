// The app's pure helpers (ADR-087) — no DOM, no network; tested with node (tests/lib.test.mjs).

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

// html`…${x}…` escapes every value unless it is raw(…) (already-safe markup) or an array of those.
export class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(String(s ?? ''));
export function html(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => {
    if (Array.isArray(v)) out += v.map((x) => (x instanceof Raw ? x.s : esc(x))).join('');
    else out += v instanceof Raw ? v.s : (v === false || v == null ? '' : esc(v));
    out += strings[i + 1];
  });
  return raw(out);
}

/** Rupiah as the owner reads it: Rp18.900 · short: 18,9 jt · 410 rb. */
export function rupiah(n, short = false) {
  const v = Number(n) || 0;
  const neg = v < 0 ? '−' : '';
  const a = Math.abs(v);
  if (short) {
    if (a >= 1e9) return `${neg}${(a / 1e9).toFixed(a >= 1e10 ? 0 : 1).replace('.', ',')} M`;
    if (a >= 1e6) return `${neg}${(a / 1e6).toFixed(a >= 1e8 ? 0 : 1).replace('.', ',').replace(',0', '')} jt`;
    if (a >= 1e3) return `${neg}${Math.round(a / 1e3)} rb`;
    return `${neg}${Math.round(a)}`;
  }
  return `${neg}Rp${Math.round(a).toLocaleString('id-ID').replace(/,/g, '.')}`;
}

export const usd = (n) => `$${(Number(n) || 0).toFixed(Number(n) >= 1 ? 2 : 3).replace('.', ',')}`;

/** "08.12" in WIB (the owner's clock). */
export function clock(d) {
  const t = d instanceof Date ? d : new Date(d);
  if (Number.isNaN(t.getTime())) return '';
  const w = new Date(t.getTime() + (7 * 60 + t.getTimezoneOffset()) * 60000);
  return `${String(w.getHours()).padStart(2, '0')}.${String(w.getMinutes()).padStart(2, '0')}`;
}

/** "baru saja", "5 mnt lalu", "2 jam lalu", "kemarin", "3 hari lalu". */
export function ago(d, now = new Date()) {
  const s = Math.round((now - (d instanceof Date ? d : new Date(d))) / 1000);
  if (Number.isNaN(s)) return '';
  if (s < 45) return 'baru saja';
  if (s < 3600) return `${Math.round(s / 60)} mnt lalu`;
  if (s < 86400) return `${Math.round(s / 3600)} jam lalu`;
  if (s < 172800) return 'kemarin';
  return `${Math.round(s / 86400)} hari lalu`;
}

/** "2 mnt 41 dtk", "1 j 5 m", "38 dtk". */
export function dur(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `${s} dtk`;
  if (s < 3600) return `${Math.floor(s / 60)} mnt${s % 60 ? ` ${s % 60} dtk` : ''}`;
  return `${Math.floor(s / 3600)} j ${Math.floor((s % 3600) / 60)} m`;
}

/** '#/misi/12?tab=log' → {name: 'misi', params: ['12'], query: {tab: 'log'}}; empty → beranda. */
export function parseRoute(hash) {
  const h = String(hash || '').replace(/^#\/?/, '');
  const [path, qs = ''] = h.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  const query = {};
  for (const kv of qs.split('&').filter(Boolean)) {
    const [k, v = ''] = kv.split('=');
    query[decodeURIComponent(k)] = decodeURIComponent(v);
  }
  return { name: parts[0] || 'beranda', params: parts.slice(1), query };
}

export const TONES = ['cyan', 'amber', 'green', 'violet', 'red', 'ice', 'muted'];
export const tone = (t) => (TONES.includes(t) ? t : 'cyan');

export const LANE_LABEL = { skill: 'skill tanpa AI', ringan: 'otak ringan', berat: 'otak berat', hermes: 'Hermes + alat', openjarvis: 'otak berat' };
export const LANE_TONE = { skill: 'green', ringan: 'cyan', berat: 'violet', hermes: 'amber', openjarvis: 'violet' };

/** A percentage 0–100 for a bar, never NaN. */
export const pct = (part, whole) => (whole > 0 ? Math.max(0, Math.min(100, Math.round((100 * part) / whole))) : 0);

/** The token handed over by the app in the fragment (#t=…&app=1), and the rest of the fragment to keep. */
export function takeToken(hash) {
  const bits = String(hash || '').replace(/^#/, '').split('&');
  const t = bits.find((b) => b.startsWith('t='));
  const embedded = bits.includes('app=1');
  const rest = bits.filter((b) => !b.startsWith('t=') && b !== 'app=1').join('&');
  return { token: t ? decodeURIComponent(t.slice(2)) : '', embedded, rest };
}

/** Group a list by a key, keeping the order keys first appear in. */
export function groupBy(list, key) {
  const out = new Map();
  for (const x of list) {
    const k = typeof key === 'function' ? key(x) : x[key];
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(x);
  }
  return out;
}
