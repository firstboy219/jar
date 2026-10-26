// The 2D board (Blueprint v4 Fase 11, ADR-055): an infinite paper like Miro / Figma. Cards, notes, text, shapes and frames live in a "world"
// (x to the right, y down — the server's x and z) that is panned and zoomed with one CSS transform; connectors are an SVG layer; the
// selection box, handles, guides and the marquee are drawn in screen space so they stay crisp at any zoom.
// Nothing here approves, sends or pays: it arranges, draws, links and takes cards off the board (the thing a card points at is never deleted).
import { MAX_ZOOM, MIN_ZOOM, alignRects, clampZoom, connectorPath, diffCards, distributeRects, ease, fitRect, panBy, rectsBounds, rectsIntersect, resizeRect,
  snapRect, snapValue, toScreen, toWorld, wheelIntent, zoomAt } from './lib.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const SVGNS = 'http://www.w3.org/2000/svg';
const sv = (tag, attrs = {}) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };

export const SWATCHES = ['#fde68a', '#fdba74', '#fca5a5', '#f9a8d4', '#c4b5fd', '#93c5fd', '#67e8f9', '#86efac', '#e5e7eb', '#1e293b'];
export const SHAPE_LABEL = { rect: 'Persegi', round: 'Persegi tumpul', ellipse: 'Elips', diamond: 'Belah ketupat' };
const NOTE_DEFAULT = '#fde68a';
const INTERACTIVE = 'button, input, textarea, select, a, audio, video, iframe, label, [contenteditable="true"], .nodrag';
const GRID = 24;

/** Black or white ink, whichever reads better on a fill. */
export function inkFor(hex) {
  const m = /^#([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return '#0f172a';
  const n = parseInt(m[1], 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#0f172a' : '#f8fafc';
}

export function createBoard(ctx) {
  const { stage, api, toast, canvasId, refresh, embedded = false, decorate = () => {} } = ctx;
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarse = matchMedia('(pointer: coarse)').matches;
  const on = { view: [], selection: [], tool: [], history: [], content: [], edit: [] };
  const emit = (k, ...a) => on[k].forEach((f) => f(...a));

  // ------------------------------------------------------------ DOM
  stage.classList.add('board');
  const world = el('div', 'world'), zonesEl = el('div', 'zones'), cardsEl = el('div', 'cards'), svg = sv('svg', { class: 'edges' });
  const defs = sv('defs');
  svg.append(defs);
  world.append(zonesEl, svg, cardsEl);
  const dotsEl = el('div', 'dots');
  const guidesEl = sv('svg', { class: 'guides' }), marquee = el('div', 'marquee'), selBox = el('div', 'selbox'), ghost = el('div', 'ghost'), wire = sv('svg', { class: 'wire' });
  marquee.hidden = ghost.hidden = selBox.hidden = true;
  const sizeBadge = el('div', 'sizebadge');
  selBox.append(sizeBadge);
  for (const h of ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']) { const hd = el('i', `handle h-${h}`); hd.dataset.handle = h; selBox.append(hd); }
  stage.append(world, guidesEl, wire, marquee, ghost, dotsEl, selBox);

  // ------------------------------------------------------------ state
  let view = { cx: 0, cy: 0, k: 0.5 }, vp = { w: innerWidth, h: innerHeight };
  const cards = new Map();           // id → {data, el, autoH}
  const widgets = new Map();         // name → {el, x, y, w, autoH}   the fixed desk panels
  let edges = [], zones = [], hiddenKinds = new Set();
  const sel = new Set();
  let selEdge = null, tool = 'select', shapeKind = 'rect', snapOn = false, guidesOn = true, spaceDown = false, gridOn = true, edgesOn = true, zonesOn = true;
  let flight = null, gesture = null, drawing = false, editing = null;
  const pointers = new Map();
  const dragging = new Set();
  const zOrder = new Map();          // id → bump counter (client-side "bring to front")
  let zCounter = 0;
  let clip = null;                   // copied objects

  const rectOf = (c) => {
    const d = c.data, w = d.w ?? (c.live ? 440 : 300);
    const h = d.type === 'text' ? (c.autoH ?? d.h ?? 60) : (d.h ?? c.autoH ?? 150);   // text grows with what is typed
    return { x: d.x, y: d.z, w, h };
  };
  const widgetRect = (w) => ({ x: w.x, y: w.y, w: w.w, h: w.autoH || 200 });
  const isObj = (c) => !!c.data.type;
  const isLocked = (c) => !!(c.data.pinned || c.data.props?.locked);

  const ro = new ResizeObserver((entries) => {
    for (const en of entries) {
      const h = Math.round(en.borderBoxSize?.[0]?.blockSize ?? en.target.offsetHeight);
      const c = en.target.__card, w = en.target.__widget;
      if (c && c.autoH !== h) { c.autoH = h; scheduleEdges(); if (sel.has(c.data.id)) syncSel(); }
      if (w && w.autoH !== h) { w.autoH = h; }
    }
  });

  // ------------------------------------------------------------ view
  function measure() { const r = stage.getBoundingClientRect(); vp = { w: r.width, h: r.height }; applyView(); }
  new ResizeObserver(measure).observe(stage);
  let cullQueued = false;
  function applyView() {
    const tx = vp.w / 2 - view.cx * view.k, ty = vp.h / 2 - view.cy * view.k;
    world.style.transform = `translate(${tx}px, ${ty}px) scale(${view.k})`;
    stage.style.setProperty('--k', view.k);
    stage.style.setProperty('--inv', 1 / view.k);
    const step = GRID * view.k * (view.k < 0.3 ? 5 : 1);
    stage.style.setProperty('--grid', `${step}px`);
    stage.style.setProperty('--gx', `${tx % step}px`); stage.style.setProperty('--gy', `${ty % step}px`);
    stage.classList.toggle('lod1', view.k < 0.5); stage.classList.toggle('lod2', view.k < 0.22);
    syncSel(); emit('view', view);
    if (hoverCard) showDots();
    if (!cullQueued) { cullQueued = true; requestAnimationFrame(cull); }
  }
  function cull() {
    cullQueued = false;
    const m = 260 / view.k, a = toWorld(view, vp, 0, 0), b = toWorld(view, vp, vp.w, vp.h);
    const win = { x: a.x - m, y: a.y - m, w: b.x - a.x + 2 * m, h: b.y - a.y + 2 * m };
    for (const c of cards.values()) c.el.classList.toggle('off', !(sel.has(c.data.id) || dragging.has(c.data.id) || rectsIntersect(rectOf(c), win)));
  }
  function setView(v, animate = 0) {
    cancelFlight();
    const next = { cx: v.cx, cy: v.cy, k: clampZoom(v.k) };
    if (!animate || reducedMotion) { view = next; applyView(); return; }
    flight = { from: { ...view }, to: next, t0: performance.now(), ms: animate };
    requestAnimationFrame(step);
  }
  function step(t) {
    if (!flight) return;
    const p = ease((t - flight.t0) / flight.ms), f = flight.from, to = flight.to;
    // zoom in log space so the flight feels even, and pan in screen terms
    const k = Math.exp(Math.log(f.k) + (Math.log(to.k) - Math.log(f.k)) * p);
    view = { k, cx: f.cx + (to.cx - f.cx) * p, cy: f.cy + (to.cy - f.cy) * p };
    applyView();
    if (p >= 1) flight = null; else requestAnimationFrame(step);
  }
  const cancelFlight = () => { flight = null; };
  const insets = { left: 0, right: 0, top: 0, bottom: 0 };
  function fit(rect, { maxK = 1.25, ms = 520, pad = 72 } = {}) {
    if (!rect) return;
    setView(fitRect(rect, vp, { pad, maxK, inset: insets }), ms);
  }
  const allRects = () => [...cards.values()].filter((c) => !c.el.classList.contains('hidden-kind')).map(rectOf);
  const fitAll = (ms) => fit(rectsBounds([...allRects(), ...[...widgets.values()].filter((w) => !w.el.hidden).map(widgetRect)]) || { x: -400, y: -300, w: 800, h: 600 }, { maxK: 1, ms });
  const fitSelection = (ms) => { const r = rectsBounds([...sel].map((id) => rectOf(cards.get(id))).filter(Boolean)); if (r) fit(r, { maxK: 1.5, ms }); };
  function focusRect(r, k = 0.9, ms = 700) { setView(fitRect(r, vp, { pad: 120, maxK: k, inset: insets }), ms); }
  function zoomBy(f, sx = vp.w / 2, sy = vp.h / 2, ms = 0) {
    const next = zoomAt(view, vp, f, sx, sy);
    setView(next, ms);
  }
  function zoomTo(k, ms = 240) {
    const r = rectsBounds([...sel].map((id) => cards.get(id)).filter(Boolean).map(rectOf));
    const at = r ? { x: r.x + r.w / 2, y: r.y + r.h / 2 } : toWorld(view, vp, vp.w / 2, vp.h / 2);
    setView({ cx: at.x, cy: at.y, k }, ms);
  }
  const worldAt = (sx, sy) => toWorld(view, vp, sx, sy);
  const stagePoint = (e) => { const r = stage.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };

  // ------------------------------------------------------------ cards
  function place(c) {
    const r = rectOf(c), d = c.data;
    c.el.style.transform = `translate(${r.x}px, ${r.y}px)`;
    c.el.style.width = `${r.w}px`;
    c.el.style.height = d.h != null && d.type !== 'text' ? `${d.h}px` : '';
    c.el.style.zIndex = d.type === 'frame' ? 1 : String(3 + (zOrder.get(d.id) || 0) + (sel.has(d.id) ? 0 : 0));
  }
  function textOf(d) { return d.props?.text ?? ''; }

  function fillCard(c) {
    const d = c.data, e = c.el, p = d.props || {};
    const live = e.querySelector(':scope > .livebox');
    e.dataset.id = d.id;
    e.className = `card ${d.type ? `obj ${d.type}` : 'ref'}${sel.has(d.id) ? ' selected' : ''}${isLocked(c) ? ' locked' : ''}${live ? ' live' : ''}${hiddenKinds.has(d.kind) ? ' hidden-kind' : ''}`;
    e.style.setProperty('--c', d.type ? (p.color || NOTE_DEFAULT) : (c.kindColor || '#67e8f9'));
    if (d.type) {
      e.style.setProperty('--fill', p.color || (d.type === 'frame' ? '#94a3b8' : NOTE_DEFAULT));
      e.style.setProperty('--ink', d.type === 'text' || d.type === 'frame' ? '' : inkFor(p.color || NOTE_DEFAULT));
      e.style.setProperty('--tc', d.type === 'text' ? (p.color || '#e6edff') : p.color || '#e6edff');
      e.style.setProperty('--font', `${p.font || (d.type === 'text' ? 28 : d.type === 'frame' ? 15 : 17)}px`);
      e.style.setProperty('--align', p.align || (d.type === 'shape' ? 'center' : 'left'));
      e.style.fontWeight = p.bold ? '700' : '';
      e.classList.toggle('outline', d.type === 'shape' && p.filled === false);
      e.dataset.shape = p.shape || 'rect';
      e.replaceChildren();
      const txt = el('div', 'txt', textOf(d));
      if (d.type === 'frame') e.append(el('div', 'frame-title', textOf(d) || 'Bingkai'), el('div', 'frame-body'));
      else { if (d.type === 'shape') e.append(el('div', 'shape-bg')); e.append(txt); }
      if (!textOf(d) && d.type !== 'frame') txt.classList.add('empty');
    } else {
      e.replaceChildren(el('div', 'kind', `${d.kind}${d.subtitle ? ` · ${d.subtitle}` : ''}`), el('div', 'title', d.title || '(tanpa judul)'));
      if (d.snippet) e.append(el('div', 'snippet', d.snippet));
      if (d.image) { const img = el('img'); img.src = d.image; img.loading = 'lazy'; img.alt = ''; e.append(img); }
      const acts = el('div', 'actions');
      if (d.url) { const b = el('button', null, 'Buka'); b.dataset.gesture = 'ok'; b.addEventListener('click', (ev) => { ev.stopPropagation(); ctx.openUrl?.(d.url).catch((err) => toast(err.message, true)); }); acts.append(b); }
      e.append(acts);
      if (live) e.insertBefore(live, acts);
    }
    if (isLocked(c)) e.append(el('i', 'lockmark', '🔒'));
    decorate(c);
  }

  function makeCard(d) {
    const c = { data: d, el: el('div'), autoH: null };
    c.el.__card = c;
    c.kindColor = zones.find((z) => z.kind === d.kind)?.color;
    cardsEl.append(c.el);
    ro.observe(c.el);
    fillCard(c); place(c);
    return c;
  }

  /** Called with what the server returned (cards, links, zones). Returns the diff so the app can say what is new. */
  function setContent({ cards: list, edges: es, constellations }) {
    if (constellations) { zones = constellations; drawZones(list); }
    const before = [...cards.values()].map((c) => c.data);
    const diff = diffCards(before, list);
    for (const d of diff.removed) { const c = cards.get(d.id); c.el.remove(); ro.unobserve(c.el); cards.delete(d.id); sel.delete(d.id); }
    const changed = new Set(diff.changed.map((c) => c.id)), moved = new Set(diff.moved.map((c) => c.id));
    for (const d of list) {
      const had = cards.get(d.id);
      if (!had) { const c = makeCard(d); cards.set(d.id, c); c.el.classList.add('pop'); setTimeout(() => c.el.classList.remove('pop'), 600); continue; }
      had.data = d; had.kindColor = zones.find((z) => z.kind === d.kind)?.color;
      if (changed.has(d.id) && editing?.id !== d.id) fillCard(had);
      if ((moved.has(d.id) || changed.has(d.id)) && !dragging.has(d.id)) place(had);
    }
    edges = es || [];
    drawEdges(); syncSel(); cull();
    emit('content', diff); emit('selection', selectionInfo());
    return diff;
  }

  function drawZones(list) {
    zonesEl.replaceChildren();
    const count = {};
    for (const d of list) count[d.kind] = (count[d.kind] || 0) + 1;
    for (const z of zones) {
      if (!count[z.kind]) continue;
      const e = el('div', 'zone', z.title);
      e.style.setProperty('--c', z.color);
      e.style.transform = `translate(${z.center[0]}px, ${z.center[2]}px) translate(-50%, -50%)`;
      zonesEl.append(e);
    }
  }

  /** The fixed desk panels (requests, n8n, storage, player, meeting): placed on the board, not selectable. */
  function setWidget(name, node, pos) {
    let w = widgets.get(name);
    if (!w) {
      w = { el: node, x: pos.x, y: pos.y, w: pos.w, autoH: null };
      node.__widget = w; node.classList.add('widget'); node.style.width = `${pos.w}px`;
      node.style.transform = `translate(${pos.x}px, ${pos.y}px)`;
      cardsEl.append(node); ro.observe(node); widgets.set(name, w);
    }
    return w;
  }

  // ------------------------------------------------------------ connectors
  let edgesQueued = false;
  const scheduleEdges = () => { if (!edgesQueued) { edgesQueued = true; requestAnimationFrame(() => { edgesQueued = false; drawEdges(); }); } };
  function arrowMarker(id, color) {
    if (defs.querySelector(`#${CSS.escape(id)}`)) return;
    const m = sv('marker', { id, viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '9', markerHeight: '9', orient: 'auto-start-reverse', markerUnits: 'userSpaceOnUse' });
    m.append(sv('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: color }));
    defs.append(m);
  }
  function drawEdges() {
    svg.querySelectorAll('g.edge').forEach((g) => g.remove());
    if (!edgesOn) return;
    for (const e of edges) {
      const a = cards.get(e.a), b = cards.get(e.b);
      if (!a || !b || a.el.classList.contains('hidden-kind') || b.el.classList.contains('hidden-kind')) continue;
      const path = connectorPath(rectOf(a), rectOf(b));
      const color = e.style?.color || '#67e8f9', mk = `ar-${color.slice(1)}`;
      arrowMarker(mk, color);
      const g = sv('g', { class: `edge${selEdge === e.id ? ' selected' : ''}` });
      g.dataset.id = e.id;
      g.append(sv('path', { d: path.d, class: 'hit' }), sv('path', { d: path.d, class: 'line', stroke: color, 'stroke-dasharray': e.style?.dash ? '8 6' : '', ...(e.style?.to === e.b ? { 'marker-end': `url(#${mk})` } : e.style?.to === e.a ? { 'marker-start': `url(#${mk})` } : {}) }));
      if (e.label) {
        const t = sv('text', { x: path.mid.x, y: path.mid.y, class: 'elabel' });
        t.textContent = e.label;
        g.append(t);
      }
      svg.append(g);
    }
  }

  // ------------------------------------------------------------ selection
  function selectionInfo() {
    const list = [...sel].map((id) => cards.get(id)).filter(Boolean);
    return { cards: list, edge: selEdge ? edges.find((e) => e.id === selEdge) : null, bounds: rectsBounds(list.map(rectOf)) };
  }
  function select(ids, { add = false } = {}) {
    if (!add) sel.clear();
    for (const id of ids) if (cards.has(id)) sel.add(id);
    selEdge = null;
    for (const c of cards.values()) c.el.classList.toggle('selected', sel.has(c.data.id));
    drawEdges(); syncSel(); emit('selection', selectionInfo());
  }
  function selectEdge(id) {
    sel.clear(); selEdge = id;
    for (const c of cards.values()) c.el.classList.remove('selected');
    drawEdges(); syncSel(); emit('selection', selectionInfo());
  }
  function syncSel() {
    const list = [...sel].map((id) => cards.get(id)).filter(Boolean);
    if (!list.length || tool !== 'select' || editing) { selBox.hidden = true; return; }
    const b = rectsBounds(list.map(rectOf)), s = toScreen(view, vp, b.x, b.y);
    selBox.hidden = false;
    Object.assign(selBox.style, { left: `${s.x}px`, top: `${s.y}px`, width: `${b.w * view.k}px`, height: `${b.h * view.k}px` });
    selBox.classList.toggle('multi', list.length > 1);
    selBox.classList.toggle('locked', list.every(isLocked));
    sizeBadge.textContent = `${Math.round(b.w)} × ${Math.round(b.h)}`;
  }

  // ------------------------------------------------------------ talking to the server (and remembering how to undo it)
  const alias = new Map();
  const live = (id) => { while (alias.has(id)) id = alias.get(id); return id; };
  const hist = { stack: [], i: 0, busy: false };
  function record(entry) { hist.stack.length = hist.i; hist.stack.push(entry); if (hist.stack.length > 120) hist.stack.shift(); hist.i = hist.stack.length; emit('history', histState()); }
  const histState = () => ({ canUndo: hist.i > 0, canRedo: hist.i < hist.stack.length, undoLabel: hist.stack[hist.i - 1]?.label, redoLabel: hist.stack[hist.i]?.label });
  async function runHist(dir) {
    if (hist.busy) return;
    const e = dir < 0 ? hist.stack[hist.i - 1] : hist.stack[hist.i];
    if (!e) return;
    hist.busy = true;
    try { await (dir < 0 ? e.undo() : e.redo()); hist.i += dir; await refresh(true); toast(`${dir < 0 ? 'Urungkan' : 'Ulangi'}: ${e.label}`); }
    catch (err) { toast(err.message, true); } finally { hist.busy = false; emit('history', histState()); }
  }
  const undo = () => runHist(-1), redo = () => runHist(1);

  // a card that never had a size of its own keeps sizing itself: only cards with `sized` send w / h
  const layoutItems = (list) => list.map((r) => ({ id: live(r.id), x: r.x, z: r.y, ...(r.sized ? { w: r.w, h: r.h } : {}) }));
  async function pushLayout(list, note) { await api.req('POST', `/api/v1/canvases/${canvasId()}/layout`, { items: layoutItems(list), note }); }
  function snapshotRects(ids) { return ids.map((id) => { const d = cards.get(id).data; return { id, ...rectOf(cards.get(id)), sized: d.w != null || d.h != null }; }); }

  /** Applies rects to the cards on screen at once and tells the server (one history entry). */
  async function commitLayout(before, after, label) {
    for (const r of after) { const c = cards.get(r.id); if (c) { c.data = { ...c.data, x: r.x, z: r.y, ...(r.sized ? { w: r.w, h: r.h } : {}) }; place(c); } }
    drawEdges(); syncSel();
    await pushLayout(after, label);
    record({ label, undo: () => pushLayout(before, `urung ${label}`), redo: () => pushLayout(after, label) });
    await refresh(true);
  }

  async function createObject(props, x, y, w, h, { select: pick = true, edit = false, record: rec = true } = {}) {
    const node = await api.req('POST', `/api/v1/canvases/${canvasId()}/objects`, { props, x, z: y, w, h });
    await refresh(true);
    if (pick) select([node.id]);
    if (edit) startEdit(node.id);
    if (rec) {
      let id = node.id; const spec = { props, x, y, w: node.w, h: node.h };
      record({ label: 'buat objek', undo: async () => { await api.req('DELETE', `/api/v1/canvas/cards/${live(id)}`); },
        redo: async () => { const n = await api.req('POST', `/api/v1/canvases/${canvasId()}/objects`, { props: spec.props, x: spec.x, z: spec.y, w: spec.w, h: spec.h }); alias.set(id, n.id); id = n.id; } });
    }
    return node;
  }

  async function setProps(ids, props, label = 'ubah tampilan') {
    const objs = ids.map((id) => cards.get(id)).filter((c) => c && isObj(c));
    if (!objs.length) return;
    const before = objs.map((c) => ({ id: c.data.id, props: Object.fromEntries(Object.keys(props).map((k) => [k, c.data.props?.[k]]).filter(([, v]) => v !== undefined)) }));
    const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null));
    for (const c of objs) { c.data = { ...c.data, props: { ...c.data.props, ...props } }; fillCard(c); }
    const send = async (items) => { for (const it of items) await api.req('PATCH', `/api/v1/canvas/cards/${live(it.id)}`, { props: it.props }); };
    await send(objs.map((c) => ({ id: c.data.id, props: clean(props) })));
    record({ label, undo: async () => { for (const b of before) { const reset = {}; for (const k of Object.keys(props)) if (b.props[k] !== undefined) reset[k] = b.props[k]; if (Object.keys(reset).length) await api.req('PATCH', `/api/v1/canvas/cards/${live(b.id)}`, { props: reset }); } },
      redo: () => send(objs.map((c) => ({ id: c.data.id, props: clean(props) }))) });
    await refresh(true);
  }

  async function setPinned(ids, pinned) {
    for (const id of ids) await api.req('PATCH', `/api/v1/canvas/cards/${live(id)}`, { pinned });
    record({ label: pinned ? 'kunci' : 'buka kunci', undo: async () => { for (const id of ids) await api.req('PATCH', `/api/v1/canvas/cards/${live(id)}`, { pinned: !pinned }); },
      redo: async () => { for (const id of ids) await api.req('PATCH', `/api/v1/canvas/cards/${live(id)}`, { pinned }); } });
    await refresh(true);
  }

  /** Takes the selected cards off the board. A note / shape / frame is the owner's own drawing, so it is really deleted (undo brings it back);
   *  a card that points at something (a task, a document…) only leaves the board — the thing itself is untouched. */
  async function removeSelection() {
    if (selEdge) return removeEdge(selEdge);
    const list = [...sel].map((id) => cards.get(id)).filter((c) => c && !isLocked(c));
    if (!list.length) return;
    const refs = list.filter((c) => !isObj(c));
    if (refs.length && !confirm(`Lepas ${refs.length} kartu dari papan? Isinya (tugas/dokumen/dll) tidak dihapus.`)) return;
    const ids = new Set(list.map((c) => c.data.id));
    const snap = list.map((c) => ({ id: c.data.id, ref: c.data.ref, data: { ...c.data }, rect: rectOf(c) }));
    const links = edges.filter((e) => ids.has(e.a) || ids.has(e.b)).map((e) => ({ ...e }));
    for (const c of list) await api.req('DELETE', `/api/v1/canvas/cards/${c.data.id}`);
    sel.clear();
    record({ label: 'lepas kartu', undo: async () => {
      for (const s of snap) {
        const n = s.data.type
          ? await api.req('POST', `/api/v1/canvases/${canvasId()}/objects`, { props: s.data.props, x: s.rect.x, z: s.rect.y, w: s.rect.w, h: s.rect.h })
          : await api.req('POST', `/api/v1/canvases/${canvasId()}/cards`, { ref: s.ref, x: s.data.x, y: s.data.y, z: s.data.z });
        if (!s.data.type && (s.data.w != null || s.data.h != null)) await api.req('PATCH', `/api/v1/canvas/cards/${n.id}`, { w: s.data.w, h: s.data.h });
        alias.set(s.id, n.id);
      }
      for (const l of links) {
        const a = live(l.a), b = live(l.b), to = l.style?.to ? live(l.style.to) : undefined;
        await api.req('POST', `/api/v1/canvases/${canvasId()}/edges`, { a, b, label: l.label, style: { ...l.style, ...(to ? { to } : {}) } }).catch(() => {});
      }
    }, redo: async () => { for (const s of snap) await api.req('DELETE', `/api/v1/canvas/cards/${live(s.id)}`); } });
    await refresh(true);
    select([]);
  }

  async function addEdge(a, b, { label = '', arrow = true } = {}) {
    if (a === b) return null;
    const style = arrow ? { to: b } : {};
    const e = await api.req('POST', `/api/v1/canvases/${canvasId()}/edges`, { a, b, label, style });
    let id = e.id; const pair = [a, b];
    record({ label: 'hubungkan', undo: async () => { await api.req('DELETE', `/api/v1/canvases/${canvasId()}/edges/${id}`); },
      redo: async () => { const n = await api.req('POST', `/api/v1/canvases/${canvasId()}/edges`, { a: live(pair[0]), b: live(pair[1]), label, style }); id = n.id; } });
    await refresh(true);
    return e;
  }
  async function removeEdge(id) {
    const e = edges.find((x) => x.id === id);
    if (!e) return;
    await api.req('DELETE', `/api/v1/canvases/${canvasId()}/edges/${id}`);
    selEdge = null;
    let cur = id;
    record({ label: 'putus garis', undo: async () => { const n = await api.req('POST', `/api/v1/canvases/${canvasId()}/edges`, { a: live(e.a), b: live(e.b), label: e.label, style: { ...e.style, ...(e.style?.to ? { to: live(e.style.to) } : {}) } }); cur = n.id; },
      redo: async () => { await api.req('DELETE', `/api/v1/canvases/${canvasId()}/edges/${cur}`); } });
    await refresh(true);
    emit('selection', selectionInfo());
  }
  async function patchEdge(id, patch, label = 'ubah garis') {
    const e = edges.find((x) => x.id === id);
    if (!e) return;
    const before = { label: e.label, style: { ...e.style } };
    await api.req('PATCH', `/api/v1/canvases/${canvasId()}/edges/${id}`, patch);
    record({ label, undo: () => api.req('PATCH', `/api/v1/canvases/${canvasId()}/edges/${id}`, { label: before.label, style: { dash: !!before.style.dash, color: before.style.color || '#67e8f9', to: before.style.to ?? null } }),
      redo: () => api.req('PATCH', `/api/v1/canvases/${canvasId()}/edges/${id}`, patch) });
    await refresh(true);
  }

  async function duplicate(offset = 28) {
    const list = [...sel].map((id) => cards.get(id)).filter((c) => c && isObj(c));
    if (!list.length) return toast('Hanya catatan, teks, bentuk dan bingkai yang bisa digandakan.');
    const made = [];
    for (const c of list) {
      const r = rectOf(c);
      const n = await api.req('POST', `/api/v1/canvases/${canvasId()}/objects`, { props: { ...c.data.props, locked: false }, x: r.x + offset, z: r.y + offset, w: r.w, h: c.data.h ?? undefined });
      made.push(n);
    }
    record({ label: 'gandakan', undo: async () => { for (const n of made) await api.req('DELETE', `/api/v1/canvas/cards/${live(n.id)}`); },
      redo: async () => { for (let i = 0; i < made.length; i++) { const n = made[i], r = n; const m = await api.req('POST', `/api/v1/canvases/${canvasId()}/objects`, { props: n.props, x: r.x, z: r.z, w: r.w, h: r.h }); alias.set(n.id, m.id); made[i] = { ...n, id: m.id }; } } });
    await refresh(true);
    select(made.map((n) => n.id));
  }
  function copy() { clip = [...sel].map((id) => cards.get(id)).filter((c) => c && isObj(c)).map((c) => ({ props: { ...c.data.props }, ...rectOf(c) })); if (clip.length) toast(`${clip.length} objek disalin.`); }
  async function paste() {
    if (!clip?.length) return;
    const at = worldAt(vp.w / 2, vp.h / 2), b = rectsBounds(clip);
    const ids = [];
    for (const o of clip) { const n = await createObject({ ...o.props, locked: false }, at.x - b.w / 2 + (o.x - b.x), at.y - b.h / 2 + (o.y - b.y), o.w, o.h, { select: false }); ids.push(n.id); }
    select(ids);
  }
  function order(front) {
    for (const id of sel) zOrder.set(id, front ? ++zCounter : -(++zCounter));
    for (const id of sel) place(cards.get(id));
  }
  async function align(mode) {
    const ids = [...sel].filter((id) => !isLocked(cards.get(id)));
    if (ids.length < 2) return;
    const before = snapshotRects(ids), after = alignRects(before, mode);
    await commitLayout(before, after, 'ratakan');
  }
  async function distribute(axis) {
    const ids = [...sel].filter((id) => !isLocked(cards.get(id)));
    if (ids.length < 3) return;
    const before = snapshotRects(ids);
    await commitLayout(before, distributeRects(before, axis), 'sebarkan');
  }
  async function arrange() {
    const list = [...cards.values()].filter((c) => !isObj(c) && !isLocked(c));
    if (!list.length) return toast('Tidak ada kartu yang perlu dirapikan.');
    const before = snapshotRects(list.map((c) => c.data.id));
    await api.req('POST', `/api/v1/canvases/${canvasId()}/arrange`);
    record({ label: 'rapikan', undo: () => pushLayout(before, 'urung rapikan'), redo: () => api.req('POST', `/api/v1/canvases/${canvasId()}/arrange`) });
    await refresh(true);
    fitAll(600);
  }
  async function setGeometry(patch) {   // typed X / Y / W / H of a single card
    const [id] = [...sel];
    const c = cards.get(id);
    if (!c || sel.size !== 1 || isLocked(c)) return;
    const before = snapshotRects([id]), r = rectOf(c);
    const next = { id, x: patch.x ?? r.x, y: patch.y ?? r.y, w: Math.max(60, patch.w ?? r.w), h: Math.max(40, patch.h ?? r.h), sized: true };
    await commitLayout(before, [next], 'atur ukuran');
  }

  // ------------------------------------------------------------ editing text in place
  function startEdit(id) {
    const c = cards.get(id);
    if (!c || !isObj(c) || isLocked(c)) return;
    finishEdit();
    const target = c.el.querySelector(c.data.type === 'frame' ? '.frame-title' : '.txt');
    if (!target) return;
    target.classList.remove('empty');
    target.textContent = textOf(c.data);
    target.contentEditable = 'true'; target.spellcheck = false;
    editing = { id, target, before: textOf(c.data) };
    c.el.classList.add('editing');
    syncSel(); emit('edit', true);
    target.focus();
    const range = document.createRange(); range.selectNodeContents(target);
    const s = getSelection(); s.removeAllRanges(); s.addRange(range);
    target.onkeydown = (ev) => {
      ev.stopPropagation();
      if (ev.key === 'Escape') { ev.preventDefault(); finishEdit(false); }
      else if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey || c.data.type === 'frame')) { ev.preventDefault(); finishEdit(); }
    };
    target.onpaste = (ev) => { ev.preventDefault(); document.execCommand('insertText', false, (ev.clipboardData || window.clipboardData).getData('text/plain')); };
    target.onblur = () => finishEdit();
  }
  function finishEdit(commit = true) {
    if (!editing) return;
    const { id, target, before } = editing; editing = null;
    const c = cards.get(id);
    target.onblur = target.onkeydown = target.onpaste = null;
    target.contentEditable = 'false';
    c?.el.classList.remove('editing');
    const text = commit ? target.innerText.replace(/\n$/, '') : before;
    emit('edit', false);
    if (c) { c.data = { ...c.data, props: { ...c.data.props, text } }; fillCard(c); }
    syncSel();
    if (commit && text !== before) {
      const send = (t) => api.req('PATCH', `/api/v1/canvas/cards/${live(id)}`, { props: { text: t } });
      send(text).then(() => { record({ label: 'ubah teks', undo: () => send(before), redo: () => send(text) }); return refresh(true); }).catch((err) => toast(err.message, true));
    }
  }

  // ------------------------------------------------------------ the pointer
  const edgeHit = (t) => t.closest?.('g.edge');
  const cardHit = (t) => t.closest?.('.card:not(.widget)');
  const holdsPan = () => spaceDown || tool === 'hand';

  stage.addEventListener('pointerdown', (e) => {
    if (e.button === 2) return;
    if (editing && !e.target.closest('.editing')) finishEdit();
    if (e.target.closest('.widget, .selbox .sizebadge, .toolrail, .topbar, .zoombar, .minimap, .inspector, .menu, .palette, .dock')) {
      if (e.target.closest('.widget') && !e.target.closest(INTERACTIVE)) { select([]); }
      return;
    }
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, t: e.pointerType });
    cancelFlight();
    if (pointers.size === 2) { startPinch(); return; }
    if (pointers.size > 2) return;
    const handle = e.target.closest?.('[data-handle]'), conn = e.target.closest?.('[data-conn]');
    const card = cardHit(e.target), edge = edgeHit(e.target);
    const interactive = e.target.closest?.(INTERACTIVE);
    if (interactive && card && !card.classList.contains('editing')) { if (!sel.has(card.__card.data.id)) select([card.__card.data.id]); return; }
    if (e.target.closest('.editing')) return;
    try { stage.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
    const start = stagePoint(e), w0 = worldAt(start.x, start.y);
    const base = { id: e.pointerId, sx: start.x, sy: start.y, w0, moved: false, shift: e.shiftKey, t: e.pointerType, button: e.button };

    if (e.button === 1 || holdsPan()) { gesture = { ...base, mode: 'pan', view0: { ...view } }; stage.classList.add('panning'); return; }
    if (handle) { startResize(base, handle.dataset.handle); return; }
    if (tool === 'connector' && card) { startWire(base, card.__card.data.id); return; }
    if (['note', 'text', 'shape', 'frame'].includes(tool)) { gesture = { ...base, mode: 'draw' }; return; }
    if (edge) { selectEdge(Number(edge.dataset.id)); gesture = { ...base, mode: 'none' }; return; }
    if (card) {
      const c = card.__card, id = c.data.id;
      if (e.shiftKey) { if (sel.has(id)) { sel.delete(id); select([...sel]); } else select([id], { add: true }); gesture = { ...base, mode: 'none' }; return; }
      if (!sel.has(id)) select([id]);
      if (isLocked(c)) { gesture = { ...base, mode: 'none' }; return; }
      startMove(base, c);
      return;
    }
    // empty paper: a touch drags the paper; a mouse draws the marquee
    if (e.pointerType === 'touch') { gesture = { ...base, mode: 'pan', view0: { ...view }, tapClear: true }; return; }
    gesture = { ...base, mode: 'marquee', prior: e.shiftKey ? new Set(sel) : new Set() };
    if (!e.shiftKey) select([]);
  });

  stage.addEventListener('pointermove', (e) => {
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, t: e.pointerType });
    if (gesture?.mode === 'pinch') return pinchMove();
    ctx.onPointer?.(worldAt(stagePoint(e).x, stagePoint(e).y));
    if (!gesture || gesture.id !== e.pointerId) { hoverConnectors(e); return; }
    const p = stagePoint(e), dx = p.x - gesture.sx, dy = p.y - gesture.sy;
    if (!gesture.moved && Math.hypot(dx, dy) < (gesture.t === 'touch' ? 8 : 3)) return;
    gesture.moved = true;
    const m = gesture.mode;
    if (m === 'pan') setView({ ...panBy(gesture.view0, dx, dy) });
    else if (m === 'move') moveTo(dx / view.k, dy / view.k, e);
    else if (m === 'resize') resizeTo(dx / view.k, dy / view.k, e);
    else if (m === 'marquee') marqueeTo(p);
    else if (m === 'draw') drawTo(p);
    else if (m === 'wire') wireTo(p);
  });

  const end = (e) => {
    const had = pointers.delete(e.pointerId);
    if (gesture?.mode === 'pinch') { if (pointers.size < 2) gesture = null; return; }
    if (!gesture || gesture.id !== e.pointerId) return;
    const g = gesture; gesture = null;
    stage.classList.remove('panning');
    try { stage.releasePointerCapture(e.pointerId); } catch { /* not captured */ }
    guidesEl.replaceChildren();
    if (g.mode === 'move') finishMove(g);
    else if (g.mode === 'resize') finishResize(g);
    else if (g.mode === 'marquee') { marquee.hidden = true; }
    else if (g.mode === 'draw') finishDraw(g, e);
    else if (g.mode === 'wire') finishWire(g, e);
    else if (g.mode === 'pan' && !g.moved && g.tapClear) select([]);
    else if (g.mode === 'none' || !had) { /* a plain click */ }
  };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', end);

  stage.addEventListener('wheel', (e) => {
    if (e.target.closest('.palette, .inspector, .menu, .minimap')) return;
    if (e.target.closest('.widget .pbody, .widget .mbody, .editing')) return;
    e.preventDefault();
    cancelFlight();
    const p = stagePoint(e);
    if (wheelIntent(e) === 'zoom') {
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      zoomBy(Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0016)), p.x, p.y);
    } else setView(panBy(view, -e.deltaX, -e.deltaY));
  }, { passive: false });

  stage.addEventListener('dblclick', (e) => {
    if (e.target.closest('.widget, .toolrail, .topbar, .zoombar, .minimap, .inspector, .menu, .palette, .dock, [data-handle]')) return;
    const card = cardHit(e.target), edge = edgeHit(e.target);
    if (edge) return editEdgeLabel(Number(edge.dataset.id), stagePoint(e));
    if (card) {
      const c = card.__card;
      if (isObj(c)) { if (c.data.type !== 'frame' || e.target.closest('.frame-title')) startEdit(c.data.id); return; }
      focusRect(rectOf(c), 1, 600); return;
    }
    const p = worldAt(stagePoint(e).x, stagePoint(e).y);
    createObject({ type: 'note', text: '', color: NOTE_DEFAULT }, p.x - 110, p.y - 90, undefined, undefined, { edit: true }).catch((err) => toast(err.message, true));
  });

  stage.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    if (e.target.closest('.toolrail, .topbar, .zoombar, .minimap, .inspector, .menu, .palette, .dock')) return;
    const card = cardHit(e.target), edge = edgeHit(e.target);
    if (card && !sel.has(card.__card.data.id)) select([card.__card.data.id]);
    if (edge) selectEdge(Number(edge.dataset.id));
    const p = stagePoint(e);
    ctx.contextMenu?.({ x: e.clientX, y: e.clientY, world: worldAt(p.x, p.y), card: card?.__card, edge: !!edge });
  });

  // a long press on a touch screen is the right click
  let press = null;
  stage.addEventListener('pointerdown', (e) => {
    if (e.pointerType !== 'touch') return;
    press = setTimeout(() => { if (gesture && !gesture.moved && pointers.size === 1) { const card = cardHit(e.target); const p = stagePoint(e);
      if (card && !sel.has(card.__card.data.id)) select([card.__card.data.id]);
      gesture = null; navigator.vibrate?.(10);
      ctx.contextMenu?.({ x: e.clientX, y: e.clientY, world: worldAt(p.x, p.y), card: card?.__card, edge: false }); } }, 520);
  });
  stage.addEventListener('pointerup', () => clearTimeout(press));
  stage.addEventListener('pointermove', () => { if (gesture?.moved) clearTimeout(press); });

  // pinch: two fingers zoom and pan together
  function startPinch() {
    const [a, b] = [...pointers.values()];
    gesture = { mode: 'pinch', d: Math.hypot(a.x - b.x, a.y - b.y) || 1, c: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } };
    marquee.hidden = true; ghost.hidden = true;
  }
  function pinchMove() {
    const [a, b] = [...pointers.values()];
    if (!b) return;
    const d = Math.hypot(a.x - b.x, a.y - b.y) || 1, c = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const r = stage.getBoundingClientRect();
    let v = zoomAt(view, vp, d / gesture.d, c.x - r.left, c.y - r.top);
    v = panBy(v, c.x - gesture.c.x, c.y - gesture.c.y);
    view = v; applyView();
    gesture.d = d; gesture.c = c;
  }

  // ---- moving
  function startMove(base, c) {
    const ids = [...sel].filter((id) => !isLocked(cards.get(id)));
    // moving a frame carries the cards that sit inside it
    const carried = new Set(ids);
    for (const id of ids) {
      const f = cards.get(id);
      if (f.data.type !== 'frame') continue;
      const fr = rectOf(f);
      for (const o of cards.values()) { if (carried.has(o.data.id) || isLocked(o)) continue; const r = rectOf(o); if (r.x >= fr.x && r.y >= fr.y && r.x + r.w <= fr.x + fr.w && r.y + r.h <= fr.y + fr.h) carried.add(o.data.id); }
    }
    const list = [...carried];
    list.forEach((id) => dragging.add(id));
    const rects = snapshotRects(list);
    const bounds = rectsBounds(rects);
    const others = [...cards.values()].filter((o) => !carried.has(o.data.id) && !o.el.classList.contains('off') && !o.el.classList.contains('hidden-kind')).map(rectOf).slice(0, 300);
    gesture = { ...base, mode: 'move', list, rects, bounds, others };
  }
  function moveTo(dx, dy, e) {
    const g = gesture;
    if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }   // Shift keeps one axis
    let nb = { ...g.bounds, x: g.bounds.x + dx, y: g.bounds.y + dy };
    guidesEl.replaceChildren();
    if (snapOn) { nb = { ...nb, x: snapValue(nb.x, GRID), y: snapValue(nb.y, GRID) }; }
    else if (guidesOn && !e.altKey) {
      const s = snapRect(nb, g.others, 7 / view.k);
      nb = { ...nb, x: nb.x + s.dx, y: nb.y + s.dy };
      for (const l of s.guides) drawGuide(l);
    }
    const ox = nb.x - g.bounds.x, oy = nb.y - g.bounds.y;
    for (const r of g.rects) { const c = cards.get(r.id); c.data = { ...c.data, x: r.x + ox, z: r.y + oy }; place(c); }
    g.delta = { x: ox, y: oy };
    scheduleEdges(); syncSel();
  }
  function drawGuide(l) {
    const a = toScreen(view, vp, l.axis === 'x' ? l.at : l.from, l.axis === 'x' ? l.from : l.at), b = toScreen(view, vp, l.axis === 'x' ? l.at : l.to, l.axis === 'x' ? l.to : l.at);
    guidesEl.append(sv('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y }));
  }
  function finishMove(g) {
    g.list.forEach((id) => dragging.delete(id));
    if (!g.moved || !g.delta || (!g.delta.x && !g.delta.y)) { cull(); return; }
    const after = g.rects.map((r) => ({ ...r, x: r.x + g.delta.x, y: r.y + g.delta.y }));
    commitLayout(g.rects, after, g.list.length > 1 ? `pindah ${g.list.length} kartu` : 'pindah kartu').catch((err) => { toast(err.message, true); refresh(true); });
  }

  // ---- resizing
  function startResize(base, handle) {
    const [id] = [...sel], c = cards.get(id);
    if (!c || sel.size !== 1 || isLocked(c)) return;
    dragging.add(id);
    gesture = { ...base, mode: 'resize', id2: id, handle, r0: rectOf(c), hadSized: c.data.w != null || c.data.h != null };
  }
  function resizeTo(dx, dy, e) {
    const g = gesture, c = cards.get(g.id2);
    const isText = c.data.type === 'text';
    let r = resizeRect(g.r0, g.handle, dx, dy, { ratio: e.shiftKey && g.handle.length === 2, center: e.altKey, min: [isText ? 80 : 60, 40] });
    if (snapOn) { r = { x: snapValue(r.x, GRID), y: snapValue(r.y, GRID), w: Math.max(60, snapValue(r.w, GRID)), h: Math.max(40, snapValue(r.h, GRID)) }; }
    c.data = { ...c.data, x: r.x, z: r.y, w: r.w, h: isText && !g.handle.match(/[ns]/) ? c.data.h : r.h };
    place(c); g.last = r; scheduleEdges(); syncSel();
  }
  function finishResize(g) {
    dragging.delete(g.id2);
    if (!g.moved || !g.last) return;
    const c = cards.get(g.id2);
    const before = [{ id: g.id2, ...g.r0, sized: g.hadSized }], after = [{ id: g.id2, ...g.last, sized: true }];
    commitLayout(before, after, 'ubah ukuran').catch((err) => { toast(err.message, true); refresh(true); });
  }

  // ---- marquee
  function marqueeTo(p) {
    const g = gesture, x = Math.min(g.sx, p.x), y = Math.min(g.sy, p.y), w = Math.abs(p.x - g.sx), h = Math.abs(p.y - g.sy);
    marquee.hidden = false;
    Object.assign(marquee.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
    const a = worldAt(x, y), b = worldAt(x + w, y + h), box = { x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y };
    const hit = [...cards.values()].filter((c) => !c.el.classList.contains('hidden-kind') && (c.data.type === 'frame' ? contains(box, rectOf(c)) : rectsIntersect(box, rectOf(c)))).map((c) => c.data.id);
    for (const c of cards.values()) c.el.classList.toggle('selected', g.prior.has(c.data.id) || hit.includes(c.data.id));
    g.hits = new Set([...g.prior, ...hit]);
    sel.clear(); g.hits.forEach((id) => sel.add(id));
    syncSel(); emit('selection', selectionInfo());
  }
  const contains = (o, i) => i.x >= o.x && i.y >= o.y && i.x + i.w <= o.x + o.w && i.y + i.h <= o.y + o.h;

  // ---- drawing a new object by dragging its size
  function drawTo(p) {
    const g = gesture, x = Math.min(g.sx, p.x), y = Math.min(g.sy, p.y), w = Math.abs(p.x - g.sx), h = Math.abs(p.y - g.sy);
    ghost.hidden = false; ghost.dataset.kind = tool;
    Object.assign(ghost.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
  }
  function finishDraw(g, e) {
    ghost.hidden = true;
    const p = stagePoint(e), a = worldAt(Math.min(g.sx, p.x), Math.min(g.sy, p.y)), b = worldAt(Math.max(g.sx, p.x), Math.max(g.sy, p.y));
    const kind = tool, dragged = g.moved && (b.x - a.x) * view.k > 24 && (b.y - a.y) * view.k > 18;
    const props = kind === 'note' ? { type: 'note', text: '', color: NOTE_DEFAULT } : kind === 'text' ? { type: 'text', text: '' }
      : kind === 'shape' ? { type: 'shape', shape: shapeKind, text: '', color: '#93c5fd' } : { type: 'frame', text: 'Bingkai', color: '#94a3b8' };
    const dflt = { note: [220, 180], text: [240, 60], shape: [180, 120], frame: [560, 380] }[kind];
    const w = dragged ? b.x - a.x : dflt[0], h = dragged ? b.y - a.y : dflt[1];
    const x = dragged ? a.x : g.w0.x - w / 2, y = dragged ? a.y : g.w0.y - h / 2;
    setTool('select');
    createObject(props, x, y, w, h, { edit: true }).catch((err) => toast(err.message, true));
  }

  // ---- connectors: drag from a side dot (or from any card with the connector tool) to another card — or to empty paper for a new note
  function hoverConnectors(e) {
    if (coarse || gesture || tool === 'hand' || tool === 'connector') return;
    if (e.target.closest?.('.dots')) return;
    const card = cardHit(e.target);
    if (hoverCard === card) return;
    hoverCard = card;
    showDots();
  }
  let hoverCard = null;
  function showDots() {
    dotsEl.replaceChildren();
    const c = hoverCard?.__card;
    if (!c || isObj(c) && c.data.type === 'frame' || editing || dragging.size) return;
    const r = rectOf(c);
    for (const s of ['n', 'e', 's', 'w']) {
      const p = toScreen(view, vp, s === 'e' ? r.x + r.w : s === 'w' ? r.x : r.x + r.w / 2, s === 'n' ? r.y : s === 's' ? r.y + r.h : r.y + r.h / 2);
      const d = el('i', 'conn'); d.dataset.conn = s; d.dataset.card = c.data.id; d.style.left = `${p.x}px`; d.style.top = `${p.y}px`;
      dotsEl.append(d);
    }
  }
  stage.addEventListener('pointerdown', (e) => {
    const dot = e.target.closest?.('[data-conn]');
    if (!dot || e.button !== 0) return;
    e.stopImmediatePropagation(); e.preventDefault();
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, t: e.pointerType });
    try { stage.setPointerCapture(e.pointerId); } catch { /* synthetic */ }
    const p = stagePoint(e);
    dotsEl.replaceChildren();
    startWire({ id: e.pointerId, sx: p.x, sy: p.y, w0: worldAt(p.x, p.y), moved: false, t: e.pointerType }, Number(dot.dataset.card));
  }, true);
  function startWire(base, fromId) { gesture = { ...base, mode: 'wire', from: fromId }; }
  function wireTo(p) {
    const c = cards.get(gesture.from), r = rectOf(c), a = toScreen(view, vp, r.x + r.w / 2, r.y + r.h / 2);
    wire.replaceChildren(sv('line', { x1: a.x, y1: a.y, x2: p.x, y2: p.y }), sv('circle', { cx: p.x, cy: p.y, r: 5 }));
  }
  async function finishWire(g, e) {
    wire.replaceChildren();
    if (!g.moved) return;
    const under = document.elementsFromPoint(e.clientX, e.clientY).map((n) => n.closest?.('.card:not(.widget)')).find(Boolean);
    try {
      if (under && under.__card.data.id !== g.from) { await addEdge(g.from, under.__card.data.id); select([under.__card.data.id]); }
      else if (!under) {
        const p = stagePoint(e), w = worldAt(p.x, p.y);
        const n = await createObject({ type: 'note', text: '', color: NOTE_DEFAULT }, w.x - 20, w.y - 90, undefined, undefined, { select: true, edit: true, record: false });
        await addEdge(g.from, n.id);
      }
    } catch (err) { toast(err.message, true); }
  }
  async function editEdgeLabel(id, at) {
    const e = edges.find((x) => x.id === id);
    if (!e) return;
    const inp = el('input', 'edge-input'); inp.value = e.label || ''; inp.placeholder = 'Label garis'; inp.maxLength = 60;
    Object.assign(inp.style, { left: `${at.x}px`, top: `${at.y}px` });
    stage.append(inp); inp.focus(); inp.select();
    const done = (save) => { if (!inp.isConnected) return; const v = inp.value.trim(); inp.remove(); if (save && v !== (e.label || '')) patchEdge(id, { label: v }, 'ubah label').catch((err) => toast(err.message, true)); };
    inp.addEventListener('keydown', (ev) => { ev.stopPropagation(); if (ev.key === 'Enter') done(true); if (ev.key === 'Escape') done(false); });
    inp.addEventListener('blur', () => done(true));
  }

  // ------------------------------------------------------------ keyboard
  function typing(t) { return t && (t.closest?.('input, textarea, select') || t.isContentEditable); }
  addEventListener('keydown', (e) => {
    if (e.key === ' ' && !typing(e.target)) { spaceDown = true; stage.classList.add('hand'); e.preventDefault(); }
    if (typing(e.target) || document.body.classList.contains('taking')) return;
    const mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
    if (mod && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (mod && k === 'y') { e.preventDefault(); redo(); return; }
    if (mod && k === 'a') { e.preventDefault(); select([...cards.keys()].filter((id) => !cards.get(id).el.classList.contains('hidden-kind'))); return; }
    if (mod && k === 'd') { e.preventDefault(); duplicate(); return; }
    if (mod && k === 'c') { copy(); return; }
    if (mod && k === 'v') { paste(); return; }
    if (mod && k === 'l') { e.preventDefault(); const ids = [...sel]; if (ids.length) setPinned(ids, !ids.every((id) => isLocked(cards.get(id)))); return; }
    if (mod) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); removeSelection().catch((err) => toast(err.message, true)); return; }
    if (e.key === 'Escape') { if (tool !== 'select') setTool('select'); else { select([]); selEdge = null; } return; }
    if (e.key === 'Enter' && sel.size === 1) { startEdit([...sel][0]); e.preventDefault(); return; }
    if (e.key.startsWith('Arrow') && sel.size) {
      e.preventDefault();
      const d = e.shiftKey ? 10 : 1, dx = e.key === 'ArrowLeft' ? -d : e.key === 'ArrowRight' ? d : 0, dy = e.key === 'ArrowUp' ? -d : e.key === 'ArrowDown' ? d : 0;
      const before = snapshotRects([...sel].filter((id) => !isLocked(cards.get(id))));
      if (before.length) nudge(before, dx, dy);
      return;
    }
    if (e.shiftKey && e.code === 'Digit1') { fitAll(420); return; }
    if (e.shiftKey && e.code === 'Digit2') { fitSelection(420); return; }
    if (e.key === '0') { zoomTo(1); return; }
    if (e.key === '+' || e.key === '=') { zoomBy(1.25, undefined, undefined, 160); return; }
    if (e.key === '-' || e.key === '_') { zoomBy(0.8, undefined, undefined, 160); return; }
    if (e.key === '[') { order(false); return; }
    if (e.key === ']') { order(true); return; }
    const map = { v: 'select', h: 'hand', n: 'note', t: 'text', r: 'shape', f: 'frame', c: 'connector' };
    if (map[k]) setTool(map[k]);
    else if (k === 'o') { shapeKind = 'ellipse'; setTool('shape'); }
  });
  addEventListener('keyup', (e) => { if (e.key === ' ') { spaceDown = false; stage.classList.remove('hand'); } });
  let nudgeTimer = null, nudgeBase = null;
  function nudge(before, dx, dy) {
    if (!nudgeBase) nudgeBase = before;
    for (const r of before) { const c = cards.get(r.id); c.data = { ...c.data, x: c.data.x + dx, z: c.data.z + dy }; place(c); }
    drawEdges(); syncSel();
    clearTimeout(nudgeTimer);
    nudgeTimer = setTimeout(() => {   // arrow keys pile up into one history entry
      const base = nudgeBase; nudgeBase = null;
      const after = base.map((r) => ({ ...r, x: cards.get(r.id).data.x, y: cards.get(r.id).data.z }));
      commitLayout(base, after, 'geser dengan tombol').catch((err) => { toast(err.message, true); refresh(true); });
    }, 450);
  }

  function setTool(t) {
    if (t === tool) return;
    finishEdit();
    tool = t; stage.dataset.tool = t;
    if (t !== 'select') { selBox.hidden = true; } else syncSel();
    hoverCard = null; dotsEl.replaceChildren();
    emit('tool', tool);
  }

  addEventListener('beforeunload', () => finishEdit());

  // ------------------------------------------------------------ the public face
  return {
    stage, cards, widgets, insets,
    get view() { return view; }, get vp() { return vp; }, get tool() { return tool; }, get shapeKind() { return shapeKind; },
    get sel() { return sel; }, get edges() { return edges; }, get zones() { return zones; }, get settings() { return { snapOn, guidesOn, gridOn, edgesOn, zonesOn, hiddenKinds }; },
    on(kind, fn) { on[kind].push(fn); return () => { on[kind] = on[kind].filter((f) => f !== fn); }; },
    setContent, setWidget, setView, fit, fitAll, fitSelection, focusRect, zoomBy, zoomTo, worldAt, rectOf, widgetRect,
    flyToCard(id, k = 0.9, ms = 700) { const c = cards.get(id); if (c) focusRect(rectOf(c), k, ms); },
    flyToPoint(x, y, k = 0.8, ms = 800) { setView({ cx: x, cy: y, k }, ms); },
    select, selectEdge, setTool, setShape(s) { shapeKind = s; setTool('shape'); },
    selectionInfo, histState, undo, redo, record,
    createObject, arrange, setProps, setPinned, removeSelection, removeEdge, patchEdge, duplicate, copy, paste, order, align, distribute, setGeometry, startEdit, addEdge,
    isObj, isLocked,
    setSnap(v) { snapOn = v; emit('tool', tool); }, setGuides(v) { guidesOn = v; emit('tool', tool); },
    setGrid(v) { gridOn = v; stage.classList.toggle('nogrid', !v); emit('tool', tool); },
    setEdgesVisible(v) { edgesOn = v; svg.style.display = v ? '' : 'none'; if (v) drawEdges(); emit('tool', tool); },
    setZones(v) { zonesOn = v; zonesEl.style.display = v ? '' : 'none'; emit('tool', tool); },
    setKindHidden(kind, hide) {
      if (hide) hiddenKinds.add(kind); else hiddenKinds.delete(kind);
      for (const c of cards.values()) c.el.classList.toggle('hidden-kind', hiddenKinds.has(c.data.kind));
      drawEdges(); emit('tool', tool);
    },
    /** The hand-tracking gestures (and tests) speak in pointer events: this turns a screen point into one. */
    pointerEvent(type, x, y, id = 99) {
      const target = document.elementFromPoint(x, y) || stage;
      target.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: id, pointerType: 'mouse', button: 0, buttons: type === 'pointerup' ? 0 : 1 }));
    },
    panBy(dx, dy) { setView(panBy(view, dx, dy)); },
    dispose() { ro.disconnect(); },
  };
}
