// Halaman aktif (mockup 22): everything open right now — music, a video, a worker's live browser, the meeting recorder, a document…
import { $, empty, get, header, html, icon, loading, on, post, render } from '../core.js';
import { liveFrame } from '../ui.js';

const TONE = { musik: 'amber', misi: 'violet', rapat: 'red', video: 'muted', doc: 'cyan', draft: 'cyan', map: 'green' };
let filter = '', current = [], typing = null;

export default {
  tab: 'beranda',
  async render(root) {
    const stops = [];
    const paint = async () => {
      stops.splice(0).forEach((f) => f());
      root.innerHTML = String(html`${header('Halaman aktif')}<div class="scr">${loading()}</div>`);
      const { pages } = await get('/api/v1/app/pages');
      const q = (filter || '').toLowerCase();
      const shown = pages.filter((p) => !q || `${p.title} ${p.sub} ${p.kind}`.toLowerCase().includes(q));
      current = pages;
      root.innerHTML = String(html`${header(`Halaman aktif · ${pages.length}`, { right: pages.length ? html`<button class="btn sm" data-act="closeAll">Tutup semua</button>` : '' })}<div class="scr">
        ${pages.length > 3 ? html`<input class="inp" id="pq" placeholder="Cari halaman…" value="${filter}">` : ''}
        ${shown.length ? html`<div class="g2">${shown.map((p) => html`<a class="card" href="${p.route}" style="padding:0;overflow:hidden;min-height:190px">
          <div class="row" style="height:36px;padding:0 4px 0 10px;border-bottom:1px solid var(--bd)"><span class="dot ${TONE[p.kind] || 'cyan'}"></span><span class="ttl grow" style="font-size:12px">${p.kind}</span>
            <button class="ib sm" data-act="close" data-id="${p.id}" aria-label="Tutup">${icon('close', 14)}</button></div>
          ${p.frame ? html`<img data-frame="${p.frame}" alt="" style="width:100%;height:110px;object-fit:cover;background:#000">` : p.image ? html`<img src="${p.image}" alt="" style="width:100%;height:110px;object-fit:cover">` : html`<div style="height:110px;display:flex;align-items:center;justify-content:center;background:var(--bg2)">${icon({ musik: 'music', misi: 'layers', rapat: 'meet', video: 'video' }[p.kind] || 'pages', 28)}</div>`}
          <div style="padding:8px 10px"><div class="ttl" style="font-size:13px">${p.title}</div><div class="small">${p.sub || ''}</div></div></a>`)}</div>`
          : empty(pages.length ? 'Tidak ada yang cocok.' : 'Tidak ada yang sedang terbuka.', 'Musik, video, misi yang memakai browser, dan rapat yang direkam muncul di sini.')}</div>`);
      $('#pq')?.addEventListener('input', (e) => { filter = e.target.value; clearTimeout(typing); typing = setTimeout(paint, 300); });
      for (const img of root.querySelectorAll('img[data-frame]')) stops.push(liveFrame(img, img.dataset.frame, 3000));
    };
    await paint();
    const offs = ['task', 'stage', 'meeting'].map((t) => on(t, () => paint()));
    return () => { offs.forEach((f) => f()); stops.forEach((f) => f()); };
  },
  actions: {
    async close(b, e) { e?.preventDefault(); await post('/api/v1/app/pages/hide', { ids: [b.dataset.id] }); render(); },
    async closeAll() { await post('/api/v1/app/pages/hide', { ids: current.filter((p) => p.kind !== 'rapat' && p.kind !== 'misi').map((p) => p.id) }); render(); },
  },
};
