// Butuh kamu / Izin (mockup 5): everything waiting for the owner — a run on his phone (admin password), an approval, a pick, a question.
import { empty, get, header, html, loading, on } from '../core.js';
import { itemCard, needActions, remember } from '../needsui.js';

let items = [];

export default {
  tab: 'beranda',
  async render(root) {
    const paint = async () => {
      root.innerHTML = String(html`${header('Butuh kamu', { sub: 'izin, pilihan, pertanyaan' })}<div class="scr">${loading()}</div>`);
      items = (await get('/api/v1/app/needs')).items;
      remember(items);
      root.querySelector('.scr').innerHTML = String(items.length ? html`${items.map((it) => itemCard(it))}` : empty('Tidak ada yang menunggu keputusanmu.', 'JARVIS akan mengabari kalau ada.'));
    };
    await paint();
    const offs = ['phone_approval', 'owner_choice', 'task'].map((t) => on(t, () => paint()));
    return () => offs.forEach((f) => f());
  },
  actions: needActions,
};
