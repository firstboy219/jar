// Misi (mockup 4): every piece of work JARVIS does — the plan, the brain/lane Hermes picked, the live screen, cost, and the controls.
import { empty, get, go, header, html, icon, loading, on, post, render, sheet, toast } from '../core.js';
import { ago, dur, pct, usd } from '../lib.js';
import { laneChip, liveFrame, resultView, statusPill } from '../ui.js';

const LANE_OF_RUNTIME = { ringan: 'ringan', openjarvis: 'berat', hermes: 'hermes' };

function listView(ms) {
  const running = ms.filter((m) => ['queued', 'running'].includes(m.status));
  const done = ms.filter((m) => !['queued', 'running'].includes(m.status));
  const row = (m) => html`<a class="li click" href="#/misi/${m.id}">
    <div class="grow"><div class="ttl">${m.title}</div><div class="small">${laneChip(LANE_OF_RUNTIME[m.runtime] || m.runtime)} ${m.progress || ''} · ${dur(m.seconds)}${m.cost ? ` · ${usd(m.cost)}` : ''}</div></div>
    ${statusPill(m.status)}</a>`;
  return html`
    ${running.length ? html`<div class="sec"><span>Sedang dikerjakan · ${running.length}</span></div><div class="list">${running.map(row)}</div>` : empty('Tidak ada misi yang berjalan.', 'Minta apa saja lewat kolom di bawah — JARVIS menjadikannya misi.')}
    ${done.length ? html`<div class="sec"><span>Terakhir</span></div><div class="list">${done.slice(0, 25).map(row)}</div>` : ''}`;
}

function detailView(t) {
  const lane = LANE_OF_RUNTIME[t.runtime] || t.runtime;
  const steps = (t.plan?.steps || []);
  const live = t.station?.steps || [];
  const doneSteps = t.status === 'completed' ? steps.length : Math.min(steps.length, Math.floor((pct(live.length, Math.max(live.length + 2, steps.length * 2)) / 100) * steps.length));
  return html`
    <div class="scr">
      <div class="row sb"><span class="small">Misi · ${ago(t.created_at)}${t.started_at ? '' : ' · belum mulai'}</span>${statusPill(t.status)}</div>
      <h1 class="big" style="font-size:22px">${t.title}</h1>
      <div class="row wrap" style="gap:6px">${laneChip(lane, t.runtime_note)}${t.model_used ? html`<span class="tag">${t.model_used.split('/').pop()}</span>` : ''}<span class="tag">${dur(t.seconds)}</span>${t.cost ? html`<span class="tag">${usd(t.cost)}</span>` : ''}</div>
      ${t.runtime_note ? html`<p class="small" style="margin:0">Hermes: ${t.runtime_note}</p>` : ''}
      ${t.station?.has_frame || t.station?.browsing ? html`<div class="livebox"><div class="bar2"><span class="dot red live"></span>LANGSUNG · ${t.station.page_title || t.station.url || 'browser'}</div><img id="frame" alt="Layar langsung misi"></div>` : ''}
      ${t.station?.thought ? html`<div class="card violet"><span class="k violet">Sedang dipikirkan</span><p class="sub">${t.station.thought}</p></div>` : ''}
      ${steps.length ? html`<div class="sec"><span>Rencana · diatur Hermes</span></div><div class="steps">${steps.map((s, i) => html`<div class="step"><div class="rail"><span class="n ${i < doneSteps ? 'done' : (i === doneSteps && t.status === 'running' ? 'now' : '')}">${i < doneSteps ? icon('check', 13) : ''}</span>${i < steps.length - 1 ? html`<span class="ln"></span>` : ''}</div><div class="body"><span style="font-size:14px;${i < doneSteps ? 'color:var(--tx2)' : ''}">${s}</span></div></div>`)}</div>` : ''}
      ${live.length ? html`<details class="card" ${t.status === 'running' ? 'open' : ''}><summary class="small">Langkah terakhir (${live.length})</summary><div style="display:flex;flex-direction:column;gap:4px;margin-top:8px">${live.slice(-8).map((s) => html`<span class="small">• ${s.text || s.label || s.name || JSON.stringify(s)}</span>`)}</div></details>` : ''}
      ${t.error ? html`<div class="card red"><span class="k red">Kendala</span><p class="sub">${t.error}</p></div>` : ''}
      ${t.status === 'completed' ? resultView(t.result?.data, t.result?.text) : ''}
      <div class="g4" style="margin-top:4px">
        <button class="btn" data-act="say" ${t.can_say ? '' : 'disabled'} style="flex-direction:column;height:60px;font-size:11px">${icon('chat', 18)}Arahkan</button>
        <button class="btn" data-native="desk" style="flex-direction:column;height:60px;font-size:11px" ${t.station ? '' : 'disabled'}>${icon('hand', 18)}Ambil alih</button>
        <button class="btn" data-act="start" ${t.can_start ? '' : 'disabled'} style="flex-direction:column;height:60px;font-size:11px">${icon('play', 18)}Mulai lagi</button>
        <button class="btn danger" data-act="stop" ${t.can_stop ? '' : 'disabled'} style="flex-direction:column;height:60px;font-size:11px">${icon('stop', 18)}Hentikan</button>
      </div>
    </div>`;
}

let currentId = null;

export default {
  tab: 'misi',
  async render(root, route) {
    currentId = route.params[0] ? Number(route.params[0]) : null;
    root.innerHTML = String(html`${header(currentId ? 'Misi' : 'Misi', { back: !!currentId, sub: currentId ? '' : 'semua pekerjaan JARVIS' })}<div class="scr">${loading()}</div>`);
    let stopFrame = null;
    const paint = async () => {
      if (currentId) {
        const t = await get(`/api/v1/app/missions/${currentId}`);
        root.innerHTML = String(html`${header('Misi', { sub: `#${t.id}` })}${detailView(t)}`);
        stopFrame?.();
        const img = root.querySelector('#frame');
        if (img) stopFrame = liveFrame(img, t.id);
      } else {
        const { missions } = await get('/api/v1/app/missions');
        root.innerHTML = String(html`${header('Misi', { back: false, sub: 'semua pekerjaan JARVIS' })}<div class="scr">${listView(missions)}</div>`);
      }
    };
    await paint();
    let t = null;
    const off = on('task', (ev) => { if (!currentId || ev.id === currentId) { clearTimeout(t); t = setTimeout(paint, 600); } });
    const off2 = on('progress', (ev) => { if (currentId && ev.task_id === currentId) { clearTimeout(t); t = setTimeout(paint, 1200); } });
    return () => { off(); off2(); stopFrame?.(); clearTimeout(t); };
  },
  actions: {
    async stop() { await post(`/api/v1/workers/${currentId}/stop`); toast('Misi dihentikan.'); render(); },
    async start() { await post(`/api/v1/workers/${currentId}/start`); toast('Misi dimulai lagi.'); render(); },
    async say() {
      const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:12px"><span class="k cyan">Arahkan misi</span>
        <label class="field">Pesan untuk JARVIS yang sedang mengerjakan<textarea name="text" required placeholder="mis. fokus ke toko resmi saja"></textarea></label>
        <button class="btn primary">Kirim</button></form>`));
      if (!r?.text) return;
      await post(`/api/v1/workers/${currentId}/say`, { text: r.text });
      toast('Pesan sampai ke misinya.');
    },
  },
};
export const openMission = (id) => go(`#/misi/${id}`);
