// Halaman aktif (mockup 22): everything open right now — music, a video, a worker's live browser, the meeting recorder, a document…
import { $, empty, get, header, html, icon, loading, on, post, render } from '../core.js';
import { liveFrame } from '../ui.js';

const TONE = { musik: 'amber', misi: 'violet', rapat: 'red', video: 'muted', doc: 'cyan', draft: 'cyan', map: 'green', perjalanan: 'green' };
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
let filter = '', current = [], typing = null;

// swipe a card sideways (more than a third of its width) to close it, like the phone's recent apps
function swipe(card) {
  let x0 = null, dx = 0;
  card.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; dx = 0; card.style.transition = 'none'; }, { passive: true });
  card.addEventListener('touchmove', (e) => { if (x0 == null) return; dx = e.touches[0].clientX - x0; card.style.transform = `translateX(${dx}px)`; card.style.opacity = String(1 - Math.min(0.7, Math.abs(dx) / 300)); }, { passive: true });
  card.addEventListener('touchend', async () => {
    card.style.transition = '';
    if (Math.abs(dx) > card.offsetWidth / 3) {
      card.style.transform = `translateX(${dx > 0 ? 400 : -400}px)`;
      await post('/api/v1/app/pages/hide', { ids: [card.dataset.id] }).catch(() => {});
      render();
    } else { card.style.transform = ''; card.style.opacity = ''; }
    x0 = null;
  });
  card.addEventListener('click', (e) => { if (Math.abs(dx) > 10) e.preventDefault(); }, true);
}

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
        ${shown.length ? html`<div class="g2">${shown.map((p) => html`<a class="card page" data-id="${p.id}" href="${p.route}" style="padding:0;overflow:hidden;min-height:190px;touch-action:pan-y;transition:transform .15s">
          <div class="row" style="height:36px;padding:0 4px 0 10px;border-bottom:1px solid var(--bd)"><span class="dot ${TONE[p.kind] || 'cyan'}"></span><span class="ttl grow" style="font-size:12px">${p.kind}</span>
            <button class="ib sm" data-act="close" data-id="${p.id}" aria-label="Tutup">${icon('close', 14)}</button></div>
          ${p.frame ? html`<img data-frame="${p.frame}" alt="" style="width:100%;height:110px;object-fit:cover;background:#000">` : p.image ? html`<img src="${p.image}" alt="" style="width:100%;height:110px;object-fit:cover">` : html`<div style="height:110px;display:flex;align-items:center;justify-content:center;background:var(--bg2)">${icon({ musik: 'music', misi: 'layers', rapat: 'meet', video: 'video', perjalanan: 'train' }[p.kind] || 'pages', 28)}</div>`}
          <div style="padding:8px 10px"><div class="ttl" style="font-size:13px">${p.title}</div><div class="small">${p.sub || ''}${p.since ? html` · <span class="mono" data-since="${p.since}">${mmss(Date.now() / 1000 - p.since)}</span>` : ''}</div></div></a>`)}</div>
          <span class="small" style="padding:0 4px">Geser kartu ke samping untuk menutupnya.</span>`
          : empty(pages.length ? 'Tidak ada yang cocok.' : 'Tidak ada yang sedang terbuka.', 'Musik, video, misi yang memakai browser, dan rapat yang direkam muncul di sini.')}</div>`);
      $('#pq')?.addEventListener('input', (e) => { filter = e.target.value; clearTimeout(typing); typing = setTimeout(paint, 300); });
      for (const img of root.querySelectorAll('img[data-frame]')) stops.push(liveFrame(img, img.dataset.frame, 3000));
      const tick = setInterval(() => root.querySelectorAll('[data-since]').forEach((e) => { e.textContent = mmss(Date.now() / 1000 - Number(e.dataset.since)); }), 1000);
      stops.push(() => clearInterval(tick));
      for (const card of root.querySelectorAll('.card.page')) swipe(card);
    };
    await paint();
    const offs = ['task', 'stage', 'meeting', 'trip'].map((t) => on(t, () => paint()));
    return () => { offs.forEach((f) => f()); stops.forEach((f) => f()); };
  },
  actions: {
    async close(b, e) { e?.preventDefault(); await post('/api/v1/app/pages/hide', { ids: [b.dataset.id] }); render(); },
    async closeAll() { await post('/api/v1/app/pages/hide', { ids: current.filter((p) => p.kind !== 'rapat' && p.kind !== 'misi').map((p) => p.id) }); render(); },
  },
};
