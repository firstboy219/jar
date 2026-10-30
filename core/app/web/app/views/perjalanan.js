// Di jalan / Rencana berubah (mockups 11 & 24): the live trip — each leg with its time, what JARVIS did (reminders, the GoRide it ordered),
// and when the plan changed because the owner was still at the station after his train left.
import { get, go, header, html, icon, loading, on, openApp, post, render, sheet, toast } from '../core.js';
import { rupiah } from '../lib.js';

const hm = (s) => (s || '').replace(':', '.');
const KIND_ICON = { ride: 'car', krl: 'train', walk: 'pin', car: 'car', end: 'check', errand: 'notes' };
let trip = null;

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
    trip = t;
    const replans = t.events.filter((e) => e.kind === 'replan' || e.kind === 'held');
    const d = t.driver;
    root.innerHTML = String(html`${header(t.direction === 'out' ? 'Perjalanan pagi' : 'Perjalanan pulang', { sub: `tiba ${hm(o.arrive)}${o.replanned_from ? ` · dulu ${hm(o.replanned_from)}` : ''}` })}
      <div class="scr">
        ${replans.length ? html`<div class="card amber"><span class="k amber">Rencana berubah</span>${replans.map((e) => html`<p class="sub">${e.at.slice(11, 16)} ${e.text}</p>`)}
          <div class="btns"><button class="btn" data-act="alts">${icon('train', 16)} Opsi lain</button><button class="btn" data-act="tellHome">${icon('chat', 16)} Kabari rumah</button></div></div>` : ''}
        ${(t.kci || []).length ? html`<div class="card amber"><span class="k amber">${icon('train', 14)} Info KCI langsung</span>${t.kci.map((k) => html`<span class="small">${k.at.slice(11, 16)} · ${k.text}</span>`)}
          <span class="small">Dibaca dari situs KCI lewat HP-mu tiap 10 menit selama perjalanan.</span></div>` : ''}
        ${t.ride && !t.ride.ok ? html`<div class="card red"><span class="k" style="color:var(--red-t)">GoRide belum terpesan</span>
          <span class="small">✓ Gojek dibuka di HP</span><span class="small">✕ ${t.ride.error || t.ride.text}</span>
          <div class="btns"><button class="btn primary" data-act="openGojek">Buka Gojek, lanjutkan</button><button class="btn" data-act="rideAgain">Pesan ulang</button><button class="btn ghost" data-act="rideDismiss">Batal</button></div></div>` : ''}
        ${t.ride?.ok ? html`<span class="small t-green2">${icon('check', 12)} ${t.ride.text}</span>` : ''}
        ${o.delay_min ? html`<div class="card red"><span class="ttl">KRL tertahan ±${o.delay_min} menit</span><span class="small">Perkiraan tiba bergeser${o.ride && t.direction === 'back' ? `; GoRide dipesan ${hm(o.ride.order_at)}` : ''}.</span></div>` : ''}
        ${d ? html`<div class="card green"><div class="row sb"><span class="ttl">${icon('car', 16)} ${d.driver || 'Driver'}${d.plate ? ` · ${d.plate}` : ''}</span><span class="mono">${d.eta_min ? `${d.eta_min} mnt` : ''}</span></div>
          <span class="small">${{ coming: 'menuju lokasimu', arrived: 'sudah sampai — temui driver', riding: 'dalam perjalanan', done: 'selesai' }[d.state] || ''}</span></div>` : ''}
        ${(t.errands || []).length ? html`<div class="card amber"><span class="k amber">Titipan</span>${t.errands.map((x) => html`<span class="sub">• ${x}</span>`)}</div>` : ''}
        <div class="steps">${t.steps.map((s, i) => html`<div class="step"><div class="rail"><span class="n ${i < nextIdx || nextIdx === -1 ? 'done' : (i === nextIdx ? 'now' : '')}">${i < nextIdx || nextIdx === -1 ? icon('check', 13) : ''}</span>${i < t.steps.length - 1 ? html`<span class="ln"></span>` : ''}</div>
          <div class="body"><div class="row sb"><span style="font-size:14px;${i === nextIdx ? 'font-weight:600' : ''}">${icon(KIND_ICON[s.kind] || 'pin', 14)} ${s.text}</span><span class="mono" style="font-size:12px">${hm(s.at)}</span></div></div></div>`)}</div>
        ${t.events.length ? html`<details class="card"><summary class="small">Yang sudah JARVIS lakukan (${t.events.length})</summary>${t.events.map((e) => html`<span class="small">• ${e.at.slice(11, 16)} ${e.text}</span>`)}</details>` : ''}
        <div class="btns"><button class="btn danger" data-act="cancel">Batalkan perjalanan</button><button class="btn" data-act="alts">Opsi lain</button></div>
        ${t.direction === 'back' && !replans.length ? html`<button class="btn ghost sm" data-act="tellHome">${icon('chat', 14)} Kabari rumah</button>` : ''}
        <p class="small" style="padding:0 4px">Kalau HP-mu masih di stasiun setelah keretanya berangkat, JARVIS menyusun ulang ke kereta berikutnya dan menggeser GoRide-nya.</p>
      </div>`);
    const off = on('trip', () => render());
    return off;
  },
  actions: {
    async alts() {
      toast('Mencari kereta berikutnya…');
      const a = await get(`/api/v1/app/commute/trip/${trip.id}/alternatives`);
      const v = await sheet(String(html`<span class="ttl">Opsi dari sekarang</span>
        ${a.options.map((o, i) => html`<button class="card" data-close="${i}" style="text-align:left;cursor:pointer"><div class="row sb"><span class="ttl">KRL ${hm(o.dep)}</span><span class="mono">tiba ${hm(o.arrive)}</span></div><span class="small">${o.route} · ±${rupiah(o.cost, true)}</span></button>`)}
        <button class="card" data-close="-1" style="text-align:left;cursor:pointer"><div class="row sb"><span class="ttl">GoCar langsung</span><span class="mono">tiba ${hm(a.car.arrive)}</span></div><span class="small">±${rupiah(a.car.cost, true)} · ${a.car.note}</span></button>
        <button class="btn" data-close="">Tetap rencana ini</button>`));
      if (v === null || v === '' || v === undefined) return;
      await post(`/api/v1/app/commute/trip/${trip.id}/switch`, { index: Number(v) });
      toast('Rencana diganti'); render();
    },
    openGojek() { openApp('gojek', 'Gojek'); },
    async rideAgain() { const r = await post(`/api/v1/app/commute/trip/${trip.id}/ride`); toast(r.status === 'failed' ? 'Belum bisa memesan' : 'Memesan ulang di HP…'); render(); },
    async rideDismiss() { await post(`/api/v1/app/commute/trip/${trip.id}/ride/dismiss`); render(); },
    async tellHome() {
      const r = await post(`/api/v1/app/commute/trip/${trip.id}/tell-home`);
      if (r.sent) return toast(`Terkirim ke ${r.to}`);
      if (navigator.share) { try { await navigator.share({ text: r.text }); return; } catch { /* cancelled */ } }
      try { await navigator.clipboard.writeText(r.text); toast(`Pesan disalin (${r.why})`); } catch { toast(r.text); }
    },
    async cancel() { const { trip } = await get('/api/v1/app/commute/active'); if (trip) await post(`/api/v1/app/commute/trip/${trip.id}/cancel`); toast('Perjalanan dibatalkan.'); go('#/'); },
  },
};
