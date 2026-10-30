// Draf email (mockup 27): the mail, a reply in the owner's own style (or formal / short / English), editable; saved into his Outlook Drafts
// and sent only when he presses Kirim (recorded as an approval he decided).
import { $, get, go, header, html, icon, loading, post, put, render, sheet, toast } from '../core.js';
import { pick, upload } from '../upload.js';
import { laneChip } from '../ui.js';

const STYLES = [['kamu', 'Gayaku'], ['formal', 'Formal'], ['singkat', 'Singkat'], ['english', 'English']];
let cur = { id: null, item: null, style: 'kamu', lane: null };

export default {
  tab: 'beranda',
  feature: 'inbox',
  async render(root, route) {
    const id = route.params[0];
    if (!id) return go('#/inbox');
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
        <button class="btn" data-act="write">${icon('bolt', 16)} ${it.draft?.body ? 'Tulis ulang' : 'Tulis draf'}</button>
        <label class="field">Draf<textarea id="body" style="min-height:260px" placeholder="Draf akan muncul di sini…">${it.draft?.body || ''}</textarea></label>
        ${cur.lane ? html`<span class="small">Ditulis oleh ${laneChip(cur.lane)} lewat alur master${it.draft?.context ? ` · konteks: email ini${it.draft.context.samples ? `, ${it.draft.context.samples} contoh gayamu` : ''}${it.draft.context.facts ? `, ${it.draft.context.facts} fakta tentangmu` : ''}${it.draft.context.instruction ? ', arahanmu' : ''}` : ''}</span>` : ''}
        ${it.source === 'outlook' ? html`<div class="row" style="gap:6px;flex-wrap:wrap">${(cur.files || []).map((f, i) => html`<span class="chip">📎 ${f.name}<button class="ib sm" data-act="unattach" data-i="${i}" aria-label="Buang">${icon('close', 12)}</button></span>`)}
          <button class="chip" data-act="attach">${icon('upload', 13)} Lampirkan</button></div>` : ''}
        ${sent ? html`<div class="card green"><span class="k green">Terkirim</span></div>` : html`<div class="btns">
          ${it.source === 'outlook' ? html`<button class="btn lg" data-act="save">Simpan ke Drafts</button>` : ''}
          <button class="btn primary lg" data-act="send">${icon('send', 16)} Kirim</button></div>`}
      </div>`);
  },
  actions: {
    style(b) { cur.style = b.dataset.v; for (const c of document.querySelectorAll('[data-act=style]')) c.classList.toggle('on', c === b); },
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
