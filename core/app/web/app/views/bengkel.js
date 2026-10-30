// Bengkel otak (mockup 47): how each job is done is a version he can change in words — the heavy brain writes the change, it is tried on the
// job's recent real inputs (old vs new, judged blind), then rolled out to 10% first and promoted or rolled back automatically; any version can
// be restored. Global: the thresholds Hermes decides by.
import { $, get, header, html, icon, loading, post, put, render, sheet, toast } from '../core.js';
import { withPassword } from '../needsui.js';
import { laneChip } from '../ui.js';

const ST = { draft: ['draf', ''], canary: ['uji', 'amber'], active: ['dipakai', 'green'], retired: ['lama', ''], rolled_back: ['dibatalkan', 'red'] };
const LANES = [['auto', 'Otomatis (Hermes memilih)'], ['skill', 'Skill tanpa AI'], ['ringan', 'Otak ringan'], ['berat', 'Otak berat']];
let draft = null, evalRes = null;

function cfgView(c, job) {
  if (!c) return html`<span class="small">cara bawaan</span>`;
  if (!job) return html`<span class="small">dipercaya setelah ${c.learn_min_runs}× · pindah ke otak berat bila otak ringan &lt; ${Math.round(c.light_min_ok * 100)}% berhasil · AI ambil alih setelah skill gagal ${c.skill_fail_streak}×</span>`;
  return html`<span class="small">jalur: ${LANES.find((l) => l[0] === c.lane)?.[1] || c.lane}${c.max_tokens ? ` · maks ${c.max_tokens} token` : ''}${c.temperature != null ? ` · suhu ${c.temperature}` : ''}</span>
    ${c.instruction ? html`<span class="sub" style="white-space:pre-wrap;border-left:3px solid var(--violet);padding-left:8px">${c.instruction}</span>` : ''}`;
}

function jobScreen(v, job) {
  const label = job ? job.replace(':', ' · ') : 'Ambang Hermes (global)';
  const b = v.built_in;
  return html`${header(label, { sub: job ? `${v.samples} contoh nyata tersimpan untuk uji ulang` : 'berlaku untuk semua pekerjaan' })}
    <div class="scr">
      <div class="card"><div class="row sb"><span class="k">Sekarang</span>${v.canary ? html`<span class="tag amber">ada uji ${v.canary.canary_pct}%</span>` : ''}</div>
        ${cfgView(v.active?.config || (job ? null : v.global), job)}
        ${v.canary ? html`<span class="small t-amber2">Sedang diuji pada ${v.canary.canary_pct}% jalan (versi #${v.canary.id}):</span>${cfgView(v.canary.config, job)}` : ''}
        ${b ? html`<span class="small">cara bawaan: ${b.runs} jalan, ${b.runs ? Math.round(100 * b.ok / b.runs) : '–'}% berhasil (30 hr)</span>` : ''}
        ${v.active || v.canary ? html`<button class="btn danger sm" data-act="rollback">Batalkan perubahan terakhir</button>` : ''}</div>
      ${v.metrics ? metricTable(v.metrics, v.metrics_prev) : ''}
      <form class="card violet" id="pf"><span class="k violet">Ubah dengan kata-kata</span>
        <textarea name="words" class="inp" required minlength="5" placeholder="${job ? 'mis. selalu sebut tenggat dan jawab lebih singkat; pakai otak berat untuk ini' : 'mis. pindahkan ke otak berat lebih cepat bila otak ringan sering gagal'}"></textarea>
        <button class="btn primary" data-act="propose">${icon('bolt', 16)} Susun perubahan (otak berat)</button></form>
      ${draft ? html`<div class="card cyan"><div class="row sb"><span class="k cyan">Usulan #${draft.id}</span>${laneChip(draft.lane)}</div>
          <span class="small">Sebelum:</span>${cfgView(draft.before, job)}<span class="small">Sesudah:</span>${cfgView(draft.config, job)}
          ${draft.note ? html`<span class="small">Alasan: ${draft.note}</span>` : ''}
          <div class="btns">${job ? html`<button class="btn" data-act="evaluate" data-id="${draft.id}">Uji ulang pada contoh nyata</button>` : ''}
            ${job ? html`<button class="btn amber" data-act="deploy" data-id="${draft.id}" data-m="canary">Pasang 10%</button>` : ''}<button class="btn primary" data-act="deploy" data-id="${draft.id}" data-m="all">Pasang semua</button></div>
          ${evalRes ? html`<div class="card" style="background:var(--bg)"><div class="row sb"><span class="ttl">Hasil uji: versi baru ${evalRes.verdict}${evalRes.worse ? html` · <span class="t-amber2">${evalRes.worse} kasus memburuk</span>` : ''}</span><span class="mono">B ${evalRes.score.B} · A ${evalRes.score.A} · seri ${evalRes.score.seri}</span></div>
            ${evalRes.samples.map((s, i) => html`<details><summary class="small">Contoh ${i + 1}: ${s.error ? `gagal (${s.error})` : s.winner === 'B' ? 'baru lebih baik' : s.winner === 'A' ? 'lama lebih baik' : 'setara'} — ${s.why || ''}</summary>
              ${s.a ? html`<span class="small">Lama:</span><pre class="mono" style="font-size:11px;white-space:pre-wrap;max-height:160px;overflow:auto">${s.a}</pre><span class="small">Baru:</span><pre class="mono" style="font-size:11px;white-space:pre-wrap;max-height:160px;overflow:auto">${s.b}</pre>` : ''}</details>`)}</div>` : ''}</div>` : ''}
      ${job ? html`<details class="card"><summary class="small">Atur manual</summary><form id="mf" style="display:flex;flex-direction:column;gap:8px">
        <label class="field">Jalur<select name="lane">${LANES.map(([k, l]) => html`<option value="${k}" ${(v.active?.config?.lane || 'auto') === k ? 'selected' : ''}>${l}</option>`)}</select></label>
        <label class="field">Aturan tambahan untuk prompt<textarea name="instruction" class="inp">${v.active?.config?.instruction || ''}</textarea></label>
        <div class="g2"><label class="field">Maks token<input name="max_tokens" type="number" min="100" max="6000" value="${v.active?.config?.max_tokens || ''}"></label>
          <label class="field">Suhu (0–1,2)<input name="temperature" type="number" min="0" max="1.2" step="0.1" value="${v.active?.config?.temperature ?? ''}"></label></div>
        <button class="btn" data-act="manual">Simpan sebagai usulan</button></form></details>` : ''}
      ${v.history.length ? html`<span class="sec">Riwayat versi</span>${v.history.map((h) => html`<div class="card"><div class="row sb"><span class="ttl">#${h.id}</span><span class="tag ${ST[h.status][1]}">${ST[h.status][0]}${h.status === 'canary' ? ` ${h.canary_pct}%` : ''}</span></div>
        ${h.request ? html`<span class="sub">“${h.request}”</span>` : ''}${cfgView(h.config, job)}
        <span class="small">${h.stats.runs} jalan · ${h.stats.runs ? Math.round(100 * h.stats.ok / h.stats.runs) : '–'}% berhasil · oleh ${h.created_by} · ${new Date(h.created_at).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}${h.eval ? ` · uji: ${h.eval.verdict}` : ''}</span>
        ${['retired', 'rolled_back', 'draft'].includes(h.status) ? html`<button class="btn sm" data-act="deploy" data-id="${h.id}" data-m="all">Pakai versi ini</button>` : ''}</div>`)}` : ''}
      ${job && v.recent.length ? html`<details class="card"><summary class="small">20 jalan terakhir</summary>${v.recent.map((r) => html`<a class="row sb" href="#/alur/${r.id}" style="font-size:13px;padding:3px 0">
        <span>${laneChip(r.lane)} ${r.brain_version ? `v#${r.brain_version}` : 'bawaan'}</span><span class="${r.status === 'failed' ? 't-amber2' : 'small'}">${r.status === 'failed' ? (r.error || 'gagal').slice(0, 40) : `${(r.seconds || 0).toFixed(1)} dtk`}</span></a>`)}</details>` : ''}
    </div>`;
}

const BRAIN = { ringan: ['Otak ringan', 'cyan'], berat: ['Otak berat', 'violet'], penglihatan: ['Mata (gambar)', 'amber'] };
const usd = (c) => (c ? `$${c < 0.01 ? c.toFixed(4) : c.toFixed(2)}` : '$0');

const price = (v) => (v == null ? '?' : v === 0 ? 'gratis' : `$${Number(v) < 1 ? Number(v).toFixed(2) : Number(v).toFixed(1)}`);

// Which model each brain uses — changed right here (the admin password), the same rules as Komposisi AI — and how each model did this week.
function editor(c) {
  const row = (cat) => html`<div style="display:flex;flex-direction:column;gap:4px;padding:8px 0;border-bottom:1px solid var(--bd)">
    <div class="row sb"><span class="tag ${BRAIN[cat.name]?.[1] || ''}">${BRAIN[cat.name]?.[0] || cat.title || cat.name}</span><span class="small">${cat.spent_usd ? `${usd(cat.spent_usd)} bulan ini · ` : ''}${cat.allow_free ? 'boleh gratis' : 'berbayar saja'}</span></div>
    ${(cat.routes || []).map((r, i) => html`<div class="row sb" style="gap:6px"><span class="mono small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%">${['①', '②', '③', '④', '⑤'][i]} ${r.model}</span>
      <span class="row" style="gap:4px"><span class="small">${price(r.price_in)}/${price(r.price_out)}</span>
        ${i > 0 ? html`<button class="ib sm" data-act="routeUp" data-c="${cat.name}" data-i="${i}" aria-label="Naikkan">↑</button>` : ''}
        ${(cat.routes || []).length > 1 ? html`<button class="ib sm" data-act="routeDel" data-c="${cat.name}" data-i="${i}" aria-label="Hapus">${icon('close', 12)}</button>` : ''}</span></div>`)}
    <div class="row" style="gap:6px;flex-wrap:wrap"><button class="chip" data-act="pickModel" data-c="${cat.name}" data-r="utama">Ganti utama</button>
      <button class="chip" data-act="pickModel" data-c="${cat.name}" data-r="cadangan">+ Cadangan</button><button class="chip" data-act="testModel" data-c="${cat.name}">Uji</button></div></div>`;
  const main = c.categories.filter((x) => BRAIN[x.name]), rest = c.categories.filter((x) => !BRAIN[x.name] && !x.locked);
  return html`${main.map(row)}${rest.length ? html`<details><summary class="small">Kategori lain (${rest.length})</summary>${rest.map(row)}</details>` : ''}
    <span class="small">OpenRouter: ${c.openrouter.has_key ? (c.openrouter.balance_usd != null ? `saldo $${Number(c.openrouter.balance_usd).toFixed(2)}` : 'tersambung') : 'kunci belum ada'} · harga per 1 juta token (masuk/keluar). Mengganti model butuh password admin.</span>`;
}

// Which model each brain uses (picked in Komposisi AI on the admin site) and how each model did this week.
function models(m) {
  return html`<details class="card"><summary class="ttl" style="cursor:pointer">${icon('layers', 14)} Model tiap otak</summary>
    ${Object.entries(m.lanes).map(([k, l]) => html`<div style="display:flex;flex-direction:column;gap:2px;padding:6px 0;border-bottom:1px solid var(--bd)">
      <div class="row sb"><span class="tag ${BRAIN[k]?.[1] || ''}">${BRAIN[k]?.[0] || k}</span><span class="small">${l.allow_free ? 'boleh model gratis' : 'berbayar saja'}</span></div>
      ${l.routes.length ? l.routes.map((r, i) => html`<span class="mono small">${i === 0 ? '①' : i === 1 ? '②' : '③'} ${r.model}</span>`) : html`<span class="small t-amber2">belum dipilih — atur di Komposisi AI</span>`}</div>`)}
    ${comp ? editor(comp) : ''}
    ${m.usage.length ? html`<span class="small" style="margin-top:6px"><b>Dipakai ${m.days} hari terakhir</b></span>${m.usage.map((u) => html`<div class="row sb" style="font-size:12px"><span class="mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:55%">${u.model}</span>
      <span class="small">${u.runs}× · ${u.ok_pct}% · ${u.avg_s ?? '–'} dtk · ${usd(u.cost)}</span></div>`)}` : ''}
    <span class="small">Semua lewat OpenRouter; isi sensitif hanya ke model berbayar.</span></details>`;
}

// the job's numbers this week against last week
function metricTable(a, b) {
  const rows = [['Berhasil', 'ok_pct', '%', true], ['Gagal', 'fail_pct', '%', false], ['Otak tepat (tanpa dinaikkan)', 'right_brain_pct', '%', true], ['Tanpa AI', 'no_ai_pct', '%', true],
    ['Biaya / hari', 'cost_per_day', '$', false], ['Waktu (median)', 'p50_s', 's', false], ['Waktu (10% terlama)', 'p90_s', 's', false]];
  const fmt = (v, u) => (v == null ? '–' : u === '$' ? usd(v) : u === 's' ? `${String(v).replace('.', ',')} dtk` : `${v}%`);
  return html`<div class="card"><div class="row sb"><span class="k">Angka 7 hari</span><span class="small">${a.runs} jalan · minggu lalu ${b?.runs ?? 0}</span></div>
    <div class="tblbox"><table class="tbl"><thead><tr><th scope="col">Ukuran</th><th scope="col">Minggu ini</th><th scope="col">Minggu lalu</th></tr></thead><tbody>
    ${rows.map(([l, k, u, up]) => { const x = a[k], y = b?.[k]; const better = x != null && y != null && x !== y ? ((x > y) === up) : null;
      return html`<tr><td>${l}</td><td class="mono" style="${better == null ? '' : `color:var(--${better ? 'green' : 'amber'}-t)`}">${fmt(x, u)}</td><td class="mono">${fmt(y, u)}</td></tr>`; })}</tbody></table></div></div>`;
}

let cur = { job: null }, comp = null;

async function reorder(cat, change) {
  const c = comp.categories.find((x) => x.name === cat);
  const list = change((c.routes || []).map((r) => r.model));
  const r = await withPassword(`Urutan model ${BRAIN[cat]?.[0] || cat}`, (password) => put('/api/v1/app/brain/routes', { category: cat, models: list, password }),
    { kicker: 'Ganti model otak', button: 'Simpan', note: list.map((m, i) => `${i + 1}. ${m}`).join(' · ') });
  if (r) { toast('Urutan disimpan'); render(); }
}

export default {
  tab: 'beranda',
  feature: 'bengkel',
  async render(root, route) {
    const job = route.params[0];
    root.innerHTML = String(html`${header('Bengkel otak')}<div class="scr">${loading()}</div>`);
    if (job) {
      if (cur.job !== job) { draft = null; evalRes = null; }
      cur.job = job;
      const v = await get(`/api/v1/app/brain/${encodeURIComponent(job)}`);
      root.innerHTML = String(jobScreen(v, job === 'global' ? '' : job));
      return;
    }
    const [d, m, c] = await Promise.all([get('/api/v1/app/brain'), get('/api/v1/app/brain/models'), get('/api/v1/app/brain/composition').catch(() => null)]);
    comp = c;
    root.innerHTML = String(html`${header('Bengkel otak', { sub: 'ubah cara kerja tiap pekerjaan, uji, pasang bertahap' })}
      <div class="scr">
        <a class="card violet" href="#/bengkel/global" style="text-decoration:none"><span class="k violet">Ambang Hermes</span>${cfgView(d.global.global, '')}</a>
        ${models(m)}
        ${d.drafts.length ? html`<div class="card cyan"><div class="row sb"><span class="k cyan">Usulan menunggu · ${d.drafts.length}</span><button class="btn sm primary" data-act="testAll">Uji semua & terapkan 10%</button></div>
          ${d.drafts.map((x) => html`<a class="row sb" href="#/bengkel/${x.job}" style="gap:8px;text-decoration:none;color:inherit;padding:4px 0">
            <span class="grow" style="min-width:0"><span style="font-size:13px">${x.job.replace(':', ' · ')}</span><br><span class="small">${x.created_by === 'jarvis' ? '🤖 usulan JARVIS' : 'usulanmu'} · ${(x.note || x.request || '').slice(0, 90)}</span></span>
            ${x.eval ? html`<span class="tag ${x.eval.verdict === 'lebih baik' ? 'green' : x.eval.verdict === 'lebih buruk' ? 'red' : ''}">${x.eval.verdict}</span>` : html`<span class="tag">belum diuji</span>`}</a>`)}
          <span class="small">Hanya yang lebih baik di uji ulang yang dipasang ke 10% jalan; dipantau dan dibatalkan otomatis bila memburuk.</span></div>` : ''}
        <div class="list">${d.jobs.map((j) => html`<a class="li click" href="#/bengkel/${j.job}"><div class="grow" style="min-width:0">
          <div class="row sb"><span style="font-size:14px">${j.feature} · ${j.action}</span><span class="mono small">${j.runs}×</span></div>
          <div class="row" style="gap:6px">${laneChip(j.lane)}<span class="small">${j.ok_pct ?? '–'}% berhasil · ${j.avg_s} dtk</span>${j.versions.map((s) => html`<span class="tag ${ST[s][1]}">${ST[s][0]}</span>`)}</div></div>${icon('right', 16)}</a>`)}</div>
        <p class="small" style="padding:0 4px">Setiap perubahan bisa diuji ulang pada masukan nyata, dipasang 10% dulu, dan dibatalkan otomatis bila lebih sering gagal.</p>
      </div>`);
  },
  actions: {
    async propose(b, e) {
      e?.preventDefault();
      const f = $('#pf'); if (!f.reportValidity()) return;
      toast('Otak berat menyusun perubahan…');
      draft = await post(`/api/v1/app/brain/${encodeURIComponent(cur.job)}/propose`, { words: new FormData(f).get('words') });
      evalRes = null; render();
    },
    async manual(b, e) {
      e?.preventDefault();
      const v = Object.fromEntries(new FormData($('#mf')).entries());
      const config = { lane: v.lane, instruction: v.instruction, ...(v.max_tokens ? { max_tokens: Number(v.max_tokens) } : {}), ...(v.temperature !== '' ? { temperature: Number(v.temperature) } : {}) };
      const r = await post(`/api/v1/app/brain/${encodeURIComponent(cur.job)}/manual`, { config, note: 'diatur manual' });
      draft = { id: r.id, config: r.config, before: null, note: 'diatur manual' }; evalRes = null; render();
    },
    async evaluate(b) { toast('Menguji ulang pada contoh nyata… (±1 menit)'); evalRes = await post(`/api/v1/app/brain/version/${b.dataset.id}/evaluate`); render(); },
    async deploy(b) {
      const all = b.dataset.m === 'all';
      const ok = await withPassword(`${all ? 'Pakai penuh' : 'Uji 10%'} versi #${b.dataset.id}`, (password) => post(`/api/v1/app/brain/version/${b.dataset.id}/deploy`, { mode: b.dataset.m, pct: 10, password }),
        { kicker: 'Ubah cara kerja otak', button: all ? 'Pakai sekarang' : 'Pasang 10%', note: cur.job === 'global' ? 'Berlaku untuk semua pekerjaan.' : 'Bisa dibatalkan kapan saja.' });
      if (!ok) return;
      toast(all ? 'Dipakai penuh' : 'Dipasang untuk 10% jalan — dipantau otomatis');
      draft = null; evalRes = null; render();
    },
    async pickModel(b) {
      const cat = b.dataset.c, role = b.dataset.r;
      const q = await sheet(String(html`<form><span class="ttl">${role === 'utama' ? 'Model utama' : 'Model cadangan'} · ${BRAIN[cat]?.[0] || cat}</span>
        <label class="field">Cari model (nama/penyedia)<input name="q" placeholder="mis. deepseek, claude, gemini, qwen"></label>
        <label class="row" style="gap:8px;font-size:13px"><input type="checkbox" name="free"> hanya yang gratis</label>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Cari</button></div></form>`));
      if (q === null || q === undefined || q === '') return;
      const r = await get(`/api/v1/app/brain/catalog?q=${encodeURIComponent(q.q || '')}&vision=${cat === 'penglihatan'}&free=${!!q.free}`);
      const pickd = await sheet(String(html`<span class="ttl">${r.models.length} model</span><div style="display:flex;flex-direction:column;gap:6px;max-height:60vh;overflow:auto">
        ${r.models.map((x) => html`<button class="card" data-close="${x.id}" style="text-align:left;cursor:pointer;padding:8px 10px"><div class="row sb"><span style="font-size:13px;font-weight:600">${x.name || x.id}</span><span class="small">${price(x.price_in)}/${price(x.price_out)}</span></div>
          <span class="small mono">${x.id}</span><span class="small">${Math.round((x.context || 0) / 1000)}k konteks${x.tools ? ' · alat' : ''}${x.vision ? ' · gambar' : ''}${x.jarvis ? ` · di JARVIS ${x.jarvis.calls}× ${x.jarvis.ok_pct}% · ${Math.round(x.jarvis.p50_ms / 100) / 10} dtk` : ''}</span></button>`)}</div>
        <button class="btn" data-close="">Batal</button>`));
      if (!pickd) return;
      const ok = await withPassword(`${BRAIN[cat]?.[0] || cat}: ${pickd}`, async (password) => {
        let res = await put('/api/v1/app/brain/model', { category: cat, model: pickd, role, password });
        if (res.needs_confirmation) {
          if ((await sheet(String(html`<p>${res.say}</p><div class="btns"><button class="btn" data-close="">Batal</button><button class="btn amber" data-close="y">Tetap pakai</button></div>`))) !== 'y') return null;
          res = await put('/api/v1/app/brain/model', { category: cat, model: pickd, role, password, confirmed: true });
        }
        return res;
      }, { kicker: 'Ganti model otak', button: 'Pakai', note: 'Model dicoba sekali dulu sebelum dipakai.' });
      if (ok) { toast(`${BRAIN[cat]?.[0] || cat}: ${ok.main || pickd}`); render(); }
    },
    async routeUp(b) { await reorder(b.dataset.c, (list) => { const i = Number(b.dataset.i); [list[i - 1], list[i]] = [list[i], list[i - 1]]; return list; }); },
    async routeDel(b) { await reorder(b.dataset.c, (list) => list.filter((_, i) => i !== Number(b.dataset.i))); },
    async testModel(b) {
      toast('Menguji…');
      const r = await post('/api/v1/composition/test', { category: b.dataset.c, text: 'Jawab satu kalimat: apa ibu kota Indonesia?' });
      toast(r.ok ? `${r.route?.model || ''} · ${r.ms} ms: ${(r.text || '').slice(0, 60)}` : `Gagal: ${r.error}`, !r.ok);
    },
    async testAll() {
      const r = await withPassword('Uji semua usulan & terapkan yang lebih baik ke 10%', (password) => post('/api/v1/app/brain/drafts/test-all', { password }),
        { kicker: 'Ubah cara kerja otak', button: 'Uji & terapkan', note: 'Diuji ulang pada masukan nyata; bisa beberapa menit.' });
      if (!r) return;
      toast(`${r.tested.filter((x) => x.result === 'dipasang 10%').length} dipasang 10% dari ${r.tested.length} usulan`); render();
    },
    async rollback() {
      const ok = await withPassword('Batalkan perubahan terakhir', (password) => post(`/api/v1/app/brain/${encodeURIComponent(cur.job)}/rollback`, { password }),
        { kicker: 'Ubah cara kerja otak', button: 'Kembalikan', note: '' });
      if (ok) { toast('Dikembalikan'); render(); }
    },
  },
};
