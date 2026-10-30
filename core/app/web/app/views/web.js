// Kerjakan di web (ADR-087 batch I): tell JARVIS what to get done on any website — book a hotel, a flight, a ticket — and it works on the
// site from your phone, step by step; when the site needs you (sign in, a robot check, a code, the payment) or before anything is sent, it
// waits on "Butuh kamu". The form profile fills the forms (personal data never goes to the AI); what worked once is replayed next time.
import { $, del, get, header, html, icon, loading, on, post, put, render, toast } from '../core.js';

let tab = 'tugas';
const ST = { queued: ['antre', ''], running: ['berjalan', 'cyan'], waiting: ['menunggumu', 'amber'], done: ['selesai', 'green'], failed: ['gagal', 'red'], stopped: ['dihentikan', ''] };
const FIELDS = [['nama', 'Nama lengkap (sesuai KTP/paspor)'], ['email', 'Email'], ['hp', 'Nomor HP'], ['tgl_lahir', 'Tanggal lahir (YYYY-MM-DD)'],
  ['jenis_kelamin', 'Jenis kelamin'], ['gelar', 'Sapaan (Tn/Ny/Nn)'], ['alamat', 'Alamat'], ['kota', 'Kota'], ['kode_pos', 'Kode pos'], ['kewarganegaraan', 'Kewarganegaraan']];
const SECRETS = [['no_ktp', 'Nomor KTP'], ['no_paspor', 'Nomor paspor'], ['paspor_berlaku', 'Paspor berlaku sampai']];
const IDEAS = ['Cari hotel di Bandung 5–6 Nov untuk 2 orang, budget Rp600 rb/malam, rating 8+, lalu pesan yang terbaik', 'Cek tiket pesawat Jakarta–Bali Jumat sore termurah dan pesan 1 kursi',
  'Pesan tiket kereta Gambir–Yogyakarta Sabtu pagi kelas eksekutif'];

export default {
  tab: 'beranda',
  feature: 'web',
  async render(root, route) {
    tab = route.query.tab || tab;
    root.innerHTML = String(html`${header('Kerjakan di web')}<div class="scr">${loading()}</div>`);
    const d = await get('/api/v1/app/web');
    const tabs = html`<div class="chips">${[['tugas', 'Tugas'], ['profil', 'Profil isian'], ['rutin', `Rutin · ${d.routines.length}`]].map(([k, l]) => html`<button class="chip ${tab === k ? 'on' : ''}" data-act="tab" data-k="${k}">${l}</button>`)}</div>`;
    let body;
    if (tab === 'profil') {
      body = html`<form class="card" id="pf"><span class="k">Profil isian formulir</span>
        <span class="small">Dipakai mengisi formulir pemesanan. Nilainya diisi JARVIS langsung di HP — tidak pernah dikirim ke AI (AI hanya menulis {profil.nama} dll).</span>
        ${FIELDS.map(([k, l]) => html`<label class="field">${l}<input name="${k}" value="${d.profile[k] || ''}"></label>`)}
        <span class="k" style="margin-top:6px">${icon('lock', 12)} Data identitas (terenkripsi)</span>
        ${SECRETS.map(([k, l]) => html`<label class="field">${l}<input name="${k}" placeholder="${d.profile[k] || 'belum diisi'}" autocomplete="off"></label>`)}
        <span class="small">Disimpan terenkripsi dengan kunci brankas JARVIS, ditampilkan tersamar. Sebelum formulir dikirim kamu selalu meninjau isinya.</span>
        <button class="btn primary" data-act="saveProfile">Simpan</button></form>`;
    } else if (tab === 'rutin') {
      body = d.routines.length ? html`<div class="list">${d.routines.map((r) => html`<div class="li"><div class="grow"><div class="ttl">${r.name}</div>
          <div class="small">${r.site} · ${r.steps} langkah · berhasil ${r.ok_runs}/${r.runs}× ${r.status === 'off' ? '· mati' : ''}</div></div>
          ${r.status === 'active' ? html`<button class="btn sm" data-act="off" data-id="${r.id}">Matikan</button>` : ''}</div>`)}</div>
        <p class="small" style="padding:0 4px">Setelah sebuah tugas berhasil, langkahnya disimpan per situs. Berikutnya diputar tanpa AI (satu panggilan untuk tanggal/kota dari permintaanmu); AI mengambil alih bila halamannya berubah. Pengiriman tetap kamu tinjau.</p>`
        : html`<div class="card"><p class="sub">Belum ada rutin web. Tugas yang berhasil akan dipelajari otomatis.</p></div>`;
    } else {
      body = html`<form class="card cyan" id="wf"><span class="k cyan">Mau dikerjakan apa di web?</span>
          <textarea name="goal" class="inp" required minlength="5" style="min-height:80px" placeholder="mis. ${IDEAS[0]}"></textarea>
          <label class="field">Situs (opsional)<input name="url" placeholder="https://www.traveloka.com — kosongkan, JARVIS yang cari"></label>
          <button class="btn primary lg" data-act="start">${icon('bolt', 18)} Kerjakan</button>
          <div class="chips" style="flex-wrap:wrap">${IDEAS.map((x) => html`<button type="button" class="chip" data-act="idea" data-v="${x}">${x.slice(0, 38)}…</button>`)}</div></form>
        ${d.waits.length ? html`<a class="card amber" href="#/butuh" style="text-decoration:none"><span class="k amber">${d.waits.length} langkah menunggumu</span><span class="small">${d.waits.map((w) => w.title).join(' · ')}</span></a>` : ''}
        ${d.tasks.length ? html`<span class="sec">Tugas web</span><div class="list">${d.tasks.map((t) => html`<a class="li click" href="${t.task_id ? `#/misi/${t.task_id}` : '#/web'}">
          <div class="grow" style="min-width:0"><div class="ttl" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${t.goal}</div>
          <div class="small">${t.site} · ${t.backend === 'hp' ? 'lewat HP' : 'browser server'}${t.routine_id ? ' · pakai rutin' : ''}${t.result?.ringkasan ? ` · ${t.result.ringkasan.slice(0, 80)}` : ''}</div></div>
          <span class="tag ${ST[t.status]?.[1] || ''}">${ST[t.status]?.[0] || t.status}</span>
          ${['queued', 'running', 'waiting'].includes(t.status) ? html`<button class="ib sm" data-act="stop" data-id="${t.id}" aria-label="Hentikan">${icon('stop', 14)}</button>` : ''}</a>`)}</div>` : ''}
        <div class="card"><span class="small">${icon('shield', 12, 'var(--green)')} JARVIS tidak pernah mengetik kata sandi, PIN, OTP, atau nomor kartu; tidak membuka situs bank/dompet digital/kripto; berhenti di pembayaran (kamu yang bayar); dan apa pun yang mengirim/memesan kamu tinjau dulu.</span></div>`;
    }
    root.innerHTML = String(html`${header('Kerjakan di web', { sub: 'semua situs — hotel, pesawat, tiket, formulir' })}<div class="scr">${tabs}${body}</div>`);
    return on('needs', () => { if (tab === 'tugas') render(); });
  },
  actions: {
    tab(b) { tab = b.dataset.k; render(); },
    idea(b) { $('#wf textarea').value = b.dataset.v; },
    async start(b, e) {
      e?.preventDefault();
      const f = $('#wf'); if (!f.reportValidity()) return;
      const v = Object.fromEntries(new FormData(f).entries());
      const r = await post('/api/v1/app/web', { goal: v.goal, url: v.url || '' });
      toast('JARVIS mulai bekerja di web (lewat HP)…');
      if (r.task_id) location.hash = `#/misi/${r.task_id}`; else render();
    },
    async stop(b, e) { e?.preventDefault(); await post(`/api/v1/app/web/${b.dataset.id}/stop`); toast('Dihentikan'); render(); },
    async off(b) { await del(`/api/v1/app/web/routines/${b.dataset.id}`); render(); },
    async saveProfile(b, e) {
      e?.preventDefault();
      const v = Object.fromEntries(new FormData($('#pf')).entries());
      await put('/api/v1/app/web/profile', v);
      toast('Profil tersimpan'); render();
    },
  },
};
