// Musik (mockup 4): music by mood (his own search words per mood), the mood he usually wants at this hour (learned), his playlists, a search
// — whatever starts plays in the app's player bar; the morning habit offers his usual mood.
import { $, get, header, html, icon, loading, on, post, put, render, toast } from '../core.js';
import { laneChip } from '../ui.js';

const MOOD_ICON = { fokus: 'bulb', semangat: 'bolt', olahraga: 'heart', santai: 'coffee', tidur: 'moon' };
let st = null;

export default {
  tab: 'beranda',
  feature: 'musik',
  async render(root) {
    root.innerHTML = String(html`${header('Musik')}<div class="scr">${loading()}</div>`);
    const s = st = await get('/api/v1/app/music');
    const u = s.usual;
    root.innerHTML = String(html`${header('Musik', { sub: s.now ? `diputar: ${s.now.title}` : '' })}
      <div class="scr">
        <button class="card violet" data-act="mood" data-m="${u.mood}" style="text-align:left;cursor:pointer"><span class="k violet">Untuk jam segini</span>
          <span class="ttl" style="font-size:20px">${icon(MOOD_ICON[u.mood] || 'music', 20)} ${u.mood}</span><span class="small">${u.why} · ketuk untuk putar</span></button>
        <div class="g3">${Object.keys(s.moods).map((m) => html`<button class="tile" data-act="mood" data-m="${m}" style="padding:14px 8px;display:flex;flex-direction:column;align-items:center;gap:6px;background:var(--s1);border:1px solid var(--bd);border-radius:14px;cursor:pointer">
          ${icon(MOOD_ICON[m] || 'music', 22)}<span style="font-size:13px">${m}</span></button>`)}</div>
        <form class="cmd" id="mq" style="display:flex"><input name="q" placeholder="Cari lagu, penyanyi, atau suasana…" style="flex:1"><button class="ib sm" data-act="search" aria-label="Putar">${icon('play', 18)}</button></form>
        ${s.now ? html`<div class="card amber"><div class="row sb"><div><span class="k amber">Sedang diputar</span><div class="ttl">${s.now.title}</div><div class="small">${s.now.artist || ''}${s.now.playlist ? ` · ${s.now.playlist.name} · lagu ${s.now.playlist.index + 1} dari ${s.now.playlist.total}` : ''}</div></div>
          <button class="btn sm" data-act="saveNow">${icon('plus', 14)} Simpan ke playlist</button></div>
          <div class="btns"><button class="btn sm" data-act="ctl" data-a="prev" aria-label="Sebelumnya">⏮</button><button class="btn sm" data-act="ctl" data-a="stop" aria-label="Berhenti">${icon('stop', 14)}</button><button class="btn sm" data-act="ctl" data-a="next" aria-label="Berikutnya">⏭</button></div></div>` : ''}
        ${s.playlists.length ? html`<span class="sec">Playlist</span><div class="list">${s.playlists.map((p) => html`<button class="li click" data-act="playlist" data-n="${p.name}" style="width:100%;text-align:left;background:none;border-left:0;border-right:0;border-top:0">
          <span class="ico violet">${icon('list', 18)}</span><div class="grow"><div class="ttl">${p.name}</div><div class="small">${p.count ?? p.songs ?? ''} lagu</div></div>${icon('play', 16)}</button>`)}</div>
          <div class="chips">${s.playlists.map((p) => html`<button class="chip" data-act="shuffle" data-n="${p.name}">🔀 Acak ${p.name}</button>`)}</div>` : ''}
        ${s.recent.length ? html`<span class="sec">Terakhir diputar</span><div class="list">${s.recent.map((r) => html`<div class="li"><div class="grow"><div style="font-size:14px">${r.title || r.query}</div>
          <div class="small">${r.mood ? `${r.mood} · ` : ''}${new Date(r.at).toLocaleString('id-ID', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}</div></div></div>`)}</div>` : ''}
        <details class="card"><summary class="small">Kata pencarian tiap mood</summary>
          <form id="moodf" style="display:flex;flex-direction:column;gap:8px">${Object.entries(s.moods).map(([m, q]) => html`<label class="field">${m}<input name="${m}" value="${q}"></label>`)}
          <button class="btn" data-act="savemoods">Simpan</button></form></details>
        <p class="small" style="padding:0 4px">Musik berlisensi bebas diputar langsung; lagu tertentu lewat pemutar YouTube resmi. Lewat alur master (skill tanpa AI).</p>
      </div>`);
    return on('stage', (e) => { if (['music', 'audio', 'video'].includes(e.panel)) setTimeout(render, 300); });
  },
  actions: {
    async mood(b) { toast(`Mencari musik ${b.dataset.m}…`); const r = await post('/api/v1/app/music/play', { mood: b.dataset.m }); toast(`▶ ${r.playing || 'diputar'}`); },
    async search(b, e) { e?.preventDefault(); const q = new FormData($('#mq')).get('q'); if (!q) return; toast('Mencari…'); const r = await post('/api/v1/app/music/play', { query: q }); toast(`▶ ${r.playing || 'diputar'}`); },
    async playlist(b) { const r = await post('/api/v1/app/music/playlist', { name: b.dataset.n }); toast(`▶ ${r.song?.title || r.playing || 'diputar'}`); },
    async ctl(b) { await post(`/api/v1/app/music/${b.dataset.a}`); setTimeout(render, 600); },
    async saveNow() { const r = await post('/api/v1/app/music/save', {}); toast(`Disimpan: ${r.saved}`); render(); },
    async shuffle(b) { const r = await post('/api/v1/app/music/playlist', { name: b.dataset.n, shuffle: true }); toast(`🔀 ${r.song?.title || r.playing || 'diputar'}`); },
    async savemoods(b, e) { e?.preventDefault(); await put('/api/v1/app/settings/music', { moods: Object.fromEntries(new FormData($('#moodf')).entries()) }); toast('Tersimpan'); render(); },
  },
};
export { laneChip };
