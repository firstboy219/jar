// The desk as pages of what JARVIS is doing right now (ADR-082), like Android's app switcher: one page per active thing — the music player,
// a video, a web page / map / document / picture JARVIS showed, a worker's browser, the meeting recorder, projects at work, the workers, the
// dev team. Swipe between them; ▢ shows them all side by side (the "recents" view), a tap opens one full screen. Nothing active → a calm
// empty page. The infinite canvas is still there behind "▦ Kanvas".
//
// The pages HOLD the same live cards the canvas shows (they are moved here, and back when the owner returns to the canvas), so every
// card keeps working exactly as before. `pagesFrom` (pure, unit-tested) decides which pages exist and in what order.

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn, title) => { const b = el('button', cls, text); b.type = 'button'; b.dataset.gesture = 'ok'; if (title) b.title = title; b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(ev); }); return b; };
const BUSY = ['queued', 'running'];
const MEETING_LIVE = ['waiting', 'recording', 'queued', 'transcribing', 'summarizing'];
const DEV_LIVE = ['analysing', 'coding', 'testing', 'reviewing', 'awaiting_owner', 'needs_human'];
const FINAL = ['completed', 'failed', 'cancelled', 'stopped'];

export const PAGE_INFO = {
  station: { icon: '🖥', title: 'Browser pekerja' },
  video: { icon: '🎬', title: 'Video' },
  player: { icon: '🎵', title: 'Musik' },
  web: { icon: '🌐', title: 'Halaman web' },
  map: { icon: '🗺', title: 'Peta' },
  doc: { icon: '📄', title: 'Dokumen' },
  image: { icon: '🖼', title: 'Gambar' },
  text: { icon: '📝', title: 'Catatan' },
  draft: { icon: '✉️', title: 'Draf balasan' },
  meeting: { icon: '🎙', title: 'Rapat' },
  projects: { icon: '🗂', title: 'Proyek' },
  workers: { icon: '👷', title: 'Pekerja' },
  devteam: { icon: '🛠', title: 'Tim Dev' },
};
const SHOWN = ['web', 'map', 'doc', 'image', 'text', 'draft'];

/** The pages there are now, in order (pure; unit-tested). `d` = the desk poll; `extra.projects` = projects at work; `extra.pinned` = a page the
 * owner asked for even though nothing is happening in it (e.g. "🗂 Proyek"). Worker browsers first, then what JARVIS plays or shows, then the work. */
export function pagesFrom(d, extra = {}) {
  const out = [];
  const add = (id, kind, sub = '') => out.push({ id, kind, sub, ...PAGE_INFO[kind] });
  for (const st of d?.stations || []) {
    if (!FINAL.includes(st.status) && (st.browsing || st.has_frame)) add(`station:${st.task_id}`, 'station', st.title || '');
  }
  if (d?.cards?.video) add('video', 'video', d.cards.video.title || '');
  if (d?.player) add('player', 'player', d.player.title || '');
  for (const slot of SHOWN) if (d?.cards?.[slot]) add(slot, slot, d.cards[slot].title || '');
  if (MEETING_LIVE.includes(d?.meeting?.state)) add('meeting', 'meeting', d.meeting.title || '');
  if (extra.projects || extra.pinned === 'projects') add('projects', 'projects', extra.projects ? 'sedang berjalan' : '');
  const busy = (d?.workers || []).filter((w) => BUSY.includes(w.status)).length;
  if (busy) add('workers', 'workers', `${busy} bekerja`);
  if ((d?.devteam?.jobs || []).some((j) => DEV_LIVE.includes(j.status))) add('devteam', 'devteam', 'sedang bekerja');
  return out;
}

/** Which page to show after the list changed: the same one if it is still there, else the newest that appeared, else the nearest (pure). */
export function nextIndex(before, after, currentId) {
  const ids = after.map((p) => p.id);
  if (currentId && ids.includes(currentId)) return ids.indexOf(currentId);
  const fresh = ids.find((id) => !before.includes(id));
  if (fresh) return ids.indexOf(fresh);
  return Math.max(0, Math.min(ids.length - 1, before.indexOf(currentId)));
}

/** Pages whose title or subtitle has every word of the search (pure; unit-tested). */
export function matches(page, query) {
  const words = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
  const hay = `${page.title} ${page.sub || ''}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

/** Can the ✕ on a page's tile close it — and what it does (pure; unit-tested): media and shown pages are closed on the server, a worker's
 * browser is the worker (stopped, after asking), the overviews (projects, workers, dev team) are only hidden here until something changes. */
export function closeKind(page) {
  if (page.kind === 'meeting') return null;
  if (page.kind === 'station') return 'stop';
  if (['projects', 'workers', 'devteam'].includes(page.kind)) return 'hide';
  return 'close';
}

export function createSwitcher({ root, holder, panelOf, stationPage, onMode, onFull, onClose, onNew, toast }) {
  let pages = [], index = 0, full = false, pinned = null, lastTouch = 0, query = '', hidden = new Map();
  // the overview of all pages, like Chrome's tab grid: a "+" (ask Jarvis for something), how many there are, and a search
  const bar = el('div', 'sw-gridbar');
  const plus = button('+', 'sw-plus', () => onNew?.(), 'Minta Jarvis membuka sesuatu');
  const count = el('span', 'sw-count', '0');
  const search = el('input', 'sw-search'); search.placeholder = 'Telusuri halaman'; search.type = 'search';
  search.addEventListener('input', () => { query = search.value; filter(); });
  search.addEventListener('keydown', (e) => e.stopPropagation());
  bar.append(plus, count, search);
  const track = el('div', 'sw-track'), dots = el('div', 'sw-dots'), empty = el('div', 'sw-empty'), none = el('div', 'sw-none muted', 'Tidak ada halaman yang cocok.');
  const nav = el('div', 'sw-nav');
  const prev = button('‹', 'sw-arrow', () => go(index - 1), 'Halaman sebelumnya');
  const all = button('▢', 'sw-recents', () => setFull(!full), 'Lihat semua halaman');
  const next = button('›', 'sw-arrow', () => go(index + 1), 'Halaman berikutnya');
  nav.append(prev, all, next);
  empty.append(el('div', 'sw-empty-icon', '🌙'), el('b', null, 'Tidak ada kegiatan aktif'),
    el('div', 'muted', 'Minta Jarvis memutar musik atau video, membuka halaman web, atau menjalankan proyek — halamannya muncul di sini.'),
    (() => { const r = el('div', 'sw-empty-actions'); r.append(button('＋ Minta Jarvis', 'pbtn', () => onNew?.()), button('🗂 Proyek', 'pbtn', () => pin('projects')),
      ...(onMode ? [button('▦ Kanvas', 'pbtn', () => onMode('kanvas'))] : [])); return r; })());
  none.hidden = true;
  root.append(bar, track, none, empty, dots, nav);
  root.classList.add('grid');
  track.addEventListener('scroll', () => {
    if (!full) return;
    lastTouch = performance.now();
    const i = Math.round(track.scrollLeft / Math.max(1, track.clientWidth));
    if (i !== index && i >= 0 && i < pages.length) { index = i; drawDots(); }
  }, { passive: true });
  track.addEventListener('pointerdown', () => { lastTouch = performance.now(); }, { passive: true });

  function frameOf(p) {
    const f = el('section', 'sw-page'); f.dataset.id = p.id;
    const head = el('div', 'sw-head');
    const x = button('✕', 'sw-x', () => close(p.id), 'Tutup');
    head.append(el('span', 'sw-icon', p.icon), el('b', 'sw-title', p.title), el('span', 'sw-sub muted', p.sub), x);
    const body = el('div', 'sw-body');
    f.append(head, body);
    f.addEventListener('click', (ev) => {   // in the overview a tap opens the page; inside an open page the card works as usual
      if (full || ev.target.closest('.sw-x')) return;
      ev.preventDefault(); ev.stopPropagation();
      index = pages.findIndex((y) => y.id === p.id); setFull(true);
    }, true);
    return f;
  }

  function fill(f, p, i) {
    const body = f.querySelector('.sw-body');
    f.querySelector('.sw-sub').textContent = p.sub;
    f.querySelector('.sw-x').hidden = !closeKind(p);
    f.classList.toggle('current', i === index);
    const content = p.kind === 'station' ? stationPage(Number(p.id.split(':')[1])) : panelOf(p.kind);
    if (content && content.parentNode !== body) { body.replaceChildren(content); content.hidden = false; }
  }

  function close(id) {
    const p = pages.find((y) => y.id === id);
    const how = p && closeKind(p);
    if (!how) return;
    if (how === 'hide') { hidden.set(id, p.sub); refresh(); return; }
    onClose?.(p, how);
  }

  let lastD = null, lastExtra = {};
  function refresh() { if (lastD) update(lastD, lastExtra); }

  function update(d, extra = {}) {
    lastD = d; lastExtra = extra;
    const before = pages.map((p) => p.id), current = pages[index]?.id;
    for (const [id, sub] of hidden) {   // a hidden overview comes back when something in it changed
      const now = pagesFrom(d, { ...extra, pinned }).find((p) => p.id === id);
      if (!now || now.sub !== sub) hidden.delete(id);
    }
    pages = pagesFrom(d, { ...extra, pinned }).filter((p) => !hidden.has(p.id));
    const ids = pages.map((p) => p.id);
    for (const f of [...track.children]) {   // gone: its card goes back to the holder (it stays alive, just unseen)
      if (!ids.includes(f.dataset.id)) { const c = f.querySelector('.sw-body')?.firstElementChild; if (c && !c.classList.contains('sw-station')) holder.append(c); f.remove(); }
    }
    const wanted = nextIndex(before, pages, current);
    const appeared = ids.find((id) => !before.includes(id));
    const jump = wanted !== index || (appeared && performance.now() - lastTouch > 2500);
    index = wanted;
    pages.forEach((p, i) => {
      let f = track.querySelector(`:scope > .sw-page[data-id="${CSS.escape(p.id)}"]`);
      if (!f) f = frameOf(p);
      if (track.children[i] !== f) track.insertBefore(f, track.children[i] || null);
      fill(f, p, i);
    });
    count.textContent = String(pages.length);
    empty.hidden = pages.length > 0;
    nav.hidden = !pages.length;
    bar.hidden = !pages.length;
    if (jump) scrollTo(index, before.length > 0);
    if (!pages.length && full) setFull(false);
    filter(); drawDots();
  }

  function filter() {
    let shown = 0;
    for (const f of track.children) {
      const p = pages.find((y) => y.id === f.dataset.id);
      const ok = full || !p || matches(p, query);
      f.classList.toggle('sw-filtered', !ok); shown += ok ? 1 : 0;
    }
    none.hidden = full || !pages.length || shown > 0;
  }
  function drawDots() {
    dots.replaceChildren(...pages.map((p, i) => button(p.icon, `sw-dot${i === index ? ' on' : ''}`, () => go(i), p.title)));
    prev.disabled = index <= 0; next.disabled = index >= pages.length - 1;
    for (const [i, f] of [...track.children].entries()) f.classList.toggle('current', i === index);
  }
  function scrollTo(i, smooth = true) {
    const f = track.children[i];
    if (!f) return;
    if (full) track.scrollTo({ left: f.offsetLeft, behavior: smooth ? 'smooth' : 'auto' });
    else f.scrollIntoView({ block: 'nearest', behavior: smooth ? 'smooth' : 'auto' });
  }
  function go(i) { if (i < 0 || i >= pages.length) return; index = i; scrollTo(i); drawDots(); }
  function setFull(on) {
    full = !!on && pages.length > 0;
    root.classList.toggle('full', full); root.classList.toggle('grid', !full);
    all.title = full ? 'Lihat semua halaman' : 'Buka halaman ini';
    onFull?.(full);
    filter(); drawDots();
    requestAnimationFrame(() => scrollTo(index, false));
  }
  function pin(kind) { pinned = kind; refresh(); const i = pages.findIndex((p) => p.kind === kind); if (i >= 0) { index = i; setFull(true); } }

  return {
    update,
    /** "🗂 Proyek" from the top bar: show that page even when nothing runs in it. */
    show(kind) { pin(kind); },
    get full() { return full; },
    /** The top bar's ▢ n: all pages ⇄ the open one (the bottom ▢ may be under the chat). */
    toggle() { setFull(!full); },
    get count() { return pages.length; },
    /** The phone's Back: an open page goes back to the overview of all pages. */
    back() { if (full) { setFull(false); return true; } return false; },
    pagesNow: () => pages.map((p) => p.id),
  };
}
