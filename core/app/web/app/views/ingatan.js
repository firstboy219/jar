// Ingatan (mockup 7): what JARVIS learned — skills and phone routines (done without AI next time), what it knows about the owner,
// and how much of its work now runs without AI.
import { del, empty, get, header, html, icon, loading, patch, post, render, sheet, toast } from '../core.js';
import { pct } from '../lib.js';

let tab = 'skill';

export default {
  tab: 'ingatan',
  async render(root, route) {
    tab = route.query.tab || tab;
    root.innerHTML = String(html`${header('Ingatan', { back: false })}<div class="scr">${loading()}</div>`);
    const d = await get('/api/v1/app/memory');
    const tabs = html`<div class="chips">
      ${[['skill', 'Skill'], ['tentang', 'Tentang kamu']].map(([k, l]) => html`<button class="chip ${tab === k ? 'on' : ''}" data-act="tab" data-k="${k}">${l}</button>`)}
      <a class="chip" href="#/kebiasaan">Kebiasaan</a><a class="chip" href="#/rapat">Rapat</a><a class="chip" href="#/catatan?tab=catatan">Catatan</a></div>`;
    const stats = html`<div class="g3">
      <div class="kpi"><b>${d.counts.skills}</b><span>skill &amp; rutin aktif</span></div>
      <div class="kpi"><b style="color:var(--green)">${d.no_ai_pct ?? '–'}${d.no_ai_pct != null ? '%' : ''}</b><span>pekerjaan tanpa AI (30 hari)</span></div>
      <div class="kpi"><b>${d.counts.memories}</b><span>hal yang diingat</span></div></div>
      ${d.saved_usd ? html`<div class="card green"><span class="small">Hemat bulan ini ±<b>$${d.saved_usd < 1 ? d.saved_usd.toFixed(3) : d.saved_usd.toFixed(2)}</b> — pekerjaan yang dikerjakan skill, bukan AI.</span></div>` : ''}`;
    let body;
    if (tab === 'skill') {
      const rows = [
        ...d.routines.map((r) => ({ name: r.name, sub: `${r.app} · ${r.steps} langkah · ${r.runs}× · ${pct(r.auto_steps, (r.auto_steps || 0) + (r.ai_steps || 0))}% tanpa AI`, ok: r.runs ? pct(r.ok_runs, r.runs) : null, status: r.status, id: r.id, kind: 'routine' })),
        ...d.skills.map((s) => ({ name: s.name, sub: `${s.description || ''}`.slice(0, 90) + (s.runs ? ` · ${s.runs}×` : ''), ok: s.runs ? pct(s.success_n, s.runs) : null, status: s.cap_status || s.status, id: s.id, kind: 'skill' })),
      ];
      body = html`
        ${d.new.length ? html`<div class="card cyan"><span class="k cyan">Baru dipelajari</span>${d.new.map((n) => html`<div class="row sb" style="gap:8px"><div class="grow"><div class="ttl">“${n.name}”</div><div class="small">${n.kind === 'rutin' ? `rutin ${n.app} · ${(n.steps || []).length || n.steps} langkah · yang berubah: ${Object.keys(n.params || {}).join(', ') || '-'}` : `skill · ${n.status}`}</div></div>
          ${n.kind === 'rutin' ? html`<button class="btn sm" data-act="steps" data-id="${n.id}">Lihat langkah</button>` : n.status === 'awaiting_approval' && n.approval_id ? html`<button class="btn sm primary" data-act="keepSkill" data-id="${n.approval_id}">Simpan skill</button>` : ''}</div>`)}</div>` : ''}
        ${rows.length ? html`<div class="list">${rows.map((r) => html`<div class="li"><div class="grow"><div class="ttl">${r.name}</div><div class="small">${r.sub}</div></div>
          ${r.ok != null ? html`<span class="mono" style="font-size:12px;color:var(--${r.ok >= 90 ? 'green' : r.ok >= 70 ? 'amber' : 'red'})">${r.ok}%</span>` : html`<span class="tag">${r.status}</span>`}
          ${r.kind === 'routine' ? html`<button class="btn sm" data-act="routine" data-id="${r.id}" data-on="${r.status === 'active' ? 1 : 0}">${r.status === 'active' ? 'Matikan' : 'Nyalakan'}</button>` : ''}</div>`)}</div>`
          : empty('Belum ada skill.', 'Setiap pekerjaan berulang yang berhasil dipelajari jadi skill: berikutnya dikerjakan tanpa AI.')}`;
    } else {
      body = html`
        <form id="addmem" class="cmd" style="height:46px">${icon('plus', 18, 'var(--mu)')}<input name="text" placeholder="Ajari JARVIS sesuatu tentangmu…" style="margin-left:8px"></form>
        ${d.prefs.length ? html`<div class="list">${d.prefs.map((m) => html`<div class="li"><div class="grow">${m.text}</div><button class="ib" data-act="forget" data-id="${m.id}" aria-label="Lupakan">${icon('close', 16)}</button></div>`)}</div>` : empty('JARVIS belum mencatat apa pun tentangmu.')}`;
    }
    root.querySelector('.scr').innerHTML = String(html`${tabs}${stats}${body}`);
    root.querySelector('#addmem')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = e.target.text.value.trim();
      if (!text) return;
      await post('/api/v1/console/memories', { text, category: 'personal', kind: 'preference' });
      toast('Diingat.'); render();
    });
  },
  actions: {
    tab(b) { tab = b.dataset.k; render(); },
    async steps(b) {
      const r = await get(`/api/v1/app/memory/routine/${b.dataset.id}`);
      await sheet(String(html`<span class="ttl">${r.name}</span><span class="small">${r.app} · ${r.runs}× · berhasil ${r.ok_runs}×</span>
        <ol style="margin:0;padding-left:20px;display:flex;flex-direction:column;gap:4px">${r.steps.map((x) => html`<li style="font-size:14px">${x.text}</li>`)}</ol>
        ${Object.keys(r.params || {}).length ? html`<span class="small">Yang berubah tiap kali: ${Object.entries(r.params).map(([k, v]) => `${k} (${v})`).join(', ')}</span>` : ''}
        <div class="btns"><button class="btn" data-close="">Tutup</button><button class="btn danger" data-close="off">Jangan pakai rutin ini</button></div>`)).then(async (v) => {
        if (v === 'off') { await patch(`/api/v1/routines/${r.id}`, { status: 'off' }); toast('Rutin dimatikan.'); render(); }
      });
    },
    async keepSkill(b) { await post(`/api/v1/app/needs/approval/${b.dataset.id}`, { approve: true }); toast('Skill disimpan — dipakai tanpa AI berikutnya.'); render(); },
    async routine(b) { await patch(`/api/v1/routines/${b.dataset.id}`, { status: b.dataset.on === '1' ? 'off' : 'active' }); render(); },
    async forget(b) { await del(`/api/v1/console/memories/${b.dataset.id}`); toast('Dilupakan.'); render(); },
  },
};
