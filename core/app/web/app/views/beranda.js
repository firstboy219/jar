// Beranda pintar (mockup 40): the hero card, two supporting cards and seven shortcuts — all picked by the server for this moment.
import { $, empty, errorBox, get, html, icon, loading, on } from '../core.js';
import { tone } from '../lib.js';
import { itemCard, needActions } from '../needsui.js';

let timer = null;

function card(c, wide = false) {
  if (!c) return '';
  const t = tone(c.tone);
  return wide
    ? html`<div class="card ${t}"><a class="row" href="${c.route}"><span class="ico ${t}">${icon(c.icon || 'grid', 20)}</span><div class="grow"><div class="ttl">${c.title}</div><div class="sub">${c.sub || ''}</div></div>${icon('right', 16)}</a>${sublist(c)}</div>`
    : html`<a class="card mini" href="${c.route}"><span style="color:var(--${t === 'amber' ? 'amber' : t})">${icon(c.icon || 'grid', 20)}</span><div class="ttl">${c.title}</div><div class="small">${c.sub || ''}</div>${c.list?.length ? html`<span class="small">${c.list.length} item</span>` : ''}</a>`;
}

function sublist(c) {   // a card's own items: running missions, today's agenda, scheduled projects
  if (!c.list?.length) return '';
  return html`<div style="display:flex;flex-direction:column;gap:6px;margin-top:4px">${c.list.map((x) => html`<a class="row sb" href="${x.route || c.route}" style="font-size:13px;gap:8px">
    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${x.status === 'running' ? html`<span class="dot violet live"></span> ` : ''}${x.title}</span>
    <span class="mono small" style="flex:none">${x.when || (x.progress != null ? `${Math.round(x.progress)}%` : x.status === 'queued' ? 'antre' : '')}</span></a>`)}</div>`;
}

function hero(c) {
  if (!c) return '';
  if (c.kind === 'needs' && c.need) return html`<span class="k amber" style="padding:0 4px">Sekarang untukmu</span>${itemCard(c.need, true)}`;   // answered right here
  const t = tone(c.tone);
  return html`<a class="card hero ${t}" href="${c.route}" style="border-color: var(--${t})">
    <span class="k ${t}">Sekarang untukmu</span>
    <div class="row"><span class="ico ${t}" style="width:48px;height:48px;border-radius:14px">${icon(c.icon || 'grid', 24)}</span>
      <div class="grow"><div class="t">${c.title}</div><div class="sub">${c.sub || ''}</div></div></div>
    ${c.cta ? html`<span class="btn block ${t === 'amber' ? 'amber' : 'primary'}">${c.cta}</span>` : ''}
  </a>`;
}

export default {
  tab: 'beranda',
  feature: false,
  async render(root, route) {
    root.innerHTML = String(loading());
    const paint = async () => {
      let d;
      try { d = await get(`/api/v1/app/home${route.query.slot ? `?slot=${encodeURIComponent(route.query.slot)}` : ''}`); }
      catch (e) { root.innerHTML = String(errorBox(e)); return; }
      const pages = await get('/api/v1/app/pages').then((p) => p.pages.length).catch(() => 0);
      root.innerHTML = String(html`
        <header class="hdr" style="padding:18px 20px 6px">
          <div class="row grow">
            <span style="width:34px;height:34px;border-radius:50%;border:1.5px solid var(--cyan);display:flex;align-items:center;justify-content:center"><span style="width:12px;height:12px;border-radius:6px;background:var(--cyan)"></span></span>
            <span class="ctx">${d.context}</span>
          </div>
          <a class="ib box" href="#/kontrol" aria-label="Kontrol">${icon('gear', 18)}</a>
          <a class="ib box" href="#/halaman" aria-label="Halaman aktif" style="position:relative">${icon('pages', 18)}${pages ? html`<span style="position:absolute;top:5px;right:5px;min-width:16px;height:16px;border-radius:8px;background:var(--cyan);color:var(--bg);font-size:10px;font-weight:600;display:flex;align-items:center;justify-content:center">${pages}</span>` : ''}</a>
        </header>
        <div class="scr">
          <div style="padding:0 4px"><h1 class="big">${d.greeting}</h1><p class="lead">${d.subtitle}</p></div>
          ${d.hero ? hero(d.hero) : empty('Belum ada yang perlu kamu putuskan.', 'Minta apa saja lewat kolom di bawah, atau buka pintasan.')}
          ${d.cards.length === 2 ? html`<div class="g2">${d.cards.map((c) => card(c))}</div>` : d.cards.map((c) => card(c, true))}
          ${d.needs > 1 ? html`<a class="card amber row" href="#/butuh"><span class="k amber grow">Butuh kamu · ${d.needs}</span>${icon('right', 16)}</a>` : ''}
          <div class="sec"><span>Pintasan</span><span class="small" style="text-transform:none;letter-spacing:0">urut menurut jam &amp; kebiasaan</span></div>
          <div class="tiles">
            ${d.shortcuts.map((s) => html`<a class="tile" href="${s.route}"><span class="sq">${icon(s.icon, 20)}</span><span>${s.label}</span></a>`)}
            <a class="tile" href="#/fitur"><span class="sq primary">${icon('grid', 20)}</span><b style="color:var(--tx)">Semua fitur</b></a>
          </div>
          ${d.all.filter((c) => ['missions', 'calendar', 'scheduled'].includes(c.kind) && c.list?.length && c.id !== d.hero?.id && !d.cards.some((x) => x.id === c.id)).map((c) => card(c, true))}
          ${d.all.length > 3 ? html`<div class="sec"><span>Lainnya sekarang</span></div><div class="list">${d.all.filter((c) => c !== d.hero && !d.cards.some((x) => x.id === c.id) && c.id !== d.hero?.id && !(['missions', 'calendar', 'scheduled'].includes(c.kind) && c.list?.length)).slice(0, 5).map((c) => html`<a class="li click" href="${c.route}"><span class="ico ${tone(c.tone)}">${icon(c.icon || 'grid', 18)}</span><div class="grow"><div class="ttl">${c.title}</div><div class="small">${c.sub || ''}</div></div>${icon('right', 16)}</a>`)}</div>` : ''}
        </div>`);
    };
    await paint();
    const refresh = () => { clearTimeout(timer); timer = setTimeout(() => { if ($('#view').dataset.view === 'beranda') paint(); }, 800); };
    const offs = ['task', 'flow', 'phone_approval', 'owner_choice', 'notify', 'place', 'meeting', 'stage'].map((t) => on(t, refresh));
    const tick = setInterval(paint, 60000);
    return () => { offs.forEach((f) => f()); clearInterval(tick); clearTimeout(timer); };
  },
  actions: needActions,
};
