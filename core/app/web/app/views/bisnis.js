// Bisnis hari ini (mockup 33): per business — sales, orders, packed, payouts so far today against the usual for this hour of this weekday,
// sales per marketplace, what needs a look (alerts), and this week's strategy in one line; read from his own APIs every few minutes.
import { $, get, header, html, icon, loading, on, post, put, render, toast } from '../core.js';
import { rupiah } from '../lib.js';

let pick = '';
export const val = (v, unit) => (v == null ? '—' : unit === 'rp' ? rupiah(v, true) : unit === '%' ? `${String(Math.round(v * 10) / 10).replace('.', ',')}%` : Math.round(v).toLocaleString('id-ID'));
const ago = (s) => { if (!s) return 'belum pernah'; const m = Math.round((Date.now() - new Date(s)) / 60000); return m < 1 ? 'baru saja' : m < 60 ? `${m} mnt lalu` : `${Math.round(m / 60)} jam lalu`; };

function kpi(k) {
  const vs = k.vs_usual;
  return html`<div class="kpi"><span>${k.label}</span><b>${val(k.value, k.unit)}</b>
    ${vs != null ? html`<span style="color:var(--${vs >= 0 ? 'green' : 'amber'}-t)">${vs >= 0 ? '▲' : '▼'} ${String(Math.abs(vs)).replace('.', ',')}% vs biasanya jam ini</span>`
      : k.yesterday != null ? html`<span>kemarin ${val(k.yesterday, k.unit)}</span>` : html`<span>&nbsp;</span>`}</div>`;
}

function business(b) {
  const main = b.kpis.filter((k) => MAIN.includes(k.metric));
  const other = b.kpis.filter((k) => !MAIN.includes(k.metric));
  const chMax = Math.max(1, ...b.channels.map((c) => c.value));
  const errs = b.sources.filter((s) => s.last_error);
  return html`
    ${b.alerts.filter((a) => a.tone !== 'green').map((a) => html`<div class="card ${a.tone === 'red' ? 'red' : 'amber'}"><span class="ttl">${a.title}</span><span class="small">${a.text}</span></div>`)}
    ${b.alerts.filter((a) => a.tone === 'green').map((a) => html`<div class="card green"><span class="ttl">🎉 ${a.title}</span><span class="small">${a.text}</span></div>`)}
    ${main.length ? html`<div class="g2">${main.map(kpi)}</div>` : html`<div class="card"><p class="sub">Belum ada angka hari ini dari ${b.name}. ${b.sources.length ? 'Menunggu sinkron berikutnya.' : ''}</p></div>`}
    ${b.packed ? html`<div class="card"><div class="row sb"><span class="k">Dikemas</span><span class="mono">${b.packed.done}/${b.packed.total} · ${b.packed.pct}%</span></div>
      <div class="bar" style="height:8px"><i class="${b.packed.pct >= 80 ? 'green' : 'amber'}" style="width:${b.packed.pct}%"></i></div></div>` : ''}
    ${b.channels.length ? html`<div class="card"><span class="k">Per kanal</span>${b.channels.map((c) => html`<div class="row" style="font-size:13px">
      <span style="width:96px;color:var(--tx2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.name}</span><div class="bar grow" style="height:8px"><i style="width:${Math.round(100 * c.value / chMax)}%"></i></div>
      <span class="mono" style="min-width:64px;text-align:right">${c.metric === 'penjualan' ? rupiah(c.value, true) : Math.round(c.value)}</span></div>`)}</div>` : ''}
    ${(b.payouts || []).length ? html`<div class="card"><span class="k">Pencairan per kanal</span>${b.payouts.map((c) => html`<div class="row sb" style="font-size:13px"><span style="color:var(--tx2)">${c.name}</span><span class="mono">${rupiah(c.value, true)}</span></div>`)}</div>` : ''}
    ${other.length ? html`<div class="g2">${other.map(kpi)}</div>` : ''}
    ${b.strategy ? html`<a class="card violet" href="#/tren?b=${encodeURIComponent(b.name)}" style="text-decoration:none"><span class="k violet">Strategi minggu ini</span><span class="sub">${b.strategy.ringkasan || ''}</span>
      ${(b.strategy.minggu_ini || []).slice(0, 3).map((x) => html`<span class="small">• ${x}</span>`)}</a>` : ''}
    <span class="small" style="padding:0 4px">Sinkron ${ago(b.synced_at)} · ${b.sources.length} sumber${errs.length ? html` · <span class="t-amber2">${errs.length} bermasalah</span>` : ''} · lewat alur master (skill tanpa AI)</span>`;
}

const MAIN = ['penjualan', 'pesanan', 'dikemas', 'pencairan'];

// Every business together: the main numbers added up (same unit), each business in one line with what needs a look.
function all(list) {
  const sum = MAIN.map((m) => {
    const ks = list.map((b) => b.kpis.find((k) => k.metric === m)).filter(Boolean);
    return ks.length ? { metric: m, label: ks[0].label, unit: ks[0].unit, value: ks.reduce((t, k) => t + k.value, 0),
      yesterday: ks.every((k) => k.yesterday != null) ? ks.reduce((t, k) => t + k.yesterday, 0) : null } : null;
  }).filter(Boolean);
  const alerts = list.flatMap((b) => b.alerts.filter((a) => a.tone !== 'green'));
  return html`
    ${alerts.map((a) => html`<div class="card ${a.tone === 'red' ? 'red' : 'amber'}"><span class="ttl">${a.title}</span><span class="small">${a.text}</span></div>`)}
    ${sum.length ? html`<div class="g2">${sum.map(kpi)}</div>` : ''}
    <div class="list">${list.map((b) => { const v = (m) => b.kpis.find((k) => k.metric === m); return html`<button class="li click" data-act="pick" data-b="${b.name}" style="width:100%;text-align:left;background:none;border-left:0;border-right:0;border-top:0">
      <div class="grow"><div class="row sb"><span class="ttl">${b.name}</span><span class="mono">${v('penjualan') ? val(v('penjualan').value, 'rp') : '—'}</span></div>
      <div class="small">${v('pesanan') ? `${Math.round(v('pesanan').value)} pesanan` : ''}${b.packed ? ` · ${b.packed.pct}% dikemas` : ''}${v('pencairan') ? ` · cair ${val(v('pencairan').value, 'rp')}` : ''}${b.alerts.filter((a) => a.tone !== 'green').length ? html` · <span class="t-amber2">${b.alerts.filter((a) => a.tone !== 'green').length} perlu dilihat</span>` : ''}</div></div>${icon('right', 16)}</button>`; })}</div>
    <span class="small" style="padding:0 4px">Gabungan ${list.length} bisnis · ketuk salah satu untuk detailnya</span>`;
}

export default {
  tab: 'beranda',
  feature: 'bisnis',
  async render(root, route) {
    pick = route.query.b || pick;
    root.innerHTML = String(html`${header('Bisnis hari ini')}<div class="scr">${loading()}</div>`);
    const [d, bs] = await Promise.all([get('/api/v1/app/bisnis'), get('/api/v1/app/settings/bisnis')]);
    if (!d.businesses.length) {
      root.innerHTML = String(html`${header('Bisnis hari ini')}<div class="scr"><div class="card cyan"><span class="k cyan">Sambungkan bisnismu</span>
        <p class="sub">Masukkan API Autotoko dan Renature (alamat, kunci API, dan di mana angka penjualan/pesanan/dikemas/pencairan berada). JARVIS membacanya tiap beberapa menit — tanpa AI — dan memberi tahu bila ada yang perlu kamu lihat.</p>
        <a class="btn primary" href="#/sumber">Tambah sumber API</a></div></div>`);
      return;
    }
    const many = d.businesses.length > 1;
    if (!d.businesses.some((b) => b.name === pick) && !(many && pick === '*')) pick = many ? '*' : d.businesses[0].name;
    const b = d.businesses.find((x) => x.name === pick);
    root.innerHTML = String(html`${header('Bisnis hari ini', { sub: new Date().toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long' }),
      right: html`<button class="ib box" data-act="sync" aria-label="Sinkron sekarang">${icon('repeat', 18)}</button>` })}
      <div class="scr">
        ${many ? html`<div class="chips"><button class="chip ${pick === '*' ? 'on' : ''}" data-act="pick" data-b="*">Semua</button>${d.businesses.map((x) => html`<button class="chip ${x.name === pick ? 'on' : ''}" data-act="pick" data-b="${x.name}">${x.name}${x.alerts.length ? html` <span class="dot amber"></span>` : ''}</button>`)}</div>` : ''}
        ${b ? business(b) : all(d.businesses)}
        <details class="card"><summary class="small">Pengaturan peringatan</summary><form id="bsf" style="display:flex;flex-direction:column;gap:8px">
          <label class="row" style="gap:8px;font-size:14px"><input type="checkbox" name="alerts" ${bs.alerts ? 'checked' : ''}> Beri tahu bila ada yang perlu dilihat</label>
          <div class="g2"><label class="field">Batas kirim kurir<input name="cutoff" type="time" value="${bs.cutoff}"></label><label class="field">Ingatkan sebelum (menit)<input name="cutoff_warn_min" type="number" min="10" max="240" value="${bs.cutoff_warn_min}"></label></div>
          <div class="g2"><label class="field">Cek belum dikemas mulai<input name="unpacked_after" type="time" value="${bs.unpacked_after}"></label><label class="field">Tertinggal bila di bawah (%)<input name="behind_pct" type="number" min="10" max="95" value="${bs.behind_pct}"></label></div>
          <button class="btn" data-act="saveAlerts">Simpan</button></form></details>
        <div class="g3"><a class="btn" href="#/tren${b ? `?b=${encodeURIComponent(b.name)}` : ''}">${icon('invest', 16)} Tren</a><a class="btn" href="#/peluang">${icon('bulb', 16)} Peluang</a><a class="btn" href="#/sumber">${icon('code', 16)} Sumber</a></div>
      </div>`);
    return on('bisnis', (e) => { if (!e.business || pick === '*' || e.business === pick) render(); });
  },
  actions: {
    pick(btn) { pick = btn.dataset.b; render(); },
    async saveAlerts(b, e) {
      e?.preventDefault();
      const f = $('#bsf'); const v = Object.fromEntries(new FormData(f).entries());
      await put('/api/v1/app/settings/bisnis', { alerts: !!v.alerts, cutoff: v.cutoff || '', cutoff_warn_min: Number(v.cutoff_warn_min) || 60, unpacked_after: v.unpacked_after || '14:00', behind_pct: Number(v.behind_pct) || 60 });
      toast('Tersimpan');
    },
    async sync() {
      const { sources } = await get('/api/v1/app/bisnis/sources');
      const mine = sources.filter((s) => pick === '*' || s.business === pick);
      toast(`Membaca ${mine.length} sumber…`);
      for (const s of mine) await post(`/api/v1/app/bisnis/sources/${s.id}/sync`);
      render();
    },
  },
};
