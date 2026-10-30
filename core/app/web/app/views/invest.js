// Investasi (mockup 39): what JARVIS read from Pluang (total, cash, each asset, the mix against his targets), the heavy brain's view of the
// market, three options (one is always "hold") — his pick, with the admin password, is carried out in Pluang by JARVIS (he types the PIN).
import { $, discuss, get, header, html, icon, loading, on, post, put, render, toast } from '../core.js';
import { withPassword } from '../needsui.js';
import { rupiah } from '../lib.js';
import { laneChip } from '../ui.js';

function trend(hist) {
  const v = hist.map((h) => Number(h.total) || 0).filter(Boolean);
  if (v.length < 2) return '';
  const lo = Math.min(...v), hi = Math.max(...v), w = 300, h = 60;
  const pts = v.map((x, i) => `${Math.round((i / (v.length - 1)) * w)},${Math.round(h - 4 - ((x - lo) / (hi - lo || 1)) * (h - 8))}`).join(' ');
  const up = v.at(-1) >= v[0];
  return html`<div class="card"><div class="row sb"><span class="k">Nilai portofolio</span><span class="small" style="color:var(--${up ? 'green' : 'red'}-t)">${up ? '+' : ''}${String(Math.round(((v.at(-1) - v[0]) / v[0]) * 1000) / 10).replace('.', ',')}% · ${v.length} bacaan</span></div>
    <svg viewBox="0 0 ${w} ${h}" style="width:100%;height:60px" role="img" aria-label="Nilai portofolio dari ${rupiah(v[0], true)} ke ${rupiah(v.at(-1), true)}"><polyline points="${pts}" fill="none" stroke="var(--${up ? 'green' : 'red'})" stroke-width="2" stroke-linejoin="round"/></svg>
    <div class="row sb small"><span>${rupiah(v[0], true)}</span><span>${rupiah(v.at(-1), true)}</span></div></div>`;
}

function settingsForm(st) {
  return html`<details class="card"><summary class="small">Pengaturan investasi</summary><form id="invf" style="display:flex;flex-direction:column;gap:8px">
    <span class="small">Target komposisi (%)</span>
    <div class="g2">${Object.keys(KIND).map((k) => html`<label class="field">${KIND[k]}<input name="t_${k}" type="number" min="0" max="100" value="${st.targets?.[k] ?? ''}"></label>`)}</div>
    <div class="g2"><label class="field">Batas per opsi (Rp)<input name="limit" type="number" min="0" step="100000" value="${st.limit}"></label>
      <label class="field">Batal bila harga bergeser > (%)<input name="price_guard_pct" type="number" min="0.1" max="10" step="0.1" value="${st.price_guard_pct}"></label></div>
    <div class="g2"><label class="field">Profil risiko<select name="risk">${['rendah', 'sedang', 'tinggi'].map((r) => html`<option ${st.risk === r ? 'selected' : ''}>${r}</option>`)}</select></label>
      <label class="field">Cek tiap<select name="check_day">${['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'].map((d, i) => html`<option value="${d}" ${st.check_day === d ? 'selected' : ''}>${['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'][i]}</option>`)}</select></label></div>
    <div class="g2"><label class="field">Jam<input name="check_at" type="time" value="${st.check_at}"></label><label class="field">Tujuan<input name="goal" value="${st.goal}" placeholder="mis. dana pendidikan 2035"></label></div>
    <button class="btn" data-act="saveSettings">Simpan</button><span class="small">${icon('lock', 12)} Menaikkan batas atau melonggarkan pengaman harga butuh password admin.</span></form></details>`;
}

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
        ${trend(s.history || [])}
        ${s.budget ? html`<div class="card ${s.budget.left ? '' : 'amber'}"><div class="row sb"><span class="k">Anggaran investasi (Gaji · ${s.budget.pot})</span><span class="mono" style="font-size:13px">${rupiah(s.budget.spent, true)} / ${rupiah(s.budget.amount, true)}</span></div>
          <div class="bar"><i class="${s.budget.left ? 'green' : 'amber'}" style="width:${Math.min(100, Math.round((100 * s.budget.spent) / (s.budget.amount || 1)))}%"></i></div><span class="small">sisa ${rupiah(s.budget.left, true)} periode ini</span></div>` : ''}
        ${p && p.status === 'new' && p.fresh ? html`<div class="card violet"><div class="row sb"><span class="k violet">Pilihan minggu ini</span>${laneChip(p.data.lane)}</div>
            <p class="sub">${p.data.ringkasan}</p>${(p.data.kondisi || []).map((k) => html`<span class="small">• ${k}</span>`)}</div>
          ${p.data.opsi.map((o) => html`<div class="card ${o.disarankan ? 'green' : ''}"><div class="row sb"><span class="ttl">${o.disarankan ? '★ ' : ''}${o.id}. ${o.judul}</span>${o.aksi.length ? html`<span class="mono small">${rupiah(o.aksi.reduce((t, a) => t + (a.jenis === 'beli' ? a.nominal : 0), 0), true)}</span>` : html`<span class="tag">tanpa transaksi</span>`}</div>
            ${o.aksi.map((a) => html`<span class="small">${a.jenis === 'beli' ? 'Beli' : 'Jual'} ${a.aset} ${rupiah(a.nominal)}</span>`)}
            <span class="sub">${o.alasan}</span>${o.risiko ? html`<span class="small t-amber2">Risiko: ${o.risiko}</span>` : ''}${o.disarankan ? html`<span class="small t-green2">Disarankan JARVIS</span>` : ''}
            <button class="btn ${o.aksi.length ? 'primary' : ''}" data-act="choose" data-o="${o.id}">${o.aksi.length ? `Pilih ${o.id} — JARVIS kerjakan di Pluang` : 'Pilih: tahan dulu'}</button></div>`)}
          <button class="btn" data-act="discuss">${icon('chat', 16)} Diskusi dulu</button>
          <span class="small" style="padding:0 4px">${icon('lock', 12)} Butuh password admin. Batas Rp${(s.settings.limit || 0).toLocaleString('id-ID')} per opsi; dibatalkan bila harga bergeser > ${String(s.settings.price_guard_pct).replace('.', ',')}% dari saat dibaca. PIN Pluang kamu yang ketik.</span>`
          : p ? html`<div class="card ${p.status === 'done' ? 'green' : p.status === 'failed' ? 'red' : ''}"><span class="k">Terakhir: ${{ done: 'selesai', failed: 'gagal', running: 'berjalan', expired: 'kedaluwarsa', new: 'kedaluwarsa' }[p.status] || p.status}</span>
            <span class="small">${p.chosen ? `Pilihan ${p.chosen}` : ''}${p.result?.tahan ? ' · ditahan' : ''}</span>
            ${(p.result?.berhasil || []).map((b) => html`<span class="small">✓ ${b.jenis} ${b.aset} ${rupiah(Number(b.nominal) || 0)}${b.harga ? ` @ ${rupiah(Number(b.harga))}` : ''}</span>`)}
            ${(p.result?.batal || []).map((b) => html`<span class="small">✗ ${b.aset}: ${b.alasan}</span>`)}
            ${(p.result?.peringatan || []).map((w) => html`<span class="small t-amber2">⚠ ${w}</span>`)}${p.result?.catatan ? html`<span class="small">${p.result.catatan}</span>` : ''}</div>` : ''}
        <div class="btns"><button class="btn" data-act="read" ${s.running ? 'disabled' : ''}>${icon('eye', 16)} Baca sekarang</button>${snap ? html`<button class="btn" data-act="analyse">${icon('bolt', 16)} Analisa ulang</button>` : ''}</div>
        ${settingsForm(s.settings)}
      </div>`);
    return on('notify', (e) => { if (e.route === '#/invest') render(); });
  },
  actions: {
    async read() { const r = await post('/api/v1/app/invest/read'); toast(r.task_id ? 'JARVIS membuka Pluang di HP…' : 'Membaca…'); render(); },
    async analyse() { toast('Otak berat menganalisa…'); await post('/api/v1/app/invest/analyse'); render(); },
    async choose(b) {
      const o = cur.proposal.data.opsi.find((x) => x.id === b.dataset.o);
      const what = o.aksi.map((a) => `${a.jenis} ${a.aset} ${rupiah(a.nominal)}`).join(', ');
      const r = await withPassword(`${o.id}. ${o.judul}`, (password) => post(`/api/v1/app/invest/proposal/${cur.proposal.id}/choose`, { option: o.id, password }),
        { kicker: 'Investasi', button: o.aksi.length ? 'Kerjakan di Pluang' : 'Tahan', note: what || 'Tanpa transaksi.' });
      if (!r) return;
      toast(r.hold ? 'Oke, ditahan dulu' : 'JARVIS membuka Pluang — ketik PIN saat diminta'); render();
    },
    discuss() {
      const p = cur.proposal.data;
      discuss(`Soal pilihan investasi minggu ini (${p.ringkasan}) — opsi: ${p.opsi.map((o) => `${o.id}. ${o.judul}`).join('; ')}. Aku mau diskusi dulu sebelum memilih: mana yang paling cocok untukku dan kenapa?`);
    },
    async saveSettings(b, e) {
      e?.preventDefault();
      const v = Object.fromEntries(new FormData($('#invf')).entries());
      const targets = Object.fromEntries(Object.keys(KIND).filter((k) => v[`t_${k}`] !== '').map((k) => [k, Number(v[`t_${k}`])]));
      const body = { targets, limit: Number(v.limit), price_guard_pct: Number(v.price_guard_pct), risk: v.risk, check_day: v.check_day, check_at: v.check_at, goal: v.goal || '' };
      const st = cur.settings;
      if (body.limit > st.limit || body.price_guard_pct > st.price_guard_pct) {
        if (!await withPassword('Longgarkan pengaman investasi', (admin_password) => put('/api/v1/app/settings/invest', { ...body, admin_password }),
          { kicker: 'Pengaturan', button: 'Simpan', note: `Batas ${rupiah(st.limit)} → ${rupiah(body.limit)} · pengaman ${st.price_guard_pct}% → ${body.price_guard_pct}%` })) return;
      } else await put('/api/v1/app/settings/invest', body);
      toast('Tersimpan'); render();
    },
  },
};
