// Tren & strategi (mockup 34): months of a number (sales by default) — per month, per weekday, the 7-day line, last 30 days against the
// 30 before — and the heavy brain's strategy from those numbers: what is happening, what to do this week, how to measure it.
import { get, header, html, icon, loading, post, render, speak, toast } from '../core.js';
import { rupiah } from '../lib.js';
import { columns, laneChip } from '../ui.js';
import { val } from './bisnis.js';

let st = { b: '', m: 'penjualan', days: 120 }, cur = null;
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const WD = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];
const LABEL = { penjualan: 'Penjualan', pesanan: 'Pesanan', dikemas: 'Dikemas', dikirim: 'Dikirim', pencairan: 'Pencairan', retur: 'Retur', mrr: 'MRR', gmv: 'GMV', pelanggan: 'Pelanggan', toko_aktif: 'Toko aktif' };

function line(daily, unit) {
  const pts = daily.map((d) => d.ma7);
  const max = Math.max(1, ...pts), min = Math.min(...pts), span = Math.max(1, max - min), w = 330, h = 110;
  const xy = pts.map((v, i) => `${(i / Math.max(1, pts.length - 1)) * w},${h - ((v - min) / span) * (h - 12) - 6}`).join(' ');
  return html`<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:120px" role="img" aria-label="rata-rata 7 hari"><polyline points="${xy}" fill="none" stroke="var(--cyan)" stroke-width="2"/></svg>
    <div class="row sb small"><span>${daily[0]?.day.slice(5)}</span><span>rata-rata 7 hari · ${val(min, unit)}–${val(max, unit)}</span><span>${daily[daily.length - 1]?.day.slice(5)}</span></div>`;
}

export default {
  tab: 'beranda',
  feature: 'tren',
  async render(root, route) {
    if (route.query.b) st.b = route.query.b;
    root.innerHTML = String(html`${header('Tren & strategi')}<div class="scr">${loading()}</div>`);
    if (!st.b) { const d = await get('/api/v1/app/bisnis'); st.b = d.businesses[0]?.name || ''; }
    if (!st.b) { root.innerHTML = String(html`${header('Tren & strategi')}<div class="scr"><div class="card"><p>Belum ada bisnis tersambung.</p><a class="btn primary" href="#/sumber">Tambah sumber API</a></div></div>`); return; }
    const d = await get(`/api/v1/app/bisnis/trend?business=${encodeURIComponent(st.b)}&metric=${encodeURIComponent(st.m)}&days=${st.days}`);
    const t = d.trend, s = cur = d.strategy, u = d.unit;
    const months = Object.entries(t.months);
    const base = d.metrics.filter((m) => !m.includes('@'));
    root.innerHTML = String(html`${header('Tren & strategi', { sub: st.b })}
      <div class="scr">
        <div class="chips">${base.map((m) => html`<button class="chip ${m === st.m ? 'on' : ''}" data-act="metric" data-m="${m}">${LABEL[m] || m.replace(/_/g, ' ')}</button>`)}</div>
        ${t.days_with_data < 7 ? html`<div class="card amber"><span class="small">Baru ${t.days_with_data} hari data. Tren lebih bermakna setelah beberapa minggu — atau isi riwayat dari Sumber API (endpoint mode "series").</span></div>` : ''}
        <div class="g2"><div class="kpi"><span>30 hari terakhir</span><b>${val(t.last30, u)}</b><span style="color:var(--${(t.change30 ?? 0) >= 0 ? 'green' : 'amber'}-t)">${t.change30 == null ? '—' : `${t.change30 >= 0 ? '▲' : '▼'} ${String(Math.abs(t.change30)).replace('.', ',')}% vs 30 hari sebelumnya`}</span></div>
          <div class="kpi"><span>Arah 4 minggu</span><b>${t.direction == null ? '—' : `${t.direction >= 0 ? '+' : ''}${String(t.direction).replace('.', ',')}%`}</b><span>${t.best_weekday != null ? `hari terbaik: ${WD[t.best_weekday]}` : ''}</span></div></div>
        ${months.length ? html`<div class="card"><span class="k">Per bulan · ${d.label}</span>${columns(months.map(([k]) => MON[Number(k.slice(5)) - 1]), months.map(([, v]) => (u === 'rp' ? Math.round(v / 1e6 * 10) / 10 : v)))}
          ${u === 'rp' ? html`<span class="small">dalam juta rupiah · bulan ini masih berjalan</span>` : ''}</div>` : ''}
        ${t.daily.length ? html`<div class="card"><span class="k">90 hari</span>${line(t.daily, u)}</div>` : ''}
        ${Object.keys(t.per_weekday).length ? html`<div class="card"><span class="k">Rata-rata per hari (8 minggu)</span>${columns(WD, WD.map((_, i) => (u === 'rp' ? Math.round((t.per_weekday[i] || 0) / 1e3) : t.per_weekday[i] || 0)), '', false)}
          ${u === 'rp' ? html`<span class="small">dalam ribu rupiah</span>` : ''}</div>` : ''}
        ${d.channels.length ? html`<div class="chips">${d.channels.map((c) => html`<button class="chip" data-act="metric" data-m="${c}">${c.split('@')[1]}</button>`)}</div>` : ''}
        <div class="card violet"><div class="row sb"><span class="k violet">Strategi</span>${s ? html`<span class="small">${new Date(s.created_at).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })} ${laneChip(s.lane)}</span>` : ''}</div>
          ${s ? html`<p class="sub">${s.ringkasan}</p>
            ${(s.minggu_ini || []).length ? html`<span class="ttl">Minggu ini</span>${s.minggu_ini.map((x) => html`<span class="small">• ${x}</span>`)}` : ''}
            ${(s.strategi || []).map((x) => html`<details class="card" style="background:var(--bg)"><summary class="ttl" style="cursor:pointer">${x.judul} <span class="tag ${x.usaha === 'rendah' ? 'green' : x.usaha === 'tinggi' ? 'red' : 'amber'}">usaha ${x.usaha || '?'}</span></summary>
              <span class="small">${x.kenapa}</span>${(x.langkah || []).map((l, i) => html`<span class="sub">${i + 1}. ${l}</span>`)}<span class="small">Dampak: ${x.dampak} · Ukur: ${x.ukur}</span></details>`)}
            ${(s.risiko || []).length ? html`<span class="small t-amber2">Risiko: ${s.risiko.join('; ')}</span>` : ''}`
          : html`<p class="sub">Belum ada strategi. Otak berat menyusunnya dari angka 4 bulan (otomatis tiap Senin pagi).</p>`}
          ${s ? html`<div class="btns"><button class="btn" data-act="read">${icon('speaker', 16)} Bacakan</button>${(s.minggu_ini || []).length ? html`<button class="btn" data-act="tasks">${icon('list', 16)} Jadikan tugas</button>` : ''}</div>` : ''}
          <button class="btn primary" data-act="strategy">${icon('bolt', 16)} ${s ? 'Susun ulang' : 'Susun strategi'} (otak berat)</button></div>
      </div>`);
  },
  actions: {
    metric(b) { st.m = b.dataset.m; render(); },
    read() { speak([`Strategi ${st.b}.`, cur.ringkasan, ...(cur.minggu_ini || []).length ? ['Minggu ini:', ...cur.minggu_ini] : []].join(' ')); },
    async tasks() { const r = await post('/api/v1/app/bisnis/strategy/tasks', { business: st.b }); toast(r.tasks.length ? `${r.tasks.length} tugas masuk Catatan` : 'Sudah ada di Catatan'); },
    async strategy() { toast('Otak berat menganalisa… (±1 menit)'); await post('/api/v1/app/bisnis/strategy', { business: st.b }); render(); },
  },
};
