// Peluang baru (mockup 35): Hermes researches the web (trends, marketplaces, news) for new business opportunities that fit what the owner
// already has — weekly, or now — each with why now, capital, potential, fit, a first step; one tap puts the first step in Catatan.
import { get, header, html, icon, loading, on, post, render, sheet, toast } from '../core.js';

const host = (u) => { try { return new URL(u).hostname; } catch { return u; } };

function deep(r) {
  if (!r) return '';
  if (r.status === 'running') return html`<a class="card violet" href="#/misi/${r.task_id}" style="text-decoration:none;background:var(--bg)"><div class="row sb"><span class="k violet">Hermes riset mendalam</span><span class="dot violet live"></span></div><span class="small">pesaing, pemasok, hitungan modal… ketuk untuk lihat</span></a>`;
  const h = r.hitungan || {};
  return html`<details class="card" style="background:var(--bg)" open><summary class="ttl" style="cursor:pointer">Hasil riset mendalam</summary>
    ${r.kesimpulan ? html`<span class="sub">${r.kesimpulan}</span>` : ''}${r.pasar ? html`<span class="small"><b>Pasar:</b> ${r.pasar}</span>` : ''}
    ${Object.keys(h).length ? html`<div class="g2">${[['modal_awal', 'Modal awal'], ['hpp_per_unit', 'HPP/unit'], ['harga_jual', 'Harga jual'], ['margin', 'Margin'], ['balik_modal', 'Balik modal']].filter(([k]) => h[k]).map(([k, l]) => html`<div class="kpi"><span>${l}</span><b style="font-size:15px">${h[k]}</b></div>`)}</div>` : ''}
    ${(r.pesaing || []).length ? html`<span class="small"><b>Pesaing</b></span>${r.pesaing.map((c) => html`<span class="small">• ${c.nama}${c.harga ? ` — ${c.harga}` : ''}${c.catatan ? ` · ${c.catatan}` : ''}</span>`)}` : ''}
    ${(r.pemasok || []).length ? html`<span class="small"><b>Pemasok:</b> ${r.pemasok.join('; ')}</span>` : ''}
    ${(r.rencana_30_hari || []).length ? html`<span class="small"><b>Rencana 30 hari</b></span>${r.rencana_30_hari.map((x) => html`<span class="small">• ${x}</span>`)}` : ''}
    ${(r.risiko || []).length ? html`<span class="small t-amber2">Risiko: ${r.risiko.join('; ')}</span>` : ''}
    ${r.catatan ? html`<span class="small">${r.catatan}</span>` : ''}
    <div class="row" style="gap:8px;flex-wrap:wrap">${(r.sumber || []).map((u) => html`<a class="small" href="${u}" target="_blank" rel="noopener">${host(u)}</a>`)}</div></details>`;
}

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
        ${cur ? cur.peluang.map((p, i) => p.dismissed ? html`<div class="card" style="opacity:.6"><div class="row sb"><span class="small">${p.judul}</span><span class="tag">bukan untukku</span></div>${p.alasan_tolak ? html`<span class="small">${p.alasan_tolak}</span>` : ''}</div>` : html`<div class="card">
          <div class="row sb"><span class="ttl">${p.judul}</span><span class="tag ${p.skor >= 8 ? 'green' : p.skor >= 6 ? 'amber' : ''}">skor ${p.skor}/10</span></div>
          <span class="sub">${p.ringkasan}</span>
          ${p.kenapa_sekarang ? html`<span class="small"><b>Kenapa sekarang:</b> ${p.kenapa_sekarang}</span>` : ''}
          ${p.cocok ? html`<span class="small"><b>Cocok karena:</b> ${p.cocok}</span>` : ''}
          <div class="row" style="gap:6px;flex-wrap:wrap">${p.modal ? html`<span class="tag">modal ${p.modal}</span>` : ''}${p.potensi ? html`<span class="tag green">potensi ${p.potensi}</span>` : ''}</div>
          ${p.langkah_pertama ? html`<span class="small t-amber2">Langkah pertama: ${p.langkah_pertama}</span>` : ''}
          <div class="row" style="gap:8px;flex-wrap:wrap">${(p.sumber || []).map((u) => html`<a class="small" href="${u}" target="_blank" rel="noopener">${host(u)}</a>`)}</div>
          ${deep(p.riset)}
          <div class="btns" style="flex-wrap:wrap">
            ${p.saved ? html`<span class="small" style="color:var(--green-t)">${icon('check', 12)} di Catatan</span>` : html`<button class="btn sm" data-act="save" data-id="${cur.id}" data-i="${i}">Simpan ke Catatan</button>`}
            ${!p.riset || p.riset.status === 'failed' ? html`<button class="btn sm" data-act="deep" data-id="${cur.id}" data-i="${i}">${icon('search', 14)} Riset mendalam</button>` : ''}
            <button class="btn sm ghost" data-act="dismiss" data-id="${cur.id}" data-i="${i}">Bukan untukku</button></div>
        </div>`) : html`<div class="card"><p class="sub">Belum ada riset. Hermes mencari peluang tiap Sabtu pagi, atau tekan tombol di atas.</p></div>`}
        ${old.length ? html`<details class="card"><summary class="ttl" style="cursor:pointer">Riset sebelumnya · ${old.length}</summary>${old.map((b) => html`<span class="small">${new Date(b.created_at).toLocaleDateString('id-ID')}: ${b.peluang.map((p) => p.judul).join(' · ')}</span>`)}</details>` : ''}
        <p class="small" style="padding:0 4px">Riset dikerjakan Hermes dengan browser (alur master → Hermes + alat). Angka bisnismu tidak dikirim ke model gratis.</p>
      </div>`);
    return on('notify', (e) => { if (e.route === '#/peluang') render(); });
  },
  actions: {
    async find() { const r = await post('/api/v1/app/bisnis/opportunities'); toast(r.task_id ? `Hermes mulai riset (misi #${r.task_id})` : 'Riset dimulai'); render(); },
    async deep(b) { const r = await post(`/api/v1/app/bisnis/opportunities/${b.dataset.id}/${b.dataset.i}/deep`); toast(r.task_id ? `Hermes mulai riset (misi #${r.task_id})` : 'Riset dimulai'); render(); },
    async dismiss(b) {
      const v = await sheet(String(html`<form><span class="ttl">Bukan untukku</span><label class="field">Kenapa? (opsional — JARVIS belajar seleramu)<input name="reason" maxlength="200" placeholder="mis. butuh stok besar, tidak suka F&B"></label>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Sembunyikan</button></div></form>`));
      if (!v) return;
      await post(`/api/v1/app/bisnis/opportunities/${b.dataset.id}/${b.dataset.i}/dismiss`, { reason: v.reason || '' });
      render();
    },
    async save(b) { await post(`/api/v1/app/bisnis/opportunities/${b.dataset.id}/${b.dataset.i}/save`); toast('Masuk ke Catatan'); render(); },
  },
};
