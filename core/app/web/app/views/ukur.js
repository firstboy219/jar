// Kamera ukur (mockup 7): near things are measured on the phone with AR (tap points, read metres); far things (a house front) are estimated
// from a photo by the brain's eyes, as a range, from objects of known size in the picture. Every measurement is kept here.
import { embedded, get, header, html, icon, loading, openNative, post, render, sheet, toast } from '../core.js';
import { laneChip } from '../ui.js';
import { pick, upload } from '../upload.js';

let look = null, paint = null;
const MODES = [['ukur', 'Ukur'], ['kenali', 'Kenali'], ['baca', 'Baca teks'], ['terjemah', 'Terjemahkan'], ['cat', 'Hitung cat']];
const m2 = (v) => `${String(v).replace('.', ',')} m`;
const range = (r) => (r.min !== r.max ? `${m2(r.perkiraan)} (${String(r.min).replace('.', ',')}–${String(r.max).replace('.', ',')})` : m2(r.perkiraan));

// width × height of a wall from a kept measurement: AR (total + height, or two segments) or photo (lebar + tinggi)
function wallOf(m) {
  if (m.kind === 'ar') return m.data.tinggi ? [m.data.total, m.data.tinggi] : m.data.segmen.length === 2 ? m.data.segmen : null;
  const u = m.data.ukuran || {};
  return u.lebar && u.tinggi ? [u.lebar.perkiraan, u.tinggi.perkiraan] : null;
}
const paintCard = (p) => html`<div class="card amber"><span class="k amber">Kebutuhan cat</span><span class="mono" style="font-size:20px">${String(p.liter).replace('.', ',')} liter</span>
  <span class="small">dinding ${String(p.luas_m2).replace('.', ',')} m² · ${p.lapis} lapis · ±10 m²/liter/lapis</span><span class="small">≈ ${p.kaleng_5l} kaleng 5 L atau ${p.kaleng_2_5l} kaleng 2,5 L</span>
  <button class="btn sm" data-act="closePaint">Tutup</button></div>`;

export default {
  tab: 'beranda',
  feature: 'kamera',
  async render(root) {
    root.innerHTML = String(html`${header('Kamera ukur')}<div class="scr">${loading()}</div>`);
    const d = await get('/api/v1/app/measure');
    root.innerHTML = String(html`${header('Kamera ukur')}
      <div class="scr">
        <div class="g2"><button class="card cyan" data-act="ar" style="text-align:left;cursor:pointer"><span class="k cyan">Ukur AR</span><span class="small">Meja, pintu, ruangan: ketuk titik di kamera, jarak langsung terbaca (sampai ±5 m).</span></button>
          <button class="card violet" data-act="photo" style="text-align:left;cursor:pointer"><span class="k violet">Dari foto</span><span class="small">Rumah, pagar, pohon: perkiraan dari benda acuan di foto (pintu, orang, mobil).</span></button></div>
        <div class="chips">${MODES.slice(1).map(([m, l]) => html`<button class="chip" data-act="photo" data-mode="${m}">${icon('camera', 13)} ${l}</button>`)}</div>
        ${look ? html`<div class="card violet"><div class="row sb"><span class="k violet">${(MODES.find((x) => x[0] === look.mode) || [])[1] || look.mode}</span>${laneChip(look.lane)}</div>
          <p class="sub" style="white-space:pre-wrap">${look.text}</p><div class="btns"><button class="btn sm" data-act="copy">Salin</button><button class="btn sm" data-act="closeLook">Tutup</button></div></div>` : ''}
        ${paint ? paintCard(paint) : ''}
        <details class="card"><summary class="small">Hitung cat dinding dari ukuran</summary><form id="pf" style="display:flex;flex-direction:column;gap:8px">
          <div class="g2"><label class="field">Lebar (m)<input name="width" inputmode="decimal" required></label><label class="field">Tinggi (m)<input name="height" inputmode="decimal" required></label></div>
          <div class="g2"><label class="field">Lapis<select name="coats"><option>1</option><option selected>2</option><option>3</option></select></label><label class="field">Pintu/jendela (m²)<input name="openings" inputmode="decimal" value="0"></label></div>
          <button class="btn" data-act="paintForm">Hitung</button></form></details>
        ${d.measures.length ? html`<span class="sec">Hasil ukur</span>${d.measures.map((m) => html`<div class="card">
          <div class="row sb"><span class="ttl">${m.label}</span><span class="tag ${m.kind === 'ar' ? 'cyan' : 'violet'}">${m.kind === 'ar' ? 'AR' : `foto · yakin ${m.data.yakin}`}</span></div>
          ${m.kind === 'ar' ? html`<span class="mono" style="font-size:20px">${m2(m.data.total)}</span>${m.data.segmen.length > 1 ? html`<span class="small">${m.data.segmen.map(m2).join(' + ')}</span>` : ''}${m.data.luas ? html`<span class="small">luas ${String(m.data.luas).replace('.', ',')} m²</span>` : ''}${m.data.tinggi ? html`<span class="small">tinggi ${m2(m.data.tinggi)}</span>` : ''}`
            : html`${Object.entries(m.data.ukuran).map(([k, r]) => html`<div class="row sb"><span class="small">${k}</span><span class="mono">${range(r)}</span></div>`)}
              ${m.data.acuan?.length ? html`<span class="small">acuan: ${m.data.acuan.join(', ')}</span>` : ''}${m.data.catatan ? html`<span class="small">${m.data.catatan}</span>` : ''}`}
          <div class="row sb"><span class="small">${new Date(m.created_at).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
            ${wallOf(m) ? html`<button class="btn sm" data-act="paintOf" data-w="${wallOf(m)[0]}" data-h="${wallOf(m)[1]}">${icon('brush', 14)} Butuh cat berapa?</button>` : ''}</div></div>`)}`
          : html`<div class="card"><p class="sub">Belum ada hasil ukur.</p></div>`}
        <p class="small" style="padding:0 4px">Perkiraan dari foto memakai model penglihatan lewat alur master; selalu berupa rentang — untuk ukuran pasti, pakai AR atau meteran.</p>
      </div>`);
  },
  actions: {
    ar() { if (!embedded) return toast('Ukur AR berjalan di aplikasi JARVIS di HP (butuh ARCore).', true); openNative('measure'); },
    async photo(b) {
      const mode = b?.dataset.mode || 'ukur';
      const [f] = await pick({ accept: 'image/*', capture: true });
      if (!f) return;
      if (['kenali', 'baca', 'terjemah'].includes(mode)) {
        toast('Mengunggah & membaca foto…');
        const [a] = await upload([f]);
        look = await post('/api/v1/app/measure/photo', { attachment_id: a.id, mode });
        return render();
      }
      if (mode === 'cat') {
        toast('Mengunggah & memperkirakan dinding…');
        const [a] = await upload([f]);
        const r = await post('/api/v1/app/measure/photo', { attachment_id: a.id, mode: 'cat', target: 'dinding yang akan dicat' });
        if (r.cat) paint = r.cat; else toast('Lebar/tinggi dinding tidak terbaca dari foto ini — isi ukurannya manual.', true);
        return render();
      }
      const v = await sheet(String(html`<form><span class="ttl">Apa yang diukur?</span><label class="field">Benda<input name="target" placeholder="mis. lebar & tinggi rumah tengah" required></label>
        <label class="field">Acuan yang kamu tahu (opsional)<input name="reference" placeholder="mis. pagar tingginya 1,5 m"></label><div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Ukur</button></div></form>`));
      if (!v?.target) return;
      toast('Mengunggah & memperkirakan…');
      const [a] = await upload([f]);
      const r = await post('/api/v1/app/measure/photo', { attachment_id: a.id, target: v.target, reference: v.reference || '' });
      toast(`${r.label}: ${Object.entries(r.ukuran).map(([k, x]) => `${k} ${range(x)}`).join(', ')}`);
      render();
    },
    async paintOf(b) { paint = await post(`/api/v1/app/measure/paint?width=${b.dataset.w}&height=${b.dataset.h}`); render(); },
    async paintForm(b, e) {
      e?.preventDefault();
      const f = document.getElementById('pf'); if (!f.reportValidity()) return;
      const v = Object.fromEntries(new FormData(f).entries());
      const n = (x) => String(x || '0').replace(',', '.');
      paint = await post(`/api/v1/app/measure/paint?width=${n(v.width)}&height=${n(v.height)}&coats=${v.coats}&openings=${n(v.openings)}`);
      render();
    },
    copy() { navigator.clipboard?.writeText(look.text); toast('Disalin'); },
    closeLook() { look = null; render(); },
    closePaint() { paint = null; render(); },
  },
};
export { laneChip };
