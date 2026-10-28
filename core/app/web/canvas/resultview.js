// The result of a project run, opened full screen (ADR-075): each worker's summary, points, tables (a numeric column can be drawn as a chart),
// charts, pictures, links and documents — and the plain text behind them. Nothing from a worker is ever put in as HTML.
import { PALETTE, barLayout, blocksOf, chartOf, fmtNum, inline, lineLayout, numericColumns, pieSlices, reportChart, runVerdict, safeUrl } from './resultmd.js';

const SVG = 'http://www.w3.org/2000/svg';
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const svg = (tag, attrs = {}, text) => { const e = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v)); if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn, title) => { const b = el('button', cls, text); b.type = 'button'; b.dataset.gesture = 'ok'; if (title) b.title = title; b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(ev); }); return b; };
const STATUS = { queued: 'antre', running: 'bekerja', completed: 'selesai', failed: 'gagal', stopped: 'dihentikan', cancelled: 'dibatalkan' };

export function spans(text) {
  const frag = document.createDocumentFragment();
  for (const s of inline(text)) {
    if (s.t === 'text') frag.append(s.text);
    else if (s.t === 'link') { const a = el('a', null, s.text); a.href = safeUrl(s.url) || '#'; a.target = '_blank'; a.rel = 'noopener noreferrer'; frag.append(a); }
    else frag.append(el(s.t === 'b' ? 'strong' : s.t === 'i' ? 'em' : 'code', null, s.text));
  }
  return frag;
}

const shortLabel = (s, n = 10) => (String(s).length > n ? `${String(s).slice(0, n - 1)}…` : String(s));

/** A bar, line or pie chart as an inline SVG (no library). */
export function chartSvg(c) {
  const W = 560, H = 260, L = 52, R = 12, T = 12, B = 54, w = W - L - R, h = H - T - B;
  const root = svg('svg', { viewBox: `0 0 ${W} ${c.kind === 'pie' ? 240 : H}`, class: 'rvchart', role: 'img', 'aria-label': c.title || 'grafik' });
  const unit = c.unit ? ` ${c.unit}` : '';
  if (c.kind === 'pie') {
    const cx = 110, cy = 120, r = 95;
    pieSlices(c.values).forEach((s, i) => {
      if (s.share <= 0) return;
      const p = (a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
      const [x1, y1] = p(s.start), [x2, y2] = p(Math.min(s.end, s.start + Math.PI * 2 - 1e-4));
      const path = svg('path', { d: `M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${s.end - s.start > Math.PI ? 1 : 0} 1 ${x2},${y2} Z`, fill: PALETTE[i % PALETTE.length], stroke: '#0b1224', 'stroke-width': 1.5 });
      path.append(svg('title', {}, `${c.labels[i]}: ${fmtNum(c.values[i])}${unit} (${Math.round(s.share * 100)}%)`));
      root.append(path);
    });
    c.labels.slice(0, 10).forEach((lb, i) => {
      root.append(svg('rect', { x: 230, y: 18 + i * 21, width: 12, height: 12, rx: 3, fill: PALETTE[i % PALETTE.length] }));
      root.append(svg('text', { x: 250, y: 28 + i * 21, class: 'rvtxt' }, `${shortLabel(lb, 22)} · ${fmtNum(c.values[i])}${unit}`));
    });
    return root;
  }
  const g = svg('g', { transform: `translate(${L},${T})` });
  const lay = c.kind === 'line' ? lineLayout(c.values, w, h) : barLayout(c.values, w, h);
  const top = c.kind === 'line' ? lay.scale.max : lay.top, low = c.kind === 'line' ? lay.low : lay.bottom, range = (top - low) || 1;
  for (const t of lay.scale.ticks) {
    const y = h - ((t - low) / range) * h;
    if (y < -1 || y > h + 1) continue;
    g.append(svg('line', { x1: 0, x2: w, y1: y, y2: y, class: 'rvgrid' }), svg('text', { x: -6, y: y + 4, class: 'rvtxt rvr' }, fmtNum(t)));
  }
  const slot = w / c.values.length;
  if (c.kind === 'line') {
    g.append(svg('polyline', { points: lay.points.map((q) => q.join(',')).join(' '), fill: 'none', stroke: PALETTE[0], 'stroke-width': 2.5, 'stroke-linejoin': 'round' }));
    lay.points.forEach(([x, y], i) => { const d = svg('circle', { cx: x, cy: y, r: 4, fill: PALETTE[0] }); d.append(svg('title', {}, `${c.labels[i]}: ${fmtNum(c.values[i])}${unit}`)); g.append(d); });
  } else {
    lay.bars.forEach((b, i) => {
      const r = svg('rect', { x: b.x, y: b.y, width: b.w, height: Math.max(1, b.h), rx: 3, fill: PALETTE[i % PALETTE.length] });
      r.append(svg('title', {}, `${c.labels[i]}: ${fmtNum(c.values[i])}${unit}`)); g.append(r);
      if (c.values.length <= 12) g.append(svg('text', { x: b.x + b.w / 2, y: Math.max(10, b.y - 4), class: 'rvtxt rvc' }, fmtNum(c.values[i])));
    });
  }
  const every = Math.ceil(c.labels.length / 12);
  c.labels.forEach((lb, i) => {
    if (i % every) return;
    const x = c.kind === 'line' && c.values.length > 1 ? (w * i) / (c.values.length - 1) : slot * i + slot / 2;
    g.append(svg('text', { x, y: h + 16, class: 'rvtxt rvc', transform: c.labels.length > 6 ? `rotate(28 ${x} ${h + 16})` : '' }, shortLabel(lb, c.labels.length > 6 ? 12 : 16)));
  });
  root.append(g);
  return root;
}

function tableEl(t, onChart) {
  const wrap = el('div', 'rvtable');
  if (t.title) wrap.append(el('div', 'rvtitle', t.title));
  const scroll = el('div', 'rvscroll'), tb = el('table');
  const hr = el('tr'); t.head.forEach((h) => hr.append(el('th', null, h)));
  tb.append(el('thead')); tb.firstChild.append(hr);
  const body = el('tbody');
  for (const r of t.rows) {
    const tr = el('tr');
    r.forEach((c) => { const td = el('td'); td.append(spans(c)); tr.append(td); });
    body.append(tr);
  }
  tb.append(body); scroll.append(tb); wrap.append(scroll);
  const nums = numericColumns(t);
  if (nums.length && onChart) {
    const bar = el('div', 'rvtools');
    bar.append(el('span', 'muted', 'Gambar sebagai grafik:'));
    for (const n of nums.slice(0, 4)) bar.append(button(`📊 ${n.name}`, 'pbtn', () => onChart(chartOf(t, n.col))));
    wrap.append(bar);
  }
  return wrap;
}

function render(blocks, host) {
  for (const b of blocks) {
    if (b.type === 'summary') host.append(el('div', 'rvsummary', b.text));
    else if (b.type === 'heading') host.append(el(`h${Math.min(4, b.level + 2)}`, 'rvh', b.text));
    else if (b.type === 'para') { const p = el('p', 'rvp'); p.append(spans(b.text)); host.append(p); }
    else if (b.type === 'quote') { const q = el('blockquote', 'rvp'); q.append(spans(b.text)); host.append(q); }
    else if (b.type === 'code') host.append(el('pre', 'rvcode', b.text));
    else if (b.type === 'list') {
      const l = el(b.ordered ? 'ol' : 'ul', 'rvlist');
      for (const it of b.items) { const li = el('li'); li.append(spans(it)); l.append(li); }
      host.append(l);
    } else if (b.type === 'table') {
      const slot = el('div'), t = tableEl(b, (chart) => { slot.replaceChildren(chartBox(chart, () => slot.replaceChildren())); });
      host.append(t, slot);
    } else if (b.type === 'chart') host.append(chartBox(b));
    else if (b.type === 'image') {
      const f = el('figure', 'rvfig'), img = el('img'); img.src = safeUrl(b.url) || ''; img.alt = b.alt || ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer';
      img.addEventListener('click', () => window.open(b.url, '_blank', 'noopener'));
      img.addEventListener('error', () => { f.replaceChildren(el('div', 'muted', `Gambar tidak bisa dimuat: ${b.url}`)); });
      f.append(img); if (b.alt) f.append(el('figcaption', null, b.alt));
      host.append(f);
    } else if (b.type === 'links') {
      const l = el('div', 'rvlinks');
      for (const it of b.items) { const a = el('a', 'chip', `🔗 ${it.teks}`); a.href = safeUrl(it.url) || '#'; a.target = '_blank'; a.rel = 'noopener noreferrer'; l.append(a); }
      host.append(l);
    } else if (b.type === 'notes') {
      const d = el('details', 'rvnotes'); d.open = !b.collapsed;
      d.append(el('summary', null, 'Catatan lengkap pekerja'));
      render(b.blocks, d);
      host.append(d);
    }
  }
}

function chartBox(c, onClose) {
  const box = el('div', 'rvchartbox');
  const head = el('div', 'rvtitle', c.title || 'Grafik');
  const kinds = el('span', 'rvkinds');
  const draw = (kind) => { c.kind = kind; box.querySelector('svg')?.remove(); box.append(chartSvg(c)); for (const b of kinds.children) b.classList.toggle('on', b.dataset.kind === kind); };
  for (const [k, t] of [['bar', 'Batang'], ['line', 'Garis'], ['pie', 'Pai']]) { const b = button(t, 'pbtn', () => draw(k)); b.dataset.kind = k; kinds.append(b); }
  head.append(kinds);
  if (onClose) head.append(button('✕', 'pbtn', onClose, 'Tutup grafik'));
  box.append(head);
  draw(c.kind);
  return box;
}

const when = (t) => (t ? new Date(t).toLocaleString('id-ID', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—');

/** ADR-078: the project's report over all its runs — numbers, a chart, and the run history (tap a run to open its results). */
function reportBox(d, onRun) {
  const r = d.report || {}, box = el('details', 'rvreport');
  box.open = true;
  box.append(el('summary', null, `📊 Laporan proyek · ${r.runs || 0} run`));
  const stats = el('div', 'rvstats');
  const stat = (v, label, cls = '') => { const s = el('div', `rvstat ${cls}`); s.append(el('b', null, v), el('span', null, label)); stats.append(s); };
  stat(String(r.runs || 0), 'run');
  stat(r.success_pct == null ? '—' : `${r.success_pct}%`, 'tingkat berhasil', r.success_pct >= 80 ? 'good' : r.success_pct != null && r.success_pct < 50 ? 'bad' : '');
  stat(`${r.completed || 0}/${r.workers || 0}`, 'pekerja selesai');
  stat(String(r.failed || 0), 'gagal', r.failed ? 'bad' : '');
  stat(r.median_minutes == null ? '—' : `${fmtNum(r.median_minutes)} mnt`, 'lama run (median)');
  stat(`$${fmtNum(r.cost_usd || 0)}`, 'biaya AI');
  box.append(stats);
  if ((d.history || []).length >= 2) box.append(chartBox(reportChart(d.history)));
  if ((d.history || []).length) {
    const wrap = el('div', 'rvscroll'), tb = el('table', 'rvruns');
    const hr = el('tr'); for (const h of ['Run', 'Mulai', 'Hasil', 'Selesai', 'Gagal', 'Lama', 'Biaya']) hr.append(el('th', null, h));
    const thead = el('thead'); thead.append(hr);
    const tbody = el('tbody');
    for (const h of d.history) {
      const v = runVerdict(h), tr = el('tr', h.run === d.run ? 'on' : '');
      tr.append(el('td', null, `#${h.run}`), el('td', null, when(h.started)));
      const verdict = el('td'); verdict.append(el('span', `chip rv-${v.cls}`, v.text)); tr.append(verdict);
      tr.append(el('td', null, `${h.completed}/${h.total}`), el('td', null, String(h.failed)),
        el('td', null, h.minutes == null || h.busy ? '—' : `${fmtNum(Math.round(h.minutes))} mnt`), el('td', null, `$${fmtNum(h.cost || 0)}`));
      tr.title = `Buka hasil run #${h.run}`;
      tr.addEventListener('click', () => onRun(h.run));
      tbody.append(tr);
    }
    tb.append(thead, tbody); wrap.append(tb); box.append(wrap);
    box.append(el('div', 'muted rvhint', 'Ketuk satu run untuk melihat hasil lengkapnya di bawah.'));
  }
  return box;
}

/** Open the results of a project run full screen. `api.req` loads them; `fetchBlob(path)` downloads a document with the owner's token. */
export function openResults({ api, toast, projectId, run, onShowTask }) {
  const ov = el('div', 'rvoverlay');
  const bar = el('div', 'rvbar'), title = el('b', 'rvname', 'Hasil proyek'), pick = el('select', 'rvrun'), body = el('div', 'rvbody');
  const close = () => { document.removeEventListener('keydown', onKey, true); ov.remove(); };
  const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  document.addEventListener('keydown', onKey, true);
  bar.append(title, pick, button('✕ Tutup', 'pbtn', close));
  ov.append(bar, body);
  document.body.append(ov);

  const fetchBlob = async (path) => {
    const r = await fetch(path, { headers: { Authorization: `Bearer ${api.token}` } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.blob();
  };

  async function load(n) {
    body.replaceChildren(el('div', 'muted', 'Memuat hasil…'));
    let d;
    try { d = await api.req('GET', `/api/v1/projects/${projectId}/results${n ? `?run=${n}` : ''}`); } catch (err) { body.replaceChildren(el('div', 'wbad', err.message)); return; }
    title.textContent = `Hasil & laporan · ${d.project.name}`;
    pick.replaceChildren(...d.runs.map((r) => { const o = el('option', null, `Run #${r}`); o.value = String(r); return o; }));
    pick.hidden = !d.runs.length; if (d.run) pick.value = String(d.run);
    body.replaceChildren(reportBox(d, (r) => { pick.value = String(r); load(r); }));
    if (d.run) body.append(el('h3', 'rvh rvrunhead', `Hasil run #${d.run}`));
    if (!d.workers.length) { body.append(el('div', 'snippet', 'Belum ada hasil. Tekan ▶ Jalankan di kartu proyek.')); return; }
    for (const w of d.workers) {
      const sec = el('section', 'rvworker');
      const head = el('div', 'rvwhead');
      head.append(el('span', `dot ${w.status === 'stopped' ? 'cancelled' : w.status}`), el('b', null, w.role), el('span', 'chip', STATUS[w.status] || w.status));
      if (w.model) head.append(el('span', 'chip wmodel', w.model.split('/').pop()));
      if (['queued', 'running'].includes(w.status) && onShowTask) head.append(button('Lihat di Meja', 'pbtn', () => { close(); onShowTask(w.id); }));
      sec.append(head);
      if (w.error) sec.append(el('div', 'snippet wbad', w.error));
      const blocks = blocksOf(w.doc, w.text);
      if (!blocks.length && !w.error) sec.append(el('div', 'snippet', ['queued', 'running'].includes(w.status) ? 'Masih dikerjakan — hasilnya muncul di sini setelah selesai.' : 'Pekerja ini tidak menulis hasil.'));
      render(blocks, sec);
      if (w.documents?.length) {
        const docs = el('div', 'rvlinks');
        for (const doc of w.documents) {
          docs.append(button(`📎 ${doc.title}.${doc.format}`, 'chip', async () => {
            try { const u = URL.createObjectURL(await fetchBlob(`/api/v1/documents/${doc.id}`)); const a = el('a'); a.href = u; a.download = `${doc.title}.${doc.format}`; a.click(); setTimeout(() => URL.revokeObjectURL(u), 4000); }
            catch (err) { toast(`Dokumen gagal diunduh: ${err.message}`, true); }
          }));
        }
        sec.append(docs);
      }
      body.append(sec);
    }
  }
  pick.addEventListener('change', () => load(Number(pick.value)));
  load(run);
  return { close };
}
