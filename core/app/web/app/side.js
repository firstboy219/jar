// The desktop cockpit's third pane (ADR-087 phase J): on a wide screen, beside whatever the owner is looking at — what waits for him (answer
// it right here), the missions running, the pages open, and how JARVIS' flow is doing today. Kept fresh by the live events.
import { get, globalActions, html, icon, on, render } from './core.js';
import { itemCard, needActions, remember } from './needsui.js';
import { laneChip } from './ui.js';

const WIDE = window.matchMedia('(min-width: 1360px)');
let timer = null, busy = false;

async function paint() {
  const el = document.getElementById('side');
  if (!el) return;
  el.hidden = !WIDE.matches;
  if (!WIDE.matches || busy) return;
  busy = true;
  try {
    const [n, m, p, f] = await Promise.all([get('/api/v1/app/needs').catch(() => ({ items: [] })), get('/api/v1/app/missions').catch(() => ({ missions: [] })),
      get('/api/v1/app/pages').catch(() => ({ pages: [] })), get('/api/v1/app/flow?hours=24').catch(() => null)]);
    remember(n.items);
    const running = m.missions.filter((x) => ['queued', 'running'].includes(x.status));
    el.innerHTML = String(html`<div class="side-in">
      <div class="sec"><span>Butuh kamu · ${n.items.length}</span><a class="small" href="#/butuh">semua</a></div>
      ${n.items.length ? n.items.slice(0, 4).map((it) => itemCard(it, true)) : html`<span class="small">Tidak ada yang menunggu. ✓</span>`}
      <div class="sec"><span>Sedang berjalan · ${running.length}</span><a class="small" href="#/misi">misi</a></div>
      ${running.length ? html`<div class="list">${running.slice(0, 5).map((x) => html`<a class="li click" href="#/misi/${x.id}"><span class="dot violet live"></span><div class="grow" style="min-width:0">
        <div style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${x.title}</div><div class="small">${x.progress || x.status}</div></div></a>`)}</div>` : html`<span class="small">Tidak ada misi berjalan.</span>`}
      ${p.pages.length ? html`<div class="sec"><span>Halaman aktif · ${p.pages.length}</span><a class="small" href="#/halaman">semua</a></div>
        <div class="list">${p.pages.slice(0, 4).map((x) => html`<a class="li click" href="${x.route}"><div class="grow" style="min-width:0"><div style="font-size:13px">${x.title}</div><div class="small">${x.kind} · ${x.sub || ''}</div></div></a>`)}</div>` : ''}
      ${f ? html`<div class="sec"><span>Alur hari ini</span><a class="small" href="#/alur">lihat</a></div>
        <div class="card" style="gap:6px"><div class="row sb"><span class="small">${f.day.runs} pekerjaan</span><span class="small">${f.day.no_ai_pct ?? 0}% tanpa AI · ${f.day.ok_pct ?? '–'}% berhasil</span></div>
          ${['skill', 'ringan', 'berat', 'hermes'].map((k) => html`<div class="row sb" style="font-size:12px">${laneChip(k)}<span class="mono">${f.stations[k]?.runs || 0}×</span></div>`)}
          ${f.live.length ? html`<span class="small">${icon('bolt', 12)} ${f.live.length} sedang jalan</span>` : ''}</div>` : ''}
    </div>`);
  } finally { busy = false; }
}

function soon() { clearTimeout(timer); timer = setTimeout(paint, 800); }

export function startSide() {
  Object.assign(globalActions, needActions, { async needRefresh() { await paint(); } });
  for (const t of ['needs', 'task', 'flow', 'stage', 'meeting', 'notify', 'phone_approval', 'owner_choice']) on(t, soon);
  WIDE.addEventListener('change', paint);
  setInterval(() => { if (WIDE.matches && !document.hidden) paint(); }, 30000);
  paint();
}
export { render };
