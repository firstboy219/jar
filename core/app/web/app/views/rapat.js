// Rekam rapat (mockup 12): start the recording on the phone (everyone agreed), the transcript minute by minute while it runs, what was decided
// and who has to do what so far (his tasks first), a question about what was said — then the minutes, the .docx and the tasks in Catatan.
import { $, api, embedded, get, header, html, icon, loading, on, openNative, post, render, sheet, toast } from '../core.js';
import { dur } from '../lib.js';
import { laneChip } from '../ui.js';

let cur = null;

const clock = (startedAt) => {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};

function startForm(next, waiting) {
  const t = waiting?.title || (next ? next.title : '');
  const who = waiting?.participants?.join(', ') || (next?.attendees || []).join(', ');
  const soon = next && new Date(next.start_at) - Date.now() < 15 * 60e3;
  return html`
    ${next ? html`<div class="card violet"><div class="row sb"><span class="k violet">${soon ? 'Sebentar lagi' : 'Rapat berikutnya'}</span><span class="mono">${new Date(next.start_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}</span></div>
      <span class="ttl">${next.title}</span><span class="small">${[next.location, next.online ? 'online' : ''].filter(Boolean).join(' · ')}${next.attendees?.length ? ` · ${next.attendees.length} peserta` : ''}</span></div>` : ''}
    <form class="card" id="startf"><span class="k">Mulai rekam</span>
      <label class="field">Judul<input name="title" value="${t}" maxlength="150" placeholder="mis. Weekly Tim Produk"></label>
      <label class="field">Peserta (pisah koma — membantu mengenali nama)<input name="participants" value="${who}"></label>
      <label class="field">Agenda (opsional)<textarea name="agenda" maxlength="2000" style="min-height:70px">${waiting?.agenda || ''}</textarea></label>
      <label class="row" style="gap:10px;font-size:14px"><input type="checkbox" name="confidential" ${waiting?.confidential ? 'checked' : ''}> Rahasia — transkrip saja, tidak dikirim ke AI</label>
      <label class="row" style="gap:10px;font-size:14px"><input type="checkbox" name="consent" required> Semua peserta setuju direkam</label>
      <button class="btn primary lg" data-act="start">${icon('mic', 18)} Mulai rekam di HP</button>
      ${embedded ? '' : html`<span class="small">Mikrofon HP-mu yang merekam: aplikasi JARVIS di HP akan mulai sendiri.</span>`}</form>`;
}

function liveView(c, lv) {
  const tr = (lv?.transcript || []).slice().sort((a, b) => a.n - b.n);
  const tasks = (lv?.tugas || []).slice().sort((a, b) => (b.pemilik ? 1 : 0) - (a.pemilik ? 1 : 0));
  return html`
    <div class="card red"><div class="row sb"><span class="row" style="gap:8px"><span class="dot red"></span><span class="k" style="color:var(--red-t)">${c.state === 'recording' ? 'Merekam' : 'Menyusun notulen…'}</span></span>
      <span class="mono" id="clk" style="font-size:22px">${c.state === 'recording' ? clock(c.started_at) : dur(c.duration_s)}</span></div>
      <span class="ttl">${c.title || 'Rapat'}</span><span class="small">${c.chunks} menit terkirim${c.confidential ? ' · rahasia: hanya transkrip' : ''}${lv?.topik ? ` · sedang membahas: ${lv.topik}` : ''}</span>
      ${c.room || (c.participants || []).length ? html`<span class="small">${c.room ? `${icon('pin', 12)} ${c.room}` : ''}${c.room && c.participants?.length ? ' · ' : ''}${(c.participants || []).length ? `${c.participants.length} peserta: ${c.participants.slice(0, 6).join(', ')}${c.participants.length > 6 ? '…' : ''}` : ''}</span>` : ''}
      ${c.paused ? html`<span class="small t-amber2">Dijeda — yang dibicarakan sekarang tidak direkam.</span>` : ''}
      ${c.state === 'recording' ? html`<div class="btns"><button class="btn" data-act="pause" data-on="${c.paused ? '' : '1'}">${c.paused ? html`${icon('play', 16)} Lanjut` : html`${icon('stop', 16)} Jeda`}</button><button class="btn" data-act="mark">${icon('alert', 16)} Tandai</button><button class="btn danger" data-act="stop">Selesai</button></div>
        <label class="row" style="gap:8px;font-size:13px"><input type="checkbox" data-act="secret" ${c.confidential ? 'checked' : ''}> Rahasia — mulai sekarang tidak dikirim ke AI</label>` : ''}</div>
    ${(lv?.keputusan || []).length ? html`<div class="card green"><span class="k green">Keputusan sejauh ini</span>${lv.keputusan.map((k) => html`<span class="sub">• ${k}</span>`)}</div>` : ''}
    ${tasks.length ? html`<div class="card amber"><span class="k amber">Tugas</span>${tasks.map((t) => html`<div class="row sb"><span style="font-size:14px">${t.pemilik ? html`<b>Kamu</b>` : (t.siapa || '?')}: ${t.apa}</span><span class="mono small">${t.kapan || ''}</span></div>`)}</div>` : ''}
    ${!c.confidential && c.state === 'recording' ? html`<form class="card" id="askf"><label class="field">Tanya soal rapat ini<input name="q" placeholder="mis. tadi Sari bilang tenggatnya kapan?" required minlength="2"></label><button class="btn" data-act="ask">Tanya</button><div id="ans"></div></form>` : ''}
    <div class="card"><span class="k">Transkrip langsung</span><div id="tr" style="max-height:340px;overflow:auto;display:flex;flex-direction:column;gap:8px">
      ${tr.length ? tr.map((x) => html`<div><span class="mono small">menit ${x.n + 1}</span><p class="sub" style="margin:2px 0 0">${x.text}</p></div>`) : html`<span class="small">Menit pertama muncul ±1 menit setelah mulai.</span>`}</div></div>`;
}

async function doneView(c) {
  const m = await get(`/api/v1/meetings/${c.id}`);
  const s = m.summary || {};
  return html`<div class="card green"><span class="k green">Notulen siap</span><span class="ttl">${m.title}</span><span class="small">${dur(m.duration_s)}${m.speakers ? ` · ${Object.keys(m.speakers).length} pembicara` : ''}</span>
      <p class="sub">${s.ringkasan || ''}</p></div>
    ${(s.keputusan || []).length ? html`<div class="card"><span class="k green">Keputusan</span>${s.keputusan.map((k) => html`<span class="sub">• ${k}</span>`)}</div>` : ''}
    ${(s.action_items || []).length ? html`<div class="card amber"><span class="k amber">Action items · sudah di Catatan</span>${s.action_items.map((a) => html`<div class="row sb"><span style="font-size:14px">${a.siapa || '?'}: ${a.apa}</span><span class="mono small">${a.tenggat || ''}</span></div>`)}</div>` : ''}
    <div class="btns">${m.document_id ? html`<button class="btn" data-act="doc" data-id="${m.document_id}" data-t="${m.title}">${icon('file', 16)} Unduh .docx</button>` : ''}
      <button class="btn primary" data-act="openask" data-id="${m.id}">Tanya soal rapat ini</button></div>`;
}

export default {
  tab: 'beranda',
  feature: 'rapat',
  async render(root) {
    root.innerHTML = String(html`${header('Rekam rapat')}<div class="scr">${loading()}</div>`);
    const d = cur = await get('/api/v1/app/meeting');
    const c = d.card;
    let main;
    if (c && (c.state === 'recording' || c.state === 'processing')) main = liveView(c, d.live);
    else if (c && c.state === 'done') main = await doneView(c);
    else if (c && c.state === 'failed') main = html`<div class="card red"><span class="k">Notulen gagal</span><p class="sub">${c.error}</p></div>${startForm(d.next, null)}`;
    else main = startForm(d.next, c?.state === 'waiting' ? c : null);
    root.innerHTML = String(html`${header('Rekam rapat', { sub: c?.state === 'recording' ? 'sedang merekam' : '' })}
      <div class="scr">${main}
        ${d.recent.length ? html`<span class="sec">Rapat sebelumnya</span><div class="list">${d.recent.filter((m) => m.status === 'done').slice(0, 6).map((m) => html`<a class="li click" href="${m.page_id ? `/notes/#page/${m.page_id}` : '#/rapat'}">
          <span class="ico violet">${icon('meet', 18)}</span><div class="grow"><div class="ttl">${m.title}</div><div class="small">${new Date(m.started_at).toLocaleDateString('id-ID', { weekday: 'short', day: 'numeric', month: 'short' })} · ${dur(m.duration_s)}${m.action_items ? ` · ${m.action_items} tugas` : ''}${m.confidential ? ' · rahasia' : ''}</div></div>${icon('right', 16)}</a>`)}</div>` : ''}
        <p class="small" style="padding:0 4px">Transkrip per menit; keputusan &amp; tugas dicatat tiap 3 menit lewat alur master (tidak pernah ke model gratis). Notulen lengkap + .docx setelah selesai.</p>
      </div>`);
    const offs = [on('meeting_live', (e) => { if (e.id === c?.id) render(); })];
    if (c?.state === 'recording') {
      const t = setInterval(() => { const el = $('#clk'); if (el) el.textContent = clock(c.started_at); }, 1000);
      offs.push(() => clearInterval(t));
    }
    if (c && ['recording', 'processing', 'waiting'].includes(c.state)) { const p = setInterval(async () => { const n = await get('/api/v1/app/meeting'); if (n.card?.key !== c.key) render(); }, 10000); offs.push(() => clearInterval(p)); }
    else if (!c) { const p = setInterval(async () => { const n = await get('/api/v1/app/meeting'); if (n.card) render(); }, 15000); offs.push(() => clearInterval(p)); }
    return () => offs.forEach((f) => f());
  },
  actions: {
    async start() {
      const f = $('#startf');
      if (!f.reportValidity()) return;
      const v = Object.fromEntries(new FormData(f).entries());
      const r = await post('/api/v1/meetings/start-request', { title: v.title || '', participants: (v.participants || '').split(',').map((x) => x.trim()).filter(Boolean),
        agenda: v.agenda || '', confidential: !!v.confidential, consent: !!v.consent });
      if (!r.delivered) { toast('HP tidak terhubung — buka aplikasi JARVIS di HP', true); if (embedded) openNative('meetings'); return; }
      toast('HP mulai merekam…'); setTimeout(render, 2500);
    },
    async stop() {
      if ((await sheet(String(html`<p>Selesaikan rekaman? Notulen lengkap disusun setelah ini.</p><div class="btns"><button class="btn" data-close="">Lanjut rekam</button><button class="btn danger" data-close="y">Selesai</button></div>`))) !== 'y') return;
      await post('/api/v1/meetings/stop-request'); toast('Rekaman dihentikan — menyusun notulen'); setTimeout(render, 2500);
    },
    async pause(b) { const on = !!b.dataset.on; await post(`/api/v1/app/meeting/${cur.card.id}/pause`, { on }); toast(on ? 'Dijeda' : 'Merekam lagi'); render(); },
    async secret(b) { const on = b.checked; await post(`/api/v1/app/meeting/${cur.card.id}/confidential`, { on }); toast(on ? 'Rahasia: transkrip saja, tanpa AI' : 'Tidak rahasia lagi'); render(); },
    async mark() { const c = cur?.card; if (!c) return; await post(`/api/v1/meetings/${c.id}/marks`, { t: Math.max(0, Date.now() / 1000 - c.started_at), note: 'penting' }); toast('Ditandai'); },
    async ask(b, e) {
      const f = $('#askf');
      if (!f.reportValidity()) return;
      const q = new FormData(f).get('q');
      $('#ans').innerHTML = String(loading());
      const r = await post(`/api/v1/app/meeting/${cur.card.id}/ask`, { question: q });
      $('#ans').innerHTML = String(html`<p class="sub">${r.answer}</p>${r.lane ? html`<span class="small">${laneChip(r.lane)}</span>` : ''}`);
    },
    async openask(b) {
      const v = await sheet(String(html`<form><label class="field">Pertanyaan<input name="q" required minlength="2" placeholder="mis. siapa yang pegang laporan Q4?"></label><div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Tanya</button></div></form>`));
      if (!v?.q) return;
      const r = await post(`/api/v1/app/meeting/${b.dataset.id}/ask`, { question: v.q });
      await sheet(String(html`<p class="sub">${r.answer}</p>${(r.sources || []).map((s) => html`<span class="small">[${String(Math.floor(s.t / 60)).padStart(2, '0')}:${String(Math.floor(s.t % 60)).padStart(2, '0')}] ${s.text}</span>`)}<button class="btn" data-close="">Tutup</button>`));
    },
    async doc(b) {
      const blob = await api('GET', `/api/v1/documents/${b.dataset.id}`, undefined, { blob: true });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = `${b.dataset.t || 'notulen'}.docx`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 30000);
    },
  },
};
