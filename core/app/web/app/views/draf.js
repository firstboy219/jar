// Draf email (mockup 27): the mail, a reply in the owner's own style (or formal / short / English), editable; saved into his Outlook Drafts
// and sent only when he presses Kirim (recorded as an approval he decided).
import { $, get, go, header, html, icon, loading, post, put, render, sheet, toast } from '../core.js';
import { pick, upload } from '../upload.js';
import { laneChip } from '../ui.js';

const STYLES = [['kamu', 'Gayaku'], ['formal', 'Formal'], ['singkat', 'Singkat'], ['english', 'English']];
let rec = null;
let cur = { id: null, item: null, style: 'kamu', lane: null };

// #/draf with no message: every reply drafted (waiting for Kirim first), and the ones sent this week.
async function list(root) {
  root.innerHTML = String(html`${header('Draf email')}<div class="scr">${loading()}</div>`);
  const { drafts } = await get('/api/v1/app/inbox/drafts');
  const waiting = drafts.filter((d) => !d.sent), sent = drafts.filter((d) => d.sent);
  const row = (d) => html`<a class="li click" href="#/draf/${d.id}"><span class="ico ${d.sent ? 'green' : 'cyan'}">${icon(d.sent ? 'check' : 'mail', 16)}</span>
    <div class="grow" style="min-width:0"><div class="ttl">${d.subject || '(tanpa subjek)'}</div><div class="small">ke ${d.sender}${d.style ? ` · gaya ${d.style}` : ''}</div>
    <div class="small" style="overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${d.preview || ''}</div></div>${icon('right', 16)}</a>`;
  root.innerHTML = String(html`${header('Draf email', { sub: `${waiting.length} menunggu dikirim` })}<div class="scr">
    ${waiting.length ? html`<div class="list">${waiting.map(row)}</div>` : html`<div class="card"><p class="sub">Tidak ada draf yang menunggu. Buka email di Perlu perhatian lalu minta JARVIS menulis balasan.</p><a class="btn" href="#/inbox">Perlu perhatian</a></div>`}
    ${sent.length ? html`<span class="sec">Terkirim minggu ini</span><div class="list">${sent.map(row)}</div>` : ''}</div>`);
}

export default {
  tab: 'beranda',
  feature: 'draf',
  async render(root, route) {
    const id = route.params[0];
    if (!id) return list(root);
    root.innerHTML = String(html`${header('Draf balasan')}<div class="scr">${loading()}</div>`);
    const it = await get(`/api/v1/app/inbox/item/${id}`);
    cur = { id, item: it, style: it.draft?.style || cur.style || 'kamu', lane: it.draft?.lane || null, files: cur.id === id ? (cur.files || []) : (it.draft?.attachments || []).map((a) => ({ id: a, name: 'lampiran' })) };
    const sent = it.draft?.sent || it.status === 'done';
    root.innerHTML = String(html`${header('Draf balasan', { sub: `ke ${it.sender}${it.sender_addr ? ` <${it.sender_addr}>` : ''}` })}
      <div class="scr">
        ${it.reason ? html`<div class="card amber"><span class="small">${it.reason}${it.due ? ` · tenggat ${it.due}` : ''}</span></div>` : ''}
        <details class="card" ${it.draft?.body ? '' : 'open'}><summary class="ttl" style="cursor:pointer">${it.subject}</summary>
          <span class="small">${it.sender} · ${new Date(it.received_at).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })}</span>
          <p class="sub" style="white-space:pre-wrap;max-height:320px;overflow:auto">${it.body}</p></details>
        <div class="chips">${STYLES.map(([v, l]) => html`<button class="chip ${cur.style === v ? 'on' : ''}" data-act="style" data-v="${v}">${l}</button>`)}</div>
        <label class="field">Mau bilang apa? (opsional)<input id="ins" placeholder="mis. setuju, tapi minta mundur ke Jumat" maxlength="600"></label>
        <button class="btn" data-act="voice" id="vbtn">${icon('mic', 16)} Ubah dengan suara</button><button class="btn" data-act="write">${icon('bolt', 16)} ${it.draft?.body ? 'Tulis ulang' : 'Tulis draf'}</button>
        <label class="field">Draf<textarea id="body" style="min-height:260px" placeholder="Draf akan muncul di sini…">${it.draft?.body || ''}</textarea></label>
        ${cur.lane ? html`<span class="small">Ditulis oleh ${laneChip(cur.lane)} lewat alur master${it.draft?.context ? ` · konteks: email ini${it.draft.context.samples ? `, ${it.draft.context.samples} contoh gayamu` : ''}${it.draft.context.instruction ? ', arahanmu' : ''}` : ''}</span>
          ${(it.draft?.context?.earlier || []).length || (it.draft?.context?.fact_list || []).length ? html`<details><summary class="small">Yang dipakai</summary>
            ${(it.draft.context.earlier || []).map((x) => html`<span class="small">✉ email sebelumnya: ${x}</span>`)}${(it.draft.context.fact_list || []).map((x) => html`<span class="small">• ${x}</span>`)}</details>` : ''}` : ''}
        ${it.draft?.needs_attachment && !(cur.files || []).length ? html`<div class="card amber"><span class="small">Emailnya menyebut “${it.draft.needs_attachment}” — sepertinya balasan perlu lampiran.</span><button class="btn sm" data-act="attach">${icon('upload', 14)} Lampirkan berkas</button></div>` : ''}
        ${it.source === 'outlook' ? html`<div class="row" style="gap:6px;flex-wrap:wrap">${(cur.files || []).map((f, i) => html`<span class="chip">📎 ${f.name}<button class="ib sm" data-act="unattach" data-i="${i}" aria-label="Buang">${icon('close', 12)}</button></span>`)}
          <button class="chip" data-act="attach">${icon('upload', 13)} Lampirkan</button></div>` : ''}
        ${sent ? html`<div class="card green"><span class="k green">Terkirim</span></div>` : html`<div class="btns">
          ${it.source === 'outlook' ? html`<button class="btn lg" data-act="save">Simpan ke Drafts</button>` : ''}
          <button class="btn primary lg" data-act="send">${icon('send', 16)} Kirim</button></div>`}
      </div>`);
  },
  actions: {
    style(b) { cur.style = b.dataset.v; for (const c of document.querySelectorAll('[data-act=style]')) c.classList.toggle('on', c === b); },
    async voice(b) {   // tap to start, tap again to stop: the recording becomes the instruction
      if (rec) { rec.stop(); return; }
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { return toast('Mikrofon tidak diizinkan.', true); }
      const chunks = [];
      rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop()); rec = null; b.innerHTML = String(html`${icon('mic', 16)} Ubah dengan suara`);
        const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' });
        toast('Mendengarkan arahanmu…');
        const [a] = await upload([new File([blob], 'arahan.webm', { type: blob.type })]);
        const d = await post(`/api/v1/app/inbox/item/${cur.id}/voice`, { attachment_id: a.id, style: cur.style });
        toast(`“${d.heard}”`); cur.lane = d.lane; render();
      };
      rec.start(); b.textContent = '■ Selesai bicara';
    },
    async write() {
      toast('Menulis draf…');
      const d = await post(`/api/v1/app/inbox/item/${cur.id}/draft`, { style: cur.style, instruction: $('#ins').value.trim() });
      $('#body').value = d.body; cur.lane = d.lane;
      render();
    },
    async save() { await put(`/api/v1/app/inbox/item/${cur.id}/draft`, { body: $('#body').value, attachments: cur.files.map((f) => f.id) }); toast('Tersimpan di folder Drafts Outlook'); },
    async attach() { const p = await pick({ multiple: true }); if (!p.length) return; toast('Mengunggah…'); cur.files = [...cur.files, ...(await upload(p))].slice(0, 5); const body = $('#body').value; render(); setTimeout(() => { if ($('#body')) $('#body').value = body; }, 400); },
    unattach(b) { cur.files.splice(Number(b.dataset.i), 1); render(); },
    async send() {
      const body = $('#body').value.trim();
      if (!body) return toast('Draf masih kosong', true);
      const ok = await sheet(String(html`<span class="ttl">Kirim ke ${cur.item.sender_addr || cur.item.sender}?</span><p class="sub" style="white-space:pre-wrap;max-height:240px;overflow:auto">${body}</p>
        <div class="btns"><button class="btn" data-close="">Batal</button><button class="btn primary" data-close="y">Kirim sekarang</button></div>`));
      if (ok !== 'y') return;
      if (cur.files.length) await put(`/api/v1/app/inbox/item/${cur.id}/draft`, { body, attachments: cur.files.map((f) => f.id) });
      await post(`/api/v1/app/inbox/item/${cur.id}/send`, { body });
      toast('Email terkirim'); go('#/inbox');
    },
  },
};
