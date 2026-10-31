// What waits for the owner (ADR-087), drawn the same on the front page and on Butuh kamu: a run on his phone (route, the learned routine's
// track record, the rules it keeps; admin password), an approval, a pick between options (★ the one he usually takes), a question.
import { get, html, icon, post, raw, render, sheet, toast } from './core.js';

let byKey = new Map();
const key = (kind, id) => `${kind}:${id}`;

export function remember(items) { byKey = new Map(items.map((it) => [key(it.kind, it.id), it])); }

export function itemCard(it, compact = false) {
  byKey.set(key(it.kind, it.id), it);
  const tone = it.kind === 'phone' ? 'amber' : it.kind === 'choice' ? 'cyan' : it.kind === 'question' ? 'violet' : 'amber';
  if (it.kind === 'web') return webCard(it, compact);
  if (it.kind === 'lagu') return songsCard(it, compact);
  const actions = it.kind === 'choice'
    ? html`<div style="display:flex;flex-direction:column;gap:8px">${it.options.map((o) => html`<button class="btn ${o.i === it.recommended ? 'primary' : ''}" data-act="needPick" data-id="${it.id}" data-opt="${o.i}" style="justify-content:space-between">
        <span>${o.i === it.recommended ? '★ ' : ''}${o.label || o.title || `Opsi ${o.i + 1}`}</span>${o.waktu ? html`<span class="mono small">${o.waktu}</span>` : ''}</button>`)}
        ${it.recommended != null ? html`<span class="small">★ biasanya kamu pilih ini</span>` : ''}</div>`
    : it.kind === 'question'
      ? (it.takeover
        ? html`<div class="btns">${it.task_id ? html`<a class="btn violet" href="#/misi/${it.task_id}">${icon('hand', 14)} Buka misi · Ambil alih</a>` : ''}
            <button class="btn" data-act="needDone" data-id="${it.id}" style="flex:0 0 ${it.task_id ? '140px' : 'auto'}">Sudah, lanjutkan</button></div>
          <span class="small">Selesaikan di layar misinya (Ambil alih), lalu ketuk “Sudah, lanjutkan”. Tidak perlu mengetik apa pun.</span>`
        : html`<div class="btns"><button class="btn violet" data-act="needAnswer" data-id="${it.id}">Jawab</button>${it.task_id ? html`<a class="btn" href="#/misi/${it.task_id}" style="flex:0 0 120px">Buka misi</a>` : ''}</div>`)
      : html`<div class="btns"><button class="btn ${tone}" data-act="needApprove" data-kind="${it.kind}" data-id="${it.id}" ${it.admin_only ? 'disabled' : ''}>${it.admin_only ? 'Hanya di admin web' : it.cta}</button>
          <button class="btn" data-act="needReject" data-kind="${it.kind}" data-id="${it.id}" style="flex:0 0 96px">Tolak</button></div>`;
  const r = it.route || {};
  return html`<div class="card ${tone}">
    <div class="row top"><span class="ico ${tone}">${icon(it.icon || 'shield', 20)}</span>
      <div class="grow"><div class="ttl">${it.title}</div><div class="sub">${it.sub}</div></div>
      ${it.expires_in_s ? html`<span class="mono small">${Math.ceil(it.expires_in_s / 60)} mnt</span>` : ''}</div>
    ${it.kind === 'phone' && (r.dari || r.ke) ? html`<div class="row" style="gap:8px;font-size:13px">${icon('pin', 14)}<span>${r.dari || '?'}</span>${icon('right', 12)}<span>${r.ke || '?'}</span></div>` : ''}
    ${it.kind === 'phone' && it.estimate ? html`<span class="small">${icon('wallet', 12)} perkiraan tarif ±Rp${Number(it.estimate).toLocaleString('id-ID')} — dibatalkan bila jauh berbeda</span>` : ''}
    ${it.kind === 'phone' && it.routine ? html`<span class="small" style="color:var(--green-t)">${icon('repeat', 12)} rutin "${it.routine.name}" · ${it.routine.steps} langkah · berhasil ${it.routine.ok}/${it.routine.runs}× — diputar tanpa AI</span>` : ''}
    ${it.kind === 'phone' && !compact ? html`<div class="card" style="background:var(--bg2)">${(it.rules || ['Hanya aplikasi itu · tanpa top-up/transfer · berhenti di layar PIN/OTP']).map((x) => html`<span class="small">${icon('shield', 12, 'var(--green)')} ${x}</span>`)}</div>` : ''}
    ${actions}
  </div>`;
}

// a web task waiting for him (ADR-087 batch I): the page itself on his phone, a pick, an answer, or the filled form to review
const mmss = (s) => (s ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '');

/** Songs to tick (owner 2026-10-31): the ticked ones become MP3s, the first plays as soon as it is ready. */
function songsCard(it, compact) {
  return html`<form class="card cyan" data-songs="${it.id}" style="gap:10px">
    <div class="row top"><span class="ico cyan">${icon('music', 20)}</span><div class="grow"><div class="ttl">${it.title}</div><div class="sub">${it.sub}</div></div></div>
    <div style="display:flex;flex-direction:column;gap:6px">${it.options.slice(0, compact ? 5 : 10).map((o, i) => html`<label class="row" style="gap:10px;cursor:pointer;padding:4px 0">
      <input type="checkbox" name="o" value="${i}" ${i === 0 ? 'checked' : ''} style="width:20px;height:20px;flex:0 0 20px">
      <img src="${o.cover}" alt="" loading="lazy" referrerpolicy="no-referrer" style="width:64px;height:36px;object-fit:cover;border-radius:6px;flex:0 0 64px">
      <span class="grow" style="min-width:0"><span style="display:block;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${o.title}</span>
        <span class="small">${o.channel}${o.duration_s ? ` · ${mmss(o.duration_s)}` : ''}</span></span></label>`)}</div>
    <div class="btns"><button class="btn cyan" data-act="songsGo" data-id="${it.id}">${icon('music', 14)} Jadikan MP3 &amp; putar</button>
      <button class="btn" data-act="needReject" data-kind="lagu" data-id="${it.id}" style="flex:0 0 96px">Batal</button></div></form>`;
}

/** One place to choose (a hotel, a restaurant): its picture, price, rating and reviews from the site, where it is and how to get there. */
function placeCard(it, c, i, compact) {
  return html`<div class="card" style="background:var(--bg2);gap:8px;padding:12px">
    ${c.gambar && !compact ? html`<img src="${c.gambar}" alt="${c.label}" loading="lazy" referrerpolicy="no-referrer" style="width:100%;max-height:170px;object-fit:cover;border-radius:10px">` : ''}
    <div class="row sb top" style="gap:8px"><b style="font-size:15px">${c.label}</b>${c.harga ? html`<span class="mono" style="white-space:nowrap">${c.harga}</span>` : ''}</div>
    ${c.rating || c.ulasan ? html`<span class="small">★ ${c.rating || '–'}${c.ulasan ? ` · ${c.ulasan}` : ''}</span>` : ''}
    ${c.kutipan ? html`<span class="small" style="font-style:italic">“${c.kutipan}”</span>` : ''}
    ${c.alamat || c.lokasi ? html`<span class="small">${icon('pin', 12)} ${c.alamat || c.lokasi}${c.perkiraan ? ' (lokasi perkiraan: daerahnya)' : ''}</span>` : ''}
    ${c.dari_stasiun ? html`<span class="small">${icon('train', 12)} ${c.dari_stasiun}</span>` : ''}
    ${c.dari_rumah ? html`<span class="small">${icon('car', 12)} ${c.dari_rumah}</span>` : ''}
    <div class="btns"><button class="btn violet sm" data-act="webPick" data-id="${it.id}" data-opt="${i}">Pilih ini</button>
      ${c.peta ? html`<a class="btn sm" href="${c.peta}" target="_blank" rel="noopener">${icon('pin', 14)} Peta</a>` : ''}
      ${c.link ? html`<a class="btn sm" href="${c.link}" target="_blank" rel="noopener">Lihat di situs</a>` : ''}</div></div>`;
}

function webCard(it, compact) {
  const tone = it.wait === 'tinjau' || it.wait === 'bayar' ? 'amber' : it.wait === 'pilih' || it.wait === 'tanya' ? 'violet' : 'cyan';
  let actions;
  if (it.session) {
    actions = html`<div class="btns"><button class="btn ${tone}" data-act="webShow" data-id="${it.id}">${icon('right', 16)} ${it.cta}</button>
      <button class="btn" data-act="webDone" data-id="${it.id}" style="flex:0 0 96px">Sudah</button><button class="btn ghost" data-act="needReject" data-kind="web" data-id="${it.id}" style="flex:0 0 80px">Batal</button></div>
      <span class="small">${it.wait === 'bayar' ? 'Halaman pembayarannya terbuka di HP — kamu yang bayar, lalu tekan Selesai.' : 'Halamannya terbuka di HP persis seperti yang JARVIS lihat. Selesaikan sendiri (JARVIS tidak membaca sandimu), lalu Selesai.'}</span>`;
  } else if (it.wait === 'pilih' && (it.cards || []).some((c) => c.harga || c.rating || c.alamat || c.peta || c.gambar)) {
    actions = html`<div style="display:flex;flex-direction:column;gap:10px">${it.cards.map((c, i) => placeCard(it, c, i, compact))}</div>
      <form class="row" data-ask="${it.id}" style="gap:8px"><input name="text" placeholder="Tanya dulu… mis. lihat ulasan & foto ${it.cards[0]?.label || ''}" style="flex:1;min-width:0">
        <button class="btn sm" data-act="webAsk" data-id="${it.id}">Tanya</button></form>
      <span class="small">Belum yakin? Minta JARVIS melihat detail, ulasan, atau lokasinya dulu — ia kembali dengan info yang lebih lengkap.</span>`;
  } else if (it.wait === 'pilih') {
    actions = html`<div style="display:flex;flex-direction:column;gap:8px">${it.options.map((o, i) => html`<button class="btn" data-act="webPick" data-id="${it.id}" data-opt="${i}" style="justify-content:flex-start;text-align:left">${o.label}</button>`)}</div>
      <form class="row" data-ask="${it.id}" style="gap:8px"><input name="text" placeholder="Tanya dulu…" style="flex:1;min-width:0"><button class="btn sm" data-act="webAsk" data-id="${it.id}">Tanya</button></form>`;
  } else if (it.wait === 'tanya') {
    actions = html`<button class="btn block" data-act="webAnswer" data-id="${it.id}">Jawab</button>${(it.missing || []).length ? html`<a class="small" href="#/web?tab=profil">atau isi profil web (${it.missing.join(', ')})</a>` : ''}`;
  } else {
    actions = html`<div class="btns"><button class="btn amber" data-act="needApprove" data-kind="web" data-id="${it.id}">${it.password ? icon('lock', 14) : ''} Kirim "${(it.button || 'lanjut').slice(0, 24)}"</button>
      <button class="btn" data-act="needReject" data-kind="web" data-id="${it.id}" style="flex:0 0 96px">Jangan</button></div>`;
  }
  return html`<div class="card ${tone}">
    <div class="row top"><span class="ico ${tone}">${icon(it.icon || 'pages', 20)}</span><div class="grow"><div class="ttl">${it.title}</div><div class="sub">${it.sub}</div></div></div>
    ${it.summary ? html`<span class="small">${it.summary}</span>` : ''}
    ${(it.rows || []).length && !compact ? html`<div class="card" style="background:var(--bg2)">${it.rows.map((r) => html`<div class="row sb" style="font-size:13px;gap:8px"><span class="small">${r.label}</span><span class="mono" style="text-align:right">${r.value}</span></div>`)}</div>` : ''}
    ${actions}</div>`;
}

const host = () => window.JarvisHost;

/** {password, remember, bio}: the fingerprint first when the phone keeps the password (APK ≥ 0.26), else typed. */
/** The phone's own lock (PIN / pattern / fingerprint) signs a one-time code from the server (APK ≥ 0.28). The first time, the admin password
 *  registers this phone once — and also approves this request. Returns what goes where the password would, or null. */
async function phoneApproval(title, force = false) {
  const st = force ? { enrolled: false } : await get('/api/v1/app/approval/key').catch(() => ({ enrolled: false }));
  if (!st.enrolled) {
    const pub = host().approvalKey();
    if (!pub) { toast('Pasang kunci layar (PIN/pola/sidik jari) di HP dulu — persetujuan memakai kunci layar HP.', true); return null; }
    const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:14px">
      <span class="k amber">Persetujuan dengan kunci layar HP</span><h3 style="margin:0;font:600 20px var(--f-head)">${force ? 'Daftarkan ulang HP ini' : 'Aktifkan sekali'}</h3>
      <p class="small" style="margin:0">Mulai sekarang setiap persetujuan cukup PIN/sidik jari HP. Masukkan password admin <b>sekali</b> untuk mendaftarkan HP ini (dan menyetujui: ${title}).</p>
      <label class="field">Password admin <input type="password" name="password" autocomplete="current-password" required autofocus></label>
      <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn amber">Daftarkan &amp; setujui</button></div></form>`));
    if (!r?.password) return null;
    await post('/api/v1/app/approval/key', { public_key: pub, password: r.password });
    toast('HP terdaftar — berikutnya cukup PIN/sidik jari.');
    return r.password;
  }
  const { nonce } = await post('/api/v1/app/approval/nonce');
  const sig = await new Promise((ok) => { window.__jarvisApprove = ok; host().approvalSign(nonce, title); });
  return sig ? `hp1:${nonce}:${sig}` : null;
}

async function askPassword(title, { kicker = 'Izin operasi HP', button = 'Setujui &amp; jalankan',
  note = 'Dari jadwal, proyek, atau kebiasaan yang kamu setujui: tanpa password, pengaman tetap sama.' } = {}) {
  if (host()?.approvalSign) {   // the app on the phone: its own lock (owner 2026-10-31: "Approval dibikin dari apps saja pakai pin/konfirmasi hp")
    const token = await phoneApproval(title);
    return token ? { password: token, phone: token.startsWith('hp1:') } : null;
  }
  if (!host()) {   // a browser: approvals are given in the app on the phone
    await sheet(String(html`<div style="display:flex;flex-direction:column;gap:12px"><span class="k amber">${kicker}</span>
      <h3 style="margin:0;font:600 20px var(--f-head)">${title}</h3>
      <p class="sub" style="margin:0">Persetujuan diberikan dari aplikasi JARVIS di HP dengan PIN atau sidik jari HP — tidak diketik di browser.</p>
      <button class="btn" data-close="">Mengerti</button></div>`));
    return null;
  }
  if (host()?.hasBiometric?.()) {   // an older app (before APK 0.28): the kept password behind the fingerprint
    const pw = await new Promise((ok) => { window.__jarvisBio = ok; host().biometric(title); });
    if (pw) return { password: pw, bio: true };
  }
  const canKeep = !!host()?.rememberPassword;
  const r = await sheet(String(html`<form class="col" style="display:flex;flex-direction:column;gap:14px">
    <span class="k amber">${kicker}</span><h3 style="margin:0;font:600 20px var(--f-head)">${title}</h3>
    <label class="field">Password admin <input type="password" name="password" autocomplete="current-password" required autofocus></label>
    ${canKeep ? html`<label class="row" style="gap:8px;font-size:13px"><input type="checkbox" name="remember"> Lain kali pakai sidik jari</label>` : ''}
    <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn amber">${raw(button)}</button></div>
    ${note ? html`<span class="small" style="text-align:center">${note}</span>` : ''}</form>`));
  return r && r.password ? { password: r.password, remember: !!r.remember } : null;
}

/** The owner's approval (the phone's lock in the app), then `fn(approval)`. A phone signature the server no longer knows (the app was
 *  reinstalled) → this phone is registered again once and `fn` runs with that. Null when cancelled. */
export async function withPassword(title, fn, opts = {}) {
  const pw = await askPassword(title, opts);
  if (!pw) return null;
  try {
    const r = await fn(pw.password);
    if (pw.remember) host()?.rememberPassword?.(pw.password);
    return r;
  } catch (e) {
    if (pw.bio && e.status === 422) host()?.rememberPassword?.('');
    if (pw.phone && e.status === 422 && /HP tidak sah/.test(e.message || '')) {
      const again = await phoneApproval(title, true);
      return again ? fn(again) : null;
    }
    throw e;
  }
}

/** The actions every screen showing these cards adds to its own. */
export const needActions = {
  async webShow(b) {
    const it = byKey.get(key('web', b.dataset.id));
    if (host()?.showWeb?.(it?.session || '', it?.title || '')) return toast('Halamannya terbuka di HP — tekan Selesai bila sudah.');
    toast('Buka aplikasi JARVIS di HP untuk menyelesaikan langkah ini.', true);
  },
  async webDone(b) { await post(`/api/v1/app/needs/web/${b.dataset.id}`, { approve: true }); toast('JARVIS melanjutkan.'); render(); },
  async songsGo(b, e) {
    e?.preventDefault();
    const f = b.closest('form'), choose = [...f.querySelectorAll('input[name=o]:checked')].map((x) => Number(x.value));
    if (!choose.length) return toast('Centang minimal satu lagu.', true);
    b.disabled = true;
    try {
      const r = await post(`/api/v1/app/music/picks/${b.dataset.id}`, { choose });
      toast(r.converter ? `${r.count} lagu sedang dijadikan MP3 — yang pertama langsung diputar.` : `${r.count} lagu: diputar lewat YouTube (converter MP3 belum dinyalakan).`);
    } catch (err) { toast(err.message || 'Gagal memproses', true); b.disabled = false; return; }
    render();
  },
  async webAsk(b, e) {
    e?.preventDefault();
    const f = b.closest('form'), text = f ? new FormData(f).get('text') : '';
    if (!text) return toast('Tulis dulu yang ingin kamu ketahui.', true);
    await post(`/api/v1/app/needs/web/${b.dataset.id}`, { text });
    toast('JARVIS melihatnya dulu, lalu kembali dengan info yang lebih lengkap.');
    render();
  },
  async webPick(b) { await post(`/api/v1/app/needs/web/${b.dataset.id}`, { option: Number(b.dataset.opt) }); toast('Pilihanmu dicatat — JARVIS melanjutkan.'); render(); },
  async webAnswer(b) {
    const it = byKey.get(key('web', b.dataset.id));
    const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:12px"><span class="k violet">Pertanyaan dari tugas web</span><p>${it?.title || ''}</p>
      <label class="field">Jawabanmu<textarea name="text" required></textarea></label><button class="btn primary">Kirim jawaban</button></form>`));
    if (!r?.text) return;
    await post(`/api/v1/app/needs/web/${b.dataset.id}`, { text: r.text });
    toast('Jawaban dikirim.'); render();
  },
  async needApprove(b) {
    const it = byKey.get(key(b.dataset.kind, b.dataset.id));
    const body = { approve: true };
    let pw = null;
    if (it?.password) { pw = await askPassword(it.title); if (!pw) return; body.password = pw.password; }
    try {
      await post(`/api/v1/app/needs/${b.dataset.kind}/${b.dataset.id}`, body);
    } catch (e) {
      if (pw?.bio && e.status === 422) host()?.rememberPassword?.('');   // the kept password is out of date: type it again next time
      throw e;
    }
    if (pw?.remember) host()?.rememberPassword?.(pw.password);
    toast('Disetujui. JARVIS mulai mengerjakan.');
    render();
  },
  async needReject(b) { await post(`/api/v1/app/needs/${b.dataset.kind}/${b.dataset.id}`, { approve: false }); toast('Ditolak.'); render(); },
  async needPick(b) { await post(`/api/v1/app/needs/choice/${b.dataset.id}`, { option: Number(b.dataset.opt) }); toast('Pilihanmu dicatat.'); render(); },
  async needDone(b) {
    await post(`/api/v1/app/needs/question/${b.dataset.id}`, { text: 'Sudah kuselesaikan, lanjutkan.' });
    toast('Misinya diberi tahu dan melanjutkan.');
    render();
  },
  async needAnswer(b) {
    const it = byKey.get(key('question', b.dataset.id));
    const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:12px"><span class="k violet">Pertanyaan dari misi</span><p style="white-space:pre-wrap">${it?.text || it?.title || ''}</p>
      ${it?.task_id ? html`<a class="small" href="#/misi/${it.task_id}" data-close="" style="color:var(--cyan)">Buka misinya (layar langsung · Ambil alih) →</a>` : ''}
      <label class="field">Jawabanmu<textarea name="text" required placeholder="mis. sudah, lanjutkan"></textarea></label><button class="btn primary">Kirim jawaban</button></form>`));
    if (!r?.text) return;
    await post(`/api/v1/app/needs/question/${b.dataset.id}`, { text: r.text });
    toast('Jawaban dikirim ke misinya.');
    render();
  },
};
