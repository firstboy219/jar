// Peluang baru (mockup 35): Hermes researches the web (trends, marketplaces, news) for new business opportunities that fit what the owner
// already has — weekly, or now — each with why now, capital, potential, fit, a first step; one tap puts the first step in Catatan.
import { get, header, html, icon, loading, on, post, render, toast } from '../core.js';

const host = (u) => { try { return new URL(u).hostname; } catch { return u; } };

export default {
  tab: 'beranda',
  feature: 'peluang',
  async render(root) {
    root.innerHTML = String(html`${header('Peluang baru')}<div class="scr">${loading()}</div>`);
    const d = await get('/api/v1/app/bisnis/opportunities');
    const [cur, ...old] = d.batches;
    root.innerHTML = String(html`${header('Peluang baru', { sub: cur ? `riset ${new Date(cur.created_at).toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'short' })}` : '' })}
      <div class="scr">
        ${d.running_task ? html`<a class="card violet" href="#/misi/${d.running_task}" style="text-decoration:none"><div class="row sb"><span class="k violet">Hermes sedang riset</span><span class="dot violet live"></span></div>
          <span class="small">Membuka Google Trends, marketplace, dan berita industri… ketuk untuk lihat langsung.</span></a>`
          : html`<button class="btn primary block" data-act="find">${icon('search', 16)} Cari peluang sekarang</button>`}
        ${cur ? cur.peluang.map((p, i) => html`<div class="card">
          <div class="row sb"><span class="ttl">${p.judul}</span><span class="tag ${p.skor >= 8 ? 'green' : p.skor >= 6 ? 'amber' : ''}">skor ${p.skor}/10</span></div>
          <span class="sub">${p.ringkasan}</span>
          ${p.kenapa_sekarang ? html`<span class="small"><b>Kenapa sekarang:</b> ${p.kenapa_sekarang}</span>` : ''}
          ${p.cocok ? html`<span class="small"><b>Cocok karena:</b> ${p.cocok}</span>` : ''}
          <div class="row" style="gap:6px;flex-wrap:wrap">${p.modal ? html`<span class="tag">modal ${p.modal}</span>` : ''}${p.potensi ? html`<span class="tag green">potensi ${p.potensi}</span>` : ''}</div>
          ${p.langkah_pertama ? html`<span class="small t-amber2">Langkah pertama: ${p.langkah_pertama}</span>` : ''}
          <div class="row" style="gap:8px;flex-wrap:wrap">${(p.sumber || []).map((u) => html`<a class="small" href="${u}" target="_blank" rel="noopener">${host(u)}</a>`)}</div>
          ${p.saved ? html`<span class="small" style="color:var(--green-t)">${icon('check', 12)} di Catatan</span>` : html`<button class="btn sm" data-act="save" data-id="${cur.id}" data-i="${i}">Simpan langkah pertama ke Catatan</button>`}
        </div>`) : html`<div class="card"><p class="sub">Belum ada riset. Hermes mencari peluang tiap Sabtu pagi, atau tekan tombol di atas.</p></div>`}
        ${old.length ? html`<details class="card"><summary class="ttl" style="cursor:pointer">Riset sebelumnya · ${old.length}</summary>${old.map((b) => html`<span class="small">${new Date(b.created_at).toLocaleDateString('id-ID')}: ${b.peluang.map((p) => p.judul).join(' · ')}</span>`)}</details>` : ''}
        <p class="small" style="padding:0 4px">Riset dikerjakan Hermes dengan browser (alur master → Hermes + alat). Angka bisnismu tidak dikirim ke model gratis.</p>
      </div>`);
    return on('notify', (e) => { if (e.route === '#/peluang') render(); });
  },
  actions: {
    async find() { const r = await post('/api/v1/app/bisnis/opportunities'); toast(r.task_id ? `Hermes mulai riset (misi #${r.task_id})` : 'Riset dimulai'); render(); },
    async save(b) { await post(`/api/v1/app/bisnis/opportunities/${b.dataset.id}/${b.dataset.i}/save`); toast('Masuk ke Catatan'); render(); },
  },
};
