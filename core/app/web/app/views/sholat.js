// Jadwal sholat (mockup 26): the Kemenag times where the owner is, the next prayer, the qibla, and how each one reminds him.
import { get, header, html, icon, loading, put, render, toast } from '../core.js';

const ORDER = ['subuh', 'terbit', 'dzuhur', 'ashar', 'maghrib', 'isya'];
const MODES = [['adzan', 'adzan'], ['notif', 'notif'], ['getar', 'getar'], ['off', 'mati']];
let st = null;

export default {
  tab: 'beranda',
  async render(root) {
    root.innerHTML = String(html`${header('Jadwal sholat')}<div class="scr">${loading()}</div>`);
    const v = await get('/api/v1/app/ibadah/today');
    st = v;
    const nowIdx = ORDER.indexOf(v.next.name);
    root.innerHTML = String(html`${header('Jadwal sholat', { sub: `${v.city.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())} · ${v.source === 'kemenag' ? 'jadwal Kemenag' : 'hitungan server'} · ${v.hijri}` })}
      <div class="scr">
        <div class="card green pad"><div class="row sb">
          <div style="display:flex;flex-direction:column;gap:4px"><span class="k green">Berikutnya</span>
            <span style="font:600 30px var(--f-head)">${v.next.label} ${v.next.time.replace(':', '.')}</span>
            <span class="sub">${v.next.in_min < 60 ? `${v.next.in_min} menit lagi` : `${Math.floor(v.next.in_min / 60)} jam ${v.next.in_min % 60} menit lagi`}${v.next.tomorrow ? ' (besok)' : ''}</span>
            ${v.quiet ? html`<span class="small t-amber2">Pengingat jadi getar: ${v.quiet}</span>` : ''}</div>
          <div role="img" aria-label="Arah kiblat ${v.qibla} derajat dari utara" style="width:76px;height:76px;border-radius:38px;border:1.5px solid var(--green-bd);position:relative;display:flex;align-items:center;justify-content:center">
            <span style="position:absolute;top:3px;font-size:10px;color:var(--mu)">U</span>
            <svg width="40" height="40" viewBox="0 0 40 40" style="transform:rotate(${v.qibla}deg)" aria-hidden="true"><path d="M20 4 26 22H14z" fill="#3DDC97"/><path d="M20 36 14 22h12z" fill="#2A3A50"/></svg>
            <span style="position:absolute;bottom:-18px;font-size:10px;color:var(--mu)">kiblat ${Math.round(v.qibla)}°</span></div>
        </div></div>
        <div class="list" style="margin-top:8px">${ORDER.filter((k) => v.times[k]).map((k, i) => html`<div class="li" style="${i === nowIdx ? 'background:var(--green-bg)' : ''}">
          <span class="grow" style="font-size:15px;${i < nowIdx && !v.next.tomorrow ? 'color:var(--mu)' : ''}${i === nowIdx ? ';font-weight:600' : ''}">${k[0].toUpperCase() + k.slice(1)}</span>
          <span class="mono" style="font-size:15px">${v.times[k].replace(':', '.')}</span>
          ${k === 'terbit' ? html`<span style="width:120px"></span>` : html`<div class="chips" style="width:120px;justify-content:flex-end">${(() => { const cur = v.reminders[k] || 'notif'; const nx = MODES[(MODES.findIndex((m) => m[0] === cur) + 1) % MODES.length]; return html`<button class="chip ${cur === 'off' ? '' : 'cyan'}" data-act="mode" data-k="${k}" data-next="${nx[0]}" title="ketuk untuk ganti">${MODES.find((m) => m[0] === cur)?.[1] || cur}</button>`; })()}</div>`}</div>`)}</div>
        ${v.today_events.length ? html`<a class="card" href="#/hijriah"><span class="k green">Hari ini</span>${v.today_events.map((e) => html`<span class="sub">${e.title}</span>`)}</a>` : ''}
        <div class="btns"><a class="btn" href="https://www.google.com/maps/search/masjid+terdekat" target="_blank" rel="noopener">${icon('pin', 18)} Masjid terdekat</a><a class="btn" href="#/hijriah">${icon('cal', 18)} Kalender Islam</a></div>
        <p class="small" style="padding:0 4px">Ketuk jenis pengingat untuk menggantinya (adzan → notif → getar → mati). Saat rapat direkam atau di KRL, pengingat otomatis jadi getar.</p>
      </div>`);
  },
  actions: {
    async mode(b) {
      const reminders = { ...st.reminders, [b.dataset.k]: b.dataset.next };
      await put('/api/v1/app/settings/ibadah', { reminders });
      toast(`${b.dataset.k}: ${b.dataset.next === 'off' ? 'mati' : b.dataset.next}`);
      render();
    },
  },
};
