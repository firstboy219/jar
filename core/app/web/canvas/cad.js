// The drafting toolkit of the desk (Blueprint v4 Fase 8, ADR-052): tool palette, view cube, navigation bar, layers, properties,
// status bar and command line — the way an AutoCAD user expects to look around a 3D space with a mouse.
// It only changes how the owner LOOKS at the canvas (camera, visibility, measuring) and moves cards the owner drags; like the rest of
// the canvas it never approves, deletes, sends or pays.
import { VIEWS, VIEW_LABEL, boundsOf, cssCubeMatrix, distance3, fitDistance, parseCommand, snapValue } from './lib.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const TOOLS = [
  ['select', '⬚', 'Pilih (V) — klik kartu; tarik kartu untuk memindah'],
  ['orbit', '⟲', 'Orbit (O) — tarik untuk memutar. Shift + tombol tengah juga memutar'],
  ['pan', '✥', 'Geser (P) — tarik untuk menggeser. Tombol tengah juga menggeser'],
  ['zoom', '⌕', 'Zoom seret (Z) — tarik ke atas/bawah. Roda mouse zoom ke arah kursor'],
  ['measure', '⟷', 'Ukur (M) — klik dua kartu: jarak dan selisih X/Y/Z'],
  ['link', '⛓', 'Hubungkan (L) — klik dua kartu untuk menarik garis'],
];
const KEYS = { v: 'select', o: 'orbit', p: 'pan', z: 'zoom', m: 'measure', l: 'link' };
const LS = 'jarvis_canvas_views';
const readViews = () => { try { return JSON.parse(localStorage.getItem(LS) || '{}'); } catch { return {}; } };

export function initCad(ctx) {
  const { THREE, view, layers } = ctx;
  let tool = 'orbit', snap = false, selectedCard = null, measureA = null, linkA = null, lastProps = 0, lastCursor = null, fps = 60, fpsAt = performance.now(), frames = 0;
  const STEP = 50;

  const root = el('div', 'cad');
  document.body.append(root);

  // ---------- tool palette (left) ----------
  const palette = el('div', 'palette');
  const toolButtons = new Map();
  for (const [name, glyph, title] of TOOLS) {
    const b = el('button', 'tb', glyph); b.title = title; b.dataset.gesture = 'ok';
    b.addEventListener('click', () => setTool(name));
    toolButtons.set(name, b); palette.append(b);
  }
  palette.append(el('div', 'sep'));
  const layersBtn = el('button', 'tb', '▤'); layersBtn.title = 'Lapisan (visibilitas)'; layersBtn.dataset.gesture = 'ok';
  const propsBtn = el('button', 'tb', '☰'); propsBtn.title = 'Properti kartu / tampilan'; propsBtn.dataset.gesture = 'ok';
  palette.append(layersBtn, propsBtn);
  root.append(palette);

  function setTool(name) {
    tool = name; measureA = null; linkA = null; clearMeasure();
    toolButtons.forEach((b, k) => b.classList.toggle('on', k === name));
    document.body.dataset.tool = name;
    chips.tool.textContent = TOOLS.find((t) => t[0] === name)[2].split(' — ')[0];
  }

  // ---------- view cube + navigation bar (top right) ----------
  const nav = el('div', 'navcluster');
  const cubeBox = el('div', 'viewcube');
  const scene3d = el('div', 'vc-scene'), cube = el('div', 'vc-cube');
  const FACES = [['top', 'ATAS'], ['bottom', 'BAWAH'], ['front', 'DEPAN'], ['back', 'BELAKANG'], ['right', 'KANAN'], ['left', 'KIRI']];
  for (const [key, label] of FACES) {
    const f = el('div', `vc-face vc-${key}`, label); f.title = `Tampilan ${VIEW_LABEL[key]}`; f.dataset.gesture = 'ok';
    f.addEventListener('click', () => goView(key));
    cube.append(f);
  }
  scene3d.append(cube); cubeBox.append(scene3d);
  const rotL = el('button', 'vc-btn vc-rl', '◀'), rotR = el('button', 'vc-btn vc-rr', '▶'), isoB = el('button', 'vc-btn vc-iso', '◇');
  rotL.title = 'Putar 90° ke kiri'; rotR.title = 'Putar 90° ke kanan'; isoB.title = 'Tampilan isometrik';
  for (const b of [rotL, rotR, isoB]) b.dataset.gesture = 'ok';
  rotL.addEventListener('click', () => ctx.flyView({ theta: view.theta + Math.PI / 2, ms: 500 }));
  rotR.addEventListener('click', () => ctx.flyView({ theta: view.theta - Math.PI / 2, ms: 500 }));
  isoB.addEventListener('click', () => goView('iso'));
  cubeBox.append(rotL, rotR, isoB);

  const navBar = el('div', 'navbar');
  const navBtn = (glyph, title, fn, id) => { const b = el('button', 'tb', glyph); b.title = title; b.dataset.gesture = 'ok'; if (id) b.id = id; b.addEventListener('click', fn); navBar.append(b); return b; };
  navBtn('⌂', 'Home — kembali ke inti', () => ctx.home());
  navBtn('⤢', 'Zoom semua (ZE) — pas ke semua kartu', () => zoomExtents());
  navBtn('◎', 'Zoom ke pilihan (ZS)', () => zoomSelection());
  const projBtn = navBtn('◧', 'Proyeksi: perspektif / ortografik', () => toggleProjection());
  const gridBtn = navBtn('▦', 'Grid lantai', () => toggleGrid());
  const snapBtn = navBtn('⌖', 'Snap ke kelipatan 50 saat memindah kartu', () => toggleSnap());
  nav.append(cubeBox, navBar);
  root.append(nav);

  function goView(key) {
    const v = VIEWS[key];
    if (!v) return;
    ctx.flyView({ theta: v.theta, phi: v.phi, ms: 600 });
  }
  function pointsOf(list) { return list.map((c) => ({ x: c.data.x, y: c.data.y, z: c.data.z })); }
  function zoomExtents() {
    const visible = [...ctx.cards().values()].filter((c) => !layers.hiddenKinds.has(c.data.kind));
    const b = boundsOf(pointsOf(visible));
    ctx.flyView({ target: b, r: fitDistance(b.radius, 60, innerWidth / innerHeight), ms: 800 });
  }
  function zoomSelection() {
    const c = ctx.cards().get(ctx.selected());
    if (!c) return zoomExtents();
    ctx.flyView({ target: c.data, r: 420, ms: 700 });
  }
  function toggleProjection(mode) {
    const next = mode || (ctx.projection() === 'ortho' ? 'persp' : 'ortho');
    ctx.setProjection(next);
    projBtn.classList.toggle('on', next === 'ortho');
    chips.proj.textContent = next === 'ortho' ? 'Ortografik' : 'Perspektif';
  }
  function toggleGrid() { layers.grid = !layers.grid; gridBtn.classList.toggle('on', layers.grid); chips.grid.classList.toggle('on', layers.grid); syncLayerBoxes(); }
  function toggleSnap() { snap = !snap; snapBtn.classList.toggle('on', snap); chips.snap.classList.toggle('on', snap); }

  // ---------- layers panel ----------
  const layersPanel = el('div', 'cadpanel layerspanel'); layersPanel.hidden = true;
  const layerBoxes = new Map();
  function buildLayers() {
    layersPanel.replaceChildren(el('h4', null, 'Lapisan'));
    const row = (key, label, color, get, set) => {
      const l = el('label', 'layerrow'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = get();
      cb.addEventListener('change', () => { set(cb.checked); ctx.rebuildStars(); });
      const dot = el('span', 'ldot'); if (color) dot.style.background = color;
      l.append(cb, dot, el('span', null, label)); layerBoxes.set(key, [cb, get]); layersPanel.append(l);
    };
    for (const c of ctx.contexts()) row(`k:${c.kind}`, c.title, c.color, () => !layers.hiddenKinds.has(c.kind), (on) => { on ? layers.hiddenKinds.delete(c.kind) : layers.hiddenKinds.add(c.kind); });
    layersPanel.append(el('div', 'sep'));
    row('live', 'Stasiun hidup (layar & langkah)', '#4ade80', () => layers.live, (on) => { layers.live = on; document.body.classList.toggle('no-live', !on); });
    row('panels', 'Panel meja (permintaan, n8n, simpanan)', '#67e8f9', () => layers.panels, (on) => { layers.panels = on; });
    row('edges', 'Garis hubung', '#94a3b8', () => layers.edges, (on) => { layers.edges = on; });
    row('stars', 'Bintang kartu', '#facc15', () => layers.stars, (on) => { layers.stars = on; });
    row('galaxy', 'Partikel galaksi', '#a78bfa', () => layers.galaxy, (on) => { layers.galaxy = on; });
    row('grid', 'Grid lantai', '#2f6f9f', () => layers.grid, (on) => { layers.grid = on; gridBtn.classList.toggle('on', on); chips.grid.classList.toggle('on', on); });
  }
  function syncLayerBoxes() { layerBoxes.forEach(([cb, get]) => { cb.checked = get(); }); }
  root.append(layersPanel);
  layersBtn.addEventListener('click', () => { buildLayers(); layersPanel.hidden = !layersPanel.hidden; layersBtn.classList.toggle('on', !layersPanel.hidden); });

  // ---------- properties panel ----------
  const props = el('div', 'cadpanel propspanel'); props.hidden = true;
  root.append(props);
  propsBtn.addEventListener('click', () => { props.hidden = !props.hidden; propsBtn.classList.toggle('on', !props.hidden); renderProps(true); });
  function field(label, input) { const r = el('label', 'prow'); r.append(el('span', null, label), input); return r; }
  function num(value, onchange, step = 1) {
    const i = el('input'); i.type = 'number'; i.step = String(step); i.value = String(Math.round(value * 100) / 100);
    i.addEventListener('change', () => onchange(Number(i.value))); return i;
  }
  async function patch(id, body) {
    try { await ctx.api.req('PATCH', `/api/v1/canvas/cards/${id}`, body); await ctx.refresh(true); } catch (err) { ctx.toast(err.message, true); }
  }
  function renderProps(force = false) {
    if (props.hidden) return;
    if (!force && props.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return;   // never fight the hand typing
    const c = ctx.cards().get(selectedCard);
    props.replaceChildren(el('h4', null, c ? 'Properti kartu' : 'Properti tampilan'));
    if (c) {
      const d = c.data;
      props.append(el('div', 'pline', `${d.kind} · ${d.ref}`), el('div', 'ptitle', d.title || ''));
      props.append(field('X', num(d.x, (v) => patch(d.id, { x: v }))), field('Y', num(d.y, (v) => patch(d.id, { y: v }))), field('Z', num(d.z, (v) => patch(d.id, { z: v }))));
      const size = el('input'); size.type = 'range'; size.min = '0.3'; size.max = '4'; size.step = '0.1'; size.value = String(d.size);
      size.addEventListener('change', () => patch(d.id, { size: Number(size.value) }));
      props.append(field('Ukuran', size));
      const pin = el('input'); pin.type = 'checkbox'; pin.checked = !!d.pinned; pin.addEventListener('change', () => patch(d.id, { pinned: pin.checked }));
      props.append(field('Pin', pin));
      const fly = el('button', null, 'Terbang ke kartu'); fly.addEventListener('click', () => ctx.flyTo(d, 420)); props.append(fly);
    } else {
      props.append(el('div', 'pline', 'Tidak ada kartu dipilih'));
      props.append(field('Proyeksi', el('span', null, ctx.projection() === 'ortho' ? 'ortografik' : 'perspektif')),
        field('Jarak', el('span', null, String(Math.round(view.r)))),
        field('Target', el('span', null, `${Math.round(view.target.x)}, ${Math.round(view.target.y)}, ${Math.round(view.target.z)}`)),
        field('Sudut', el('span', null, `${Math.round((view.theta * 180) / Math.PI)}°, ${Math.round((view.phi * 180) / Math.PI)}°`)));
    }
  }

  // ---------- status bar + command line (bottom) ----------
  const status = el('div', 'statusbar');
  const coords = el('span', 'coords', 'X —  Y 0  Z —');
  const cmd = el('input', 'cmdline'); cmd.placeholder = 'Perintah: top, front, iso, ortho, grid, ze, ukur, layer tugas off, view save A, cari …  (? = bantuan)';
  cmd.autocomplete = 'off'; cmd.spellcheck = false;
  const chipBox = el('span', 'chips');
  const chip = (txt, title, on) => { const c = el('button', 'chip', txt); c.title = title; c.dataset.gesture = 'ok'; c.addEventListener('click', on); chipBox.append(c); return c; };
  const chips = {
    tool: el('span', 'chip static', 'Orbit'),
    proj: chip('Perspektif', 'Ganti proyeksi', () => toggleProjection()),
    grid: chip('Grid', 'Grid lantai', () => toggleGrid()),
    snap: chip('Snap', 'Snap kelipatan 50', () => toggleSnap()),
    fps: el('span', 'chip static', '60 fps'),
  };
  chipBox.prepend(chips.tool); chipBox.append(chips.fps);
  status.append(coords, cmd, chipBox);
  root.append(status);

  function runCommand(text) {
    const c = parseCommand(text);
    const say = (m, bad) => ctx.toast(m, bad);
    switch (c.name) {
      case 'none': return;
      case 'view': goView(c.view); return say(`Tampilan ${VIEW_LABEL[c.view]}.`);
      case 'home': return ctx.home();
      case 'extents': return zoomExtents();
      case 'selection': return zoomSelection();
      case 'projection': return toggleProjection(c.mode);
      case 'grid': return toggleGrid();
      case 'snap': toggleSnap(); return say(snap ? 'Snap nyala (kelipatan 50).' : 'Snap mati.');
      case 'tool': return setTool(c.tool);
      case 'find': return ctx.openFind(c.query);
      case 'layer': {
        const k = ctx.contexts().find((x) => x.kind === c.layer || x.title.toLowerCase() === c.layer);
        if (!k) return say(`Lapisan "${c.layer}" tidak ada. Yang ada: ${ctx.contexts().map((x) => x.kind).join(', ')}.`, true);
        const on = c.on ?? layers.hiddenKinds.has(k.kind);
        on ? layers.hiddenKinds.delete(k.kind) : layers.hiddenKinds.add(k.kind);
        ctx.rebuildStars(); syncLayerBoxes();
        return say(`Lapisan ${k.title}: ${on ? 'tampil' : 'disembunyikan'}.`);
      }
      case 'saveView': {
        const all = readViews();
        all[c.as] = { t: [view.target.x, view.target.y, view.target.z], r: view.r, th: view.theta, ph: view.phi, proj: ctx.projection() };
        try { localStorage.setItem(LS, JSON.stringify(all)); } catch { /* private mode */ }
        return say(`Tampilan "${c.as}" disimpan.`);
      }
      case 'namedView': {
        const v = readViews()[c.as];
        if (!v) return say(`Tampilan "${c.as}" belum disimpan. Yang ada: ${Object.keys(readViews()).join(', ') || '—'}.`, true);
        toggleProjection(v.proj); ctx.flyView({ target: { x: v.t[0], y: v.t[1], z: v.t[2] }, r: v.r, theta: v.th, phi: v.ph, ms: 800 });
        return;
      }
      case 'help': return say('Perintah: top/atas, front/depan, back, left, right, bottom, iso · home · ze (semua) · zs (pilihan) · ortho/persp · grid · snap · orbit/pan/zoom/select/ukur/hubung · layer <nama> on|off · view save <nama> · view <nama> · cari <kata>');
      default: return say('Perintah tidak dikenal. Ketik ? untuk bantuan.', true);
    }
  }
  cmd.addEventListener('keydown', (e) => { if (e.key === 'Enter') { runCommand(cmd.value); cmd.value = ''; } e.stopPropagation(); });
  addEventListener('keydown', (e) => {   // one-letter tool keys, not while typing
    if (e.target.closest?.('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (KEYS[e.key]) setTool(KEYS[e.key]);
    else if (e.key === 'F7') { e.preventDefault(); toggleGrid(); }
    else if (e.key === 'F9') { e.preventDefault(); toggleSnap(); }
    else if (e.key === '/') { e.preventDefault(); cmd.focus(); }
  });

  // ---------- measuring + linking ----------
  const measureLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xfacc15 }));
  measureLine.visible = false; ctx.scene.add(measureLine);
  const measureLabel = el('div', 'measurelabel'); measureLabel.hidden = true; root.append(measureLabel);
  let measureMid = null;
  function clearMeasure() { measureLine.visible = false; measureLabel.hidden = true; measureMid = null; }
  function showMeasure(a, b) {
    const m = distance3(a, b);
    measureLine.geometry.setFromPoints([new THREE.Vector3(a.x, a.y, a.z), new THREE.Vector3(b.x, b.y, b.z)]);
    measureLine.visible = true;
    measureMid = new THREE.Vector3((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2);
    measureLabel.textContent = `${Math.round(m.d)}  (ΔX ${Math.round(m.dx)}, ΔY ${Math.round(m.dy)}, ΔZ ${Math.round(m.dz)})`;
    measureLabel.hidden = false;
  }

  /** A card was clicked while a measuring / linking tool is active. True = handled (do not drag it). */
  function onCardPick(id) {
    const c = ctx.cards().get(id);
    if (!c) return false;
    if (tool === 'measure') {
      if (measureA == null) { measureA = id; clearMeasure(); ctx.toast('Klik kartu kedua untuk mengukur.'); }
      else { showMeasure(ctx.cards().get(measureA).data, c.data); measureA = null; }
      return true;
    }
    if (tool === 'link') {
      if (linkA == null) { linkA = id; ctx.toast('Klik kartu kedua untuk menghubungkan.'); return true; }
      if (linkA === id) { linkA = null; return true; }
      const a = linkA; linkA = null;
      ctx.api.req('POST', `/api/v1/canvases/${ctx.current().id}/edges`, { a, b: id })
        .then(() => { ctx.toast('Dua kartu terhubung.'); return ctx.refresh(true); }).catch((err) => ctx.toast(err.message, true));
      return true;
    }
    return false;
  }

  // ---------- per-frame + pointer ----------
  const ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  function onPointer(x, y) { lastCursor = [x, y]; }
  function updateCoords() {
    if (!lastCursor) return;
    ctx.raycaster.setFromCamera(ctx.ndc(lastCursor[0], lastCursor[1]), ctx.camera());
    const hit = ctx.raycaster.ray.intersectPlane(ground, new THREE.Vector3());
    if (!hit) { coords.textContent = 'X —  Y 0  Z —'; return; }
    const f = (v) => String(Math.round(snap ? snapValue(v, STEP) : v)).padStart(6, ' ');
    coords.textContent = `X ${f(hit.x)}  Y 0  Z ${f(hit.z)}`;
  }
  const tmp = new THREE.Vector3();
  function frame() {
    frames++;
    const now = performance.now();
    if (now - fpsAt > 1000) { fps = Math.round((frames * 1000) / (now - fpsAt)); frames = 0; fpsAt = now; chips.fps.textContent = `${fps} fps`; }
    const cam = ctx.camera();
    cube.style.transform = cssCubeMatrix(cam.matrixWorldInverse.elements);
    updateCoords();
    if (measureMid && !measureLabel.hidden) {
      tmp.copy(measureMid).project(cam);
      const vis = tmp.z < 1 && Math.abs(tmp.x) < 1.1 && Math.abs(tmp.y) < 1.1;
      measureLabel.style.visibility = vis ? 'visible' : 'hidden';
      if (vis) measureLabel.style.transform = `translate(-50%, -50%) translate(${(tmp.x + 1) / 2 * innerWidth}px, ${(1 - tmp.y) / 2 * innerHeight}px)`;
    }
    if (now - lastProps > 600) { lastProps = now; renderProps(false); }
  }

  function onSelect(id) { selectedCard = id; renderProps(true); }

  // snap while dragging a card: the viewer asks before it patches (kept simple: applied on the PATCH body by the drag end)
  setTool('orbit');
  chips.proj.textContent = 'Perspektif';
  return {
    get tool() { return tool; }, get snap() { return snap; }, snapPoint: (p) => (snap ? { x: snapValue(p.x, STEP), y: snapValue(p.y, STEP), z: snapValue(p.z, STEP) } : p),
    onCardPick, onPointer, onSelect, frame, runCommand, setTool,
  };
}
