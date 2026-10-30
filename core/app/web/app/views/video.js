// Video (mockup 5): find a YouTube video (or paste its link), play it in the official player, and understand it — the summary, chapters with
// times (tap one to jump there), and answers to "di menit berapa dia bahas X?" — from the video's own subtitles.
import { $, castTv, get, header, html, icon, loading, pickSpeaker, pipVideo, post, render, toast } from '../core.js';
import { dur } from '../lib.js';
import { laneChip } from '../ui.js';

let state = { q: '', results: null, rate: 1, cc: '' };
const yt = () => $('#yt')?.contentWindow;
const info = () => { try { return JSON.parse(yt()?.jv?.({ cmd: 'info' }) || '{}'); } catch { return {}; } };
const mmss = (t) => { t = Math.floor(t || 0); return t >= 3600 ? `${Math.floor(t / 3600)}:${String(Math.floor(t % 3600 / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}` : `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`; };

function detail(id, n) {
  const s = n?.summary;
  return html`<div class="card"><div style="aspect-ratio:16/9;border-radius:12px;overflow:hidden;background:#000"><iframe id="yt" src="/embed/youtube/${id}?autoplay=0" style="width:100%;height:100%;border:0" allow="autoplay; encrypted-media; fullscreen" allowfullscreen title="video"></iframe></div>
      <div class="row" style="gap:6px;flex-wrap:wrap">${[0.75, 1, 1.25, 1.5, 2].map((r) => html`<button class="chip ${state.rate === r ? 'on' : ''}" data-act="rate" data-v="${r}">${String(r).replace('.', ',')}×</button>`)}
        ${[['', 'Subtitle mati'], ['id', 'Sub ID'], ['en', 'Sub EN']].map(([l, t]) => html`<button class="chip ${state.cc === l ? 'on' : ''}" data-act="cc" data-l="${l}">${t}</button>`)}</div>
      <div class="row" style="gap:6px;flex-wrap:wrap"><button class="chip" data-act="pip" data-id="${id}">${icon('pages', 13)} Jendela kecil</button>
        <button class="chip" data-act="tv" data-id="${id}">${icon('screen', 13)} Ke TV</button><button class="chip" data-act="speaker">${icon('speaker', 13)} Speaker</button></div>
      <span class="ttl">${n?.title || ''}</span><span class="small">${n?.channel || ''}${n?.duration_s ? ` · ${dur(n.duration_s)}` : ''}</span>
      <div class="btns"><button class="btn" data-act="play" data-id="${id}" data-t="${n?.title || ''}">${icon('play', 16)} Putar di pemutar</button>${s ? '' : html`<button class="btn primary" data-act="summary" data-id="${id}">${icon('bolt', 16)} Ringkas</button>`}</div></div>
    ${s ? html`<div class="card violet"><div class="row sb"><span class="k violet">Ringkasan</span>${laneChip(s.lane)}</div><p class="sub">${s.ringkasan}</p>
        ${(s.poin || []).map((p) => html`<span class="small">• ${p}</span>`)}${s.untuk_siapa ? html`<span class="small t-amber2">${s.untuk_siapa}</span>` : ''}</div>
      ${(s.bab || []).length ? html`<div class="card"><span class="k">Bab</span>${s.bab.map((b) => html`<button class="row" data-act="seek" data-id="${id}" data-t="${b.t}" style="background:none;border:0;color:inherit;text-align:left;gap:10px;cursor:pointer;padding:2px 0">
        <span class="mono" style="color:var(--cyan-t);min-width:56px">${mmss(b.t)}</span><span style="font-size:14px">${b.judul}</span></button>`)}</div>` : ''}
      <form class="card" id="vq"><label class="field">Tanya soal video ini<input name="q" placeholder="mis. di menit berapa dia bahas harga?" required minlength="2"></label><button class="btn" data-act="ask" data-id="${id}">Tanya</button><div id="vans"></div></form>` : ''}
    <span class="small" style="padding:0 4px">Dari subtitle video${n?.source === 'phone' ? ' (diambil lewat HP-mu)' : ''}; ringkasan & jawaban lewat alur master.</span>`;
}

export default {
  tab: 'beranda',
  feature: 'video',
  async render(root, route) {
    const id = route.params[0];
    root.innerHTML = String(html`${header('Video')}<div class="scr">${loading()}</div>`);
    if (id) {
      const { notes } = await get(`/api/v1/app/video/${id}`);
      root.innerHTML = String(html`${header(notes?.title ? 'Video' : 'Video', { sub: notes?.channel || '' })}<div class="scr">${detail(id, notes)}</div>`);
      return;
    }
    const d = await get('/api/v1/app/video');
    root.innerHTML = String(html`${header('Video')}
      <div class="scr">
        <form class="cmd" id="vs" style="display:flex"><input name="q" value="${state.q}" placeholder="Cari video atau tempel link YouTube…" style="flex:1"><button class="ib sm" data-act="find" aria-label="Cari">${icon('search', 18)}</button></form>
        ${state.results ? html`<div class="list">${state.results.map((v) => html`<a class="li click" href="#/video/${v.id}"><img src="${v.thumbnail}" alt="" style="width:96px;height:54px;object-fit:cover;border-radius:8px;flex:none">
          <div class="grow" style="min-width:0"><div style="font-size:14px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${v.title || v.id}</div><div class="small">${v.channel}${v.duration_s ? ` · ${dur(v.duration_s)}` : ''}</div></div></a>`)}</div>` : ''}
        ${d.recent.length ? html`<span class="sec">Sudah dibuka</span><div class="list">${d.recent.map((v) => html`<a class="li click" href="#/video/${v.video_id}"><img src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg" alt="" style="width:80px;height:45px;object-fit:cover;border-radius:6px;flex:none">
          <div class="grow" style="min-width:0"><div style="font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${v.title}</div><div class="small">${v.channel}${v.summarized ? ' · diringkas' : ''}</div></div></a>`)}</div>` : ''}
      </div>`);
  },
  actions: {
    async find(b, e) { e?.preventDefault(); state.q = new FormData($('#vs')).get('q') || ''; if (!state.q) return; toast('Mencari…'); state.results = (await get(`/api/v1/app/video?q=${encodeURIComponent(state.q)}`)).results; render(); },
    async play(b) { await post(`/api/v1/app/video/${b.dataset.id}/play`, { title: b.dataset.t }); toast('Diputar di pemutar'); },
    async summary(b) { toast('Mengambil subtitle & meringkas…'); await post(`/api/v1/app/video/${b.dataset.id}/summary`); render(); },
    seek(b) {   // a jump without reloading the player (its speed and subtitles stay)
      if (yt()?.jv?.({ cmd: 'seek', t: Number(b.dataset.t) }) === 'ok') return;
      const f = $('#yt'); if (f) f.src = `/embed/youtube/${b.dataset.id}?play=1&start=${Math.floor(Number(b.dataset.t))}&rate=${state.rate}&cc=${state.cc}`;
    },
    rate(b) { state.rate = Number(b.dataset.v); yt()?.jv?.({ cmd: 'rate', v: state.rate }); document.querySelectorAll('[data-act=rate]').forEach((c) => c.classList.toggle('on', c === b)); },
    cc(b) { state.cc = b.dataset.l; yt()?.jv?.({ cmd: 'cc', lang: state.cc }); document.querySelectorAll('[data-act=cc]').forEach((c) => c.classList.toggle('on', c === b)); },
    pip(b) { const t = info().t || 0; yt()?.jv?.({ cmd: 'pause' }); pipVideo(b.dataset.id, t); },
    tv(b) { const t = info().t || 0; yt()?.jv?.({ cmd: 'pause' }); castTv(b.dataset.id, t); },
    speaker() { pickSpeaker(); },
    async ask(b, e) {
      e?.preventDefault();
      const q = new FormData($('#vq')).get('q');
      $('#vans').innerHTML = String(loading());
      const r = await post(`/api/v1/app/video/${b.dataset.id}/ask`, { question: q });
      $('#vans').innerHTML = String(html`<p class="sub">${r.answer}</p>${r.moments.slice(0, 3).map((m) => html`<button class="chip" data-act="seek" data-id="${b.dataset.id}" data-t="${m.t}">${mmss(m.t)}</button>`)}`);
    },
  },
};
