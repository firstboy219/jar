// Semua fitur (mockup 41): every feature in one place, grouped, searchable; a dot where something must be connected first.
import { get, header, html, icon, loading } from '../core.js';

let cache = null;
async function catalog() {
  if (!cache) cache = await get('/api/v1/app/features');
  setTimeout(() => { cache = null; }, 60000);
  return cache;
}

const norm = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[^\w ]/g, '');
const ALIASES = { kopi: ['ngopi', 'coffee'], sholat: ['salat', 'shalat', 'adzan', 'azan'], quran: ['alquran', 'ngaji', 'mengaji'], bioskop: ['film', 'nonton'],
  inbox: ['email', 'whatsapp', 'wa', 'outlook', 'pesan'], bisnis: ['penjualan', 'pencairan', 'packing', 'renature', 'autotoko'], invest: ['pluang', 'saham', 'emas'],
  karier: ['jobstreet', 'lamar', 'lowongan', 'kerja baru'], berkas: ['pdf', 'word', 'excel', 'konversi'], kamera: ['ukur', 'meteran'], dongeng: ['cerita', 'anak'],
  bangun: ['alarm', 'bangunin'], berangkat: ['krl', 'kereta', 'goride', 'ojek'], pulang: ['krl pulang'], gaji: ['alokasi', 'budget'], hijriah: ['puasa', 'bekam', 'hijriyah'] };

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
    root.innerHTML = String(html`${header('Semua fitur', { right: html`<span class="small" style="padding-right:8px">ketuk untuk buka</span>` })}<div class="scr">${loading()}</div>`);
    const { groups, features } = await catalog();
    const draw = (q = '') => {
      const n = norm(q);
      const fit = (f) => !n || norm(f.label).includes(n) || f.id.includes(n) || (ALIASES[f.id] || []).some((a) => a.includes(n));
      return groups.map((g) => {
        const fs = features.filter((f) => f.group === g && fit(f));
        if (!fs.length) return '';
        return html`<div class="sec"><span>${g}</span></div><div class="tiles">${fs.map((f) => html`<a class="ftile" ${f.route.startsWith('native:') ? html`data-native="${f.route.slice(7)}" href="#"` : html`href="${f.route}"`} title="${f.setup || ''}">${icon(f.icon, 20)}<span>${f.label}</span>${f.ready === false ? html`<span class="need" aria-label="${f.setup}"></span>` : ''}</a>`)}</div>`;
      });
    };
    root.querySelector('.scr').innerHTML = String(html`
      <label class="cmd" style="height:46px"><input id="fq" placeholder="Cari: “pencairan”, “dongeng”, “ukur”…" autocomplete="off"></label>
      <div id="fl">${draw()}</div>
      <p class="small" style="padding:0 4px">Titik kuning: perlu disambungkan dulu. Buka fiturnya untuk melihat caranya.</p>`);
    root.querySelector('#fq').addEventListener('input', (e) => { root.querySelector('#fl').innerHTML = String(html`${draw(e.target.value)}`); });
  },
};
