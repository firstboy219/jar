// The app's player (ADR-087): whatever JARVIS puts on the stage as music, a sound or a video — from Musik, Video, a playlist, the chat —
// plays here, in a bar above the dock (a video opens above it, in the official YouTube player served from JARVIS' own origin). The server
// hears "ended"/"next"/"prev" back, so a playlist moves on by itself.
import { $, api, embedded, get, html, icon, on, post, send } from './core.js';

const YT = /^https:\/\/(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/;
let cur = null, audio = null, lastUrl = null, open = false, watch = null;

// the embed page is JARVIS' own origin: its title says when the video ended (a playlist then moves on)
function watchVideo() {
  clearInterval(watch);
  watch = setInterval(() => {
    const f = document.querySelector('#player iframe');
    let t = '';
    try { t = f?.contentDocument?.title || ''; } catch { /* not loaded */ }
    if (t === 'ended' && cur) { clearInterval(watch); send({ type: 'stage_event', id: cur.id, event: 'ended' }); }
  }, 2000);
}

function bar() {
  let el = $('#player');
  if (!el) { el = document.createElement('div'); el.id = 'player'; document.body.append(el); }
  return el;
}

const mmss = (t) => (Number.isFinite(t) ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}` : '–:––');

// elapsed / duration and the seek bar follow the song without repainting the whole bar
function tick() {
  if (!audio) return;
  const t = $('#ptime'); if (t) t.textContent = `${mmss(audio.currentTime)} / ${mmss(audio.duration)}`;
  const r = $('#pseek'); if (r && document.activeElement !== r) { r.max = String(Math.floor(audio.duration || 0)); r.value = String(Math.floor(audio.currentTime)); }
}

function paint() {
  const el = bar();
  if (!cur) { el.hidden = true; document.body.classList.remove('has-player'); return; }
  const yt = YT.exec(cur.url || '');
  const playing = audio && !audio.paused;
  el.hidden = false;
  document.body.classList.add('has-player');
  el.innerHTML = String(html`
    ${yt && open ? html`<div class="pv"><iframe src="/embed/youtube/${yt[1]}?play=1" title="${cur.title}" allow="autoplay; encrypted-media; fullscreen" allowfullscreen></iframe></div>` : ''}
    <div class="pb">
      ${cur.cover_url ? html`<img src="${cur.cover_url}" alt="">` : html`<span class="ico">${icon(cur.panel === 'video' ? 'video' : 'music', 18)}</span>`}
      <div class="grow" style="min-width:0"><div class="pt">${cur.title || 'Diputar'}</div><div class="small pa">${cur.artist || ''}${cur.playlist ? ` · ${cur.playlist.index + 1}/${cur.playlist.total}` : ''}${audio ? html` · <span class="mono" id="ptime">${mmss(audio.currentTime)} / ${mmss(audio.duration)}</span>` : ''}</div>
        ${audio ? html`<input type="range" id="pseek" min="0" max="${Math.floor(audio.duration || 0)}" value="${Math.floor(audio.currentTime)}" style="width:100%;height:14px" aria-label="Posisi lagu">` : ''}</div>
      ${cur.playlist ? html`<button class="ib sm" data-pl="prev" aria-label="Sebelumnya">${icon('back', 18)}</button>` : ''}
      ${yt ? html`<button class="ib sm" data-pl="toggle" aria-label="${open ? 'Tutup video' : 'Buka video'}">${icon(open ? 'down' : 'play', 18)}</button>`
           : html`<button class="ib sm" data-pl="play" aria-label="${playing ? 'Jeda' : 'Putar'}">${icon(playing ? 'pause' : 'play', 18)}</button>`}
      ${cur.playlist ? html`<button class="ib sm" data-pl="next" aria-label="Berikutnya">${icon('right', 18)}</button>` : ''}
      <button class="ib sm" data-pl="close" aria-label="Tutup pemutar">${icon('close', 16)}</button>
    </div>`);
}

async function load(autoplay) {
  const yt = YT.exec(cur.url || '');
  if (audio) { audio.pause(); audio = null; }
  if (lastUrl) { URL.revokeObjectURL(lastUrl); lastUrl = null; }
  if (yt) { open = autoplay; paint(); if (open) watchVideo(); return; }
  let src = cur.url;
  if (src.startsWith('/api/v1/media/')) {   // JARVIS' own file: an <audio> cannot send the device token, so it is fetched first
    const b = await api('GET', src, undefined, { blob: true });
    src = lastUrl = URL.createObjectURL(b);
  }
  if (!src) return paint();
  audio = new Audio(src);
  audio.addEventListener('ended', () => { send({ type: 'stage_event', id: cur?.id, event: 'ended' }); paint(); });
  audio.addEventListener('play', paint);
  audio.addEventListener('pause', paint);
  audio.addEventListener('timeupdate', tick);
  audio.addEventListener('loadedmetadata', paint);
  if (autoplay) audio.play().catch(() => paint());
  paint();
}

function take(p, autoplay) {
  if (!p || !p.url) return;
  if (cur && cur.id === p.id && cur.url === p.url) return;
  cur = p;
  load(autoplay);
}

export function startPlayer() {
  if (embedded) return;   // inside the APK the phone's own player (the talk sheet's music/video panel, with its media session) plays it
  on('stage', (e) => {
    if (!['music', 'audio', 'video'].includes(e.panel)) return;
    if (e.mode === 'close') { if (cur && cur.id === e.id) { audio?.pause(); cur = null; paint(); } return; }
    const p = e.payload || {};
    take({ id: e.id, panel: e.panel, title: p.title, artist: p.artist || p.channel, url: p.url, cover_url: p.cover_url || p.thumbnail_url, playlist: p.playlist }, true);
  });
  get('/api/v1/app/music').then((s) => { if (s.now) take(s.now, false); }).catch(() => {});
  document.addEventListener('change', (e) => { if (e.target.id === 'pseek' && audio) audio.currentTime = Number(e.target.value); });
  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-pl]');
    if (!b || !cur) return;
    const a = b.dataset.pl;
    if (a === 'play') { if (!audio) return; if (audio.paused) audio.play(); else audio.pause(); }
    else if (a === 'toggle') { open = !open; paint(); if (open) watchVideo(); else clearInterval(watch); }
    else if (a === 'next' || a === 'prev') { send({ type: 'stage_event', id: cur.id, event: a }); }
    else if (a === 'close') { audio?.pause(); send({ type: 'stage_event', id: cur.id, event: 'closed' }); post('/api/v1/app/music/stop').catch(() => {}); cur = null; open = false; paint(); }
  });
}

/** The track now playing (for the Musik screen). */
export const nowPlaying = () => cur;
