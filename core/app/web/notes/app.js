// Catatan & Tugas (ADR-060): the owner's notes, to-dos and meeting minutes — the app's Catatan tab and /notes/ on the web.
// Pages are made of blocks (editor.js); every to-do of every page is also in the task lists; a finished meeting becomes a page of its own.
import { createEditor } from './editor.js';
import { PRIORITY, dueLabel, groupTasks, isoDay, nextPriority, pageLabel, pageTree } from './lib.js';

const $ = (s) => document.querySelector(s);
const PLAIN = (() => { const d = document.createElement('div'); d.contentEditable = 'plaintext-only'; return d.contentEditable === 'plaintext-only' ? 'plaintext-only' : 'true'; })();
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn, title) => { const b = el('button', cls, text); if (title) b.title = title; b.addEventListener('click', (e) => { e.stopPropagation(); fn(e); }); return b; };

// the app passes its device token in the fragment (never sent to a server); a browser shares the desk's sign-in
const hash = location.hash.replace(/^#/, '').split('&');
const embedded = hash.includes('app=1');
const passed = hash.find((p) => p.startsWith('t='));
const TOKEN_KEY = 'jarvis_canvas_token';
const store = { get() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } }, set(v) { try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ } } };
if (passed) store.set(decodeURIComponent(passed.slice(2)));
if (passed || embedded) history.replaceState(null, '', location.pathname + location.search + (hash.filter((p) => !p.startsWith('t=') && p !== 'app=1').join('&') ? `#${hash.filter((p) => !p.startsWith('t=') && p !== 'app=1').join('&')}` : ''));
if (embedded) document.documentElement.classList.add('in-app');

const api = {
  async req(method, path, body) {
    const r = await fetch(path, { method, headers: { Authorization: `Bearer ${store.get()}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined });
    if (r.status === 401 || r.status === 403) { showLogin(r.status === 403); throw new Error('perlu masuk sebagai pemilik'); }
    const data = r.headers.get('content-type')?.includes('json') ? await r.json() : null;
    if (r.status === 409 && data?.stale) { const e = new Error('stale'); e.stale = data.page; throw e; }
    if (!r.ok) throw new Error((data && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))) || `HTTP ${r.status}`);
    return data;
  },
};

function toast(text, bad = false) {
  const t = el('div', `toast${bad ? ' bad' : ''}`, text);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), 3800);
}

function showLogin(notOwner) {
  $('#login').hidden = false;
  $('#login-error').textContent = notOwner ? 'Perangkat ini bukan perangkat pemilik.' : '';
  $('#password').focus();
}
$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const r = await fetch('/api/v1/devices/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: $('#password').value, device_name: 'Catatan (web)' }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'gagal');
    store.set(d.token); $('#password').value = ''; $('#login').hidden = true;
    await loadPages(); route();
  } catch (err) { $('#login-error').textContent = err.message; }
});

// ------------------------------------------------------------------ state

let pages = [], current = null, saving = null, dirty = false, stale = null;
const editor = createEditor({ root: $('#editor'), onChange: () => markDirty(), toast });

function setStatus(text, cls = '') { const s = $('#status'); s.textContent = text; s.className = `status ${cls}`; }

function markDirty() {
  if (!current) return;
  dirty = true; setStatus('Menyimpan…');
  clearTimeout(saving); saving = setTimeout(save, 700);
}

async function save(force = false) {
  if (!current || (!dirty && !force)) return;
  clearTimeout(saving); dirty = false;
  const body = { title: $('#title').textContent.trim(), icon: current.icon || '', blocks: editor.blocks, version: current.version };
  try {
    const p = await api.req('PUT', `/api/v1/notes/${current.id}`, body);
    current.version = p.version; current.title = p.title; stale = null;
    setStatus('Tersimpan', 'ok');
    const row = pages.find((x) => x.id === current.id);
    if (row) { row.title = p.title; row.icon = p.icon; row.updated_at = p.updated_at; renderSidebar(); }
  } catch (err) {
    if (err.stale) { stale = err.stale; dirty = true; showConflict(); return; }
    dirty = true; setStatus('Belum tersimpan — mencoba lagi', 'bad');
    saving = setTimeout(save, 5000);
  }
}
addEventListener('beforeunload', (e) => { if (dirty) { save(); e.preventDefault(); e.returnValue = ''; } });
document.addEventListener('visibilitychange', () => { if (document.hidden) save(); });

function showConflict() {
  setStatus('Diubah di perangkat lain', 'bad');
  const bar = $('#conflict'); bar.hidden = false;
  bar.replaceChildren(el('span', null, 'Halaman ini baru saja diubah di perangkat lain.'),
    button('Muat versi terbaru', 'btn', () => { bar.hidden = true; dirty = false; openPage(stale.id, stale); }),
    button('Simpan versiku', 'btn primary', () => { bar.hidden = true; current.version = stale.version; save(true); }));
}

// ------------------------------------------------------------------ sidebar

async function loadPages() {
  pages = (await api.req('GET', '/api/v1/notes')).pages;
  renderSidebar();
}

function navItem(icon, label, hrefHash, count) {
  const a = el('a', `nav${location.hash === hrefHash ? ' on' : ''}`); a.href = hrefHash;
  a.append(el('span', 'nicon', icon), el('span', 'nlabel', label));
  if (count) a.append(el('span', 'ncount', String(count)));
  a.addEventListener('click', () => { if (innerWidth < 900) document.body.classList.remove('side-open'); });
  return a;
}

function renderSidebar() {
  const open = pages.filter((p) => !p.archived);
  const special = open.filter((p) => p.kind === 'inbox' || p.kind === 'tasks');
  const meetings = open.filter((p) => p.kind === 'meeting');
  const others = open.filter((p) => p.kind === 'page');
  const nav = $('#nav');
  nav.replaceChildren(
    el('div', 'nsec', 'Tugas'),
    navItem('☀️', 'Hari ini', '#tasks/today'), navItem('🗓', '7 hari ke depan', '#tasks/week'), navItem('📋', 'Semua tugas', '#tasks/all'),
    navItem('⏰', 'Terlambat', '#tasks/overdue'), navItem('✔️', 'Selesai', '#tasks/done'),
    el('div', 'nsec', 'Catatan'),
    ...special.map((p) => navItem(p.icon || '📄', pageLabel(p), `#page/${p.id}`, p.open_tasks)),
  );
  const pinned = others.filter((p) => p.pinned);
  if (pinned.length) nav.append(el('div', 'nsec', 'Disematkan'), ...pinned.map((p) => navItem(p.icon || '📄', pageLabel(p), `#page/${p.id}`, p.open_tasks)));
  const sec = el('div', 'nsec'); sec.append(el('span', null, 'Halaman'), button('＋', 'nadd', () => newPage(), 'Halaman baru'));
  nav.append(sec);
  for (const { page: p, depth } of pageTree(others.filter((x) => !x.pinned))) {
    const a = navItem(p.icon || '📄', pageLabel(p), `#page/${p.id}`, p.open_tasks);
    a.style.paddingLeft = `${10 + depth * 14}px`;
    nav.append(a);
  }
  if (!others.length) nav.append(el('div', 'nempty', 'Belum ada halaman.'));
  const ms = el('div', 'nsec'); ms.append(el('span', null, 'Notulen rapat'), button('⤓', 'nadd', () => importMeetings(), 'Impor notulen rapat'));
  nav.append(ms, ...meetings.map((p) => navItem('🎙', pageLabel(p).replace(/^Rapat:\s*/, ''), `#page/${p.id}`, p.open_tasks)));
  if (!meetings.length) nav.append(el('div', 'nempty', 'Notulen rapat yang selesai muncul di sini otomatis.'));
  nav.append(el('div', 'nsec', ''), navItem('🗑', 'Sampah', '#trash'));
}

// ------------------------------------------------------------------ views

function showView(name) {
  for (const v of ['#pageview', '#tasksview', '#trashview', '#searchview']) $(v).hidden = v !== name;
}

async function openPage(id, given) {
  if (current && dirty) await save();
  let p = given;
  try { p ||= await api.req('GET', `/api/v1/notes/${id}`); } catch (err) { toast(err.message, true); return; }
  current = p; dirty = false; stale = null; $('#conflict').hidden = true;
  showView('#pageview');
  $('#icon').textContent = p.icon || '📄';
  $('#title').textContent = p.title || '';
  $('#title').contentEditable = p.kind === 'inbox' || p.kind === 'tasks' ? 'false' : PLAIN;
  $('#crumbs').replaceChildren(...crumbs(p));
  editor.load(p.blocks);
  $('#pin').textContent = p.pinned ? '📌 Disematkan' : '📌 Sematkan';
  $('#pin').hidden = p.kind !== 'page' && p.kind !== 'meeting';
  $('#archive').hidden = p.kind === 'inbox' || p.kind === 'tasks';
  $('#subpage').hidden = p.kind !== 'page';
  setStatus('Tersimpan', 'ok');
  document.title = `${pageLabel(p)} · Catatan`;
  if (!p.blocks.length && p.kind === 'page' && !p.title) $('#title').focus();
}

function crumbs(p) {
  const out = [];
  let x = p;
  const seen = new Set();
  while (x?.parent_id && !seen.has(x.parent_id)) {
    seen.add(x.parent_id);
    const parent = pages.find((q) => q.id === x.parent_id);
    if (!parent) break;
    const a = el('a', null, `${parent.icon || '📄'} ${pageLabel(parent)}`); a.href = `#page/${parent.id}`;
    out.unshift(a, el('span', 'sep', '/'));
    x = parent;
  }
  return out;
}

$('#title').addEventListener('input', () => markDirty());
$('#title').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); editor.focusEnd(); } });
const ICONS = ['📄', '📝', '💡', '📌', '🎯', '📚', '💼', '🏠', '💰', '🧾', '🛒', '✈️', '❤️', '⭐', '🚀', '🛠', '📊', '📅', '🎙', '🧠'];
$('#icon').addEventListener('click', () => {
  if (!current || current.kind === 'inbox' || current.kind === 'tasks') return;
  const m = $('#iconpick'); m.hidden = !m.hidden;
  m.replaceChildren(...ICONS.map((i) => button(i, 'ipick', () => { current.icon = i; $('#icon').textContent = i; m.hidden = true; markDirty(); })));
});
$('#pin').addEventListener('click', async () => {
  try { const p = await api.req('PATCH', `/api/v1/notes/${current.id}`, { pinned: !current.pinned }); current.pinned = p.pinned; $('#pin').textContent = p.pinned ? '📌 Disematkan' : '📌 Sematkan'; await loadPages(); }
  catch (err) { toast(err.message, true); }
});
$('#archive').addEventListener('click', async () => {
  if (!confirm(`Pindahkan "${pageLabel(current)}" ke Sampah?`)) return;
  try { await save(); await api.req('PATCH', `/api/v1/notes/${current.id}`, { archived: true }); current = null; await loadPages(); location.hash = '#tasks/today'; toast('Dipindah ke Sampah.'); }
  catch (err) { toast(err.message, true); }
});
$('#subpage').addEventListener('click', () => newPage(current?.id));
$('#addtodo').addEventListener('click', () => editor.addTodo());

async function newPage(parent) {
  try {
    const p = await api.req('POST', '/api/v1/notes', { title: '', icon: '📄', parent_id: parent || null, blocks: [] });
    await loadPages();
    location.hash = `#page/${p.id}`;
  } catch (err) { toast(err.message, true); }
}

// ---- task lists

const VIEW_TITLE = { today: '☀️ Hari ini', week: '🗓 7 hari ke depan', all: '📋 Semua tugas', overdue: '⏰ Terlambat', done: '✔️ Selesai' };
let taskView = 'today';
async function openTasks(view) {
  if (current && dirty) await save();
  current = null; taskView = VIEW_TITLE[view] ? view : 'today';
  showView('#tasksview');
  $('#tasks-title').textContent = VIEW_TITLE[taskView];
  document.title = 'Tugas · Catatan';
  await drawTasks();
}

async function drawTasks() {
  const box = $('#tasklist');
  let tasks;
  try { tasks = (await api.req('GET', `/api/v1/notes/tasks?view=${taskView}`)).tasks; } catch (err) { box.replaceChildren(el('div', 'empty', err.message)); return; }
  const groups = groupTasks(tasks);
  if (!groups.length) { box.replaceChildren(el('div', 'empty', taskView === 'done' ? 'Belum ada tugas selesai.' : 'Tidak ada tugas di sini. 🎉')); return; }
  box.replaceChildren(...groups.flatMap((g) => [el('div', `tgroup ${g.key}`, `${g.label} · ${g.items.length}`), ...g.items.map(taskRow)]));
}

function taskRow(t) {
  const r = el('div', `trow${t.checked ? ' done' : ''}`);
  const c = el('input', 'bcheck'); c.type = 'checkbox'; c.checked = t.checked;
  c.addEventListener('change', async () => {
    r.classList.toggle('done', c.checked);
    try { await api.req('PATCH', `/api/v1/notes/${t.page_id}/blocks/${t.id}`, { checked: c.checked }); setTimeout(drawTasks, 600); await loadPages(); }
    catch (err) { c.checked = !c.checked; toast(err.stale ? 'Halaman sedang diubah di perangkat lain — coba lagi.' : err.message, true); }
  });
  const body = el('div', 'tbody');
  body.append(el('div', 'ttext', t.text));
  const meta = el('div', 'tmeta');
  const page = el('a', 'chip', `${t.page_icon || '📄'} ${t.page_title || 'Tanpa judul'}`); page.href = `#page/${t.page_id}`;
  const due = el('label', `chip due${t.due && !t.checked && t.due < isoDay(new Date()) ? ' late' : ''}`, t.due ? `📅 ${dueLabel(t.due)}` : '📅 Tenggat');
  const d = el('input'); d.type = 'date'; d.value = t.due || '';
  d.addEventListener('change', () => patchTask(t, { due: d.value || '' }));
  due.append(d);
  const pr = button(t.priority ? `⚑ ${PRIORITY[t.priority].label}` : '⚑', `chip prio ${PRIORITY[t.priority]?.cls || ''}`, () => patchTask(t, { priority: nextPriority(t.priority) }), 'Prioritas');
  meta.append(due, pr, page);
  if (t.who) meta.append(el('span', 'chip who', `👤 ${t.who}`));
  body.append(meta);
  r.append(c, body);
  return r;
}

async function patchTask(t, change) {
  try { await api.req('PATCH', `/api/v1/notes/${t.page_id}/blocks/${t.id}`, change); await drawTasks(); }
  catch (err) { toast(err.stale ? 'Halaman sedang diubah di perangkat lain — coba lagi.' : err.message, true); }
}

$('#quickadd').addEventListener('submit', async (e) => {
  e.preventDefault();
  const i = $('#quickadd input'), text = i.value.trim();
  if (!text) return;
  const due = taskView === 'today' ? isoDay(new Date()) : undefined;
  try { await api.req('POST', '/api/v1/notes/tasks', { text, ...(due && !/\b(besok|lusa|minggu depan|pekan depan)\b/i.test(text) ? { due } : {}) }); i.value = ''; await drawTasks(); await loadPages(); }
  catch (err) { toast(err.message, true); }
});

// ---- meetings, trash, search

async function importMeetings() {
  let list;
  try { list = (await api.req('GET', '/api/v1/notes/meetings')).meetings; } catch (err) { toast(err.message, true); return; }
  if (!list.length) { toast('Semua notulen rapat sudah ada di Catatan.'); return; }
  const dlg = $('#dialog'); dlg.hidden = false;
  dlg.querySelector('.dbody').replaceChildren(el('h3', null, 'Impor notulen rapat'), el('p', 'muted', 'Ringkasan, keputusan, dan action item (jadi tugas) masuk sebagai halaman.'),
    ...list.map((m) => button(`🎙 ${m.title}${m.done_at ? ` · ${new Date(m.done_at).toLocaleDateString('id-ID')}` : ''}`, 'mrow', async () => {
      try { const p = await api.req('POST', `/api/v1/notes/meetings/${m.id}`); dlg.hidden = true; await loadPages(); location.hash = `#page/${p.id}`; }
      catch (err) { toast(err.message, true); }
    })), button('Tutup', 'btn', () => { dlg.hidden = true; }));
}

async function openTrash() {
  if (current && dirty) await save();
  current = null; showView('#trashview');
  const box = $('#trashlist');
  const list = (await api.req('GET', '/api/v1/notes?archived=true')).pages;
  if (!list.length) { box.replaceChildren(el('div', 'empty', 'Sampah kosong.')); return; }
  box.replaceChildren(...list.map((p) => {
    const r = el('div', 'trow');
    r.append(el('div', 'ttext', `${p.icon || '📄'} ${pageLabel(p)}`),
      button('Pulihkan', 'btn', async () => { await api.req('PATCH', `/api/v1/notes/${p.id}`, { archived: false }); await loadPages(); openTrash(); toast('Dipulihkan.'); }),
      button('Hapus permanen', 'btn bad', async () => { if (confirm('Hapus permanen? Tidak bisa dibatalkan.')) { await api.req('DELETE', `/api/v1/notes/${p.id}`); openTrash(); } }));
    return r;
  }));
}

let searchTimer = null;
$('#search').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  searchTimer = setTimeout(async () => {
    if (q.length < 2) { if (!$('#searchview').hidden) route(); return; }
    const res = (await api.req('GET', `/api/v1/notes/search?q=${encodeURIComponent(q)}`)).results;
    showView('#searchview');
    $('#searchlist').replaceChildren(...(res.length ? res.map((r) => {
      const a = el('a', 'trow'); a.href = `#page/${r.id}`;
      a.append(el('div', 'ttext', `${r.icon || '📄'} ${pageLabel(r)}`), el('div', 'muted', r.hit || ''));
      a.addEventListener('click', () => { $('#search').value = ''; });
      return a;
    }) : [el('div', 'empty', 'Tidak ditemukan.')]));
  }, 250);
});
addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#search').focus(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(true); }
});
$('#menu').addEventListener('click', () => document.body.classList.toggle('side-open'));
$('#scrim').addEventListener('click', () => document.body.classList.remove('side-open'));

// ------------------------------------------------------------------ routing

function route() {
  const [kind, arg] = location.hash.replace(/^#/, '').split('/');
  if (kind === 'page' && arg) openPage(arg);
  else if (kind === 'trash') openTrash();
  else openTasks(kind === 'tasks' ? arg : 'today');
  renderSidebar();
}
addEventListener('hashchange', route);

(async () => {
  if (!store.get()) { showLogin(); return; }
  try { await loadPages(); route(); } catch (err) { if (!/masuk/.test(err.message)) toast(err.message, true); }
})();
