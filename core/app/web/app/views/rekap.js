// Rekap hari ini (mockup 15): what the day was, what is still open, and the action plan — already tasks in Catatan, each with its source.
import { get, header, html, icon, loading, post, render, speak, toast } from '../core.js';
import { laneChip } from '../ui.js';

let cur = null;

export default {
  tab: 'catatan',
  async render(root) {
    root.innerHTML = String(html`${header('Rekap hari ini')}<div class="scr">${loading()}</div>`);
    const { recap, page } = await get('/api/v1/app/recap');
    cur = recap;
    if (!recap) {
      root.innerHTML = String(html`${header('Rekap hari ini')}<div class="scr"><div class="card"><p>Belum ada rekap. Rekap dibuat otomatis saat kamu sampai rumah (atau jam 21.00), atau buat sekarang.</p>
        <button class="btn primary" data-act="now">Buat rekap sekarang</button></div></div>`);
      return;
    }
    const d = recap.data || {}, st = recap.stats || {};
    const todos = (page?.blocks || []).filter((b) => b.type === 'todo');
    root.innerHTML = String(html`${header('Rekap hari ini', { sub: new Date(`${recap.day}T00:00:00`).toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long' }), right: html`<button class="ib box" data-act="now" aria-label="Buat ulang">${icon('repeat', 18)}</button>` })}
      <div class="scr">
        <p class="lead" style="padding:0 4px">${d.ringkasan || ''}</p>
        <div class="g4"><div class="kpi"><b>${st.meetings ?? 0}</b><span>rapat</span></div><div class="kpi"><b>${st.tasks_done ?? 0}</b><span>misi selesai</span></div>
          <div class="kpi"><b>${st.plan ?? 0}</b><span>action plan</span></div><div class="kpi"><b>${st.no_ai ?? 0}</b><span>kerja tanpa AI</span></div></div>
        ${(d.selesai || []).length ? html`<div class="card"><span class="k green">Selesai</span>${d.selesai.map((x) => html`<span class="sub">${x}</span>`)}</div>` : ''}
        ${(d.belum || []).length ? html`<div class="card"><span class="k muted">Belum selesai</span>${d.belum.map((x) => html`<span class="sub">${x}</span>`)}</div>` : ''}
        ${todos.length ? html`<div class="card amber"><div class="row sb"><span class="k amber">Action plan · ${todos.length}</span><span class="small t-amber2">sudah di Catatan</span></div>
          ${todos.map((t) => html`<div class="row top"><span style="width:18px;height:18px;flex:none;border-radius:5px;border:1.5px solid var(--${t.checked ? 'green' : 'amber'});margin-top:2px;display:flex;align-items:center;justify-content:center">${t.checked ? icon('check', 12, 'var(--green)') : ''}</span>
            <div class="grow row sb"><span style="font-size:14px">${t.text}</span><span class="mono" style="font-size:11px;color:var(--amber-t)">${t.due || ''}</span></div></div>`)}</div>` : ''}
        ${d.besok ? html`<p class="small" style="text-align:center">${d.besok}</p>` : ''}
        <span class="small" style="padding:0 4px">Ditulis oleh ${laneChip(recap.lane)} lewat alur master</span>
        <div class="btns"><button class="btn lg" data-act="read">${icon('speaker', 18)} Bacakan</button><a class="btn primary lg" href="#/catatan?tab=tugas">Buka di Catatan</a></div>
      </div>`);
  },
  actions: {
    read() { const d = cur?.data || {}; speak([d.ringkasan, ...(d.action_plan || []).map((p) => p.tugas), d.besok].filter(Boolean).join('. ')); },
    async now() { toast('Menyusun rekap… (±30 detik)'); await post('/api/v1/app/recap/now'); render(); },
  },
};
