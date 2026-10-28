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

export function createSwitcher({ root, holder, panelOf, stationPage, onMode, onFull, toast }) {
  let pages = [], index = 0, full = false, pinned = null, lastTouch = 0;
  const track = el('div', 'sw-track'), dots = el('div', 'sw-dots'), empty = el('div', 'sw-empty');
  const nav = el('div', 'sw-nav');
  const prev = button('‹', 'sw-arrow', () => go(index - 1), 'Halaman sebelumnya');
  const recents = button('▢', 'sw-recents', () => setFull(!full), 'Semua kegiatan (seperti tombol ▢ di Android)');
  const next = button('›', 'sw-arrow', () => go(index + 1), 'Halaman berikutnya');
  nav.append(prev, recents, next);
  empty.append(el('div', 'sw-empty-icon', '🌙'), el('b', null, 'Tidak ada kegiatan aktif'),
    el('div', 'muted', 'Minta Jarvis memutar musik atau video, membuka halaman web, atau menjalankan proyek — halamannya muncul di sini.'),
    (() => { const r = el('div', 'sw-empty-actions'); r.append(button('🗂 Proyek', 'pbtn', () => pin('projects')), button('▦ Kanvas', 'pbtn', () => onMode('kanvas'))); return r; })());
  root.append(track, empty, dots, nav);
  root.classList.add('recents');
  track.addEventListener('scroll', () => {
    lastTouch = performance.now();
    const w = track.firstElementChild?.getBoundingClientRect().width || track.clientWidth;
    const i = Math.round(track.scrollLeft / Math.max(1, w + (full ? 0 : 14)));
    if (i !== index && i >= 0 && i < pages.length) { index = i; drawDots(); }
  }, { passive: true });
  track.addEventListener('pointerdown', () => { lastTouch = performance.now(); }, { passive: true });

  function frameOf(p) {
    const f = el('section', 'sw-page'); f.dataset.id = p.id;
    const head = el('div', 'sw-head');
    head.append(el('span', 'sw-icon', p.icon), el('b', 'sw-title', p.title), el('span', 'sw-sub muted', p.sub));
    const body = el('div', 'sw-body');
    f.append(head, body);
    f.addEventListener('click', (ev) => {   // in the recents view a tap opens the page; inside an open page the card works as usual
      if (full) return;
      ev.preventDefault(); ev.stopPropagation();
      index = pages.findIndex((x) => x.id === p.id); setFull(true);
    }, true);
    return f;
  }

  function fill(f, p) {
    const body = f.querySelector('.sw-body'), sub = f.querySelector('.sw-sub');
    sub.textContent = p.sub;
    const content = p.kind === 'station' ? stationPage(Number(p.id.split(':')[1])) : panelOf(p.kind);
    if (content && content.parentNode !== body) { body.replaceChildren(content); content.hidden = false; }
  }

  function update(d, extra = {}) {
    const before = pages.map((p) => p.id), current = pages[index]?.id;
    pages = pagesFrom(d, { ...extra, pinned });
    const ids = pages.map((p) => p.id);
    for (const f of [...track.children]) {   // gone: its card goes back to the holder (it stays alive, just unseen)
      if (!ids.includes(f.dataset.id)) { const c = f.querySelector('.sw-body')?.firstElementChild; if (c && !c.classList.contains('sw-station')) holder.append(c); f.remove(); }
    }
    pages.forEach((p, i) => {
      let f = track.querySelector(`:scope > .sw-page[data-id="${CSS.escape(p.id)}"]`);
      if (!f) f = frameOf(p);
      if (track.children[i] !== f) track.insertBefore(f, track.children[i] || null);
      fill(f, p);
    });
    empty.hidden = pages.length > 0;
    nav.hidden = !pages.length;
    const wanted = nextIndex(before, pages, current);
    const appeared = ids.find((id) => !before.includes(id));
    if (wanted !== index || (appeared && performance.now() - lastTouch > 2500)) { index = wanted; scrollTo(index, before.length > 0); }
    if (!pages.length && full) setFull(false);
    drawDots();
  }

  function drawDots() {
    dots.replaceChildren(...pages.map((p, i) => { const b = button(p.icon, `sw-dot${i === index ? ' on' : ''}`, () => go(i), p.title); return b; }));
    prev.disabled = index <= 0; next.disabled = index >= pages.length - 1;
  }
  function scrollTo(i, smooth = true) {
    const f = track.children[i];
    if (f) track.scrollTo({ left: f.offsetLeft - (full ? 0 : (track.clientWidth - f.clientWidth) / 2), behavior: smooth ? 'smooth' : 'auto' });
  }
  function go(i) { if (i < 0 || i >= pages.length) return; index = i; scrollTo(i); drawDots(); }
  function setFull(on) {
    full = !!on && pages.length > 0;
    root.classList.toggle('full', full); root.classList.toggle('recents', !full);
    recents.textContent = full ? '▢' : '⤢';
    recents.title = full ? 'Semua kegiatan (seperti tombol ▢ di Android)' : 'Buka halaman ini';
    onFull?.(full);
    requestAnimationFrame(() => scrollTo(index, false));
  }
  function pin(kind) { pinned = kind; toast?.('Membuka Proyek…'); onMode('geser'); }

  return {
    update,
    /** "🗂 Proyek" from the top bar: show that page even when nothing runs in it. */
    show(kind) { pinned = kind; const i = pages.findIndex((p) => p.kind === kind); if (i >= 0) { go(i); setFull(true); } },
    get full() { return full; },
    back() { if (full) { setFull(false); return true; } return false; },
    pagesNow: () => pages.map((p) => p.id),
  };
}
