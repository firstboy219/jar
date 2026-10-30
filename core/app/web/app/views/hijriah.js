// Kalender Islam (mockup 46): today's Hijri date, sunnah fasting, bekam days and feasts ahead (the Kemenag date; feasts await the isbat).
import { get, header, html, loading, put, render, toast } from '../core.js';
import { toggle } from '../ui.js';

const DAY = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
let settings = null, monthOff = 0, showMonth = false;

async function monthGrid() {
  const m = await get(`/api/v1/app/ibadah/month?offset=${monthOff}`);
  const lead = m.days.length ? m.days[0].weekday : 0;
  return html`<div class="card"><div class="row sb"><button class="ib sm" data-act="prev" aria-label="Bulan sebelumnya">‹</button><span class="ttl">${m.title}</span><button class="ib sm" data-act="next" aria-label="Bulan berikutnya">›</button></div>
    <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;text-align:center">${DAY.map((d) => html`<span class="small">${d}</span>`)}
      ${Array.from({ length: lead }, () => html`<span></span>`)}
      ${m.days.map((d) => { const g = new Date(`${d.date}T00:00:00`); const ev = d.events.length; return html`<div ${ev ? html`data-act="day" data-ev="${d.events.join(' · ')}" data-d="${d.day} · ${g.getDate()} ${MON[g.getMonth()]}"` : ''} style="padding:4px 0;border-radius:8px;${ev ? 'cursor:pointer;' : ''}${d.today ? 'background:var(--green-bg);border:1px solid var(--green)' : ''}">
        <div style="font-size:14px;font-weight:600">${d.day}</div><div style="font-size:9px;color:var(--mu)">${g.getDate()} ${MON[g.getMonth()]}</div>${ev ? html`<div style="width:5px;height:5px;border-radius:3px;background:var(--amber);margin:2px auto 0"></div>` : ''}</div>`; })}</div>
    <span class="small"><span style="color:var(--amber)">●</span> ada puasa sunnah / hari besar / hari bekam — ketuk tanggalnya untuk detail</span></div>`;
}

export default {
  tab: 'beranda',
  async render(root, route) {
    if (route?.query?.bulan) showMonth = true;
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
      <button class="btn" data-act="month">${showMonth ? 'Sembunyikan kalender bulan' : 'Lihat sebulan penuh'}</button>
      ${showMonth ? await monthGrid() : ''}
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
    day(b) { toast(`${b.dataset.d}: ${b.dataset.ev}`); },
    month() { showMonth = !showMonth; monthOff = 0; render(); },
    prev() { monthOff -= 1; render(); },
    next() { monthOff += 1; render(); },
    async toggle(b) { await put('/api/v1/app/settings/ibadah', { [b.dataset.k]: !settings[b.dataset.k] }); toast('Disimpan.'); render(); },
  },
};
