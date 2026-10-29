// A route that has no screen (an old link): back to the front page.
import { header, html } from '../core.js';

export default {
  feature: false,
  async render(root, route) {
    root.innerHTML = String(html`${header('JARVIS')}<div class="scr"><div class="card"><p>Halaman “${route.name}” tidak ada.</p><a class="btn primary" href="#/">Ke beranda</a></div></div>`);
  },
};
