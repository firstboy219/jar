// Halaman aktif (mockup 22): everything open right now — music, a video, a worker's live browser, the meeting recorder, a document…
import { empty, get, header, html, icon, loading, on } from '../core.js';
import { liveFrame } from '../ui.js';

const TONE = { musik: 'amber', misi: 'violet', rapat: 'red', video: 'muted', doc: 'cyan', draft: 'cyan', map: 'green' };

export default {
  tab: 'beranda',
  async render(root) {
    const stops = [];
    const paint = async () => {
      stops.splice(0).forEach((f) => f());
      root.innerHTML = String(html`${header('Halaman aktif')}<div class="scr">${loading()}</div>`);
      const { pages } = await get('/api/v1/app/pages');
      root.innerHTML = String(html`${header(`Halaman aktif · ${pages.length}`)}<div class="scr">
        ${pages.length ? html`<div class="g2">${pages.map((p) => html`<a class="card" href="${p.route}" style="padding:0;overflow:hidden;min-height:190px">
          <div class="row" style="height:36px;padding:0 10px;border-bottom:1px solid var(--bd)"><span class="dot ${TONE[p.kind] || 'cyan'}"></span><span class="ttl grow" style="font-size:12px">${p.kind}</span></div>
          ${p.frame ? html`<img data-frame="${p.frame}" alt="" style="width:100%;height:110px;object-fit:cover;background:#000">` : p.image ? html`<img src="${p.image}" alt="" style="width:100%;height:110px;object-fit:cover">` : html`<div style="height:110px;display:flex;align-items:center;justify-content:center;background:var(--bg2)">${icon({ musik: 'music', misi: 'layers', rapat: 'meet', video: 'video' }[p.kind] || 'pages', 28)}</div>`}
          <div style="padding:8px 10px"><div class="ttl" style="font-size:13px">${p.title}</div><div class="small">${p.sub || ''}</div></div></a>`)}</div>`
          : empty('Tidak ada yang sedang terbuka.', 'Musik, video, misi yang memakai browser, dan rapat yang direkam muncul di sini.')}</div>`);
      for (const img of root.querySelectorAll('img[data-frame]')) stops.push(liveFrame(img, img.dataset.frame, 3000));
    };
    await paint();
    const offs = ['task', 'stage', 'meeting'].map((t) => on(t, () => paint()));
    return () => { offs.forEach((f) => f()); stops.forEach((f) => f()); };
  },
};
