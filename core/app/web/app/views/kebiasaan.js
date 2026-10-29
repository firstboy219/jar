// Kebiasaan (mockup 23): what JARVIS does on its own — when (a time, arriving or leaving a place) and how (otomatis / tanya dulu / mati);
// suggestions learned from what the owner keeps doing; and his places.
import { get, header, html, icon, loading, post, put, render, sheet, toast } from '../core.js';

const MODES = { auto: ['Otomatis', 'green'], ask: ['Tanya dulu', 'amber'], off: ['Mati', 'muted'] };
const NEXT = { auto: 'ask', ask: 'off', off: 'auto' };
const DAYS = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];
let data = null;

function when(t) {
  if (t.type === 'time') return { top: t.at, sub: t.days?.length === 7 ? 'TIAP HARI' : (t.days?.join() === '0,1,2,3,4' ? 'HARI KERJA' : (t.days || []).map((d) => DAYS[d]).join(' ')) };
  return { top: t.place, sub: t.type === 'arrive' ? 'SAMPAI' : 'KELUAR' };
}

export default {
  tab: 'ingatan',
  async render(root) {
    root.innerHTML = String(html`${header('Kebiasaanmu', { sub: 'dipelajari dari pemakaianmu' })}<div class="scr">${loading()}</div>`);
    data = await get('/api/v1/app/habits');
    const sug = data.habits.filter((h) => h.status === 'suggested');
    const act = data.habits.filter((h) => h.status === 'active');
    root.innerHTML = String(html`${header('Kebiasaanmu', { sub: 'yang JARVIS kerjakan tanpa disuruh', right: html`<button class="ib box" data-act="add" aria-label="Ajari kebiasaan">${icon('plus', 18)}</button>` })}
      <div class="scr">
        ${sug.map((h) => html`<div class="card cyan"><span class="k cyan">Usulan baru</span><span style="font-size:14px">${h.title} — terlihat ${h.seen} dari ${h.of_days} hari kerja.</span>
          <div class="btns"><button class="btn primary" data-act="accept" data-id="${h.id}">Ya, jadikan kebiasaan</button><button class="btn" data-act="reject" data-id="${h.id}" style="flex:0 0 96px">Jangan</button></div></div>`)}
        <div class="list">${act.map((h) => { const w = when(h.trigger); const m = MODES[h.mode]; return html`<div class="li">
          <div style="width:58px;display:flex;flex-direction:column"><span class="mono" style="font-size:13px">${w.top}</span><span style="font-size:10px;letter-spacing:.08em;color:var(--mu)">${w.sub}</span></div>
          <div class="grow"><div class="ttl" style="font-weight:500;font-size:13px">${h.title}</div><div class="small">${h.seen ? `${h.seen} dari ${h.of_days} hari` : (h.source === 'builtin' ? 'bawaan' : h.source)}${h.last_fired ? ` · terakhir ${new Date(h.last_fired).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}` : ''}</div></div>
          <button class="chip" style="color:var(--${m[1] === 'muted' ? 'mu' : m[1]})" data-act="mode" data-id="${h.id}" data-next="${NEXT[h.mode]}">${m[0]}</button></div>`; })}</div>
        <div class="card"><span class="k muted">Tempatmu</span>${data.places.length ? data.places.map((p) => html`<span class="small">${p.name} · ${p.source === 'owner' ? 'diatur kamu' : 'dipelajari dari lokasi'}</span>`) : html`<span class="small">Belum ada. Rumah &amp; kantor dipelajari dari lokasi HP (izinkan lokasi), atau tandai di Kontrol.</span>`}
          <a class="small t-cyan" href="#/kontrol">Atur tempat →</a></div>
        <p class="small" style="padding:0 4px">Ketuk mode untuk ganti: <span class="t-green">Otomatis</span> · <span class="t-amber">Tanya dulu</span> · Mati. Yang menyangkut uang atau HP tetap minta izin sesuai aturanmu. Lokasi rumah &amp; kantor tidak dikirim ke AI.</p>
      </div>`);
  },
  actions: {
    async mode(b) { await put(`/api/v1/app/habits/${b.dataset.id}/mode`, { mode: b.dataset.next }); render(); },
    async accept(b) { await post(`/api/v1/app/habits/${b.dataset.id}/accept`); toast('Kebiasaan ditambahkan.'); render(); },
    async reject(b) { await post(`/api/v1/app/habits/${b.dataset.id}/reject`); toast('Tidak akan diusulkan lagi.'); render(); },
    async add() {
      const opts = Object.entries(data.actions).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
      const r = await sheet(`<form style="display:flex;flex-direction:column;gap:12px"><span class="k cyan">Ajari kebiasaan baru</span>
        <label class="field">Nama<input name="title" required placeholder="mis. Rencana pulang lebih awal tiap Jumat"></label>
        <label class="field">Jam<input name="at" type="time" required value="16:30"></label>
        <label class="field">Hari (0=Sen … 6=Min, pisah koma)<input name="days" value="4"></label>
        <label class="field">Yang dikerjakan<select name="action">${opts}</select></label>
        <label class="field">Mode<select name="mode"><option value="ask">Tanya dulu</option><option value="auto">Otomatis</option></select></label>
        <button class="btn primary">Simpan</button></form>`);
      if (!r?.title) return;
      await post('/api/v1/app/habits', { title: r.title, at: r.at, days: r.days.split(',').map((x) => Number(x.trim())).filter((x) => x >= 0 && x <= 6), action: r.action, mode: r.mode });
      toast('Kebiasaan ditambahkan.'); render();
    },
  },
};
