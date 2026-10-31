// Semua fitur (mockup 41): every feature in one place, grouped, searchable; a dot where something must be connected first.
import { get, header, html, icon, loading, put, render, toast } from '../core.js';

let cache = null, pinning = false, pins = [];
async function catalog() {
  if (!cache) cache = await get('/api/v1/app/features');
  setTimeout(() => { cache = null; }, 60000);
  return cache;
}

const norm = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[^\w ]/g, '');
const ALIASES = { web: ['situs', 'website', 'hotel', 'pesawat', 'tiket', 'booking', 'formulir'], kopi: ['ngopi', 'coffee'], sholat: ['salat', 'shalat', 'adzan', 'azan'], quran: ['alquran', 'ngaji', 'mengaji'], bioskop: ['film', 'nonton'],
  inbox: ['email', 'whatsapp', 'wa', 'outlook', 'pesan'], bisnis: ['penjualan', 'pencairan', 'packing', 'renature', 'autotoko'], invest: ['pluang', 'saham', 'emas'],
  karier: ['jobstreet', 'lamar', 'lowongan', 'kerja baru'], berkas: ['pdf', 'word', 'excel', 'konversi'], kamera: ['ukur', 'meteran'], dongeng: ['cerita', 'anak'],
  bangun: ['alarm', 'bangunin'], berangkat: ['krl', 'kereta', 'goride', 'ojek'], pulang: ['krl pulang'], gaji: ['alokasi', 'budget'], hijriah: ['puasa', 'bekam', 'hijriyah'],
  penyimpanan: ['storage', 'disk', 'memori server', 'hapus file', 'zip'] };

/** The feature a typed word means (its name, or a word the owner says for it); null when nothing fits well. */
export async function findFeature(q) {
  const n = norm(q);
  if (n.length < 3 || n.split(' ').length > 3) return null;
  const { features } = await catalog();
  return features.find((f) => norm(f.label) === n || f.id === n || (ALIASES[f.id] || []).includes(n)) || null;
}

export default {
  tab: 'fitur',
  async render(root) {
    const head = () => header('Semua fitur', { right: html`<button class="chip ${pinning ? 'on' : ''}" data-act="pinMode">${icon('star', 13)} ${pinning ? 'Selesai' : 'Sematkan'}</button>` });
    root.innerHTML = String(html`${head()}<div class="scr">${loading()}</div>`);
    const [{ groups, features }, home] = await Promise.all([catalog(), get('/api/v1/app/settings/home')]);
    pins = home.pinned || [];
    const draw = (q = '') => {
      const n = norm(q);
      const fit = (f) => !n || norm(f.label).includes(n) || f.id.includes(n) || (ALIASES[f.id] || []).some((a) => a.includes(n));
      return groups.map((g) => {
        const fs = features.filter((f) => f.group === g && fit(f));
        if (!fs.length) return '';
        return html`<div class="sec"><span>${g}</span></div><div class="tiles">${fs.map((f) => (pinning && f.route.startsWith('#/')
          ? html`<button class="ftile" data-act="pin" data-id="${f.id}" style="${pins.includes(f.id) ? 'border-color:var(--amber)' : ''}">${icon(f.icon, 20)}<span>${f.label}</span>${pins.includes(f.id) ? html`<span style="position:absolute;top:4px;right:6px;color:var(--amber)">★</span>` : ''}</button>`
          : html`<a class="ftile" ${f.route.startsWith('native:') ? html`data-native="${f.route.slice(7)}" href="#"` : html`href="${f.route}"`} title="${f.setup || ''}">${icon(f.icon, 20)}<span>${f.label}</span>${pins.includes(f.id) ? html`<span style="position:absolute;top:4px;right:6px;color:var(--amber);font-size:11px">★</span>` : ''}${f.ready === false ? html`<span class="need" aria-label="${f.setup}"></span>` : ''}</a>`))}</div>`;
      });
    };
    root.querySelector('.scr').innerHTML = String(html`
      <label class="cmd" style="height:46px"><input id="fq" placeholder="Cari: “pencairan”, “dongeng”, “ukur”…" autocomplete="off"></label>
      ${pinning ? html`<div class="card amber"><span class="small">Ketuk fitur untuk menyematkannya di halaman depan (maks 4, ★). Sisanya JARVIS pilih sesuai waktu & kebiasaanmu.</span></div>` : ''}
      <div id="fl">${draw()}</div>
      <p class="small" style="padding:0 4px">Titik kuning: perlu disambungkan dulu. ★ disematkan di halaman depan.</p>`);
    root.querySelector('#fq').addEventListener('input', (e) => { root.querySelector('#fl').innerHTML = String(html`${draw(e.target.value)}`); });
  },
  actions: {
    pinMode() { pinning = !pinning; render(); },
    async pin(b) {
      const id = b.dataset.id;
      const next = pins.includes(id) ? pins.filter((p) => p !== id) : [...pins, id];
      if (next.length > 4) return toast('Maksimal 4 fitur disematkan', true);
      await put('/api/v1/app/settings/home', { pinned: next });
      pins = next; render();
    },
  },
};
