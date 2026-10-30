// Bimbing layar (mockup 8): tell JARVIS what you want to do in an app; the phone shares its screen and JARVIS says the one next step each time
// the screen changes (a floating bubble on the phone, spoken too) until it is done. Here: start, follow the steps, stop, see past sessions.
import { $, embedded, get, header, html, icon, loading, on, openNative, post, render, speak, toast } from '../core.js';
import { laneChip } from '../ui.js';

export default {
  tab: 'beranda',
  feature: 'bimbing',
  async render(root) {
    root.innerHTML = String(html`${header('Bimbing layar')}<div class="scr">${loading()}</div>`);
    const d = await get('/api/v1/app/guide');
    const a = d.active;
    root.innerHTML = String(html`${header('Bimbing layar', { sub: a ? 'sedang membimbing' : '' })}
      <div class="scr">
        ${a ? html`<div class="card cyan"><div class="row sb"><span class="k cyan">Tujuan</span>${(a.steps || []).length ? html`<span class="small">langkah ${a.steps.at(-1).n}${a.steps.at(-1).total > a.steps.at(-1).n ? ` dari ±${a.steps.at(-1).total}` : ''}</span>` : ''}</div><span class="ttl">${a.goal}</span>
            ${(a.steps || []).length ? html`<div class="steps">${a.steps.map((s, i) => html`<div class="step"><div class="rail"><span class="n ${i < a.steps.length - 1 ? 'done' : 'now'}">${i < a.steps.length - 1 ? icon('check', 13) : s.n}</span>${i < a.steps.length - 1 ? html`<span class="ln"></span>` : ''}</div>
              <div class="body"><span style="font-size:14px;${i === a.steps.length - 1 ? 'font-weight:600' : ''}">${s.instruksi}</span>${s.target ? html`<span class="small">"${s.target}" · ${s.posisi}</span>` : ''}</div></div>`)}</div>`
              : html`<span class="small">${embedded ? 'Bagikan layar dari gelembung JARVIS, lalu buka aplikasinya.' : 'Buka aplikasi JARVIS di HP: layar dibagikan dari sana.'}</span>`}
            <div class="btns">${embedded ? html`<button class="btn" data-act="share">${icon('screen', 16)} Bagikan layar</button>` : ''}${(a.steps || []).length ? html`<button class="btn" data-act="repeat" data-id="${a.id}">${icon('repeat', 16)} Ulangi</button>` : ''}${(a.steps || []).length && a.steps.at(-1).app ? html`<button class="btn" data-act="doit" data-id="${a.id}">${icon('bolt', 16)} Kerjakan untukku</button>` : ''}<button class="btn danger" data-act="stop" data-id="${a.id}">Selesai</button></div></div>`
          : html`<form class="card" id="gf"><span class="k">Mau dibimbing apa?</span><label class="field">Tujuan<input name="goal" required minlength="4" placeholder="mis. cara mengaktifkan notifikasi tagihan di BCA mobile"></label>
            <button class="btn primary lg" data-act="start">${icon('screen', 18)} Mulai bimbing</button>
            <span class="small">JARVIS hanya membimbing — kamu yang mengetuk. PIN/OTP tidak pernah dibaca.</span></form>`}
        ${d.sessions.filter((s) => s.status !== 'active').length ? html`<span class="sec">Sebelumnya</span><div class="list">${d.sessions.filter((s) => s.status !== 'active').map((s) => html`<div class="li"><div class="grow">
          <div style="font-size:14px">${s.goal}</div><div class="small">${s.steps.length} langkah · ${s.status === 'done' ? 'tercapai' : 'dihentikan'} ${s.steps.at(-1)?.lane ? laneChip(s.steps.at(-1).lane) : ''}</div></div></div>`)}</div>` : ''}
      </div>`);
    return on('guide', () => render());
  },
  actions: {
    async start(b, e) {
      e?.preventDefault();
      const f = $('#gf'); if (!f.reportValidity()) return;
      await post('/api/v1/app/guide', { goal: new FormData(f).get('goal') });
      if (embedded) openNative('guide'); else toast('Lanjutkan di HP: bagikan layar dari aplikasi JARVIS.');
      render();
    },
    share() { openNative('guide'); },
    async repeat(b) { const s = await post(`/api/v1/app/guide/${b.dataset.id}/repeat`); speak(s.instruksi); },
    async doit(b) { const r = await post(`/api/v1/app/guide/${b.dataset.id}/do`); toast(`JARVIS mengerjakannya di HP (misi #${r.task_id})`); location.hash = `#/misi/${r.task_id}`; },
    async stop(b) { await post(`/api/v1/app/guide/${b.dataset.id}/stop`); render(); },
  },
};
