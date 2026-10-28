// A worker's result as blocks the desk can draw (ADR-075): the pure parts — markdown text → blocks, inline spans, Indonesian numbers,
// chart geometry — tested with node (tests/results.test.mjs). resultview.js turns them into DOM.

/** "https://…" only: anything else (javascript:, data:) is never put in a link or an image. */
export const safeUrl = (u) => (/^https?:\/\/[^\s<>"']+$/i.test(String(u || '').trim()) ? String(u).trim() : null);

/** Text → inline spans: **bold**, *italic*, `code`, [label](url) and bare https links. */
export function inline(text) {
  const out = [];
  const re = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>)"']+)|(?<![*\w])\*([^*\s][^*]*?)\*(?!\*)/g;
  let last = 0, m;
  const s = String(text || '');
  while ((m = re.exec(s))) {
    if (m.index > last) out.push({ t: 'text', text: s.slice(last, m.index) });
    if (m[1] != null) out.push({ t: 'b', text: m[1] });
    else if (m[2] != null) out.push({ t: 'code', text: m[2] });
    else if (m[3] != null) out.push({ t: 'link', text: m[3], url: m[4] });
    else if (m[5] != null) out.push({ t: 'link', text: m[5].replace(/[.,;:!?]+$/, ''), url: m[5].replace(/[.,;:!?]+$/, '') });
    else out.push({ t: 'i', text: m[6] });
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push({ t: 'text', text: s.slice(last) });
  return out;
}

const cells = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
const isSep = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line) && line.includes('-');

/** Markdown → blocks: heading, para, list, table, image, code, quote. Tables need a header and a --- line; images may stand alone on a line. */
export function parseMarkdown(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let para = [];
  const flush = () => { if (para.length) { out.push({ type: 'para', text: para.join(' ') }); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i], t = line.trim();
    if (!t) { flush(); continue; }
    if (/^```/.test(t)) {
      flush();
      const code = [];
      for (i++; i < lines.length && !/^```/.test(lines[i].trim()); i++) code.push(lines[i]);
      out.push({ type: 'code', text: code.join('\n') });
      continue;
    }
    const h = /^(#{1,4})\s+(.+)$/.exec(t);
    if (h) { flush(); out.push({ type: 'heading', level: h[1].length, text: h[2].replace(/\s*#+$/, '') }); continue; }
    if (t.includes('|') && i + 1 < lines.length && isSep(lines[i + 1]) && !isSep(line)) {
      flush();
      const head = cells(t), rows = [];
      for (i += 2; i < lines.length && lines[i].trim() && lines[i].includes('|'); i++) rows.push((cells(lines[i]).concat(head.map(() => ''))).slice(0, head.length));
      i--;
      out.push({ type: 'table', title: '', head, rows });
      continue;
    }
    const img = /^!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)$/.exec(t);
    if (img) { flush(); out.push({ type: 'image', alt: img[1], url: img[2] }); continue; }
    const li = /^([-*•]|\d+[.)])\s+(.*)$/.exec(t);
    if (li) {
      flush();
      const ordered = /\d/.test(li[1]), items = [li[2]];
      while (i + 1 < lines.length) {
        const nx = /^\s*([-*•]|\d+[.)])\s+(.*)$/.exec(lines[i + 1]);
        if (!nx || /\d/.test(nx[1]) !== ordered) break;
        items.push(nx[2]); i++;
      }
      out.push({ type: 'list', ordered, items });
      continue;
    }
    if (/^>\s?/.test(t)) { flush(); out.push({ type: 'quote', text: t.replace(/^>\s?/, '') }); continue; }
    if (/^(---+|\*\*\*+)$/.test(t)) { flush(); continue; }
    para.push(t);
  }
  flush();
  return out;
}

/** The structured result (results.py) + the rest of its text → blocks in reading order: summary, points, tables, charts, images, links, notes. */
export function blocksOf(doc, text) {
  const d = doc || {}, out = [];
  if (d.ringkasan) out.push({ type: 'summary', text: d.ringkasan });
  if (d.poin?.length) out.push({ type: 'list', ordered: false, items: d.poin });
  if (d.pilihan?.length) out.push({ type: 'list', ordered: true, items: d.pilihan.map((o) => `${o.label}${o.waktu ? ` (jam ${o.waktu})` : ''}${o.detail ? ` — ${o.detail}` : ''}`) });
  for (const t of d.tabel || []) out.push({ type: 'table', title: t.judul || '', head: t.kolom, rows: t.baris });
  for (const g of d.grafik || []) out.push({ type: 'chart', title: g.judul || '', kind: g.jenis || 'bar', labels: g.label, values: g.nilai, unit: g.satuan || '' });
  for (const i of d.gambar || []) if (safeUrl(i.url)) out.push({ type: 'image', alt: i.keterangan || '', url: i.url });
  if (d.tautan?.length) out.push({ type: 'links', items: d.tautan.filter((l) => safeUrl(l.url)) });
  const rest = parseMarkdown(text);
  if (rest.length) out.push({ type: 'notes', blocks: rest, collapsed: out.length > 0 });
  return out;
}

/** "Rp1.900.000" → 1900000, "25 jt" → 25, "1,5" → 1.5, "12%" → 12, "-3" → -3; anything else → null. */
export function parseNumber(s) {
  let t = String(s ?? '').trim();
  if (!t || /[a-zA-Z]{4,}/.test(t.replace(/rp|idr|usd/gi, ''))) return null;
  t = t.replace(/^(rp\.?|idr|usd|\$)\s*/i, '').replace(/\s*(%|jt|juta|rb|ribu|k|m|miliar|x|menit|jam|hari|km)\.?$/i, '').replace(/\s+/g, '');
  if (!/^-?[\d.,]+$/.test(t) || !/\d/.test(t)) return null;
  const neg = t.startsWith('-');
  t = t.replace(/^-/, '');
  const dots = (t.match(/\./g) || []).length, commas = (t.match(/,/g) || []).length;
  let n;
  if (dots && commas) { const dec = t.lastIndexOf('.') > t.lastIndexOf(',') ? '.' : ','; n = t.split(dec === '.' ? ',' : '.').join('').replace(dec, '.'); }
  else if (dots) n = dots > 1 || /^\d{1,3}\.\d{3}$/.test(t) ? t.replace(/\./g, '') : t;
  else if (commas) n = commas > 1 ? t.replace(/,/g, '') : t.replace(',', '.');
  else n = t;
  const v = Number(n);
  return Number.isFinite(v) ? (neg ? -v : v) : null;
}

/** Columns of a table that are numbers in at least 60% of the rows, with at least 2 rows: they can be drawn as a chart. */
export function numericColumns(table) {
  const out = [];
  if (!table || (table.rows || []).length < 2) return out;
  table.head.forEach((name, c) => {
    const vals = table.rows.map((r) => parseNumber(r[c]));
    if ((c > 0 || table.head.length === 1) && vals.filter((v) => v != null).length / vals.length >= 0.6) out.push({ col: c, name });
  });
  return out;
}

/** A chart of one numeric column of a table, labelled by its first column (rows without a number are left out). */
export function chartOf(table, col, kind = 'bar') {
  const pts = table.rows.map((r) => [String(r[0] ?? ''), parseNumber(r[col])]).filter(([, v]) => v != null).slice(0, 40);
  return { type: 'chart', title: `${table.head[col]}${table.title ? ` — ${table.title}` : ''}`, kind, labels: pts.map((p) => p[0]), values: pts.map((p) => p[1]), unit: '' };
}

/** A readable number in Indonesian format: 1234567 → "1.234.567", 2.5 → "2,5". */
export const fmtNum = (v) => new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 }).format(v);

/** A "nice" axis maximum ≥ v (1, 2, 5 × 10ⁿ) and its ticks. */
export function niceScale(max, ticks = 4) {
  if (!(max > 0)) return { max: 1, ticks: [0, 1] };
  const exp = 10 ** Math.floor(Math.log10(max)), f = max / exp;
  const top = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * exp;
  const step = top / ticks;
  return { max: top, ticks: Array.from({ length: ticks + 1 }, (_, i) => +(i * step).toPrecision(12)) };
}

/** Bars: x, y, width, height of each value inside a w×h plot (negative values hang below the zero line). */
export function barLayout(values, w, h) {
  const lo = Math.min(0, ...values), hi = Math.max(0, ...values);
  const span = niceScale(Math.max(hi, -lo)).max;
  const top = hi > 0 ? span : 0, bottom = lo < 0 ? -span : 0, range = top - bottom || 1;
  const zero = h * (top / range), slot = w / values.length, bw = Math.min(slot * 0.7, 80);
  return { zero, scale: niceScale(Math.max(hi, -lo)), top, bottom,
    bars: values.map((v, i) => { const bh = Math.abs(v) / range * h; return { x: slot * i + (slot - bw) / 2, y: v >= 0 ? zero - bh : zero, w: bw, h: bh }; }) };
}

/** Line: the polyline points of each value in a w×h plot. */
export function lineLayout(values, w, h) {
  const lo = Math.min(0, ...values), hi = Math.max(0, ...values), top = hi > 0 ? niceScale(hi).max : 0, range = top - lo || 1;
  return { scale: niceScale(hi), low: lo, points: values.map((v, i) => [values.length === 1 ? w / 2 : (w * i) / (values.length - 1), h - ((v - lo) / range) * h]) };
}

/** Pie: start/end angle (radians from 12 o'clock) and share of every positive value. */
export function pieSlices(values) {
  const pos = values.map((v) => Math.max(0, v)), total = pos.reduce((a, b) => a + b, 0) || 1;
  let a = 0;
  return pos.map((v) => { const share = v / total, s = a; a += share * Math.PI * 2; return { start: s, end: a, share }; });
}

export const PALETTE = ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f87171', '#fb923c', '#2dd4bf', '#e879f9', '#a3e635', '#94a3b8'];

/** ADR-078: the project report's chart — workers finished per run, oldest run first (pure; unit-tested). */
export function reportChart(history) {
  const h = [...(history || [])].sort((a, b) => a.run - b.run).slice(-20);
  return { type: 'chart', title: 'Pekerja selesai per run', kind: h.length > 8 ? 'line' : 'bar', labels: h.map((x) => `#${x.run}`), values: h.map((x) => x.completed), unit: '' };
}

/** How a run went, in a word: berjalan / berhasil / sebagian / gagal (pure; unit-tested). */
export function runVerdict(r) {
  if (r.busy) return { text: 'berjalan', cls: 'running' };
  if (r.failed && !r.completed) return { text: 'gagal', cls: 'failed' };
  if (r.failed) return { text: 'sebagian', cls: 'partial' };
  return { text: 'berhasil', cls: 'completed' };
}
