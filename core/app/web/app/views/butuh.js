// Butuh kamu / Izin (mockup 5): everything waiting for the owner — a run on his phone (admin password), an approval, a pick, a question.
import { empty, get, header, html, icon, loading, on, post, render, sheet, toast } from '../core.js';

let items = [];

function itemCard(it) {
  const tone = it.kind === 'phone' ? 'amber' : it.kind === 'choice' ? 'cyan' : it.kind === 'question' ? 'violet' : 'amber';
  const actions = it.kind === 'choice'
    ? html`<div class="g3">${it.options.map((o) => html`<button class="btn" data-act="pick" data-id="${it.id}" data-opt="${o.i}">${o.label || o.title || `Opsi ${o.i + 1}`}</button>`)}</div>`
    : it.kind === 'question'
      ? html`<button class="btn block" data-act="answer" data-id="${it.id}">Jawab</button>`
      : html`<div class="btns"><button class="btn ${tone}" data-act="approve" data-kind="${it.kind}" data-id="${it.id}" ${it.admin_only ? 'disabled' : ''}>${it.admin_only ? 'Hanya di admin web' : it.cta}</button><button class="btn" data-act="reject" data-kind="${it.kind}" data-id="${it.id}" style="flex:0 0 96px">Tolak</button></div>`;
  return html`<div class="card ${tone}">
    <div class="row top"><span class="ico ${tone}">${icon(it.icon || 'shield', 20)}</span>
      <div class="grow"><div class="ttl">${it.title}</div><div class="sub">${it.sub}</div></div></div>
    ${it.kind === 'phone' ? html`<div class="card" style="background:var(--bg2)"><span class="small">${icon('shield', 14, 'var(--green)')} Hanya aplikasi itu · tanpa top-up/transfer · berhenti di layar PIN/OTP</span></div>` : ''}
    ${actions}
  </div>`;
}

async function askPassword(title) {
  const r = await sheet(String(html`<form class="col" style="display:flex;flex-direction:column;gap:14px">
    <span class="k amber">Izin operasi HP</span><h3 style="margin:0;font:600 20px var(--f-head)">${title}</h3>
    <label class="field">Password admin <input type="password" name="password" autocomplete="current-password" required autofocus></label>
    <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn amber">Setujui &amp; jalankan</button></div>
    <span class="small" style="text-align:center">Dari jadwal, proyek, atau kebiasaan yang kamu setujui: tanpa password, pengaman tetap sama.</span></form>`));
  return r && r.password ? r.password : null;
}

export default {
  tab: 'beranda',
  async render(root) {
    const paint = async () => {
      root.innerHTML = String(html`${header('Butuh kamu', { sub: 'izin, pilihan, pertanyaan' })}<div class="scr">${loading()}</div>`);
      items = (await get('/api/v1/app/needs')).items;
      root.querySelector('.scr').innerHTML = String(items.length ? html`${items.map(itemCard)}` : empty('Tidak ada yang menunggu keputusanmu.', 'JARVIS akan mengabari kalau ada.'));
    };
    await paint();
    const offs = ['phone_approval', 'owner_choice', 'task'].map((t) => on(t, () => paint()));
    return () => offs.forEach((f) => f());
  },
  actions: {
    async approve(b) {
      const it = items.find((x) => String(x.id) === b.dataset.id && x.kind === b.dataset.kind);
      const body = { approve: true };
      if (it?.password) { const pw = await askPassword(it.title); if (!pw) return; body.password = pw; }
      await post(`/api/v1/app/needs/${b.dataset.kind}/${b.dataset.id}`, body);
      toast('Disetujui. JARVIS mulai mengerjakan.');
      render();
    },
    async reject(b) {
      await post(`/api/v1/app/needs/${b.dataset.kind}/${b.dataset.id}`, { approve: false });
      toast('Ditolak.');
      render();
    },
    async pick(b) {
      await post(`/api/v1/app/needs/choice/${b.dataset.id}`, { option: Number(b.dataset.opt) });
      toast('Pilihanmu dicatat.');
      render();
    },
    async answer(b) {
      const it = items.find((x) => String(x.id) === b.dataset.id && x.kind === 'question');
      const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:12px"><span class="k violet">Pertanyaan dari misi</span><p>${it?.title || ''}</p>
        <label class="field">Jawabanmu<textarea name="text" required></textarea></label><button class="btn primary">Kirim jawaban</button></form>`));
      if (!r?.text) return;
      await post(`/api/v1/app/needs/question/${b.dataset.id}`, { text: r.text });
      toast('Jawaban dikirim ke misinya.');
      render();
    },
  },
};
