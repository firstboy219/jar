// Kontrol (mockup 8): health of every service, the AI budget, the brains, the owner's places — and every older setting, searchable.
import { get, header, html, icon, loading, put, render, sheet, toast, host, del } from '../core.js';
import { usd } from '../lib.js';

// the older settings screens: still the phone's own screens (opened through the app), grouped like the mockup
const SETTINGS = [
  ['Otak & model AI', 'cpu', 'violet', [['composition', 'Komposisi AI per kategori'], ['model-stats', 'Statistik model'], ['jarvis-voice', 'Suara JARVIS & model dengar']]],
  ['Pengaman & izin', 'shield', 'green', [['server', 'Kunci API, anggaran, jam tenang, password admin'], ['passwords', 'Password tersimpan'], ['devices', 'Token perangkat']]],
  ['HP & perangkat', 'lock', 'cyan', [['phone', 'Setelan HP (siaga, aksesibilitas)'], ['voice', 'Suaraku (voiceprint)'], ['update', 'Pembaruan aplikasi'], ['app', 'Pengaturan aplikasi']]],
  ['Jejak & kualitas', 'chart', 'amber', [['audit', 'Audit tindakan'], ['flow', 'Pengawas alur'], ['background', 'Di balik layar'], ['dashboard', 'Dasbor server'], ['studio', 'Hermes Studio'], ['notifications', 'Notifikasi diteruskan']]],
];

export default {
  tab: 'kontrol',
  async render(root) {
    root.innerHTML = String(html`${header('Kontrol')}<div class="scr">${loading()}</div>`);
    const d = await get('/api/v1/app/control');
    const bad = d.health.filter((h) => !h.ok);
    const b = d.budget;
    const cats = Object.entries(b.categories || {}).filter(([, v]) => v.spent_usd > 0).sort((x, y) => y[1].spent_usd - x[1].spent_usd).slice(0, 4);
    root.querySelector('.scr').innerHTML = String(html`
      <label class="cmd" style="height:46px">${icon('search', 18, 'var(--mu)')}<input id="sq" placeholder="Cari pengaturan: suara, anggaran, password…" style="margin-left:10px"></label>
      <div class="card"><div class="row sb"><span class="k muted">Kesehatan</span><span class="small" style="color:var(--${bad.length ? 'amber' : 'green'})">${d.health.length - bad.length} dari ${d.health.length} normal</span></div>
        <div class="g2" style="gap:8px">${d.health.map((h) => html`<span class="row" style="gap:8px;font-size:13px" title="${h.detail || ''}"><span class="dot ${h.ok ? 'green' : 'amber'}"></span>${h.name}</span>`)}
          <span class="row" style="gap:8px;font-size:13px"><span class="dot ${d.phone_online ? 'green' : 'amber'}"></span>HP ${d.phone_online ? 'terhubung' : 'tidak terhubung'}</span></div>
        ${bad.length ? html`<p class="small" style="margin:0">${bad.map((h) => `${h.name}: ${h.detail || 'bermasalah'}`).join(' · ')}</p>` : ''}</div>
      <div class="card"><div class="row sb"><span class="k muted">Anggaran AI · ${b.month}</span><span class="mono" style="font-size:13px">${usd(b.spent_usd)} <span class="muted">/ ${usd(b.budget_usd)}</span></span></div>
        <div class="bar"><i class="${b.pct > 80 ? 'amber' : ''}" style="width:${Math.min(100, b.pct)}%"></i></div>
        <div class="row wrap" style="gap:12px;font-size:11px;color:var(--tx2)">${cats.map(([k, v]) => html`<span>${k} ${usd(v.spent_usd)}</span>`)}<span>hari ini ${usd(b.today_usd)}</span></div></div>
      <div class="card"><div class="row sb"><span class="k muted">Alur master · 7 hari</span><a class="small t-cyan" href="#/alur">Alur langsung →</a></div>
        <div class="g4">${['skill', 'ringan', 'berat', 'hermes'].map((l) => html`<div class="kpi" style="padding:8px"><b style="font-size:15px">${d.flow.lanes[l]?.runs || 0}</b><span>${{ skill: 'tanpa AI', ringan: 'ringan', berat: 'berat', hermes: 'Hermes+alat' }[l]}</span></div>`)}</div>
        <span class="small">Berhasil ${d.flow.ok_pct ?? '–'}% · biaya ${usd(d.flow.cost)} · jalur ringan ${d.lanes.light_on ? 'aktif' : 'mati'} · OpenJarvis ${d.lanes.openjarvis_on ? 'aktif' : 'mati'}</span></div>
      <div class="card"><div class="row sb"><span class="k muted">Tempatmu</span><span class="small">${d.here.place ? `sekarang di ${d.here.place}` : 'lokasi belum diketahui'}</span></div>
        ${d.places.length ? html`<div class="list" style="background:transparent">${d.places.map((p) => html`<div class="li" style="padding:8px 0"><div class="grow"><div class="ttl">${p.name}</div><div class="small">${p.label || `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`} · ${p.source === 'owner' ? 'diatur kamu' : 'dipelajari'} · ${p.radius_m} m</div></div><button class="ib" data-act="delplace" data-n="${p.name}" aria-label="Hapus">${icon('close', 16)}</button></div>`)}</div>` : html`<p class="small" style="margin:0">Belum ada. JARVIS mempelajari rumah &amp; kantor dari lokasi HP (izinkan lokasi di aplikasi), atau tandai sekarang.</p>`}
        <div class="btns"><button class="btn sm" data-act="here" data-n="rumah">Tandai di sini: rumah</button><button class="btn sm" data-act="here" data-n="kantor">Tandai di sini: kantor</button></div></div>
      <div id="sets">${SETTINGS.map(([title, ic, tone, items]) => html`<div class="list" style="margin-bottom:10px"><div class="li"><span class="ico ${tone}">${icon(ic, 18)}</span><div class="grow"><div class="ttl">${title}</div></div></div>
        ${items.map(([id, label]) => html`<a class="li click set" href="#" data-act="console" data-id="${id}"><div class="grow small" style="color:var(--tx)">${label}</div>${icon('right', 16)}</a>`)}</div>`)}</div>`);
    root.querySelector('#sq').addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase();
      for (const a of root.querySelectorAll('.set')) a.hidden = q && !a.textContent.toLowerCase().includes(q);
    });
  },
  actions: {
    console(b) {
      if (host.has('open')) return host.call('open', `console:${b.dataset.id}`);
      toast('Pengaturan ini dibuka dari aplikasi JARVIS di HP (Kontrol → item ini).');
    },
    async delplace(b) { await del(`/api/v1/app/places/${encodeURIComponent(b.dataset.n)}`); toast('Tempat dihapus.'); render(); },
    async here(b) {
      const pos = await new Promise((res, rej) => {
        const fromHost = host.call('location');
        if (fromHost) { try { return res(JSON.parse(fromHost)); } catch { /* fall through */ } }
        if (!navigator.geolocation) return rej(new Error('lokasi tidak tersedia'));
        navigator.geolocation.getCurrentPosition((p) => res({ lat: p.coords.latitude, lon: p.coords.longitude }), () => rej(new Error('izin lokasi ditolak')), { timeout: 15000 });
      });
      const ok = await sheet(String(html`<span class="k cyan">Tandai tempat</span><p>Simpan lokasimu sekarang sebagai <b>${b.dataset.n}</b>?</p><div class="btns"><button class="btn" data-close="">Batal</button><button class="btn primary" data-close="ya">Simpan</button></div>`));
      if (ok !== 'ya') return;
      await put(`/api/v1/app/places/${b.dataset.n}`, { lat: pos.lat, lon: pos.lon, radius_m: 200 });
      toast(`Disimpan sebagai ${b.dataset.n}.`); render();
    },
  },
};
