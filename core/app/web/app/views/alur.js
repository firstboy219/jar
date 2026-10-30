// Alur langsung (mockup 46): JARVIS at work — every job goes router → Hermes → skill / otak ringan / otak berat / Hermes + alat; the ones running
// now move on the graph, each run opens to its steps, and every job shows how well it does (success, share without AI, time, cost).
import { get, header, html, icon, loading, on, render } from '../core.js';
import { laneChip, statusPill } from '../ui.js';

const LANES = [['skill', 'Skill', 'tanpa AI', 'green'], ['ringan', 'Otak ringan', 'jar', 'cyan'], ['berat', 'Otak berat', 'OpenJarvis', 'violet'], ['hermes', 'Hermes + alat', 'browser · HP', 'amber']];
const ago = (s) => { const m = Math.round((Date.now() - new Date(s)) / 60000); return m < 1 ? 'baru' : m < 60 ? `${m} mnt` : m < 1440 ? `${Math.round(m / 60)} jam` : `${Math.round(m / 1440)} hr`; };
const secs = (s) => (s == null ? '' : s < 60 ? `${s.toFixed(1).replace('.', ',')} dtk` : `${Math.round(s / 60)} mnt`);
const usd = (c) => (c ? `$${c < 0.01 ? c.toFixed(4) : c.toFixed(2)}` : '');

const INPUTS = [['owner', 'Kamu'], ['habit', 'Kebiasaan'], ['schedule', 'Jadwal'], ['event', 'Peristiwa']];

function graph(d) {
  const st = d.stations, total = Math.max(1, d.total);
  const liveBy = (l) => d.live.filter((r) => (r.lane || 'routing') === l).length;
  const w = 360, laneY = [8, 70, 132, 194], inY = [14, 72, 130, 188];
  const thick = (n) => 1.5 + 7 * Math.sqrt((n || 0) / total);
  const tr = d.triggers || {};
  return html`<svg viewBox="0 0 ${w} 246" style="width:100%;height:auto" role="img" aria-label="pemicu ke router ke Hermes ke empat jalur">
    <defs><style>.pulse{animation:pl 1.4s ease-in-out infinite}@keyframes pl{0%,100%{opacity:.35}50%{opacity:1}}</style></defs>
    ${INPUTS.map(([k, name], i) => html`<rect x="2" y="${inY[i]}" width="56" height="40" rx="9" fill="var(--s1)" stroke="var(--bd2)"/>
      <text x="30" y="${inY[i] + 17}" text-anchor="middle" fill="var(--tx)" font-size="9.5" font-weight="600">${name}</text>
      <text x="30" y="${inY[i] + 31}" text-anchor="middle" fill="var(--mu)" font-size="9">${tr[k] || 0}×</text>
      <path d="M58 ${inY[i] + 20} C 64 ${inY[i] + 20}, 62 123, 68 123" fill="none" stroke="var(--bd2)" stroke-width="${thick(tr[k])}"/>`)}
    <rect x="68" y="98" width="62" height="50" rx="12" fill="var(--s1)" stroke="var(--bd2)"/><text x="99" y="118" text-anchor="middle" fill="var(--tx)" font-size="11.5" font-weight="600">Router</text>
    <text x="99" y="134" text-anchor="middle" fill="var(--mu)" font-size="9">${d.router ? `${String(d.router.avg_s).replace('.', ',')} dtk` : `${total}×`}</text>
    <line x1="130" y1="123" x2="146" y2="123" stroke="var(--bd2)" stroke-width="${thick(total)}"/>
    <rect x="146" y="98" width="70" height="50" rx="12" fill="var(--s1)" stroke="var(--violet)"/><text x="181" y="118" text-anchor="middle" fill="var(--tx)" font-size="11.5" font-weight="600">Hermes</text>
    <text x="181" y="134" text-anchor="middle" fill="var(--mu)" font-size="9">${d.queue?.routing ? `${d.queue.routing} antre` : 'memilih jalur'}</text>
    ${(st.routing?.runs || liveBy('routing')) ? html`<circle class="pulse" cx="138" cy="123" r="5" fill="var(--cyan)"/>` : ''}
    ${LANES.map(([k, name, sub, tone], i) => html`
      <path d="M216 123 C 236 123, 236 ${laneY[i] + 22}, 258 ${laneY[i] + 22}" fill="none" stroke="var(--${tone})" stroke-opacity=".55" stroke-width="${thick(st[k]?.runs)}"/>
      <rect x="258" y="${laneY[i]}" width="98" height="46" rx="10" fill="var(--s1)" stroke="var(--${tone})"/>
      <text x="307" y="${laneY[i] + 15}" text-anchor="middle" fill="var(--tx)" font-size="11" font-weight="600">${name}</text>
      <text x="307" y="${laneY[i] + 28}" text-anchor="middle" fill="var(--mu)" font-size="9.5">${st[k]?.runs || 0}× · ${st[k]?.runs && st[k].ok_pct != null ? `${st[k].ok_pct}% berhasil` : sub}</text>
      ${st[k]?.runs && st[k].avg_s != null ? html`<text x="307" y="${laneY[i] + 40}" text-anchor="middle" fill="var(--mu)" font-size="9">${secs(st[k].avg_s)}${st[k].cost ? ` · ${usd(st[k].cost)}` : ''}</text>` : ''}
      ${liveBy(k) ? html`<circle class="pulse" cx="246" cy="${laneY[i] + 22}" r="6" fill="var(--${tone})"/><text x="246" y="${laneY[i] + 10}" text-anchor="middle" fill="var(--${tone})" font-size="10">${liveBy(k)}</text>` : ''}`)}
  </svg>`;
}

// what sits around the graph: how fast and how right the router is, what JARVIS remembers, Hermes' tools, the queue
function around(d) {
  return html`<div class="g2">
    <div class="kpi"><span>Router</span><b style="font-size:16px">${d.router?.right_pct ?? '–'}% tepat</b><span>${String(d.router?.avg_s ?? 0).replace('.', ',')} dtk memilah</span></div>
    <div class="kpi"><span>Ingatan</span><b style="font-size:16px">${d.memory?.skills || 0} skill · ${d.memory?.routines || 0} rutin</b><span>dipakai ${d.memory?.used || 0}× tanpa AI</span></div>
    <div class="kpi"><span>Alat Hermes</span><b style="font-size:16px">HP ${d.tools?.hp || 0} · browser ${d.tools?.browser || 0}</b><span>jalan dengan alat</span></div>
    <div class="kpi"><span>Antrean</span><b style="font-size:16px">${(d.queue?.routing || 0) + (d.queue?.workers || 0)}</b><span>${d.queue?.workers || 0} menunggu pekerja</span></div></div>`;
}

let rp = null;   // the replay: {day, runs, t, timer}

function replayFrame() {
  const T = rp.t * 60;
  const upto = rp.runs.filter((r) => r.t <= T);
  const stations = {};
  for (const r of upto) { const k = r.lane || 'routing'; stations[k] = stations[k] || { runs: 0, failed: 0 }; stations[k].runs += 1; if (r.status === 'failed') stations[k].failed += 1; }
  const live = rp.runs.filter((r) => r.t > T - 300 && r.t <= T);
  const triggers = {}; for (const r of upto) triggers[r.trigger] = (triggers[r.trigger] || 0) + 1;
  return { stations, total: upto.length, live, triggers };
}

function paintReplay() {
  const box = document.getElementById('rpbox'); if (!box || !rp) return;
  const f = replayFrame();
  box.innerHTML = String(html`${graph(f)}<div class="row sb small"><span>${String(Math.floor(rp.t / 60)).padStart(2, '0')}.${String(rp.t % 60).padStart(2, '0')}</span><span>${f.total} pekerjaan sampai jam ini</span></div>
    <div class="small">${f.live.slice(-4).map((r) => `${r.feature} · ${r.action}`).join(' — ') || '—'}</div>`);
  const sl = document.getElementById('rpslider'); if (sl) sl.value = String(rp.t);
}

function detail(r) {
  return html`${header(`${r.feature} · ${r.action}`, { sub: `#${r.id} · ${new Date(r.started_at).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })}` })}
    <div class="scr">
      <div class="card"><div class="row sb"><span class="ttl">${r.goal}</span>${statusPill(r.status)}</div>
        <div class="row" style="gap:6px;flex-wrap:wrap">${laneChip(r.lane, r.why)}<span class="tag">${r.trigger}</span>${r.model ? html`<span class="tag">${r.model}</span>` : ''}
          <span class="tag">${secs(r.seconds)}</span>${r.cost_usd ? html`<span class="tag">${usd(r.cost_usd)}</span>` : ''}${r.brain_version ? html`<a class="tag violet" href="#/bengkel/${r.feature}:${r.action}">versi otak #${r.brain_version}</a>` : ''}</div>
        ${r.why ? html`<span class="small">Hermes: ${r.why}</span>` : ''}</div>
      <div class="steps">${(r.steps || []).map((s, i, a) => { const took = i < a.length - 1 ? (new Date(a[i + 1].at) - new Date(s.at)) / 1000 : null; return html`<div class="step"><div class="rail"><span class="n done">${icon('check', 12)}</span>${i < a.length - 1 ? html`<span class="ln"></span>` : ''}</div>
        <div class="body"><div class="row sb"><span style="font-size:14px;font-weight:600">${s.stage}${s.no_ai ? html` <span class="tag green">tanpa AI</span>` : ''}${s.tool ? html` <span class="tag amber">${s.tool === 'hp' ? 'HP' : 'browser'}</span>` : ''}</span><span class="mono small">${new Date(s.at).toLocaleTimeString('id-ID')}${took != null ? html` · <span style="color:var(--${took > 30 ? 'amber' : 'mu'}${took > 30 ? '-t' : ''})">${secs(took)}</span>` : ''}</span></div><span class="small">${s.text}</span>${s.model || s.tokens || s.cost ? html`<span class="small mono">${[s.model, s.tokens && `${s.tokens} token`, s.cost && usd(s.cost)].filter(Boolean).join(' · ')}</span>` : ''}</div></div>`; })}</div>
      ${r.error ? html`<div class="card red"><span class="k">Gagal</span><span class="small">${r.error}</span></div>` : ''}
      ${r.result_preview ? html`<details class="card"><summary class="small">Hasil</summary><pre class="mono" style="font-size:11px;white-space:pre-wrap">${r.result_preview}</pre></details>` : ''}
      ${r.task_id ? html`<a class="btn" href="#/misi/${r.task_id}">Buka misi #${r.task_id}</a>` : ''}
      <a class="btn" href="#/bengkel/${r.feature}:${r.action}">${icon('code', 16)} Atur cara kerja pekerjaan ini</a>
    </div>`;
}

let timer = null, hours = 24;
const RANGES = [[1, '1 jam'], [24, '24 jam'], [48, '48 jam'], [168, '7 hari']];
const WEAK = { gagal: 'red', lambat: 'amber', mahal: 'amber', 'bisa-skill': 'green' };

export default {
  tab: 'beranda',
  feature: 'alur',
  async render(root, route) {
    const id = route.params[0];
    root.innerHTML = String(html`${header('Alur langsung')}<div class="scr">${loading()}</div>`);
    if (id) { root.innerHTML = String(detail(await get(`/api/v1/app/flow/${id}`))); return on('flow', (e) => { if (String(e.run) === id) { clearTimeout(timer); timer = setTimeout(render, 600); } }); }
    if (route.query.h) hours = Number(route.query.h) || 24;
    const d = await get(`/api/v1/app/flow?hours=${hours}`);
    setTimeout(() => { paintReplay(); document.getElementById('rpslider')?.addEventListener('input', (e) => { rp.t = Number(e.target.value); paintReplay(); }); }, 0);
    const day = d.day;
    root.innerHTML = String(html`${header('Alur langsung', { sub: `${day.runs} pekerjaan hari ini · ${day.no_ai_pct ?? 0}% tanpa AI · ${day.ok_pct ?? '–'}% berhasil` })}
      <div class="scr">
        <div class="chips">${RANGES.map(([h, l]) => html`<button class="chip ${h === hours ? 'on' : ''}" data-act="range" data-h="${h}">${l}</button>`)}</div>
        <div class="card">${graph(d)}</div>
        ${around(d)}
        ${rp ? html`<div class="card violet"><div class="row sb"><span class="k violet">Putar ulang ${rp.day}</span><button class="ib sm" data-act="rpClose" aria-label="Tutup">${icon('close', 14)}</button></div>
          <div id="rpbox"></div><input id="rpslider" type="range" min="0" max="1439" value="${rp.t}" style="width:100%">
          <div class="btns"><button class="btn sm" data-act="rpPlay">${rp.timer ? 'Jeda' : 'Putar'}</button><button class="btn sm" data-act="rpSpeed">${rp.speed}×</button></div></div>`
          : html`<button class="btn" data-act="replay">${icon('play', 16)} Putar ulang kemarin</button>`}
        ${d.weak.length ? html`<div class="card amber"><span class="k amber">Titik lemah</span>${d.weak.map((w) => html`<a class="row" href="#/bengkel/${w.job}" style="gap:8px;text-decoration:none;color:inherit;padding:3px 0">
          <span class="tag ${WEAK[w.kind] || ''}">${w.kind}</span><span class="small grow">${w.text}</span>${icon('right', 14)}</a>`)}</div>` : ''}
        <div class="g4"><div class="kpi"><b>${d.live.length}</b><span>berjalan</span></div><div class="kpi"><b>${d.week.ok_pct ?? '–'}%</b><span>berhasil 7 hr</span></div>
          <div class="kpi"><b>${d.week.no_ai_pct ?? 0}%</b><span>tanpa AI</span></div><div class="kpi"><b>${usd(d.week.cost) || '$0'}</b><span>biaya 7 hr</span></div></div>
        ${d.live.length ? html`<span class="sec">Sedang berjalan</span><div class="list">${d.live.map((r) => html`<a class="li click" href="#/alur/${r.id}"><span class="dot ${r.lane === 'hermes' ? 'amber' : r.lane === 'berat' ? 'violet' : 'cyan'} live"></span>
          <div class="grow" style="min-width:0"><div style="font-size:14px">${r.feature} · ${r.action}</div><div class="small">${r.path.join(' → ')} · langkah ${r.steps_n}${r.task_progress ? ` · ${r.task_progress}` : ''}${r.cost_now ? ` · ${usd(r.cost_now)}` : ''}</div>
          <div class="small" style="overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${r.last_step?.text || r.goal}</div></div><span class="mono small">${secs(r.seconds)}</span></a>`)}</div>` : ''}
        <span class="sec">Terakhir</span>
        <div class="list">${d.recent.slice(0, 25).map((r) => html`<a class="li click" href="#/alur/${r.id}"><div class="grow" style="min-width:0">
          <div class="row sb"><span style="font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${r.feature} · ${r.action}</span><span class="small">${ago(r.started_at)}</span></div>
          <div class="row" style="gap:6px">${laneChip(r.lane, r.why)}${r.status === 'failed' ? html`<span class="tag red">gagal</span>` : r.status !== 'done' ? html`<span class="tag amber">${r.status}</span>` : ''}
            <span class="small">${secs(r.seconds)}${r.cost ? ` · ${usd(r.cost)}` : ''}</span></div></div></a>`)}</div>
        <span class="sec">Efektivitas per pekerjaan · ${hours >= 168 ? '7 hari' : hours > 24 ? `${hours} jam` : '24 jam'}</span>
        <div class="tblbox"><table class="tbl"><thead><tr><th scope="col">Pekerjaan</th><th scope="col">Jalan</th><th scope="col">Berhasil</th><th scope="col">Tanpa AI</th><th scope="col">Waktu</th></tr></thead>
          <tbody>${d.jobs.map((j) => html`<tr data-go="#/bengkel/${j.feature}:${j.action}" style="cursor:pointer"><td>${j.feature}<br><span class="small">${j.action}</span></td><td class="mono">${j.runs}</td>
            <td class="mono" style="color:var(--${(j.ok_pct ?? 100) >= 90 ? 'green' : (j.ok_pct ?? 100) >= 70 ? 'amber' : 'red'}-t)">${j.ok_pct ?? '–'}%</td><td class="mono">${j.no_ai_pct}%</td><td class="mono">${secs(j.avg_s)}</td></tr>`)}</tbody></table></div>
        <a class="btn block" href="#/bengkel">${icon('code', 16)} Bengkel otak</a>
      </div>`);
    return on('flow', () => { clearTimeout(timer); timer = setTimeout(render, 1500); });
  },
  actions: {
    range(b) { hours = Number(b.dataset.h); render(); },
    async replay() {
      const y = new Date(Date.now() - 86400000); const day = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, '0')}-${String(y.getDate()).padStart(2, '0')}`;
      const r = await get(`/api/v1/app/flow/replay?day=${day}`);
      rp = { day, runs: r.runs, t: r.runs.length ? Math.floor(r.runs[0].t / 60) : 360, timer: null, speed: 5 };
      render();
    },
    rpPlay(b) {
      if (rp.timer) { clearInterval(rp.timer); rp.timer = null; b.textContent = 'Putar'; return; }
      rp.timer = setInterval(() => { rp.t += rp.speed; if (rp.t >= 1439) { rp.t = 1439; clearInterval(rp.timer); rp.timer = null; } paintReplay(); }, 120);
      b.textContent = 'Jeda';
    },
    rpSpeed(b) { rp.speed = rp.speed === 5 ? 15 : rp.speed === 15 ? 1 : 5; b.textContent = `${rp.speed}×`; },
    rpClose() { if (rp?.timer) clearInterval(rp.timer); rp = null; render(); },
  },
};
