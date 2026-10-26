// The board's interface (ADR-055): tool rail, zoom bar, minimap, inspector, context menu and the search palette — the parts around the paper
// that make it feel like a design tool. They only call the board; the board talks to the server.
import { matchCards, miniMapFit, rectsBounds } from './lib.js';
import { SHAPE_LABEL, SWATCHES } from './board.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { /* private mode */ } return null; };

const I = {   // 24×24 line icons
  select: '<path d="M5 3l13 7.5-5.5 1.6L15.5 19l-2.8 1.3-3-7-4.2 3.7z"/>',
  hand: '<path d="M8 12V6.5a1.5 1.5 0 013 0V11M11 10.5V4.5a1.5 1.5 0 013 0V11M14 11V6a1.5 1.5 0 013 0v7M17 10.5a1.5 1.5 0 013 0V15a6 6 0 01-6 6h-1.2a6 6 0 01-4.6-2.2L4.2 14.6a1.5 1.5 0 012.3-1.9L8 14"/>',
  note: '<path d="M4 4h16v11l-5 5H4z"/><path d="M15 20v-5h5"/>',
  text: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
  rect: '<rect x="4" y="5" width="16" height="14" rx="1.5"/>',
  round: '<rect x="4" y="5" width="16" height="14" rx="5"/>',
  ellipse: '<ellipse cx="12" cy="12" rx="8.5" ry="7"/>',
  diamond: '<path d="M12 3l9 9-9 9-9-9z"/>',
  frame: '<path d="M7 3v18M17 3v18M3 7h18M3 17h18"/>',
  connector: '<circle cx="5" cy="19" r="1.6"/><path d="M5 17.4C5 9 19 12 19 5.5"/><path d="M15.5 6.5L19 5l1.5 3.5"/>',
  card: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8.5v7M8.5 12h7"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h9a6 6 0 010 12h-2"/>',
  redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9h-9a6 6 0 000 12h2"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  minus: '<path d="M5 12h14"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  map: '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  trash: '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>',
  lock: '<rect x="6" y="11" width="12" height="9" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 017 0v3"/>',
  front: '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M4 16V4h12"/>', back: '<rect x="4" y="4" width="12" height="12" rx="1.5"/><path d="M8 20h12V8"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 00-2-2H6a2 2 0 00-2 2v8a2 2 0 002 2h2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
  alignL: '<path d="M4 3v18"/><rect x="7" y="6" width="12" height="4" rx="1"/><rect x="7" y="14" width="7" height="4" rx="1"/>',
  alignC: '<path d="M12 3v18"/><rect x="5" y="6" width="14" height="4" rx="1"/><rect x="8" y="14" width="8" height="4" rx="1"/>',
  alignR: '<path d="M20 3v18"/><rect x="5" y="6" width="12" height="4" rx="1"/><rect x="10" y="14" width="7" height="4" rx="1"/>',
  alignT: '<path d="M3 4h18"/><rect x="6" y="7" width="4" height="12" rx="1"/><rect x="14" y="7" width="4" height="7" rx="1"/>',
  alignM: '<path d="M3 12h18"/><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="8" width="4" height="8" rx="1"/>',
  alignB: '<path d="M3 20h18"/><rect x="6" y="5" width="4" height="12" rx="1"/><rect x="14" y="10" width="4" height="7" rx="1"/>',
  distH: '<path d="M4 3v18M20 3v18"/><rect x="10" y="7" width="4" height="10" rx="1"/>', distV: '<path d="M3 4h18M3 20h18"/><rect x="7" y="10" width="10" height="4" rx="1"/>',
  arrowTo: '<path d="M4 12h14M13 7l5 5-5 5"/>', arrowFrom: '<path d="M20 12H6M11 7l-5 5 5 5"/>', arrowNone: '<path d="M4 12h16"/>',
  dash: '<path d="M3 12h4M10 12h4M17 12h4"/>',
};
const icon = (name) => { const s = el('span', 'ico'); s.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[name] || ''}</svg>`; return s; };
const btn = (name, title, fn, cls = '') => { const b = el('button', `ib ${cls}`); b.append(icon(name)); b.title = title; b.setAttribute('aria-label', title); b.dataset.gesture = 'ok'; if (fn) b.addEventListener('click', (e) => { e.stopPropagation(); fn(e); }); return b; };

export function createChrome({ board, api, toast, canvasId, refresh, fillFromLibrary, openHistory, kindsFor }) {
  const small = matchMedia('(max-width: 700px)').matches;

  // ------------------------------------------------------------ tool rail
  const rail = el('nav', 'toolrail');
  rail.setAttribute('aria-label', 'Alat papan');
  const toolBtns = {};
  const addTool = (name, ico, title) => { const b = btn(ico, title, () => board.setTool(name), 'tool'); toolBtns[name] = b; rail.append(b); return b; };
  addTool('select', 'select', 'Pilih (V)');
  addTool('hand', 'hand', 'Geser kertas (H atau tahan Spasi)');
  rail.append(el('i', 'sep'));
  addTool('note', 'note', 'Catatan (N) — klik, atau seret untuk menentukan ukuran');
  addTool('text', 'text', 'Teks (T)');
  const shapeBtn = addTool('shape', 'rect', 'Bentuk (R) — klik lagi untuk memilih jenis');
  addTool('frame', 'frame', 'Bingkai (F) — pengelompok; menggeser bingkai membawa isinya');
  addTool('connector', 'connector', 'Penghubung (C) — seret dari satu kartu ke kartu lain');
  const flyout = el('div', 'flyout'); flyout.hidden = true;
  for (const k of Object.keys(SHAPE_LABEL)) { const b = btn(k, SHAPE_LABEL[k], () => { board.setShape(k); flyout.hidden = true; shapeBtn.replaceChildren(icon(k)); }); flyout.append(b); }
  shapeBtn.addEventListener('click', () => { if (board.tool === 'shape') flyout.hidden = !flyout.hidden; });
  addEventListener('pointerdown', (e) => { if (!flyout.hidden && !e.target.closest('.flyout, .toolrail')) flyout.hidden = true; });
  rail.append(flyout, el('i', 'sep'));
  rail.append(btn('card', 'Tambahkan kartu dari Simpanan (Ctrl+K)', () => openPalette('add')));
  const undoB = btn('undo', 'Urungkan (Ctrl+Z)', () => board.undo()), redoB = btn('redo', 'Ulangi (Ctrl+Shift+Z)', () => board.redo());
  rail.append(el('i', 'sep'), undoB, redoB);
  document.body.append(rail);
  board.on('tool', (t) => {
    for (const [name, b] of Object.entries(toolBtns)) b.classList.toggle('on', name === t);
    shapeBtn.replaceChildren(icon(board.shapeKind));
    if (t !== 'shape') flyout.hidden = true;
    renderInspector();
  });
  board.on('history', (h) => {
    undoB.disabled = !h.canUndo; redoB.disabled = !h.canRedo;
    undoB.title = h.undoLabel ? `Urungkan: ${h.undoLabel} (Ctrl+Z)` : 'Urungkan (Ctrl+Z)';
    redoB.title = h.redoLabel ? `Ulangi: ${h.redoLabel} (Ctrl+Shift+Z)` : 'Ulangi (Ctrl+Shift+Z)';
  });
  undoB.disabled = redoB.disabled = true;
  toolBtns.select.classList.add('on');

  // ------------------------------------------------------------ zoom bar + minimap
  const zoom = el('div', 'zoombar');
  const pct = el('button', 'zpct', '100%'); pct.title = 'Perbesaran — klik untuk pilihan'; pct.dataset.gesture = 'ok';
  const zmenu = el('div', 'zmenu'); zmenu.hidden = true;
  const zitem = (label, kbd, fn) => { const b = el('button', 'mi'); b.append(el('span', null, label), el('kbd', null, kbd)); b.addEventListener('click', () => { zmenu.hidden = true; fn(); }); zmenu.append(b); };
  zitem('Pas semua', 'Shift 1', () => board.fitAll(420)); zitem('Pas pilihan', 'Shift 2', () => board.fitSelection(420));
  zitem('50%', '', () => board.zoomTo(0.5)); zitem('100%', '0', () => board.zoomTo(1)); zitem('200%', '', () => board.zoomTo(2));
  pct.addEventListener('click', (e) => { e.stopPropagation(); zmenu.hidden = !zmenu.hidden; });
  addEventListener('pointerdown', (e) => { if (!zmenu.hidden && !e.target.closest('.zmenu, .zpct')) zmenu.hidden = true; });
  const mapB = btn('map', 'Peta mini', () => setMinimap(!mini.classList.contains('show')), 'toggle');
  zoom.append(btn('minus', 'Perkecil (-)', () => board.zoomBy(0.8, undefined, undefined, 160)), pct, btn('plus', 'Perbesar (+)', () => board.zoomBy(1.25, undefined, undefined, 160)),
    el('i', 'sep'), btn('fit', 'Pas semua (Shift+1)', () => board.fitAll(420)), mapB, zmenu);
  document.body.append(zoom);

  const mini = el('div', 'minimap');
  const mcv = el('canvas'); mini.append(mcv);
  document.body.append(mini);
  const MW = 200, MH = 128;
  function setMinimap(on) { mini.classList.toggle('show', on); mapB.classList.toggle('on', on); LS('jarvis_board_minimap', on ? 'on' : 'off'); if (on) drawMini(); }
  let miniFit = null, miniQueued = false;
  function drawMini() {
    if (!mini.classList.contains('show') || miniQueued) return;
    miniQueued = true;
    requestAnimationFrame(() => {
      miniQueued = false;
      const dpr = devicePixelRatio || 1;
      mcv.width = MW * dpr; mcv.height = MH * dpr; mcv.style.width = `${MW}px`; mcv.style.height = `${MH}px`;
      const g = mcv.getContext('2d'); g.scale(dpr, dpr); g.clearRect(0, 0, MW, MH);
      const rects = [...board.cards.values()].map((c) => ({ r: board.rectOf(c), c })), ws = [...board.widgets.values()].map((w) => board.widgetRect(w));
      const all = rectsBounds([...rects.map((x) => x.r), ...ws, viewRect()]);
      if (!all) return;
      miniFit = miniMapFit(all, { w: MW, h: MH }, 120);
      const { s, ox, oy } = miniFit;
      for (const { r, c } of rects) {
        const d = c.data; g.fillStyle = d.type ? (d.props?.color || '#94a3b8') : (board.zones.find((z) => z.kind === d.kind)?.color || '#67e8f9');
        g.globalAlpha = d.type === 'frame' ? 0.25 : 0.85; g.fillRect(r.x * s + ox, r.y * s + oy, Math.max(2, r.w * s), Math.max(2, r.h * s));
      }
      g.globalAlpha = 0.5; g.fillStyle = '#e2e8f0'; for (const r of ws) g.fillRect(r.x * s + ox, r.y * s + oy, Math.max(2, r.w * s), Math.max(2, r.h * s));
      g.globalAlpha = 1; const v = viewRect();
      g.strokeStyle = '#67e8f9'; g.lineWidth = 1.5; g.fillStyle = 'rgba(103,232,249,0.12)';
      g.fillRect(v.x * s + ox, v.y * s + oy, v.w * s, v.h * s); g.strokeRect(v.x * s + ox, v.y * s + oy, v.w * s, v.h * s);
    });
  }
  const viewRect = () => { const a = board.worldAt(0, 0), b = board.worldAt(board.vp.w, board.vp.h); return { x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y }; };
  let mdrag = false;
  const mjump = (e) => { if (!miniFit) return; const r = mcv.getBoundingClientRect(); board.setView({ ...board.view, cx: (e.clientX - r.left - miniFit.ox) / miniFit.s, cy: (e.clientY - r.top - miniFit.oy) / miniFit.s }); };
  mini.addEventListener('pointerdown', (e) => { mdrag = true; mini.setPointerCapture(e.pointerId); mjump(e); e.stopPropagation(); });
  mini.addEventListener('pointermove', (e) => { if (mdrag) mjump(e); });
  mini.addEventListener('pointerup', () => { mdrag = false; });
  board.on('view', (v) => { pct.textContent = `${Math.round(v.k * 100)}%`; drawMini(); });
  board.on('content', drawMini);
  setMinimap(LS('jarvis_board_minimap') ? LS('jarvis_board_minimap') === 'on' : !small);

  // ------------------------------------------------------------ inspector
  const insp = el('aside', 'inspector');
  insp.setAttribute('aria-label', 'Properti');
  document.body.append(insp);
  let inspOpen = small ? false : LS('jarvis_board_inspector') !== 'closed';
  const inspToggle = btn('panel', 'Panel properti', () => { inspOpen = !inspOpen; LS('jarvis_board_inspector', inspOpen ? 'open' : 'closed'); renderInspector(); }, 'toggle');
  const row = (label, ...kids) => { const r = el('div', 'prow'); if (label) r.append(el('label', null, label)); r.append(...kids); return r; };
  const section = (title, ...kids) => { const s = el('section', 'psec'); if (title) s.append(el('h4', null, title)); s.append(...kids); return s; };
  const toggle = (label, on, fn) => { const l = el('label', 'switch'); const c = el('input'); c.type = 'checkbox'; c.checked = on; c.addEventListener('change', () => fn(c.checked)); l.append(c, el('span', null, label)); return l; };
  const number = (label, v, fn) => { const w = el('label', 'num'); w.append(el('span', null, label)); const i = el('input'); i.type = 'number'; i.value = Math.round(v); i.step = 1;
    i.addEventListener('change', () => fn(Number(i.value))); i.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') i.blur(); }); w.append(i); return w; };
  const swatches = (current, fn) => { const w = el('div', 'swatches'); for (const c of SWATCHES) { const b = el('button', `sw${c === current ? ' on' : ''}`); b.style.background = c; b.title = c; b.dataset.gesture = 'ok'; b.addEventListener('click', () => fn(c)); w.append(b); } return w; };
  const group = (...bs) => { const g = el('div', 'bgroup'); g.append(...bs); return g; };
  const lab = (text, fn, cls = '') => { const b = el('button', `tbtn ${cls}`, text); b.dataset.gesture = 'ok'; b.addEventListener('click', fn); return b; };

  const TYPE_NAME = { note: 'Catatan', text: 'Teks', shape: 'Bentuk', frame: 'Bingkai' };
  function renderInspector() {
    const a = document.activeElement;
    if (a && insp.contains(a) && /^(INPUT|SELECT)$/.test(a.tagName) && a.type !== 'checkbox') return;   // never rebuild a field the owner is typing in
    insp.classList.toggle('open', inspOpen);
    document.body.classList.toggle('insp-open', inspOpen);
    board.insets.right = inspOpen && !small ? 288 : 0;
    insp.replaceChildren();
    const info = board.selectionInfo();
    const head = el('header', 'phead');
    const close = btn('panel', 'Tutup panel', () => { inspOpen = false; LS('jarvis_board_inspector', 'closed'); renderInspector(); });
    if (info.edge) { head.append(el('b', null, 'Garis penghubung'), close); insp.append(head, edgePanel(info.edge)); }
    else if (info.cards.length) {
      const one = info.cards.length === 1 ? info.cards[0] : null;
      head.append(el('b', null, one ? (one.data.type ? TYPE_NAME[one.data.type] : `Kartu ${one.data.kind}`) : `${info.cards.length} kartu dipilih`), close);
      insp.append(head, ...cardPanels(info));
    } else { head.append(el('b', null, 'Papan'), close); insp.append(head, ...boardPanels()); }
  }

  function boardPanels() {
    const s = board.settings;
    const kinds = kindsFor();
    return [
      section('Tampilan', toggle('Titik-titik kisi', s.gridOn, (v) => board.setGrid(v)), toggle('Tempel ke kisi saat menggeser', s.snapOn, (v) => board.setSnap(v)),
        toggle('Garis bantu pintar', s.guidesOn, (v) => board.setGuides(v)), toggle('Garis penghubung', s.edgesOn, (v) => board.setEdgesVisible(v)), toggle('Nama area', s.zonesOn, (v) => board.setZones(v))),
      kinds.length ? section('Lapisan', ...kinds.map((k) => { const l = el('label', 'layer'); const c = el('input'); c.type = 'checkbox'; c.checked = !s.hiddenKinds.has(k.kind);
        c.addEventListener('change', () => board.setKindHidden(k.kind, !c.checked)); const dot = el('i', 'dot'); dot.style.background = k.color; l.append(c, dot, el('span', null, k.title), el('em', null, String(k.count))); return l; })) : '',
      section('Tindakan', group(lab('Pas semua', () => board.fitAll(420)), lab('Rapikan kartu', () => board.arrange().catch((e) => toast(e.message, true))), lab('Isi dari Simpanan', () => fillFromLibrary()), lab('Riwayat', () => openHistory()))),
      (() => { const d = el('details', 'tips'); d.append(el('summary', null, 'Pintasan keyboard'), el('div', 'keys',
        'V pilih · H geser · N catatan · T teks · R bentuk · F bingkai · C penghubung\nSpasi+seret geser · roda zoom · Shift+1 pas semua · 0 = 100%\nCtrl+Z urungkan · Ctrl+D gandakan · Ctrl+A semua · Del hapus\nPanah geser 1px (Shift 10) · [ ] belakang/depan · Ctrl+L kunci\nKlik dua kali kertas = catatan baru · Ctrl+K cari')); return d; })(),
    ].filter(Boolean);
  }

  function cardPanels(info) {
    const list = info.cards, one = list.length === 1 ? list[0] : null, objs = list.filter((c) => board.isObj(c)), allObjs = objs.length === list.length;
    const ids = list.map((c) => c.data.id), out = [];
    const r = info.bounds;
    if (one) {
      const rr = board.rectOf(one), g = el('div', 'grid2');
      g.append(number('X', rr.x, (v) => board.setGeometry({ x: v })), number('Y', rr.y, (v) => board.setGeometry({ y: v })), number('L', rr.w, (v) => board.setGeometry({ w: v })), number('T', rr.h, (v) => board.setGeometry({ h: v })));
      out.push(section('Ukuran & posisi', g));
    }
    if (objs.length) {
      const p = objs[0].data.props || {}, type = objs[0].data.type;
      out.push(section('Warna', swatches(p.color, (c) => board.setProps(objs.map((o) => o.data.id), { color: c }, 'ubah warna'))));
      if (type !== 'frame' || objs.length === 1) {
        const size = p.font || (type === 'text' ? 28 : type === 'frame' ? 15 : 17);
        const fontRow = row('Teks',
          group(lab('A−', () => board.setProps(objs.map((o) => o.data.id), { font: Math.max(10, size - 2) }, 'ukuran teks')), el('span', 'fval', `${size}`), lab('A+', () => board.setProps(objs.map((o) => o.data.id), { font: Math.min(96, size + 2) }, 'ukuran teks'))),
          group(lab('B', () => board.setProps(objs.map((o) => o.data.id), { bold: !p.bold }, 'tebal'), p.bold ? 'on bold' : 'bold'),
            ...['left', 'center', 'right'].map((a) => lab({ left: '⇤', center: '↔', right: '⇥' }[a], () => board.setProps(objs.map((o) => o.data.id), { align: a }, 'rata teks'), (p.align || (type === 'shape' ? 'center' : 'left')) === a ? 'on' : ''))));
        out.push(section('', fontRow));
      }
      if (type === 'shape') {
        const sel = el('select'); for (const [k, v] of Object.entries(SHAPE_LABEL)) { const o = el('option', null, v); o.value = k; sel.append(o); }
        sel.value = p.shape || 'rect'; sel.addEventListener('change', () => board.setProps(objs.map((o) => o.data.id), { shape: sel.value }, 'ubah bentuk'));
        out.push(section('Bentuk', sel, toggle('Berisi warna', p.filled !== false, (v) => board.setProps(objs.map((o) => o.data.id), { filled: v }, 'isi bentuk'))));
      }
    } else if (one) {
      out.push(section('Kartu', el('div', 'psub', `${one.data.subtitle || ''}`), el('div', 'ptitle', one.data.title || ''), one.data.snippet ? el('div', 'psnip', one.data.snippet) : ''));
    }
    if (list.length > 1) out.push(section('Ratakan',
      (() => { const g = el('div', 'bgrid'); for (const [m, ic, t] of [['left', 'alignL', 'Rata kiri'], ['hcenter', 'alignC', 'Tengah horizontal'], ['right', 'alignR', 'Rata kanan'], ['top', 'alignT', 'Rata atas'], ['vcenter', 'alignM', 'Tengah vertikal'], ['bottom', 'alignB', 'Rata bawah']]) g.append(btn(ic, t, () => board.align(m)));
        if (list.length > 2) g.append(btn('distH', 'Sebar horizontal', () => board.distribute('h')), btn('distV', 'Sebar vertikal', () => board.distribute('v'))); return g; })()));
    const locked = list.every((c) => board.isLocked(c));
    const acts = [];
    acts.push(btn('front', 'Bawa ke depan (])', () => board.order(true)), btn('back', 'Kirim ke belakang ([)', () => board.order(false)), btn('lock', locked ? 'Buka kunci (Ctrl+L)' : 'Kunci (Ctrl+L)', () => board.setPinned(ids, !locked), locked ? 'on' : ''));
    if (allObjs) acts.push(btn('copy', 'Gandakan (Ctrl+D)', () => board.duplicate()));
    out.push(section('Susunan', group(...acts)));
    const go = [];
    if (one) go.push(lab('Terbang ke', () => board.flyToCard(one.data.id, 1, 600)));
    if (one && one.data.url) go.push(lab('Buka', () => window.dispatchEvent(new CustomEvent('board:open', { detail: one.data.url }))));
    go.push(lab(allObjs ? 'Hapus' : 'Lepas dari papan', () => board.removeSelection().catch((e) => toast(e.message, true)), 'danger'));
    out.push(section('', group(...go)));
    return out;
  }

  function edgePanel(e) {
    const label = el('input'); label.value = e.label || ''; label.placeholder = 'Label garis'; label.maxLength = 60;
    label.addEventListener('keydown', (ev) => { ev.stopPropagation(); if (ev.key === 'Enter') label.blur(); });
    label.addEventListener('change', () => board.patchEdge(e.id, { label: label.value.trim() }, 'ubah label'));
    const to = e.style?.to ?? null;
    const arrow = group(
      btn('arrowFrom', 'Panah ke kartu pertama', () => board.patchEdge(e.id, { style: { to: e.a } }, 'arah panah'), to === e.a ? 'on' : ''),
      btn('arrowNone', 'Tanpa panah', () => board.patchEdge(e.id, { style: { to: null } }, 'tanpa panah'), to === null ? 'on' : ''),
      btn('arrowTo', 'Panah ke kartu kedua', () => board.patchEdge(e.id, { style: { to: e.b } }, 'arah panah'), to === e.b ? 'on' : ''));
    return el('div', null, section('Label', label),
      section('Garis', row('Panah', arrow), toggle('Putus-putus', !!e.style?.dash, (v) => board.patchEdge(e.id, { style: { dash: v } }, 'gaya garis')),
        swatches(e.style?.color, (c) => board.patchEdge(e.id, { style: { color: c } }, 'warna garis'))),
      section('', group(lab('Putus garis', () => board.removeEdge(e.id), 'danger'))));
  }

  board.on('selection', () => { if (small) inspOpen = board.selectionInfo().cards.length > 0 || !!board.selectionInfo().edge; renderInspector(); });
  board.on('content', () => { if (!board.selectionInfo().cards.length && !board.selectionInfo().edge) renderInspector(); });
  board.on('edit', (on) => { insp.classList.toggle('dim', on); });
  renderInspector();

  // ------------------------------------------------------------ context menu
  const menu = el('div', 'menu'); menu.hidden = true;
  document.body.append(menu);
  const closeMenu = () => { menu.hidden = true; };
  addEventListener('pointerdown', (e) => { if (!e.target.closest('.menu')) closeMenu(); }, true);
  addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });
  function openMenu(x, y, items) {
    menu.replaceChildren();
    for (const it of items) {
      if (it === '-') { menu.append(el('i', 'msep')); continue; }
      if (it.swatches) { const w = swatches(it.current, (c) => { closeMenu(); it.swatches(c); }); w.classList.add('inmenu'); menu.append(w); continue; }
      const b = el('button', `mi${it.danger ? ' danger' : ''}`); b.disabled = !!it.disabled;
      b.append(el('span', null, it.label), it.kbd ? el('kbd', null, it.kbd) : '');
      b.addEventListener('click', () => { closeMenu(); it.run(); });
      menu.append(b);
    }
    menu.hidden = false;
    const w = menu.offsetWidth, h = menu.offsetHeight;
    menu.style.left = `${Math.min(x, innerWidth - w - 8)}px`; menu.style.top = `${Math.min(y, innerHeight - h - 8)}px`;
  }
  function contextMenu({ x, y, world, card, edge }) {
    const items = [];
    const make = (props, label) => ({ label, run: () => board.createObject(props, world.x - 110, world.y - 70, undefined, undefined, { edit: true }).catch((e) => toast(e.message, true)) });
    if (edge) {
      const e = board.selectionInfo().edge;
      items.push({ label: 'Ubah label', run: () => { board.selectEdge(e.id); const l = insp.querySelector('input'); l?.focus(); } }, { label: 'Putus garis', danger: true, kbd: 'Del', run: () => board.removeEdge(e.id) });
    } else if (card) {
      const c = card, obj = board.isObj(c), ids = [...board.sel], locked = board.isLocked(c);
      if (obj) items.push({ label: 'Edit teks', kbd: 'Enter', run: () => board.startEdit(c.data.id), disabled: locked });
      else items.push({ label: 'Terbang ke', run: () => board.flyToCard(c.data.id, 1, 600) });
      if (!obj && c.data.url) items.push({ label: 'Buka', run: () => window.dispatchEvent(new CustomEvent('board:open', { detail: c.data.url })) });
      if (obj) { items.push({ swatches: (col) => board.setProps(ids, { color: col }, 'ubah warna'), current: c.data.props?.color }); items.push({ label: 'Gandakan', kbd: 'Ctrl D', run: () => board.duplicate() }); }
      items.push('-', { label: 'Bawa ke depan', kbd: ']', run: () => board.order(true) }, { label: 'Kirim ke belakang', kbd: '[', run: () => board.order(false) },
        { label: locked ? 'Buka kunci' : 'Kunci', kbd: 'Ctrl L', run: () => board.setPinned(ids, !locked) }, '-',
        { label: obj ? 'Hapus' : 'Lepas dari papan', danger: true, kbd: 'Del', run: () => board.removeSelection().catch((e) => toast(e.message, true)), disabled: locked });
    } else {
      items.push(make({ type: 'note', text: '', color: '#fde68a' }, 'Catatan di sini'), make({ type: 'text', text: '' }, 'Teks di sini'),
        make({ type: 'shape', shape: 'rect', text: '', color: '#93c5fd' }, 'Bentuk di sini'), make({ type: 'frame', text: 'Bingkai', color: '#94a3b8' }, 'Bingkai di sini'), '-',
        { label: 'Tambah kartu dari Simpanan…', kbd: 'Ctrl K', run: () => openPalette('add') }, { label: 'Tempel', kbd: 'Ctrl V', run: () => board.paste() }, '-',
        { label: 'Pas semua', kbd: 'Shift 1', run: () => board.fitAll(420) }, { label: 'Rapikan kartu', run: () => board.arrange().catch((e) => toast(e.message, true)) }, { label: board.settings.gridOn ? 'Sembunyikan kisi' : 'Tampilkan kisi', run: () => board.setGrid(!board.settings.gridOn) });
    }
    openMenu(x, y, items);
  }

  // ------------------------------------------------------------ palette: find on the board, add from storage
  const pal = el('div', 'palette'); pal.hidden = true;
  const pin = el('input'); pin.placeholder = 'Cari kartu di papan, atau tambahkan dari Simpanan…'; pin.autocomplete = 'off'; pin.setAttribute('aria-label', 'Cari');
  const plist = el('div', 'plist');
  pal.append(pin, plist, el('div', 'phint', '↑↓ pilih · Enter buka · Esc tutup'));
  document.body.append(pal);
  let palItems = [], palAt = 0, palTimer = null;
  function openPalette(mode = 'find') { pal.hidden = false; pin.value = ''; plist.replaceChildren(); palItems = []; pin.focus(); if (mode === 'add') { pin.placeholder = 'Cari tugas, dokumen, memori, rapat… untuk ditaruh di papan'; searchStore(''); } else pin.placeholder = 'Cari kartu di papan, atau tambahkan dari Simpanan…'; }
  const closePalette = () => { pal.hidden = true; pin.blur(); };
  function paint() {
    plist.replaceChildren(...palItems.map((it, i) => { const b = el('button', `pitem${i === palAt ? ' on' : ''}`); b.append(el('b', null, it.title || '(tanpa judul)'), el('span', null, it.sub)); b.addEventListener('click', () => { palAt = i; choose(); }); b.dataset.gesture = 'ok'; return b; }));
    plist.children[palAt]?.scrollIntoView({ block: 'nearest' });
  }
  async function choose() {
    const it = palItems[palAt];
    if (!it) return;
    closePalette();
    if (it.card) { board.flyToCard(it.card.id, 1, 700); board.select([it.card.id]); return; }
    try { const n = await api.req('POST', `/api/v1/canvases/${canvasId()}/cards`, { ref: it.ref }); await refresh(true); board.flyToCard(n.id, 1, 700); board.select([n.id]); }
    catch (e) { toast(e.message, true); }
  }
  async function searchStore(q) {
    try {
      const items = await api.req('GET', `/api/v1/canvases/${canvasId()}/search?q=${encodeURIComponent(q)}`);
      const have = new Set([...board.cards.values()].map((c) => c.data.ref));
      const add = items.filter((i) => !have.has(i.ref)).map((i) => ({ ref: i.ref, title: i.title, sub: `Tambahkan · ${i.kind}` }));
      palItems = [...palItems.filter((p) => p.card), ...add]; palAt = Math.min(palAt, Math.max(0, palItems.length - 1)); paint();
    } catch { /* offline */ }
  }
  pin.addEventListener('input', () => {
    const found = matchCards([...board.cards.values()].map((c) => c.data), pin.value).slice(0, 8).map((c) => ({ card: c, title: c.title, sub: `Di papan · ${c.type ? TYPE_NAME[c.type] : c.kind}` }));
    palItems = found; palAt = 0; paint();
    clearTimeout(palTimer); palTimer = setTimeout(() => pin.value.trim().length >= 2 && searchStore(pin.value.trim()), 250);
  });
  pin.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Escape') closePalette();
    else if (e.key === 'ArrowDown') { e.preventDefault(); palAt = Math.min(palItems.length - 1, palAt + 1); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); palAt = Math.max(0, palAt - 1); paint(); }
    else if (e.key === 'Enter') { e.preventDefault(); choose(); }
  });
  addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); pal.hidden ? openPalette('find') : closePalette(); } });
  addEventListener('pointerdown', (e) => { if (!pal.hidden && !e.target.closest('.palette')) closePalette(); }, true);

  return { openPalette, contextMenu, renderInspector, inspToggle, openMenu };
}
