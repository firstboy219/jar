// Alarm (mockup 25): when JARVIS wakes the owner, on which days, and what it says. The alarm itself rings on the phone (exact, works
// offline); the greeting (subuh, weather, the first thing of the day) is made by the server when it rings.
import { get, header, host, html, icon, loading, put, render, speak, toast } from '../core.js';
import { toggle } from '../ui.js';

const DAYS = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];
let s = null;

async function save(patch) {
  s = await put('/api/v1/app/settings/alarm', patch);
  host.call('syncAlarm', s);
}

export default {
  tab: 'beranda',
  async render(root) {
    root.innerHTML = String(html`${header('Alarm')}<div class="scr">${loading()}</div>`);
    const [alarm, wake] = await Promise.all([get('/api/v1/app/settings/alarm'), get('/api/v1/app/ibadah/wake').catch(() => null)]);
    s = alarm;
    root.innerHTML = String(html`${header('Alarm', { sub: host.has('syncAlarm') ? 'berbunyi di HP ini' : 'berbunyi di aplikasi JARVIS di HP' })}<div class="scr">
      <div class="card pad" style="align-items:center;text-align:center">
        <label for="t" class="small">Bangunkan aku jam</label>
        <input id="t" type="time" value="${s.time}" style="font:400 64px var(--f-head);background:transparent;border:0;color:var(--tx);text-align:center;width:100%">
        <div class="row" style="gap:6px">${DAYS.map((d, i) => html`<button class="chip ${s.days.includes(i) ? 'on' : ''}" data-act="day" data-i="${i}">${d}</button>`)}</div>
        <div class="row sb" style="width:100%"><span>Alarm aktif</span>${toggle(s.enabled, 'enable')}</div></div>
      <div class="card"><span class="k muted">Saat berbunyi</span>
        <div class="row sb"><span style="font-size:13px">Sapaan dibacakan pelan (subuh, cuaca, agenda)</span>${toggle(s.voice_greeting, 'greet')}</div>
        <div class="row sb"><span style="font-size:13px">Tunda</span><span class="mono">${s.snooze_min} mnt</span></div>
        <div class="row sb"><span style="font-size:13px">Belum ada respons → lebih keras &amp; getar setelah</span><span class="mono">${s.escalate_after_min} mnt</span></div></div>
      ${wake ? html`<div class="card amber"><span class="k amber">Contoh sapaan besok</span><p style="font-size:15px;line-height:1.5">“${wake.text}”</p><button class="btn sm" data-act="hear" data-t="${wake.text}">${icon('speaker', 14)} Dengarkan</button></div>` : ''}
      <p class="small" style="padding:0 4px">Alarm memakai jam HP, tetap berbunyi walau internet atau server mati.</p></div>`);
    root.querySelector('#t').addEventListener('change', async (e) => { await save({ time: e.target.value }); toast(`Alarm ${e.target.value}`); });
  },
  actions: {
    async day(b) { const i = Number(b.dataset.i); const days = s.days.includes(i) ? s.days.filter((x) => x !== i) : [...s.days, i].sort(); await save({ days }); render(); },
    async enable() { await save({ enabled: !s.enabled }); render(); },
    async greet() { await save({ voice_greeting: !s.voice_greeting }); render(); },
    hear(b) { speak(b.dataset.t); },
  },
};
