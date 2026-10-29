// Investasi (mockup 39): what JARVIS read from Pluang (total, cash, each asset, the mix against his targets), the heavy brain's view of the
// market, three options (one is always "hold") — his pick, with the admin password, is carried out in Pluang by JARVIS (he types the PIN).
import { get, header, html, icon, loading, on, post, render, sheet, toast } from '../core.js';
import { rupiah } from '../lib.js';
import { laneChip } from '../ui.js';

const KIND = { emas: 'Emas', saham_as: 'Saham AS', kripto: 'Kripto', reksa_dana: 'Reksa dana', lainnya: 'Lainnya' };
let cur = null;

export default {
  tab: 'beranda',
  feature: 'invest',
  async render(root) {
    root.innerHTML = String(html`${header('Investasi')}<div class="scr">${loading()}</div>`);
    const s = cur = await get('/api/v1/app/invest');
    const snap = s.snapshot?.data, p = s.proposal;
    root.innerHTML = String(html`${header('Investasi', { sub: s.snapshot ? `Pluang · dibaca ${new Date(s.snapshot.at).toLocaleString('id-ID', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}` : 'Pluang' })}
      <div class="scr">
        ${s.running ? html`<a class="card violet" href="#/misi/${s.running.task_id}" style="text-decoration:none"><div class="row sb"><span class="k violet">${s.running.action === 'eksekusi' ? 'Menjalankan pilihanmu di Pluang' : 'Membaca Pluang di HP'}</span><span class="dot violet live"></span></div>
          <span class="small">Ketuk untuk melihat langsung. ${s.running.action === 'eksekusi' ? 'Ketik PIN-mu sendiri saat diminta.' : 'Tidak ada yang dibeli/dijual.'}</span></a>` : ''}
        ${snap ? html`<div class="card"><div class="row sb"><span class="k">Portofolio</span><span class="mono" style="font-size:20px">${rupiah(snap.total, true)}</span></div>
            <span class="small">kas ${rupiah(snap.kas, true)}</span>
            ${snap.aset.map((a) => html`<div class="row sb"><div><div style="font-size:14px">${a.nama}</div><div class="small">${KIND[a.jenis] || a.jenis}${a.jumlah ? ` · ${Number(a.jumlah).toLocaleString('id-ID', { maximumFractionDigits: 4 })}${a.jenis === 'emas' ? ' g' : ''}` : ''}</div></div>
              <div style="text-align:right"><div class="mono">${rupiah(a.nilai, true)}</div>${a.untung_pct != null ? html`<div class="small" style="color:var(--${a.untung_pct >= 0 ? 'green' : 'red'}-t)">${a.untung_pct >= 0 ? '+' : ''}${String(a.untung_pct).replace('.', ',')}%</div>` : ''}</div></div>`)}</div>
          <div class="card"><span class="k">Komposisi${Object.keys(s.settings.targets || {}).length ? ' vs target' : ''}</span>${Object.entries(s.allocation).map(([k, v]) => html`<div class="row" style="font-size:13px">
            <span style="width:90px;color:var(--tx2)">${KIND[k] || k}</span><div class="bar grow" style="height:8px"><i style="width:${v}%"></i></div><span class="mono" style="min-width:90px;text-align:right">${String(v).replace('.', ',')}%${s.settings.targets?.[k] != null ? ` / ${s.settings.targets[k]}%` : ''}</span></div>`)}</div>`
          : html`<div class="card"><p class="sub">JARVIS belum pernah membaca Pluang. Tiap ${s.settings.check_day} ${s.settings.check_at} ia membukanya di HP-mu dan membaca portofolio (tanpa membeli apa pun), atau tekan Baca sekarang.</p></div>`}
        ${p && p.status === 'new' && p.fresh ? html`<div class="card violet"><div class="row sb"><span class="k violet">Pilihan minggu ini</span>${laneChip(p.data.lane)}</div>
            <p class="sub">${p.data.ringkasan}</p>${(p.data.kondisi || []).map((k) => html`<span class="small">• ${k}</span>`)}</div>
          ${p.data.opsi.map((o) => html`<div class="card"><div class="row sb"><span class="ttl">${o.id}. ${o.judul}</span>${o.aksi.length ? html`<span class="mono small">${rupiah(o.aksi.reduce((t, a) => t + (a.jenis === 'beli' ? a.nominal : 0), 0), true)}</span>` : html`<span class="tag">tanpa transaksi</span>`}</div>
            ${o.aksi.map((a) => html`<span class="small">${a.jenis === 'beli' ? 'Beli' : 'Jual'} ${a.aset} ${rupiah(a.nominal)}</span>`)}
            <span class="sub">${o.alasan}</span>${o.risiko ? html`<span class="small t-amber2">Risiko: ${o.risiko}</span>` : ''}
            <button class="btn ${o.aksi.length ? 'primary' : ''}" data-act="choose" data-o="${o.id}">${o.aksi.length ? `Pilih ${o.id} — JARVIS kerjakan di Pluang` : 'Pilih: tahan dulu'}</button></div>`)}
          <span class="small" style="padding:0 4px">${icon('lock', 12)} Butuh password admin. Batas Rp${(s.settings.limit || 0).toLocaleString('id-ID')} per opsi; dibatalkan bila harga bergeser > ${String(s.settings.price_guard_pct).replace('.', ',')}% dari saat dibaca. PIN Pluang kamu yang ketik.</span>`
          : p ? html`<div class="card ${p.status === 'done' ? 'green' : p.status === 'failed' ? 'red' : ''}"><span class="k">Terakhir: ${{ done: 'selesai', failed: 'gagal', running: 'berjalan', expired: 'kedaluwarsa', new: 'kedaluwarsa' }[p.status] || p.status}</span>
            <span class="small">${p.chosen ? `Pilihan ${p.chosen}` : ''} ${p.result ? JSON.stringify(p.result).slice(0, 200) : ''}</span></div>` : ''}
        <div class="btns"><button class="btn" data-act="read" ${s.running ? 'disabled' : ''}>${icon('eye', 16)} Baca sekarang</button>${snap ? html`<button class="btn" data-act="analyse">${icon('bolt', 16)} Analisa ulang</button>` : ''}</div>
      </div>`);
    return on('notify', (e) => { if (e.route === '#/invest') render(); });
  },
  actions: {
    async read() { const r = await post('/api/v1/app/invest/read'); toast(r.task_id ? 'JARVIS membuka Pluang di HP…' : 'Membaca…'); render(); },
    async analyse() { toast('Otak berat menganalisa…'); await post('/api/v1/app/invest/analyse'); render(); },
    async choose(b) {
      const o = cur.proposal.data.opsi.find((x) => x.id === b.dataset.o);
      const v = await sheet(String(html`<form><span class="ttl">${o.id}. ${o.judul}</span>${o.aksi.map((a) => html`<span class="small">${a.jenis} ${a.aset} ${rupiah(a.nominal)}</span>`)}
        <label class="field">Password admin<input name="password" type="password" required autocomplete="current-password"></label>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">${o.aksi.length ? 'Kerjakan' : 'Tahan'}</button></div></form>`));
      if (!v?.password) return;
      const r = await post(`/api/v1/app/invest/proposal/${cur.proposal.id}/choose`, { option: o.id, password: v.password });
      toast(r.hold ? 'Oke, ditahan dulu' : 'JARVIS membuka Pluang — ketik PIN saat diminta'); render();
    },
  },
};
