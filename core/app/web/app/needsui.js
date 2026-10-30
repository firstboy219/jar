// What waits for the owner (ADR-087), drawn the same on the front page and on Butuh kamu: a run on his phone (route, the learned routine's
// track record, the rules it keeps; admin password), an approval, a pick between options (★ the one he usually takes), a question.
import { html, icon, post, raw, render, sheet, toast } from './core.js';

let byKey = new Map();
const key = (kind, id) => `${kind}:${id}`;

export function remember(items) { byKey = new Map(items.map((it) => [key(it.kind, it.id), it])); }

export function itemCard(it, compact = false) {
  byKey.set(key(it.kind, it.id), it);
  const tone = it.kind === 'phone' ? 'amber' : it.kind === 'choice' ? 'cyan' : it.kind === 'question' ? 'violet' : 'amber';
  if (it.kind === 'web') return webCard(it, compact);
  const actions = it.kind === 'choice'
    ? html`<div style="display:flex;flex-direction:column;gap:8px">${it.options.map((o) => html`<button class="btn ${o.i === it.recommended ? 'primary' : ''}" data-act="needPick" data-id="${it.id}" data-opt="${o.i}" style="justify-content:space-between">
        <span>${o.i === it.recommended ? '★ ' : ''}${o.label || o.title || `Opsi ${o.i + 1}`}</span>${o.waktu ? html`<span class="mono small">${o.waktu}</span>` : ''}</button>`)}
        ${it.recommended != null ? html`<span class="small">★ biasanya kamu pilih ini</span>` : ''}</div>`
    : it.kind === 'question'
      ? html`<div class="btns"><button class="btn violet" data-act="needAnswer" data-id="${it.id}">Jawab</button>${it.task_id ? html`<a class="btn" href="#/misi/${it.task_id}" style="flex:0 0 120px">Buka misi</a>` : ''}</div>`
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
function webCard(it, compact) {
  const tone = it.wait === 'tinjau' || it.wait === 'bayar' ? 'amber' : it.wait === 'pilih' || it.wait === 'tanya' ? 'violet' : 'cyan';
  let actions;
  if (it.session) {
    actions = html`<div class="btns"><button class="btn ${tone}" data-act="webShow" data-id="${it.id}">${icon('right', 16)} ${it.cta}</button>
      <button class="btn" data-act="webDone" data-id="${it.id}" style="flex:0 0 96px">Sudah</button><button class="btn ghost" data-act="needReject" data-kind="web" data-id="${it.id}" style="flex:0 0 80px">Batal</button></div>
      <span class="small">${it.wait === 'bayar' ? 'Halaman pembayarannya terbuka di HP — kamu yang bayar, lalu tekan Selesai.' : 'Halamannya terbuka di HP persis seperti yang JARVIS lihat. Selesaikan sendiri (JARVIS tidak membaca sandimu), lalu Selesai.'}</span>`;
  } else if (it.wait === 'pilih') {
    actions = html`<div style="display:flex;flex-direction:column;gap:8px">${it.options.map((o, i) => html`<button class="btn" data-act="webPick" data-id="${it.id}" data-opt="${i}" style="justify-content:flex-start;text-align:left">${o.label}</button>`)}</div>`;
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
async function askPassword(title, { kicker = 'Izin operasi HP', button = 'Setujui &amp; jalankan',
  note = 'Dari jadwal, proyek, atau kebiasaan yang kamu setujui: tanpa password, pengaman tetap sama.' } = {}) {
  if (host()?.hasBiometric?.()) {
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

/** Ask for the admin password (fingerprint when kept), then run `fn(password)`; a wrong kept password is forgotten. Null when cancelled. */
export async function withPassword(title, fn, opts = {}) {
  const pw = await askPassword(title, opts);
  if (!pw) return null;
  try {
    const r = await fn(pw.password);
    if (pw.remember) host()?.rememberPassword?.(pw.password);
    return r;
  } catch (e) {
    if (pw.bio && e.status === 422) host()?.rememberPassword?.('');
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
