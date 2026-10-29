// Kalender Islam (mockup 46): today's Hijri date, sunnah fasting, bekam days and feasts ahead (the Kemenag date; feasts await the isbat).
import { get, header, html, loading, put, render, toast } from '../core.js';
import { toggle } from '../ui.js';

const DAY = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
let settings = null;

export default {
  tab: 'beranda',
  async render(root) {
    root.innerHTML = String(html`${header('Kalender Islam')}<div class="scr">${loading()}</div>`);
    const [c, s] = await Promise.all([get('/api/v1/app/ibadah/calendar?days=220'), get('/api/v1/app/settings/ibadah')]);
    settings = s;
    const today = new Date();
    const evs = c.events.filter((e) => !e.weekly || e.date === today.toISOString().slice(0, 10));
    const shown = []; const seen = new Set();
    for (const e of evs) { const k = `${e.kind}:${e.title}:${e.hijri.split(' ').slice(1).join(' ')}`; if (e.kind === 'fast' && e.title === 'Puasa Ayyamul Bidh' && seen.has(k)) continue; seen.add(k); shown.push(e); }
    root.innerHTML = String(html`${header('Kalender Islam')}<div class="scr">
      <div class="card green pad"><span class="small">${today.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</span>
        <span style="font:600 26px var(--f-head)">${c.hijri}</span>
        ${c.today_events.length ? html`<span class="t-green2" style="font-size:13px">Hari ini: ${c.today_events.map((e) => e.title).join(' · ')}</span>` : ''}</div>
      <div class="sec"><span>Yang akan datang</span></div>
      <div class="list">${shown.slice(0, 18).map((e) => { const d = new Date(`${e.date}T00:00:00`); return html`<div class="li">
        <div style="width:66px;display:flex;flex-direction:column"><span class="mono" style="font-size:13px">${d.getDate()} ${MON[d.getMonth()]}</span><span style="font-size:10px;color:var(--mu)">${DAY[(d.getDay() + 6) % 7]} · ${e.hijri.split(' ').slice(0, 2).join(' ')}</span></div>
        <span class="grow" style="font-size:13px">${e.title}${e.kind === 'bekam' && e.best ? ' (Sen/Sel/Kam — paling dianjurkan)' : ''}</span>
        ${e.isbat ? html`<span class="tag">tunggu isbat</span>` : ''}</div>`; })}</div>
      <div class="card"><span class="k muted">Pengingat</span>
        <div class="row sb"><span style="font-size:13px">Puasa sunnah: bangunkan sahur ${settings.sahur_time}</span>${toggle(settings.sahur_reminder, 'toggle', 'data-k="sahur_reminder"')}</div>
        <div class="row sb"><span style="font-size:13px">Hari bekam: ingatkan H-1 (19.00)</span>${toggle(settings.bekam_reminder, 'toggle', 'data-k="bekam_reminder"')}</div></div>
      <p class="small" style="padding:0 4px">Tanggal Hijriah mengikuti kalender Kemenag. Awal Ramadan, Syawal &amp; Dzulhijjah menunggu sidang isbat.</p></div>`);
  },
  actions: {
    async toggle(b) { await put('/api/v1/app/settings/ibadah', { [b.dataset.k]: !settings[b.dataset.k] }); toast('Disimpan.'); render(); },
  },
};
