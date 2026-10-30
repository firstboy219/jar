// What waits for the owner (ADR-087), drawn the same on the front page and on Butuh kamu: a run on his phone (route, the learned routine's
// track record, the rules it keeps; admin password), an approval, a pick between options (★ the one he usually takes), a question.
import { html, icon, post, render, sheet, toast } from './core.js';

let byKey = new Map();
const key = (kind, id) => `${kind}:${id}`;

export function remember(items) { byKey = new Map(items.map((it) => [key(it.kind, it.id), it])); }

export function itemCard(it, compact = false) {
  byKey.set(key(it.kind, it.id), it);
  const tone = it.kind === 'phone' ? 'amber' : it.kind === 'choice' ? 'cyan' : it.kind === 'question' ? 'violet' : 'amber';
  const actions = it.kind === 'choice'
    ? html`<div style="display:flex;flex-direction:column;gap:8px">${it.options.map((o) => html`<button class="btn ${o.i === it.recommended ? 'primary' : ''}" data-act="needPick" data-id="${it.id}" data-opt="${o.i}" style="justify-content:space-between">
        <span>${o.i === it.recommended ? '★ ' : ''}${o.label || o.title || `Opsi ${o.i + 1}`}</span>${o.waktu ? html`<span class="mono small">${o.waktu}</span>` : ''}</button>`)}
        ${it.recommended != null ? html`<span class="small">★ biasanya kamu pilih ini</span>` : ''}</div>`
    : it.kind === 'question'
      ? html`<button class="btn block" data-act="needAnswer" data-id="${it.id}">Jawab</button>`
      : html`<div class="btns"><button class="btn ${tone}" data-act="needApprove" data-kind="${it.kind}" data-id="${it.id}" ${it.admin_only ? 'disabled' : ''}>${it.admin_only ? 'Hanya di admin web' : it.cta}</button>
          <button class="btn" data-act="needReject" data-kind="${it.kind}" data-id="${it.id}" style="flex:0 0 96px">Tolak</button></div>`;
  const r = it.route || {};
  return html`<div class="card ${tone}">
    <div class="row top"><span class="ico ${tone}">${icon(it.icon || 'shield', 20)}</span>
      <div class="grow"><div class="ttl">${it.title}</div><div class="sub">${it.sub}</div></div>
      ${it.expires_in_s ? html`<span class="mono small">${Math.ceil(it.expires_in_s / 60)} mnt</span>` : ''}</div>
    ${it.kind === 'phone' && (r.dari || r.ke) ? html`<div class="row" style="gap:8px;font-size:13px">${icon('pin', 14)}<span>${r.dari || '?'}</span>${icon('right', 12)}<span>${r.ke || '?'}</span></div>` : ''}
    ${it.kind === 'phone' && it.routine ? html`<span class="small" style="color:var(--green-t)">${icon('repeat', 12)} rutin "${it.routine.name}" · ${it.routine.steps} langkah · berhasil ${it.routine.ok}/${it.routine.runs}× — diputar tanpa AI</span>` : ''}
    ${it.kind === 'phone' && !compact ? html`<div class="card" style="background:var(--bg2)">${(it.rules || ['Hanya aplikasi itu · tanpa top-up/transfer · berhenti di layar PIN/OTP']).map((x) => html`<span class="small">${icon('shield', 12, 'var(--green)')} ${x}</span>`)}</div>` : ''}
    ${actions}
  </div>`;
}

const host = () => window.JarvisHost;

/** {password, remember, bio}: the fingerprint first when the phone keeps the password (APK ≥ 0.26), else typed. */
async function askPassword(title) {
  if (host()?.hasBiometric?.()) {
    const pw = await new Promise((ok) => { window.__jarvisBio = ok; host().biometric(title); });
    if (pw) return { password: pw, bio: true };
  }
  const canKeep = !!host()?.rememberPassword;
  const r = await sheet(String(html`<form class="col" style="display:flex;flex-direction:column;gap:14px">
    <span class="k amber">Izin operasi HP</span><h3 style="margin:0;font:600 20px var(--f-head)">${title}</h3>
    <label class="field">Password admin <input type="password" name="password" autocomplete="current-password" required autofocus></label>
    ${canKeep ? html`<label class="row" style="gap:8px;font-size:13px"><input type="checkbox" name="remember"> Lain kali pakai sidik jari</label>` : ''}
    <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn amber">Setujui &amp; jalankan</button></div>
    <span class="small" style="text-align:center">Dari jadwal, proyek, atau kebiasaan yang kamu setujui: tanpa password, pengaman tetap sama.</span></form>`));
  return r && r.password ? { password: r.password, remember: !!r.remember } : null;
}

/** The actions every screen showing these cards adds to its own. */
export const needActions = {
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
    const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:12px"><span class="k violet">Pertanyaan dari misi</span><p>${it?.title || ''}</p>
      <label class="field">Jawabanmu<textarea name="text" required></textarea></label><button class="btn primary">Kirim jawaban</button></form>`));
    if (!r?.text) return;
    await post(`/api/v1/app/needs/question/${b.dataset.id}`, { text: r.text });
    toast('Jawaban dikirim ke misinya.');
    render();
  },
};
