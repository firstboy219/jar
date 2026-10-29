// Catatan (mockup 16): the owner's tasks — where each came from (a meeting, an email, a mission, the evening recap) — and his notes.
// The full block editor stays the notes page (/notes/), opened from here.
import { empty, get, header, html, icon, loading, patch, post, render, toast } from '../core.js';

const VIEWS = [['all', 'Semua'], ['today', 'Hari ini'], ['week', 'Minggu ini'], ['done', 'Selesai']];
let tab = 'tugas', view = 'all', tasks = [];

function due(d) {
  if (!d) return '';
  const t = new Date(`${d}T00:00:00`), now = new Date();
  const days = Math.round((t - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  if (days === 0) return 'Hari ini';
  if (days === 1) return 'Besok';
  if (days < 0) return `${-days} hr lewat`;
  if (days < 7) return ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'][t.getDay()];
  return `${t.getDate()}/${t.getMonth() + 1}`;
}

function source(t) {
  const k = t.page_kind || '';
  if (k === 'meeting') return html`<span class="tag violet">dari rapat</span>`;
  if (k === 'recap') return html`<span class="tag amber">dari rekap</span>`;
  if (k === 'inbox') return html`<span class="tag">catatan cepat</span>`;
  if (/^(email|whatsapp|wa)\b/i.test(t.page_title || '')) return html`<span class="tag cyan">dari ${t.page_title.slice(0, 24)}</span>`;
  return t.page_title ? html`<span class="tag">${t.page_title.slice(0, 28)}</span>` : '';
}

function taskRow(t) {
  const late = t.due && !t.checked && new Date(`${t.due}T23:59:59`) < new Date();
  return html`<div class="li"><button class="switch ${t.checked ? 'on' : ''}" style="width:24px;height:24px;border-radius:7px;padding:0;align-items:center;justify-content:center;${t.checked ? '' : `background:transparent;border:1.5px solid var(--${late ? 'red' : t.priority === 3 ? 'amber' : 'mu'})`}" data-act="tick" data-page="${t.page_id}" data-id="${t.id}" data-on="${t.checked ? 1 : 0}" aria-label="Selesai">${t.checked ? icon('check', 14, 'var(--bg)') : ''}</button>
    <div class="grow"><div class="ttl" style="font-weight:500;${t.checked ? 'text-decoration:line-through;color:var(--mu)' : ''}">${t.text}</div><div class="row wrap" style="gap:6px;margin-top:4px">${source(t)}${t.who ? html`<span class="tag">${t.who}</span>` : ''}</div></div>
    <span class="mono" style="font-size:11px;color:var(--${late ? 'red-t' : 'amber-t'})">${due(t.due)}</span></div>`;
}

export default {
  tab: 'catatan',
  async render(root, route) {
    tab = route.query.tab || tab;
    root.innerHTML = String(html`${header('Catatan', { back: false, right: html`<a class="btn sm" href="/notes/#tasks/today" target="_self">Buka editor</a>` })}<div class="scr">${loading()}</div>`);
    const tabs = html`<div class="chips">${[['tugas', 'Tugas'], ['catatan', 'Catatan'], ['rekap', 'Rekap harian']].map(([k, l]) => html`<button class="chip ${tab === k ? 'on' : ''}" data-act="tab" data-k="${k}">${l}</button>`)}</div>`;
    const scr = root.querySelector('.scr');
    if (tab === 'tugas') {
      tasks = (await get(`/api/v1/notes/tasks?view=${view}`)).tasks;
      scr.innerHTML = String(html`${tabs}
        <div class="chips">${VIEWS.map(([k, l]) => html`<button class="chip ${view === k ? 'cyan' : ''}" data-act="view" data-k="${k}">${l}</button>`)}</div>
        <form id="qadd" class="cmd" style="height:46px;border-style:dashed">${icon('plus', 18, 'var(--mu)')}<input name="text" placeholder="Tambah tugas, mis. “telepon Pak Budi besok”" style="margin-left:8px"></form>
        ${tasks.length ? html`<div class="list">${tasks.map(taskRow)}</div>` : empty(view === 'done' ? 'Belum ada yang selesai.' : 'Tidak ada tugas di sini.', 'Action plan dari rapat, email, dan rekap malam masuk ke sini sendiri.')}`);
      scr.querySelector('#qadd').addEventListener('submit', async (e) => {
        e.preventDefault();
        const text = e.target.text.value.trim();
        if (!text) return;
        await post('/api/v1/notes/tasks', { text, due: view === 'today' ? new Date().toISOString().slice(0, 10) : null });
        toast('Tugas ditambahkan.');
        render();
      });
    } else {
      const { pages } = await get('/api/v1/notes');
      const want = tab === 'rekap' ? (p) => p.kind === 'recap' : (p) => p.kind !== 'recap';
      const list = (pages || []).filter(want);
      scr.innerHTML = String(html`${tabs}${list.length ? html`<div class="list">${list.map((p) => html`<a class="li click" href="/notes/#page/${p.id}"><span style="font-size:18px">${p.icon || '📄'}</span><div class="grow"><div class="ttl">${p.title || 'Tanpa judul'}</div><div class="small">${p.kind === 'meeting' ? 'notulen rapat' : p.kind === 'recap' ? 'rekap harian' : ''}</div></div>${icon('right', 16)}</a>`)}</div>` : empty(tab === 'rekap' ? 'Belum ada rekap harian.' : 'Belum ada catatan.', tab === 'rekap' ? 'Rekap dibuat saat kamu sampai rumah (atau jam 21.00).' : '')}`);
    }
  },
  actions: {
    tab(b) { tab = b.dataset.k; render(); },
    view(b) { view = b.dataset.k; render(); },
    async tick(b) {
      await patch(`/api/v1/notes/${b.dataset.page}/blocks/${b.dataset.id}`, { checked: b.dataset.on !== '1' });
      render();
    },
  },
};
