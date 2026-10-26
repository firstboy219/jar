// Catatan & Tugas (ADR-060): the pure parts of the editor and the task lists — tested with node (tests/notes.test.mjs).

export const BLOCK_TYPES = {
  p: { label: 'Teks', icon: '¶', hint: 'Paragraf biasa' },
  h1: { label: 'Judul 1', icon: 'H1', hint: 'Judul besar', md: '#' },
  h2: { label: 'Judul 2', icon: 'H2', hint: 'Judul bagian', md: '##' },
  h3: { label: 'Judul 3', icon: 'H3', hint: 'Sub-bagian', md: '###' },
  todo: { label: 'Tugas', icon: '☑', hint: 'Kotak centang, tenggat, prioritas', md: '[]' },
  bullet: { label: 'Daftar poin', icon: '•', hint: 'Daftar tanpa nomor', md: '-' },
  number: { label: 'Daftar bernomor', icon: '1.', hint: 'Daftar berurutan', md: '1.' },
  toggle: { label: 'Lipat', icon: '▸', hint: 'Sembunyikan isi di bawahnya (yang menjorok)', md: '>>' },
  quote: { label: 'Kutipan', icon: '❝', hint: 'Kutipan / sorotan', md: '>' },
  callout: { label: 'Callout', icon: '💡', hint: 'Kotak penting dengan ikon', md: '!' },
  code: { label: 'Kode', icon: '</>', hint: 'Blok kode', md: '```' },
  divider: { label: 'Garis pemisah', icon: '—', hint: 'Garis horizontal', md: '---' },
};
export const LIST_TYPES = new Set(['bullet', 'number', 'todo']);

/** What typing "<prefix><space>" at the start of a block turns it into (the Notion/Markdown shortcuts). */
export function shortcutFor(text) {
  const m = /^(#{1,3}|[-*+]|1[.)]|\[\s?\]|\[[xX]\]|>>|>|!|```|---)\s(.*)$/s.exec(text || '');
  if (!m) return null;
  const k = m[1], rest = m[2];
  if (k === '#') return { type: 'h1', rest };
  if (k === '##') return { type: 'h2', rest };
  if (k === '###') return { type: 'h3', rest };
  if (/^[-*+]$/.test(k)) return { type: 'bullet', rest };
  if (/^1[.)]$/.test(k)) return { type: 'number', rest };
  if (/^\[\s?\]$/.test(k)) return { type: 'todo', rest, checked: false };
  if (/^\[[xX]\]$/.test(k)) return { type: 'todo', rest, checked: true };
  if (k === '>>') return { type: 'toggle', rest };
  if (k === '>') return { type: 'quote', rest };
  if (k === '!') return { type: 'callout', rest };
  if (k === '```') return { type: 'code', rest };
  if (k === '---') return { type: 'divider', rest: '' };
  return null;
}

/** The "/" menu: block types whose name, hint or markdown matches what was typed after the slash. */
export function filterSlash(q) {
  const s = String(q || '').trim().toLowerCase();
  return Object.entries(BLOCK_TYPES)
    .filter(([k, v]) => !s || k.startsWith(s) || v.label.toLowerCase().includes(s) || v.hint.toLowerCase().includes(s))
    .map(([type, v]) => ({ type, ...v }));
}

/** The number a numbered-list block shows: counts up through consecutive numbered blocks at the same indent. */
export function numberOf(blocks, i) {
  const ind = blocks[i].indent || 0;
  let n = 1;
  for (let j = i - 1; j >= 0; j--) {
    const b = blocks[j], bi = b.indent || 0;
    if (bi > ind) continue;                     // a nested block does not break the count
    if (bi < ind || b.type !== 'number') break;
    n++;
  }
  return n;
}

/** Indexes hidden by a closed toggle: everything after it that is indented deeper, up to the next block at its level. */
export function hiddenByToggles(blocks) {
  const hidden = new Set();
  blocks.forEach((b, i) => {
    if (b.type !== 'toggle' || b.open || hidden.has(i)) return;
    const ind = b.indent || 0;
    for (let j = i + 1; j < blocks.length && (blocks[j].indent || 0) > ind; j++) hidden.add(j);
  });
  return hidden;
}

/** A date as people say it, relative to today ("Hari ini", "Besok", "3 hari lagi", "Kemarin", "Sen, 3 Nov"). */
export function dueLabel(due, today = new Date()) {
  if (!due) return '';
  const d = new Date(`${due}T00:00:00`), t = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((d - t) / 86400000);
  if (days === 0) return 'Hari ini';
  if (days === 1) return 'Besok';
  if (days === -1) return 'Kemarin';
  if (days > 1 && days <= 6) return `${days} hari lagi`;
  if (days < -1 && days >= -6) return `${-days} hari lalu`;
  const wd = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'][d.getDay()];
  const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'][d.getMonth()];
  return `${wd}, ${d.getDate()} ${mo}${d.getFullYear() !== t.getFullYear() ? ` ${d.getFullYear()}` : ''}`;
}

export const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** The task list in groups, the way a planner shows it: overdue, today, tomorrow, this week, later, no date, done. */
export function groupTasks(tasks, today = new Date()) {
  const t0 = isoDay(today), t1 = isoDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1));
  const t7 = isoDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 7));
  const groups = [['overdue', 'Terlambat'], ['today', 'Hari ini'], ['tomorrow', 'Besok'], ['week', '7 hari ke depan'], ['later', 'Nanti'],
    ['nodate', 'Tanpa tanggal'], ['done', 'Selesai']].map(([key, label]) => ({ key, label, items: [] }));
  const by = Object.fromEntries(groups.map((g) => [g.key, g]));
  for (const x of tasks) {
    const key = x.checked ? 'done' : !x.due ? 'nodate' : x.due < t0 ? 'overdue' : x.due === t0 ? 'today' : x.due === t1 ? 'tomorrow' : x.due <= t7 ? 'week' : 'later';
    by[key].items.push(x);
  }
  for (const g of groups) g.items.sort((a, b) => (a.due || '9999').localeCompare(b.due || '9999') || (b.priority || 0) - (a.priority || 0));
  return groups.filter((g) => g.items.length);
}

/** Pasted text → blocks: one per line, Markdown prefixes understood, fenced code kept together. */
export function parseLines(text) {
  const out = [];
  let code = null;
  for (const raw of String(text || '').replace(/\r\n?/g, '\n').split('\n')) {
    if (code) {
      if (/^```\s*$/.test(raw)) { out.push({ type: 'code', text: code.join('\n') }); code = null; } else code.push(raw);
      continue;
    }
    if (/^```/.test(raw)) { code = []; continue; }
    if (!raw.trim()) continue;
    const indent = Math.min(4, Math.floor((/^\s*/.exec(raw)[0].replace(/\t/g, '  ').length) / 2));
    const line = raw.trim();
    const s = /^\d+[.)]\s/.test(line) ? { type: 'number', rest: line.replace(/^\d+[.)]\s/, '') } : shortcutFor(line);
    const b = s ? { type: s.type, text: s.rest, ...(s.checked ? { checked: true } : {}) } : { type: 'p', text: line };
    if (indent) b.indent = indent;
    out.push(b);
  }
  if (code) out.push({ type: 'code', text: code.join('\n') });
  return out;
}

/** "Rapat: Anggaran" → the page's label in lists, with a fallback for an untitled page. */
export const pageLabel = (p) => (p?.title || '').trim() || 'Tanpa judul';

/** The priority flag cycles none → 1 → 2 → 3 → none. */
export const nextPriority = (p) => ((p || 0) + 1) % 4;
export const PRIORITY = { 1: { label: 'Rendah', cls: 'p1' }, 2: { label: 'Sedang', cls: 'p2' }, 3: { label: 'Tinggi', cls: 'p3' } };

/** Page tree: children under their parent, in the order given; orphans (parent archived/missing) at the top level. */
export function pageTree(pages) {
  const ids = new Set(pages.map((p) => p.id));
  const kids = new Map();
  for (const p of pages) {
    const key = p.parent_id && ids.has(p.parent_id) ? p.parent_id : '';
    if (!kids.has(key)) kids.set(key, []);
    kids.get(key).push(p);
  }
  const walk = (key, depth) => (kids.get(key) || []).flatMap((p) => [{ page: p, depth }, ...walk(p.id, depth + 1)]);
  return walk('', 0);
}
