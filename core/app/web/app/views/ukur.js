// Kamera ukur (mockup 7): near things are measured on the phone with AR (tap points, read metres); far things (a house front) are estimated
// from a photo by the brain's eyes, as a range, from objects of known size in the picture. Every measurement is kept here.
import { embedded, get, header, html, icon, loading, openNative, post, render, sheet, toast } from '../core.js';
import { laneChip } from '../ui.js';
import { pick, upload } from '../upload.js';

const m2 = (v) => `${String(v).replace('.', ',')} m`;
const range = (r) => (r.min !== r.max ? `${m2(r.perkiraan)} (${String(r.min).replace('.', ',')}–${String(r.max).replace('.', ',')})` : m2(r.perkiraan));

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
        ${d.measures.length ? html`<span class="sec">Hasil ukur</span>${d.measures.map((m) => html`<div class="card">
          <div class="row sb"><span class="ttl">${m.label}</span><span class="tag ${m.kind === 'ar' ? 'cyan' : 'violet'}">${m.kind === 'ar' ? 'AR' : `foto · yakin ${m.data.yakin}`}</span></div>
          ${m.kind === 'ar' ? html`<span class="mono" style="font-size:20px">${m2(m.data.total)}</span>${m.data.segmen.length > 1 ? html`<span class="small">${m.data.segmen.map(m2).join(' + ')}</span>` : ''}${m.data.luas ? html`<span class="small">luas ${String(m.data.luas).replace('.', ',')} m²</span>` : ''}`
            : html`${Object.entries(m.data.ukuran).map(([k, r]) => html`<div class="row sb"><span class="small">${k}</span><span class="mono">${range(r)}</span></div>`)}
              ${m.data.acuan?.length ? html`<span class="small">acuan: ${m.data.acuan.join(', ')}</span>` : ''}${m.data.catatan ? html`<span class="small">${m.data.catatan}</span>` : ''}`}
          <span class="small">${new Date(m.created_at).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span></div>`)}`
          : html`<div class="card"><p class="sub">Belum ada hasil ukur.</p></div>`}
        <p class="small" style="padding:0 4px">Perkiraan dari foto memakai model penglihatan lewat alur master; selalu berupa rentang — untuk ukuran pasti, pakai AR atau meteran.</p>
      </div>`);
  },
  actions: {
    ar() { if (!embedded) return toast('Ukur AR berjalan di aplikasi JARVIS di HP (butuh ARCore).', true); openNative('measure'); },
    async photo() {
      const [f] = await pick({ accept: 'image/*', capture: true });
      if (!f) return;
      const v = await sheet(String(html`<form><span class="ttl">Apa yang diukur?</span><label class="field">Benda<input name="target" placeholder="mis. lebar & tinggi rumah tengah" required></label>
        <label class="field">Acuan yang kamu tahu (opsional)<input name="reference" placeholder="mis. pagar tingginya 1,5 m"></label><div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Ukur</button></div></form>`));
      if (!v?.target) return;
      toast('Mengunggah & memperkirakan…');
      const [a] = await upload([f]);
      const r = await post('/api/v1/app/measure/photo', { attachment_id: a.id, target: v.target, reference: v.reference || '' });
      toast(`${r.label}: ${Object.entries(r.ukuran).map(([k, x]) => `${k} ${range(x)}`).join(', ')}`);
      render();
    },
  },
};
export { laneChip };
