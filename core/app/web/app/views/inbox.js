// Perlu perhatian (mockups 13 & 30): Outlook, Gmail and WhatsApp in one list — what needs the owner, what is just good to know — with the same
// matter across sources as one card, quick WhatsApp replies, drafts in his style, and errands taken out of messages for the trip home.
import { $, del, get, go, header, html, icon, loading, on, post, put, render, sheet, speak, toast } from '../core.js';

const SRC = { outlook: ['Outlook', 'mail', 'cyan'], gmail: ['Gmail', 'mail', 'violet'], whatsapp: ['WhatsApp', 'chat', 'green'] };
let state = { source: '', data: null };

const when = (s) => {
  if (!s) return '';
  const d = new Date(s), now = new Date();
  return d.toDateString() === now.toDateString() ? d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString('id-ID', { weekday: 'short', day: 'numeric' });
};
const srcTag = (s) => html`<span class="tag ${SRC[s]?.[2] || ''}">${SRC[s]?.[0] || s}</span>`;

function outlookCard(o) {
  if (o.connected) return '';
  if (o.pending) {
    return html`<div class="card cyan"><span class="k cyan">Masuk ke Microsoft</span>
      <p class="sub">Buka <b>${o.pending.uri}</b> di HP atau laptop, lalu masukkan kode:</p>
      <div class="row sb"><span class="mono" style="font-size:26px;letter-spacing:3px">${o.pending.user_code}</span><a class="btn sm" href="${o.pending.uri}" target="_blank" rel="noopener">Buka</a></div>
      <span class="small">JARVIS menunggu… halaman ini berganti sendiri setelah kamu masuk.</span></div>`;
  }
  return html`<div class="card cyan"><span class="k cyan">Sambungkan Outlook</span>
    <p class="sub">Daftarkan aplikasi sekali di Microsoft Entra (Mobile &amp; desktop, aktifkan <i>public client flows</i>, izin Mail.ReadWrite, Mail.Send, Calendars.ReadWrite, User.Read, offline_access), lalu tempel client id-nya.</p>
    <label class="field">Client ID aplikasi<input id="cid" value="${o.client_id}" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" autocomplete="off"></label>
    <label class="field">Tenant (biarkan "common" bila ragu)<input id="ten" value="${o.tenant || 'common'}"></label>
    <button class="btn primary" data-act="connect">Sambungkan</button>
    <span class="small">JARVIS membaca, menandai, dan membuat draf. Email hanya terkirim saat kamu menekan Kirim.</span></div>`;
}

function itemRow(it) {
  const wa = it.source === 'whatsapp';
  return html`<div class="li" style="align-items:flex-start;padding:10px 0;border-color:var(--bd)">
    <div class="grow" style="min-width:0">
      <div class="row sb"><span style="font-size:14px;font-weight:600">${it.sender || '—'}</span><span class="mono" style="font-size:11px;color:var(--tx2)">${when(it.received_at)}</span></div>
      <div class="row" style="gap:6px;margin:3px 0">${srcTag(it.source)}${it.flagged ? html`<span class="tag amber">ditandai</span>` : ''}${it.due ? html`<span class="tag red">${it.due}</span>` : ''}</div>
      ${it.subject ? html`<span class="small" style="display:block;color:var(--tx)">${it.subject}</span>` : ''}
      <span class="small" style="display:block;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${it.snippet}</span>
      ${it.task ? html`<span class="small t-amber2">${icon('check', 12)} ${it.task}${it.data?.task_added ? ' — sudah di Catatan' : ''}</span>` : ''}
      <div class="chips" style="margin-top:8px">
        ${wa ? (it.replies || []).map((r) => html`<button class="chip" data-act="wa" data-id="${it.id}" data-text="${r}">${r}</button>`) : ''}
        ${wa ? html`<button class="chip" data-act="wacustom" data-id="${it.id}">${icon('send', 13)} Balas…</button>`
              : html`<button class="chip cyan" data-go="#/draf/${it.id}">${icon('text', 13)} Draf balasan</button>`}
        <button class="chip" data-act="state" data-id="${it.id}" data-s="done">${icon('check', 13)} Selesai</button>
        <button class="chip" data-act="snooze" data-id="${it.id}">${icon('clock', 13)} Nanti</button>
        ${it.job_reply ? html`<a class="chip amber" href="#/karier?tab=undangan">${icon('job', 13)} balasan wawancara: ${{ pending: 'menunggu jeda', sent: 'terkirim', draft: 'draf', cancelled: 'batal', failed: 'gagal' }[it.job_reply] || it.job_reply}</a>` : ''}
      </div></div></div>`;
}

function card(c, tone) {
  const head = c.items[0];
  return html`<div class="card ${tone}">
    <div class="row sb"><span class="ttl">${c.topic || head.sender}</span><span class="row" style="gap:4px">${c.sources.map((s) => html`<span title="${SRC[s]?.[0]}">${icon(SRC[s]?.[1] || 'mail', 14, `var(--${SRC[s]?.[2] || 'tx2'})`)}</span>`)}</span></div>
    ${head.reason ? html`<span class="small" style="color:var(--tx)">${head.reason}</span>` : (head.triage === 'new' ? html`<span class="small">baru masuk — sedang dipilah</span>` : '')}
    ${c.items.slice(0, 4).map(itemRow)}
    ${c.items.length > 4 ? html`<span class="small">+${c.items.length - 4} pesan lain di urusan ini</span>` : ''}</div>`;
}

export default {
  tab: 'beranda',
  feature: 'inbox',
  async render(root, route) {
    state.source = route.query.src || state.source || '';
    root.innerHTML = String(html`${header('Perlu perhatian')}<div class="scr">${loading()}</div>`);
    const d = state.data = await get(`/api/v1/app/inbox${state.source ? `?source=${state.source}` : ''}`);
    const c = d.counts, o = d.outlook;
    const chip = (v, label) => html`<button class="chip ${state.source === v ? 'on' : ''}" data-act="src" data-v="${v}">${label}</button>`;
    root.innerHTML = String(html`${header('Perlu perhatian', { sub: `${c.needs} butuh kamu · ${c.fyi} cukup tahu${c.new ? ` · ${c.new} baru` : ''}`,
      right: html`<button class="ib box" data-act="refresh" aria-label="Periksa sekarang">${icon('repeat', 18)}</button>` })}
      <div class="scr">
        ${d.needs.length && !o.pending ? '' : outlookCard(o)}
        ${!d.whatsapp_seen ? html`<div class="card"><span class="small">${icon('chat', 14)} WhatsApp belum terbaca — izinkan JARVIS membaca notifikasi di HP (Kontrol → Izin HP). Pesan OTP &amp; kata sandi tidak pernah dibaca.</span></div>` : ''}
        <div class="chips">${chip('', 'Semua')}${chip('email', `Email · ${d.sources.outlook + d.sources.gmail}`)}${chip('whatsapp', `WhatsApp · ${d.sources.whatsapp}`)}${d.family.length ? chip('keluarga', 'Keluarga') : ''}
          <button class="chip" data-act="readAll">${icon('speaker', 13)} Bacakan</button></div>
        ${d.snoozed ? html`<span class="small" style="padding:0 4px">${icon('clock', 12)} ${d.snoozed} ditunda — muncul lagi pada waktunya</span>` : ''}
        ${d.errands.length ? html`<div class="card amber"><span class="k amber">Titipan pulang</span>${d.errands.map((e) => html`<span class="sub">• ${e}</span>`)}<span class="small">Ikut di rencana pulang &amp; Catatan.</span></div>` : ''}
        ${d.needs.length ? d.needs.map((x) => card(x, 'amber')) : html`<div class="card green"><span class="k green">Aman</span><p class="sub">Tidak ada yang butuh kamu sekarang.</p></div>`}
        ${o.connected && c.needs ? html`<button class="btn block" data-act="flag">${icon('alert', 16)} Tandai yang penting di Outlook</button>` : ''}
        ${d.fyi.length ? html`<details class="card"><summary class="ttl" style="cursor:pointer">Cukup tahu · ${d.fyi.length}</summary>${d.fyi.map((x) => card(x, ''))}</details>` : ''}
        ${d.ignored.length ? html`<details class="card"><summary class="small" style="cursor:pointer">Diabaikan · ${d.counts.ignore} (promo, notifikasi otomatis)</summary>${d.ignored.map((x) => html`<span class="small">• ${x.sender}: ${x.subject}</span>`)}</details>` : ''}
        <details class="card"><summary class="small" style="cursor:pointer">Keluarga</summary><form id="famf" style="display:flex;flex-direction:column;gap:8px">
          <label class="field">Nama pengirim keluarga (pisah koma)<input name="family" value="${d.family.join(', ')}" placeholder="Istri, Ibu, Ayah"></label><button class="btn sm" data-act="saveFamily">Simpan</button></form></details>
        ${d.needs.length && !o.pending ? outlookCard(o) : ''}
        <p class="small" style="padding:0 4px">Dipilah tiap 5 menit lewat alur master (Hermes memilih otaknya; isi pesan tidak pernah ke model gratis).${o.connected ? ` Outlook: ${o.account}.` : ''}</p>
        ${o.connected ? html`<button class="btn ghost sm" data-act="disconnect">Putuskan Outlook</button>` : ''}
      </div>`);
    const offs = [on('notify', (e) => { if (e.route === '#/inbox') render(); })];
    if (o.pending) { const t = setInterval(async () => { const s = await get('/api/v1/app/outlook'); if (s.connected || !s.pending) render(); }, 5000); offs.push(() => clearInterval(t)); }
    return () => offs.forEach((f) => f());
  },
  actions: {
    src(b) { state.source = b.dataset.v; go(`#/inbox${state.source ? `?src=${state.source}` : ''}`); },
    async refresh() { toast('Memeriksa email & WhatsApp…'); const r = await post('/api/v1/app/inbox/refresh'); toast(`${r.triaged || 0} pesan dipilah${r.needs ? ` · ${r.needs} butuh kamu` : ''}`); render(); },
    async connect() {
      await put('/api/v1/app/outlook/client', { client_id: $('#cid').value.trim(), tenant: $('#ten').value.trim() || 'common' });
      await post('/api/v1/app/outlook/login');
      render();
    },
    async disconnect() { if ((await sheet(html`<p>Putuskan Outlook? JARVIS berhenti membaca email &amp; kalender kantormu.</p><div class="btns"><button class="btn" data-close="">Batal</button><button class="btn danger" data-close="y">Putuskan</button></div>`.toString())) !== 'y') return; await del('/api/v1/app/outlook'); render(); },
    async flag() { const r = await post('/api/v1/app/inbox/flag'); toast(`${r.flagged} email ditandai "JARVIS: Penting"`); render(); },
    async state(b) { await post(`/api/v1/app/inbox/item/${b.dataset.id}/${b.dataset.s}`); render(); },
    async snooze(b) {
      const v = await sheet(String(html`<span class="ttl">Ingatkan lagi</span><div class="g2">${[['1j', '1 jam lagi'], ['3j', '3 jam lagi'], ['14:00', 'Jam 14.00'], ['17:00', 'Jam 17.00'], ['besok', 'Besok pagi'], ['senin', 'Senin pagi']].map(([k, l]) => html`<button class="btn" data-close="${k}">${l}</button>`)}</div><button class="btn ghost" data-close="">Batal</button>`));
      if (!v) return;
      const r = await post(`/api/v1/app/inbox/item/${b.dataset.id}/snooze`, { until: v });
      toast(`Diingatkan ${new Date(r.until).toLocaleString('id-ID', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}`); render();
    },
    readAll() {
      const d = state.data; const n = d.needs;
      if (!n.length) return speak('Tidak ada pesan yang butuh kamu sekarang.');
      speak(`${n.length} urusan butuh kamu. ` + n.slice(0, 6).map((c, i) => `${i + 1}. ${c.topic || c.items[0].sender}: ${c.items[0].reason || c.items[0].subject || c.items[0].snippet}`).join('. '));
    },
    async saveFamily(b, e) { e?.preventDefault(); await put('/api/v1/app/settings/inbox', { family: new FormData($('#famf')).get('family').split(',').map((x) => x.trim()).filter(Boolean) }); toast('Tersimpan'); render(); },
    async wa(b) { const r = await post(`/api/v1/app/inbox/item/${b.dataset.id}/reply`, { text: b.dataset.text }); toast(`Terkirim ke ${r.to || 'WhatsApp'}`); render(); },
    async wacustom(b) {
      const v = await sheet(String(html`<form><label class="field">Balasan WhatsApp<textarea name="text" required maxlength="2000"></textarea></label>
        <span class="small">Dikirim lewat balasan notifikasi WhatsApp di HP-mu.</span><div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Kirim</button></div></form>`));
      if (!v?.text) return;
      const r = await post(`/api/v1/app/inbox/item/${b.dataset.id}/reply`, { text: v.text });
      toast(`Terkirim ke ${r.to || 'WhatsApp'}`); render();
    },
  },
};
