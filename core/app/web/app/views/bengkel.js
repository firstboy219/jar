// Bengkel otak (mockup 47): how each job is done is a version he can change in words — the heavy brain writes the change, it is tried on the
// job's recent real inputs (old vs new, judged blind), then rolled out to 10% first and promoted or rolled back automatically; any version can
// be restored. Global: the thresholds Hermes decides by.
import { $, get, header, html, icon, loading, post, render, toast } from '../core.js';
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
      <form class="card violet" id="pf"><span class="k violet">Ubah dengan kata-kata</span>
        <textarea name="words" class="inp" required minlength="5" placeholder="${job ? 'mis. selalu sebut tenggat dan jawab lebih singkat; pakai otak berat untuk ini' : 'mis. pindahkan ke otak berat lebih cepat bila otak ringan sering gagal'}"></textarea>
        <button class="btn primary" data-act="propose">${icon('bolt', 16)} Susun perubahan (otak berat)</button></form>
      ${draft ? html`<div class="card cyan"><div class="row sb"><span class="k cyan">Usulan #${draft.id}</span>${laneChip(draft.lane)}</div>
          <span class="small">Sebelum:</span>${cfgView(draft.before, job)}<span class="small">Sesudah:</span>${cfgView(draft.config, job)}
          ${draft.note ? html`<span class="small">Alasan: ${draft.note}</span>` : ''}
          <div class="btns">${job ? html`<button class="btn" data-act="evaluate" data-id="${draft.id}">Uji ulang pada contoh nyata</button>` : ''}
            ${job ? html`<button class="btn amber" data-act="deploy" data-id="${draft.id}" data-m="canary">Pasang 10%</button>` : ''}<button class="btn primary" data-act="deploy" data-id="${draft.id}" data-m="all">Pasang semua</button></div>
          ${evalRes ? html`<div class="card" style="background:var(--bg)"><div class="row sb"><span class="ttl">Hasil uji: versi baru ${evalRes.verdict}</span><span class="mono">B ${evalRes.score.B} · A ${evalRes.score.A} · seri ${evalRes.score.seri}</span></div>
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

let cur = { job: null };

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
    const d = await get('/api/v1/app/brain');
    root.innerHTML = String(html`${header('Bengkel otak', { sub: 'ubah cara kerja tiap pekerjaan, uji, pasang bertahap' })}
      <div class="scr">
        <a class="card violet" href="#/bengkel/global" style="text-decoration:none"><span class="k violet">Ambang Hermes</span>${cfgView(d.global.global, '')}</a>
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
      await post(`/api/v1/app/brain/version/${b.dataset.id}/deploy`, { mode: b.dataset.m, pct: 10 });
      toast(b.dataset.m === 'canary' ? 'Dipasang untuk 10% jalan — dipantau otomatis' : 'Dipakai penuh');
      draft = null; evalRes = null; render();
    },
    async rollback() { await post(`/api/v1/app/brain/${encodeURIComponent(cur.job)}/rollback`); toast('Dikembalikan'); render(); },
  },
};
