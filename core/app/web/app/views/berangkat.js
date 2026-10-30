// Berangkat & Pulang (mockups 10 & 14): door-to-door options — GoRide to the station, KRL (with the change at Manggarai), the walk — with
// times and costs; the one the owner takes becomes a live trip (reminders, the GoRide ordered at the right moment, a new plan if a train is missed).
import { $, get, go, header, html, icon, loading, post, put, render, toast } from '../core.js';
import { rupiah } from '../lib.js';

let state = { dir: 'out', trip: null };
const hm = (s) => (s || '').replace(':', '.');

function stationPicker(s) {
  return html`<div class="card cyan"><span class="k cyan">Atur dulu</span><p class="sub">Pilih stasiun KRL dekat rumah dan dekat kantor. Jarak naik GoRide &amp; jalan kaki dihitung dari tempatmu (rumah &amp; kantor dipelajari dari lokasi HP).</p>
    <label class="field">Stasiun dekat rumah<input id="hs" list="stlist" value="${s.home_station}" placeholder="mis. Bogor"></label>
    <label class="field">Stasiun dekat kantor<input id="os" list="stlist" value="${s.office_station}" placeholder="mis. Sudirman"></label>
    <div class="g2"><label class="field">Jalan kaki stasiun↔kantor (mnt)<input id="wm" type="number" min="0" max="40" value="${s.walk_min}"></label>
      <label class="field">Tiba di kantor sebelum<input id="ab" type="time" value="${s.arrive_before}"></label></div>
    <datalist id="stlist"></datalist><button class="btn primary" data-act="savest">Simpan</button></div>`;
}

function optionCard(o, i, best, dir) {
  const sel = i === best;
  const total = Math.max(1, o.minutes || 1), ride = o.ride?.min || 0;
  const segs = dir === 'out'
    ? [ride && ['green', ride], ['bd2', 5], ['cyan', Math.max(10, total - ride - 11)], ['mu', 6]]
    : [['mu', 6], ['bd2', 5], ['cyan', Math.max(10, total - ride - 11)], ride && ['green', ride]];
  return html`<div class="card ${sel ? 'sel' : ''}">
    <div class="row sb"><span class="ttl">${String.fromCharCode(65 + i)} · KRL ${hm(o.dep)} ${sel ? html`<span class="tag cyan">biasanya</span>` : ''}${o.late ? html`<span class="tag amber">telat</span>` : ''}</span>
      <span class="mono">tiba ${hm(o.arrive)}</span></div>
    <div class="stack" aria-hidden="true">${segs.filter(Boolean).map(([c, f]) => html`<i style="flex:${f};background:var(--${c})"></i>`)}</div>
    <span class="small">${dir === 'out' ? (o.ride ? `GoRide ${hm(o.leave)} → ` : `berangkat ${hm(o.leave)} → `) : `jalan ${hm(o.leave)} → `}${o.route}${o.change ? ` (tiba ${hm(o.change.arr)}, lanjut ${hm(o.change.dep)})` : ''}</span>
    <span class="small">±${rupiah(o.cost, true)} · ${o.minutes} menit${o.ride && dir === 'back' ? ` · GoRide dipesan ${hm(o.ride.order_at)}` : ''}</span>
    <button class="btn ${sel ? 'primary' : ''} block" data-act="choose" data-i="${i}">${dir === 'out' && o.ride ? `Pakai & pesankan GoRide ${hm(o.leave)}` : 'Pakai rencana ini'}</button></div>`;
}

export default {
  tab: 'beranda',
  feature: false,
  async render(root, route) {
    state.dir = route.name === 'pulang' ? 'back' : 'out';
    post('/api/v1/app/opened', { feature: route.name }).catch(() => {});
    const title = state.dir === 'out' ? 'Berangkat' : 'Pulang';
    root.innerHTML = String(html`${header(title)}<div class="scr">${loading()}</div>`);
    const d = await get(`/api/v1/app/commute/${state.dir}`);
    if (d.active) return go('#/perjalanan');
    const s = d.settings;
    if (!s.home_station || !s.office_station) {
      root.innerHTML = String(html`${header(title)}<div class="scr">${stationPicker(s)}</div>`);
      const dl = $('#stlist', root);
      get('/api/v1/app/commute/stations').then((r) => { dl.innerHTML = r.stations.map((x) => `<option value="${x.name}">`).join(''); });
      return;
    }
    let t = d.latest;
    if (!t) {
      root.innerHTML = String(html`${header(title)}<div class="scr">${loading()}<p class="small" style="text-align:center">Menyusun rencana dari jadwal KRL…</p></div>`);
      try { t = { plan: await post(`/api/v1/app/commute/${state.dir}/plan`), id: null }; t.id = t.plan.trip_id; } catch (e) { root.innerHTML = String(html`${header(title)}<div class="scr"><div class="card red"><p>${e.message}</p><button class="btn" data-act="replan">Coba lagi</button></div>${stationPicker(s)}</div>`); return; }
    }
    state.trip = t;
    const p = t.plan;
    const music = state.dir === 'out' ? await get('/api/v1/app/music').catch(() => null) : null;
    const w = p.weather;
    root.innerHTML = String(html`${header(title, { sub: `${p.from.name} → ${p.to.name} · disusun ${hm(p.made_at.slice(11, 16))}`, right: html`<button class="ib box" data-act="replan" aria-label="Susun ulang">${icon('repeat', 18)}</button>` })}
      <div class="scr">
        <span class="ctx">${icon('clock', 13)} ${state.dir === 'out' ? `Target tiba di kantor sebelum ${hm(s.arrive_before)}` : `Pulang setelah ${hm(s.leave_after)}`}${w ? ` · ${w.temp}°C ${w.text}${p.rain_note ? ` · ${p.rain_note}` : ''}` : ''}</span>
        ${(p.errands || []).length ? html`<div class="card amber"><span class="k amber">Titipan pulang</span>${p.errands.map((x) => html`<span class="sub">• ${x}</span>`)}<span class="small">Masuk ke langkah perjalananmu.</span></div>` : ''}
        ${state.dir === 'out' && music ? html`<div class="card violet"><div class="row sb"><span class="k violet">${icon('music', 14)} Musik pagi</span>${music.now ? html`<span class="small">${music.now.title}${music.now.playlist ? ` · ${music.now.playlist.index + 1}/${music.now.playlist.total}` : ''}</span>` : ''}</div>
          <div class="chips">${Object.keys(music.moods).map((m) => html`<button class="chip ${m === music.usual.mood ? 'on' : ''}" data-act="mood" data-m="${m}">${m}</button>`)}</div></div>` : ''}
        ${p.no_places?.length ? html`<div class="card amber"><span class="small">Tempat ${p.no_places.join(' & ')} belum diketahui — waktu naik GoRide masih perkiraan. Tandai di Kontrol.</span></div>` : ''}
        ${p.options.length ? p.options.map((o, i) => optionCard(o, i, p.best, state.dir)) : html`<div class="card"><p>Tidak ada KRL yang cocok dari jam ini.</p></div>`}
        <div class="card"><div class="row sb"><div><div class="ttl">${state.dir === 'out' ? 'GoCar langsung ke kantor' : 'GoCar langsung ke rumah'}</div><div class="small">±${rupiah(p.car.cost, true)} · ${p.car.note}</div></div>
          <span class="mono">${hm(p.car.arrive)}</span></div><button class="btn block" data-act="choose" data-i="-1">Pesan GoCar</button></div>
        ${p.rain_note ? html`<span class="small t-amber2">${icon('rain', 14)} ${p.rain_note} Bawa jas hujan.</span>` : ''}
        <p class="small" style="padding:0 4px">Dari jadwal KRL resmi (Comuline). GoRide dipesan di HP-mu lewat aplikasi Gojek — kamu tetap yang mengisi PIN bila diminta.</p>
      </div>`);
  },
  actions: {
    async mood(b) { toast(`Memutar musik ${b.dataset.m}…`); await post('/api/v1/app/music/play', { mood: b.dataset.m }); },
    async choose(b) {
      await post(`/api/v1/app/commute/trip/${state.trip.id}/choose`, { index: Number(b.dataset.i) });
      toast('Rencana dipakai. JARVIS mengingatkan & memesan di waktunya.');
      go('#/perjalanan');
    },
    async replan() { await post(`/api/v1/app/commute/${state.dir}/plan`); render(); },
    async savest(b) {
      const root = b.closest('.scr');
      await put('/api/v1/app/settings/commute', { home_station: $('#hs', root).value.trim(), office_station: $('#os', root).value.trim(),
        walk_min: Number($('#wm', root).value) || 6, arrive_before: $('#ab', root).value || '09:00' });
      toast('Disimpan.'); render();
    },
  },
};
