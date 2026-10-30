// Berkas & PDF (mockup 6): pick files, pick a tool — merge, take pages, compress, rotate, lock, to pictures / Word / text, pictures or Word
// to PDF — and download the result; or ask what a document says. Files are kept 30 days; results are in Dokumen.
import { $, api, get, header, html, icon, loading, post, render, sheet, toast } from '../core.js';
import { laneChip } from '../ui.js';
import { pick, upload } from '../upload.js';

let files = [], tool = null, meta = null;
const kb = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
const ACCEPT = { pdf: 'application/pdf,.pdf', image: 'image/*', docx: '.docx' };

async function download(id, name) {
  const blob = await api('GET', `/api/v1/documents/${id}`, undefined, { blob: true });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name || 'berkas'; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 30000);
}

export default {
  tab: 'beranda',
  feature: 'berkas',
  async render(root) {
    root.innerHTML = String(html`${header('Berkas & PDF')}<div class="scr">${loading()}</div>`);
    meta = await get('/api/v1/app/files');
    const t = meta.tools.find((x) => x.op === tool);
    root.innerHTML = String(html`${header('Berkas & PDF')}
      <div class="scr">
        <div class="g2">${meta.tools.map((x) => html`<button class="card ${x.op === tool ? 'sel' : ''}" data-act="tool" data-op="${x.op}" style="text-align:left;cursor:pointer;padding:10px 12px">
          <span class="ttl" style="font-size:13px">${x.label}</span><span class="small">${x.kinds.join('/')}${x.count === 'many' ? ' · beberapa' : ''}</span></button>`)}</div>
        ${t ? html`<div class="card cyan"><span class="k cyan">${t.label}</span>
          <div class="list">${files.map((f, i) => html`<div class="li"><span class="ico">${icon(f.kind === 'image' ? 'camera' : 'file', 16)}</span><div class="grow"><div style="font-size:14px">${f.name}</div><div class="small">${kb(f.size)} · ${f.kind}</div></div>
            <button class="ib sm" data-act="rm" data-i="${i}" aria-label="Buang">${icon('close', 14)}</button></div>`)}</div>
          <button class="btn" data-act="add">${icon('upload', 16)} ${files.length ? 'Tambah berkas' : 'Pilih berkas'}</button>
          ${['pisah', 'putar'].includes(t.op) ? html`<label class="field">Halaman (mis. 1-3, 5)<input id="pages" placeholder="${t.op === 'putar' ? 'semua' : '1-3'}"></label>` : ''}
          ${t.op === 'putar' ? html`<label class="field">Putar<select id="deg"><option value="90">90° kanan</option><option value="180">180°</option><option value="270">90° kiri</option></select></label>` : ''}
          ${t.op === 'kunci' ? html`<label class="field">Password untuk membuka PDF<input id="pw" type="password" minlength="4" autocomplete="new-password"></label>` : ''}
          <button class="btn primary lg" data-act="run" ${files.length ? '' : 'disabled'}>Kerjakan</button></div>` : html`<p class="small" style="padding:0 4px">Pilih alat di atas.</p>`}
        ${files.length === 1 && ['pdf', 'docx', 'text', 'xlsx', 'pptx'].includes(files[0].kind) ? html`<div class="card"><span class="k">Tentang ${files[0].name}</span>
          <div class="btns"><button class="btn" data-act="summary">${icon('bolt', 16)} Ringkas</button><button class="btn" data-act="ask">Tanya isinya</button></div><div id="fout"></div></div>` : ''}
        ${meta.recent.length ? html`<span class="sec">Hasil terakhir</span><div class="list">${meta.recent.map((r) => html`<div class="li"><span class="ico">${icon('file', 16)}</span>
          <div class="grow"><div style="font-size:14px">${r.title || r.label}</div><div class="small">${r.label} · ${r.format || ''}${r.result?.before ? ` · ${kb(r.result.before)} → ${kb(r.result.after)}` : ''}</div></div>
          ${r.document_id ? html`<button class="ib sm" data-act="dl" data-id="${r.document_id}" data-n="${(r.title || 'berkas')}.${r.format}" aria-label="Unduh">${icon('down', 16)}</button>` : ''}</div>`)}</div>` : ''}
        <p class="small" style="padding:0 4px">Diproses di server JARVIS (tanpa AI, lewat alur master); ringkasan & tanya jawab memakai otak ringan dan tidak ke model gratis.</p>
      </div>`);
  },
  actions: {
    tool(b) { tool = b.dataset.op; files = files.filter((f) => meta.tools.find((x) => x.op === tool).kinds.includes(f.kind)); render(); },
    rm(b) { files.splice(Number(b.dataset.i), 1); render(); },
    async add() {
      const t = meta.tools.find((x) => x.op === tool);
      const picked = await pick({ accept: t.kinds.map((k) => ACCEPT[k] || '').join(','), multiple: t.count === 'many' });
      if (!picked.length) return;
      toast(`Mengunggah ${picked.length} berkas…`);
      const got = await upload(picked);
      files = t.count === 'one' ? got.slice(-1) : [...files, ...got];
      render();
    },
    async run() {
      const body = { op: tool, ids: files.map((f) => f.id), pages: $('#pages')?.value || '', degrees: Number($('#deg')?.value || 90), password: $('#pw')?.value || '' };
      toast('Mengerjakan…');
      const r = await post('/api/v1/app/files/run', body);
      toast(`${r.label} selesai · ${kb(r.before)} → ${kb(r.after)}`);
      await download(r.document.id, r.document.download_name);
      files = []; render();
    },
    dl(b) { return download(b.dataset.id, b.dataset.n); },
    async summary() {
      $('#fout').innerHTML = String(loading());
      const r = await post(`/api/v1/app/files/${files[0].id}/summary`);
      $('#fout').innerHTML = String(html`<p class="sub">${r.ringkasan}</p>${(r.poin || []).map((p) => html`<span class="small">• ${p}</span>`)}${(r.tindakan || []).length ? html`<span class="small t-amber2">Tindakan: ${r.tindakan.join('; ')}</span>` : ''}<span class="small">${laneChip(r.lane)}</span>`);
    },
    async ask() {
      const v = await sheet(String(html`<form><label class="field">Pertanyaan<input name="q" required minlength="2"></label><div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Tanya</button></div></form>`));
      if (!v?.q) return;
      $('#fout').innerHTML = String(loading());
      const r = await post(`/api/v1/app/files/${files[0].id}/ask`, { question: v.q });
      $('#fout').innerHTML = String(html`<p class="sub">${r.answer}</p>`);
    },
  },
};
