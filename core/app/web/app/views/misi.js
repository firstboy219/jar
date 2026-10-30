// Misi (mockup 4): every piece of work JARVIS does — the plan, the brain/lane Hermes picked, the live screen, cost, and the controls.
import { empty, get, go, header, html, icon, loading, on, post, render, sheet, speak, toast } from '../core.js';
import { ago, dur, pct, usd } from '../lib.js';
import { laneChip, liveFrame, resultView, statusPill } from '../ui.js';

const LANE_OF_RUNTIME = { ringan: 'ringan', openjarvis: 'berat', hermes: 'hermes' };

// a result kept, shared, read aloud, or asked about further (mockup "Hasil")
export function resultText(t) {
  const d = t.result?.data || {};
  return [d.ringkasan, ...(d.poin || []), t.result?.text].filter(Boolean).join('\n');
}

function resultBlocks(t) {
  const d = t.result?.data || {};
  const b = [];
  if (d.ringkasan) b.push({ type: 'callout', text: String(d.ringkasan).slice(0, 2000) });
  for (const p of d.poin || []) b.push({ type: 'bullet', text: String(p).slice(0, 500) });
  for (const tb of d.tabel || []) { b.push({ type: 'h2', text: tb.judul || 'Tabel' }); for (const r of tb.baris || []) b.push({ type: 'bullet', text: r.join(' · ').slice(0, 500) }); }
  for (const para of String(t.result?.text || '').split(/\n{2,}/).slice(0, 40)) if (para.trim()) b.push({ type: 'p', text: para.trim().slice(0, 2000) });
  for (const l of d.tautan || []) b.push({ type: 'bullet', text: `${l.teks}: ${l.url}` });
  return b;
}

function scheduledView(ps) {
  const sch = ps.filter((p) => p.schedule && p.schedule !== 'manual');
  if (!sch.length) return empty('Belum ada misi terjadwal.', 'Proyek dengan jadwal (tiap jam / harian / mingguan) muncul di sini.');
  return html`<div class="list">${sch.map((p) => html`<div class="li"><span class="ico cyan">${icon('clock', 18)}</span><div class="grow"><div class="ttl">${p.name}</div>
    <div class="small">${p.schedule_text || p.schedule}${p.next_run ? ` · berikutnya ${new Date(p.next_run).toLocaleString('id-ID', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}` : ''}${p.status ? ` · ${p.status}` : ''}</div></div>
    <button class="btn sm" data-act="runProject" data-id="${p.id}">${icon('play', 14)} Jalankan</button></div>`)}</div>`;
}

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

// What finished missions produced: a line of each result, newest first; each opens to its full report.
function resultsView(ms) {
  if (!ms.length) return empty('Belum ada hasil.', 'Misi yang selesai — riset, laporan, pesanan — beserta hasilnya muncul di sini.');
  const text = (p) => { if (!p) return ''; try { const j = JSON.parse(p); return j.summary || j.ringkasan || j.text || p; } catch { return p; } };
  return html`<div class="list">${ms.map((m) => html`<a class="li click" href="#/misi/${m.id}"><span class="ico green">${icon('check', 16)}</span>
    <div class="grow" style="min-width:0"><div class="ttl">${m.title}</div><div class="small" style="overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${text(m.preview)}</div>
    <div class="small">${new Date(m.finished_at || m.created_at).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}${m.cost ? ` · ${usd(m.cost)}` : ''}</div></div>${icon('right', 16)}</a>`)}</div>`;
}

function detailView(t) {
  const lane = LANE_OF_RUNTIME[t.runtime] || t.runtime;
  const steps = (t.plan?.steps || []);
  const live = t.station?.steps || [];
  const doneSteps = t.status === 'completed' ? steps.length : Math.min(steps.length, Math.floor((pct(live.length, Math.max(live.length + 2, steps.length * 2)) / 100) * steps.length));
  const left = t.status === 'running' && doneSteps > 0 && steps.length > doneSteps ? Math.round((t.seconds / doneSteps) * (steps.length - doneSteps) / 60) : null;
  return html`
    <div class="scr">
      <div class="row sb"><span class="small">Misi · ${ago(t.created_at)}${t.started_at ? '' : ' · belum mulai'}</span>${statusPill(t.status)}</div>
      <h1 class="big" style="font-size:22px">${t.title}</h1>
      <div class="row wrap" style="gap:6px">${laneChip(lane, t.runtime_note)}${t.model_used ? html`<span class="tag">${t.model_used.split('/').pop()}</span>` : ''}<span class="tag">${dur(t.seconds)}</span>${t.cost ? html`<span class="tag">${usd(t.cost)}</span>` : ''}</div>
      ${t.runtime_note ? html`<p class="small" style="margin:0">Hermes: ${t.runtime_note}</p>` : ''}
      ${t.station?.has_frame || t.station?.browsing ? html`<div class="livebox"><div class="bar2"><span class="dot red live"></span>LANGSUNG · ${t.station.page_title || t.station.url || 'browser'}</div><img id="frame" alt="Layar langsung misi"></div>` : ''}
      ${t.station?.thought ? html`<div class="card violet"><span class="k violet">Sedang dipikirkan</span><p class="sub">${t.station.thought}</p></div>` : ''}
      ${steps.length ? html`<div class="sec"><span>Rencana · diatur Hermes</span><span class="small" style="text-transform:none;letter-spacing:0">${doneSteps}/${steps.length}${left != null ? ` · sisa ±${Math.max(1, left)} mnt` : ''}</span></div><div class="steps">${steps.map((s, i) => html`<div class="step"><div class="rail"><span class="n ${i < doneSteps ? 'done' : (i === doneSteps && t.status === 'running' ? 'now' : '')}">${i < doneSteps ? icon('check', 13) : ''}</span>${i < steps.length - 1 ? html`<span class="ln"></span>` : ''}</div><div class="body"><span style="font-size:14px;${i < doneSteps ? 'color:var(--tx2)' : ''}">${s}</span></div></div>`)}</div>` : ''}
      ${live.length ? html`<details class="card" ${t.status === 'running' ? 'open' : ''}><summary class="small">Langkah terakhir (${live.length})</summary><div style="display:flex;flex-direction:column;gap:4px;margin-top:8px">${live.slice(-8).map((s) => html`<span class="small">• ${s.text || s.label || s.name || JSON.stringify(s)}</span>`)}</div></details>` : ''}
      ${t.error ? html`<div class="card red"><span class="k red">Kendala</span><p class="sub">${t.error}</p></div>` : ''}
      ${t.status === 'completed' ? resultView(t.result?.data, t.result?.text) : ''}
      ${t.status === 'completed' && (t.result?.text || t.result?.data?.ringkasan) ? html`<div class="g4">
        <button class="btn" data-act="readResult" style="flex-direction:column;height:56px;font-size:11px">${icon('speaker', 18)}Bacakan</button>
        <button class="btn" data-act="saveResult" style="flex-direction:column;height:56px;font-size:11px">${icon('notes', 18)}Simpan</button>
        <button class="btn" data-act="shareResult" style="flex-direction:column;height:56px;font-size:11px">${icon('upload', 18)}Bagikan</button>
        <button class="btn" data-act="askMore" style="flex-direction:column;height:56px;font-size:11px">${icon('chat', 18)}Tanya lanjut</button></div>` : ''}
      ${t.episode ? html`<span class="small" style="padding:0 4px">${t.episode.success ? '✓ dipelajari' : '✗ dicatat'}: ${t.episode.lesson || t.episode.approach || ''}</span>` : ''}
      <div class="g4" style="margin-top:4px">
        <button class="btn" data-act="say" ${t.can_say ? '' : 'disabled'} style="flex-direction:column;height:60px;font-size:11px">${icon('chat', 18)}Arahkan</button>
        <button class="btn" data-native="desk" style="flex-direction:column;height:60px;font-size:11px" ${t.station ? '' : 'disabled'}>${icon('hand', 18)}Ambil alih</button>
        <button class="btn" data-act="start" ${t.can_start ? '' : 'disabled'} style="flex-direction:column;height:60px;font-size:11px">${icon('play', 18)}Mulai lagi</button>
        <button class="btn danger" data-act="stop" ${t.can_stop ? '' : 'disabled'} style="flex-direction:column;height:60px;font-size:11px">${icon('stop', 18)}Hentikan</button>
      </div>
    </div>`;
}

let currentId = null, current = null, tab = 'misi';

export default {
  tab: 'misi',
  async render(root, route) {
    currentId = route.params[0] ? Number(route.params[0]) : null;
    root.innerHTML = String(html`${header(currentId ? 'Misi' : 'Misi', { back: !!currentId, sub: currentId ? '' : 'semua pekerjaan JARVIS' })}<div class="scr">${loading()}</div>`);
    let stopFrame = null;
    const paint = async () => {
      if (currentId) {
        const t = current = await get(`/api/v1/app/missions/${currentId}`);
        root.innerHTML = String(html`${header('Misi', { sub: `#${t.id}` })}${detailView(t)}`);
        stopFrame?.();
        const img = root.querySelector('#frame');
        if (img) stopFrame = liveFrame(img, t.id);
      } else {
        tab = ['jadwal', 'hasil'].includes(route.query.tab) ? route.query.tab : 'misi';
        const body = tab === 'jadwal' ? scheduledView((await get('/api/v1/projects')).projects || [])
          : tab === 'hasil' ? resultsView((await get('/api/v1/app/missions?done=true')).missions) : listView((await get('/api/v1/app/missions')).missions);
        root.innerHTML = String(html`${header('Misi', { back: false, sub: 'semua pekerjaan JARVIS' })}<div class="scr">
          <div class="chips"><a class="chip ${tab === 'misi' ? 'on' : ''}" href="#/misi">Misi</a><a class="chip ${tab === 'hasil' ? 'on' : ''}" href="#/misi?tab=hasil">${icon('chart', 13)} Hasil & laporan</a><a class="chip ${tab === 'jadwal' ? 'on' : ''}" href="#/misi?tab=jadwal">${icon('clock', 13)} Terjadwal</a></div>${body}</div>`);
      }
    };
    await paint();
    let t = null;
    const off = on('task', (ev) => { if (!currentId || ev.id === currentId) { clearTimeout(t); t = setTimeout(paint, 600); } });
    const off2 = on('progress', (ev) => { if (currentId && ev.task_id === currentId) { clearTimeout(t); t = setTimeout(paint, 1200); } });
    return () => { off(); off2(); stopFrame?.(); clearTimeout(t); };
  },
  actions: {
    readResult() { speak(resultText(current)); },
    async saveResult() {
      const page = await post('/api/v1/notes', { title: `Hasil: ${current.title}`.slice(0, 200), icon: '📋', blocks: resultBlocks(current) });
      toast('Tersimpan di Catatan'); if (page?.id) go('#/catatan?tab=halaman');
    },
    async shareResult() {
      const text = `${current.title}\n\n${resultText(current)}`.slice(0, 8000);
      if (navigator.share) { try { await navigator.share({ title: current.title, text }); return; } catch { /* cancelled */ } }
      try { await navigator.clipboard.writeText(text); toast('Hasil disalin — tempel di mana saja'); } catch { toast('Tidak bisa membagikan di sini', true); }
    },
    async askMore() {
      const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:12px"><span class="k cyan">Tanya lanjut</span>
        <label class="field">Pertanyaan tentang hasil ini<textarea name="q" required placeholder="mis. mana yang paling hemat baterai?"></textarea></label><button class="btn primary">Tanya JARVIS</button></form>`));
      if (!r?.q) return;
      sessionStorage.setItem('jarvis_app_pending', `Tentang hasil misi #${current.id} "${current.title}": ${r.q}`);
      go('#/obrolan');
    },
    async runProject(b) { await post(`/api/v1/projects/${b.dataset.id}/run`); toast('Proyek dijalankan sekarang'); render(); },
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
