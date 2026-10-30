// Karier JobStreet (mockup 32): postings found on schedule and scored against his CV (what fits, what is missing), applied for by JARVIS within
// his rules or by his tap, the progress of each application, and replies to interview invitations — sent after an undo window, or as a
// draft for his Kirim — with the interview in his calendar.
import { $, get, go, header, html, icon, loading, on, post, put, render, sheet, speak, toast } from '../core.js';
import { pick, upload } from '../upload.js';

const TABS = [['cocok', 'Cocok'], ['lamaran', 'Lamaran'], ['undangan', 'Undangan'], ['atur', 'Atur']];
const STATUS = { applying: ['dikirim…', 'cyan'], applied: ['terkirim', 'cyan'], viewed: ['dilihat', 'violet'], interview: ['wawancara', 'amber'], offer: ['penawaran!', 'green'],
  rejected: ['tidak lanjut', ''], failed: ['gagal', 'red'], withdrawn: ['ditarik', ''] };
let tab = 'cocok', cur = null;
const when = (s) => (s ? new Date(s).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' }) : '');
const list = (v) => (v || []).join(', ');

function ring(score) {
  const c = score >= 85 ? 'green' : score >= 70 ? 'cyan' : 'amber';
  return html`<span class="mono" style="min-width:52px;height:52px;border-radius:26px;border:3px solid var(--${c});display:flex;align-items:center;justify-content:center;font-size:15px;flex:none">${score ?? '–'}</span>`;
}

function cocok(d) {
  const s = d.settings;
  if (!d.good.length) return html`<div class="card"><p class="sub">${d.ready.roles ? 'Belum ada lowongan yang dinilai. Tekan "Cari sekarang".' : 'Isi peran yang dicari dan CV di tab Atur.'}</p></div>`;
  return d.good.map((p) => html`<div class="card ${p.score >= s.min_match ? '' : ''}"><div class="row top" style="gap:12px">${ring(p.score)}
      <div class="grow" style="min-width:0"><a class="ttl" href="${p.url}" target="_blank" rel="noopener">${p.title}</a><div class="small">${p.company} · ${p.location}${p.salary ? ` · ${p.salary}` : ''}${p.arrangement ? ` · ${p.arrangement}` : ''}</div>
        <span class="small">${p.score_data?.alasan || ''}</span></div></div>
    ${p.score_data?.cocok?.length ? html`<span class="small" style="color:var(--green-t)">✓ ${list(p.score_data.cocok)}</span>` : ''}
    ${p.score_data?.kurang?.length ? html`<span class="small t-amber2">✗ ${list(p.score_data.kurang)}</span>` : ''}
    ${p.questions?.length ? html`<span class="small">${p.questions.length} pertanyaan penyaringan — dijawab dari profilmu</span>` : ''}
    <div class="btns">${p.link_out ? html`<a class="btn" href="${p.url}" target="_blank" rel="noopener">Lamar di situs perusahaan</a>` : html`<button class="btn primary" data-act="apply" data-id="${p.id}">Lamar lewat JobStreet</button>`}
      <button class="btn ghost" data-act="skip" data-id="${p.id}">Lewati</button></div></div>`);
}

function lamaran(d) {
  if (!d.applications.length) return html`<div class="card"><p class="sub">Belum ada lamaran.</p></div>`;
  return d.applications.map((a) => html`<details class="card"><summary style="cursor:pointer;list-style:none"><div class="row sb"><span class="ttl">${a.title}</span><span class="tag ${STATUS[a.status][1]}">${STATUS[a.status][0]}</span></div>
      <span class="small">${a.company} · ${a.via === 'jarvis' ? 'oleh JARVIS' : 'olehmu'} · ${when(a.applied_at || a.updated_at)}${a.interview?.at ? ` · wawancara ${new Date(a.interview.at).toLocaleString('id-ID', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}` : ''}</span></summary>
    ${(a.events || []).map((e) => html`<span class="small">• ${when(e.at)} ${e.kind}: ${e.text}</span>`)}
    ${a.cover_letter ? html`<details><summary class="small">Surat lamaran</summary><p class="sub" style="white-space:pre-wrap">${a.cover_letter}</p></details>` : ''}</details>`);
}

function undangan(d) {
  const now = Date.now();
  const rs = d.replies;
  const iv = d.applications.filter((a) => a.status === 'interview');
  return html`${rs.length ? rs.map((r) => {
      const left = r.send_at ? Math.max(0, Math.round((new Date(r.send_at) - now) / 1000)) : null;
      return html`<div class="card ${r.status === 'pending' ? 'amber' : r.status === 'sent' ? 'green' : r.status === 'failed' ? 'red' : 'cyan'}">
        <div class="row sb"><span class="ttl">${r.company || 'Undangan'}</span><span class="tag">${{ pending: `terkirim dalam ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`, draft: 'draf', sent: 'terkirim', cancelled: 'batal', failed: 'gagal' }[r.status]}</span></div>
        <span class="small">${r.proposal?.summary || ''}</span>
        ${r.proposal?.accept ? html`<span class="small" style="color:var(--green-t)">Menerima: ${new Date(r.proposal.accept).toLocaleString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}</span>`
          : (r.proposal?.slots || []).length ? html`<span class="small">Menawarkan: ${r.proposal.slots.map((x) => new Date(x).toLocaleString('id-ID', { weekday: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })).join(' · ')}</span>` : ''}
        ${['draft', 'failed'].includes(r.status) ? html`<textarea class="inp" id="rb${r.id}" style="min-height:160px">${r.body}</textarea>` : html`<details><summary class="small">Isi balasan</summary><p class="sub" style="white-space:pre-wrap">${r.body}</p></details>`}
        ${r.error ? html`<span class="small t-amber2">${r.error}</span>` : ''}
        <a class="small" href="#/draf/${r.inbox_item_id}">${icon('mail', 12)} Lihat email undangannya</a>
        <div class="btns">${r.status === 'pending' ? html`<button class="btn danger" data-act="cancel" data-id="${r.id}">Batalkan</button>` : ''}
          ${['draft', 'failed'].includes(r.status) ? html`<button class="btn primary" data-act="send" data-id="${r.id}">${icon('send', 16)} Kirim</button>` : ''}</div></div>`;
    }) : html`<div class="card"><p class="sub">Belum ada undangan. Email undangan dari perusahaan yang kamu lamar dideteksi otomatis dari Perlu perhatian (Outlook/Gmail).</p></div>`}
    ${iv.length ? html`<span class="sec">Wawancara</span>${iv.map((a) => html`<div class="card"><span class="ttl">${a.company}</span><span class="small">${a.title}${a.interview?.at ? ` · ${new Date(a.interview.at).toLocaleString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}` : ' · menunggu jadwal'}</span>
      ${a.interview?.prep ? html`<details><summary class="small" style="cursor:pointer">${icon('book', 12)} Persiapan & latihan</summary>
        ${(a.interview.prep.pertanyaan || []).map((q) => html`<div style="margin-top:6px"><span style="font-size:14px">${q.tanya}</span><br><span class="small">${q.jawab_singkat}</span></div>`)}
        ${a.interview.prep.tentang ? html`<span class="small">Tentang: ${a.interview.prep.tentang}</span>` : ''}${(a.interview.prep.bawa || []).length ? html`<span class="small">Bawa: ${a.interview.prep.bawa.join(', ')}</span>` : ''}
        <button class="btn sm" data-act="practice" data-id="${a.id}">${icon('speaker', 14)} Latihan (dibacakan)</button></details>` : html`<span class="small">Catatan persiapan dibuat malam sebelum wawancara.</span>`}</div>`)}` : ''}`;
}

function atur(d) {
  const s = d.settings;
  return html`<form class="card" id="jf"><span class="k">Yang dicari</span>
      <label class="field">Peran (pisah koma)<input name="roles" value="${list(s.roles)}" placeholder="mis. Product Manager, Business Analyst"></label>
      <label class="field">Lokasi (pisah koma; "Remote" boleh)<input name="locations" value="${list(s.locations)}" placeholder="Jakarta Raya, Bogor"></label>
      <div class="g2"><label class="field">Gaji minimal (Rp)<input name="min_salary" type="number" min="0" step="500000" value="${s.min_salary || ''}"></label>
        <label class="field">Skor minimal (%)<input name="min_match" type="number" min="40" max="100" value="${s.min_match}"></label></div>
      <label class="field">Lewati bila mengandung (pisah koma)<input name="exclude" value="${list(s.exclude)}" placeholder="mis. MLM, sales lapangan, PT Contoh"></label>
      <label class="field">Catatan profil (opsional)<textarea name="profile" class="inp" style="min-height:70px">${s.profile}</textarea></label>
      <span class="k" style="margin-top:6px">Otonom</span>
      <label class="row" style="gap:10px;font-size:14px"><input type="checkbox" name="auto_apply" ${s.auto_apply ? 'checked' : ''}> JARVIS melamar sendiri lowongan ≥ skor minimal</label>
      <div class="g2"><label class="field">Maks lamaran/hari<input name="max_per_day" type="number" min="1" max="30" value="${s.max_per_day}"></label>
        <label class="field">Jam cari (pisah koma)<input name="times" value="${list(s.times)}"></label></div>
      <label class="row" style="gap:10px;font-size:14px"><input type="checkbox" name="auto_reply_invites" ${s.auto_reply_invites ? 'checked' : ''}> Balas undangan wawancara otomatis</label>
      <label class="field">Jeda batal sebelum terkirim (menit)<input name="undo_min" type="number" min="1" max="60" value="${s.undo_min}"></label>
      <button class="btn primary" data-act="save">Simpan</button></form>
    <div class="card"><span class="k">CV</span><span class="small">${s.cv_attachment ? 'CV tersimpan — dipakai untuk menilai lowongan & menulis surat lamaran (CV di aplikasi JobStreet tetap dipakai saat melamar).' : 'Unggah CV (PDF/Word).'}</span>
      <button class="btn" data-act="cv">${icon('upload', 16)} ${s.cv_attachment ? 'Ganti CV' : 'Unggah CV'}</button></div>`;
}

export default {
  tab: 'beranda',
  feature: 'karier',
  async render(root, route) {
    tab = route.query.tab || tab;
    root.innerHTML = String(html`${header('Karier JobStreet')}<div class="scr">${loading()}</div>`);
    const d = cur = await get('/api/v1/app/jobs');
    const body = { cocok, lamaran, undangan, atur }[tab](d);
    root.innerHTML = String(html`${header('Karier JobStreet', { sub: `${d.week} lamaran minggu ini · ${d.counts.seen} dilihat HR · ${d.counts.interview} wawancara${d.counts.offer ? ` · ${d.counts.offer} penawaran` : ''}`,
      right: html`<button class="ib box" data-act="round" aria-label="Cari sekarang">${icon('search', 18)}</button>` })}
      <div class="scr">
        ${!d.ready.roles || !d.ready.cv ? html`<div class="card amber"><span class="small">Lengkapi ${[!d.ready.roles && 'peran yang dicari', !d.ready.cv && 'CV'].filter(Boolean).join(' dan ')} di tab Atur agar JARVIS bisa mencari & menilai.</span></div>` : ''}
        <div class="chips">${TABS.map(([k, l]) => html`<button class="chip ${tab === k ? 'on' : ''}" data-act="tab" data-k="${k}">${l}${k === 'undangan' && d.replies.some((r) => ['pending', 'draft'].includes(r.status)) ? html` <span class="dot amber"></span>` : ''}</button>`)}</div>
        ${body}
        <p class="small" style="padding:0 4px">Dicari ${d.settings.times.join(' & ')} lewat API JobStreet (tanpa AI); dinilai & surat lamaran oleh otak ringan (tidak ke model gratis); melamar lewat aplikasi JobStreet di HP-mu.${d.last_round ? ` Terakhir: ${new Date(d.last_round).toLocaleString('id-ID', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}.` : ''}</p>
      </div>`);
    const t = tab === 'undangan' && d.replies.some((r) => r.status === 'pending') ? setInterval(render, 15000) : null;
    const off = on('notify', (e) => { if ((e.route || '').startsWith('#/karier')) render(); });
    return () => { off(); if (t) clearInterval(t); };
  },
  actions: {
    tab(b) { tab = b.dataset.k; go(`#/karier?tab=${tab}`); },
    async round() { toast('Mencari di JobStreet & menilai…'); const r = await post('/api/v1/app/jobs/round'); toast(`${r.search?.new ?? 0} baru · ${r.score?.scored ?? 0} dinilai · ${r.good} cocok`); render(); },
    async apply(b) {
      const p = cur.good.find((x) => x.id === b.dataset.id);
      if ((await sheet(String(html`<span class="ttl">Lamar ${p.title}?</span><p class="sub">JARVIS menulis surat lamaran & jawaban penyaringan, lalu melamar lewat aplikasi JobStreet di HP-mu dengan CV yang tersimpan di sana.</p>
        <div class="btns"><button class="btn" data-close="">Batal</button><button class="btn primary" data-close="y">Lamar</button></div>`))) !== 'y') return;
      await post(`/api/v1/app/jobs/post/${b.dataset.id}/apply`); toast('Menulis surat & membuka JobStreet di HP…'); render();
    },
    practice(b) {
      const a = cur.applications.find((x) => String(x.id) === b.dataset.id);
      speak((a?.interview?.prep?.pertanyaan || []).map((q, i) => `Pertanyaan ${i + 1}: ${q.tanya}`).join('. '));
    },
    async skip(b) { await post(`/api/v1/app/jobs/post/${b.dataset.id}/skip`); render(); },
    async cancel(b) { await post(`/api/v1/app/jobs/reply/${b.dataset.id}/cancel`); toast('Dibatalkan — tersimpan sebagai draf'); render(); },
    async send(b) { await post(`/api/v1/app/jobs/reply/${b.dataset.id}/send`, { body: $(`#rb${b.dataset.id}`)?.value || '' }); toast('Balasan terkirim'); render(); },
    async save(b, e) {
      e?.preventDefault();
      const f = $('#jf'); const v = Object.fromEntries(new FormData(f).entries());
      const split = (x) => String(x || '').split(',').map((y) => y.trim()).filter(Boolean);
      await put('/api/v1/app/settings/jobs', { roles: split(v.roles), locations: split(v.locations), min_salary: Number(v.min_salary) || 0, min_match: Number(v.min_match) || 80,
        exclude: split(v.exclude), profile: v.profile || '', auto_apply: !!v.auto_apply, max_per_day: Number(v.max_per_day) || 8, times: split(v.times),
        auto_reply_invites: !!v.auto_reply_invites, undo_min: Number(v.undo_min) || 5 });
      toast('Tersimpan'); render();
    },
    async cv() {
      const [f] = await pick({ accept: '.pdf,.docx,application/pdf' });
      if (!f) return;
      toast('Mengunggah & membaca CV…');
      const [a] = await upload([f]);
      const r = await put('/api/v1/app/jobs/cv', { attachment_id: a.id });
      toast(`CV terbaca: ${r.profile?.ringkasan?.slice(0, 80) || r.name}`); render();
    },
  },
};
