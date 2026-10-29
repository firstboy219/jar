// Di jalan / Rencana berubah (mockups 11 & 24): the live trip — each leg with its time, what JARVIS did (reminders, the GoRide it ordered),
// and when the plan changed because the owner was still at the station after his train left.
import { get, go, header, html, icon, loading, on, post, render, toast } from '../core.js';

const hm = (s) => (s || '').replace(':', '.');
const KIND_ICON = { ride: 'car', krl: 'train', walk: 'pin', car: 'car', end: 'check' };

export default {
  tab: 'beranda',
  feature: 'perjalanan',
  async render(root, route) {
    root.innerHTML = String(html`${header('Di jalan')}<div class="scr">${loading()}</div>`);
    const { trip: t } = await get('/api/v1/app/commute/active');
    if (!t) {
      root.innerHTML = String(html`${header('Di jalan')}<div class="scr"><div class="card"><p>Tidak ada perjalanan yang berjalan.</p>
        <div class="btns"><a class="btn primary" href="#/berangkat">Rencana berangkat</a><a class="btn" href="#/pulang">Rencana pulang</a></div></div></div>`);
      return;
    }
    const o = t.chosen, now = new Date();
    const nowMin = now.getHours() * 60 + now.getMinutes();
    const mins = (s) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5));
    const nextIdx = t.steps.findIndex((s) => mins(s.at) >= nowMin);
    const replans = t.events.filter((e) => e.kind === 'replan');
    root.innerHTML = String(html`${header(t.direction === 'out' ? 'Perjalanan pagi' : 'Perjalanan pulang', { sub: `tiba ${hm(o.arrive)}${o.replanned_from ? ` · dulu ${hm(o.replanned_from)}` : ''}` })}
      <div class="scr">
        ${replans.length ? html`<div class="card amber"><span class="k amber">Rencana berubah</span>${replans.map((e) => html`<p class="sub">${e.text}</p>`)}</div>` : ''}
        <div class="steps">${t.steps.map((s, i) => html`<div class="step"><div class="rail"><span class="n ${i < nextIdx || nextIdx === -1 ? 'done' : (i === nextIdx ? 'now' : '')}">${i < nextIdx || nextIdx === -1 ? icon('check', 13) : ''}</span>${i < t.steps.length - 1 ? html`<span class="ln"></span>` : ''}</div>
          <div class="body"><div class="row sb"><span style="font-size:14px;${i === nextIdx ? 'font-weight:600' : ''}">${icon(KIND_ICON[s.kind] || 'pin', 14)} ${s.text}</span><span class="mono" style="font-size:12px">${hm(s.at)}</span></div></div></div>`)}</div>
        ${t.events.length ? html`<details class="card"><summary class="small">Yang sudah JARVIS lakukan (${t.events.length})</summary>${t.events.map((e) => html`<span class="small">• ${e.at.slice(11, 16)} ${e.text}</span>`)}</details>` : ''}
        <div class="btns"><button class="btn danger" data-act="cancel">Batalkan perjalanan</button><a class="btn" href="#/${t.direction === 'out' ? 'berangkat' : 'pulang'}">Lihat opsi</a></div>
        <p class="small" style="padding:0 4px">Kalau HP-mu masih di stasiun setelah keretanya berangkat, JARVIS menyusun ulang ke kereta berikutnya dan menggeser GoRide-nya.</p>
      </div>`);
    const off = on('trip', () => render());
    return off;
  },
  actions: {
    async cancel() { const { trip } = await get('/api/v1/app/commute/active'); if (trip) await post(`/api/v1/app/commute/trip/${trip.id}/cancel`); toast('Perjalanan dibatalkan.'); go('#/'); },
  },
};
