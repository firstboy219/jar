// Gaji & pengeluaran (mockup 38): this pay period — spent against the salary, each pot of his allocation (80% warning), spending per
// category, the latest transactions (recorded from GoPay/bank notifications; category fixable) — and next period's proposed allocation.
import { $, del, get, header, html, icon, loading, on, post, put, render, sheet, toast } from '../core.js';
import { rupiah } from '../lib.js';
import { laneChip } from '../ui.js';

let cur = null;
const d = (s) => new Date(`${String(s).slice(0, 10)}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });
const SRC = { notif: 'notifikasi', manual: 'manual', jarvis: 'JARVIS', email: 'struk email' };

function setup(s) {
  return html`<form class="card cyan" id="setf"><span class="k cyan">Atur gaji</span>
    <div class="g2"><label class="field">Gaji bersih per bulan<input name="salary" type="number" min="0" step="50000" value="${s.salary || ''}" required></label>
      <label class="field">Tanggal gajian<input name="payday" type="number" min="1" max="31" value="${s.payday}" required></label></div>
    <label class="field">Tujuan keuangan (opsional)<input name="goals" value="${s.goals}" placeholder="mis. dana darurat 6× gaji, DP rumah 2028"></label>
    <div class="g2"><label class="field">Dana darurat sekarang<input name="emergency_saved" type="number" min="0" step="100000" value="${s.emergency_saved || 0}"></label>
      <label class="field">Target (× pengeluaran bulanan)<input name="emergency_months" type="number" min="1" max="24" value="${s.emergency_months}"></label></div>
    <button class="btn primary" data-act="savesettings">Simpan</button>
    <span class="small">Pengeluaran dicatat otomatis dari notifikasi GoPay & bank di HP (izin baca notifikasi). Notifikasi berisi OTP/PIN tidak pernah dibaca.</span></form>`;
}

function plan(p) {
  return html`<div class="card violet"><div class="row sb"><span class="k violet">Usulan alokasi · mulai ${d(p.period_start)}</span>${laneChip(p.lane)}</div>
    <p class="sub">${p.ringkasan}</p>
    ${p.pos.map((x, i) => html`<div class="row sb" style="gap:8px"><span style="font-size:14px" class="grow">${x.name}<br><span class="small">${x.alasan}</span>${x.last ? html`<br><span class="small">periode lalu terpakai ${rupiah(x.last, true)}</span>` : ''}</span>
      <input class="inp mono" style="width:130px;height:38px;text-align:right" data-pot="${i}" type="number" min="0" step="50000" value="${x.amount}"></div>`)}
    <div class="row sb"><span class="small">Total</span><span class="mono">${rupiah(p.total)} / ${rupiah(p.salary)}</span></div>
    ${(p.hemat || []).map((h) => html`<span class="small">• ${h}</span>`)}
    ${p.catatan ? html`<span class="small t-amber2">${p.catatan}</span>` : ''}
    <button class="btn primary" data-act="apply" data-id="${p.id}">Pakai alokasi ini</button></div>`;
}

function emergency(e) {
  if (!e || !e.target) return '';
  return html`<div class="card ${e.pct >= 100 ? 'green' : 'cyan'}"><div class="row sb"><span class="k ${e.pct >= 100 ? 'green' : 'cyan'}">Dana darurat</span><span class="mono" style="font-size:13px">${rupiah(e.saved, true)} / ${rupiah(e.target, true)}</span></div>
    <div class="bar"><i class="${e.pct >= 100 ? 'green' : ''}" style="width:${e.pct}%"></i></div>
    <span class="small">cukup untuk ${String(e.covers_months).replace('.', ',')} bulan (target ${e.months}× ≈ ${rupiah(e.monthly, true)}/bulan). Transfer berkategori "tabungan" ikut terhitung.</span></div>`;
}

export default {
  tab: 'beranda',
  feature: 'gaji',
  async render(root) {
    root.innerHTML = String(html`${header('Gaji & pengeluaran')}<div class="scr">${loading()}</div>`);
    const s = cur = await get('/api/v1/app/money');
    const pr = s.period;
    if (!s.salary) { root.innerHTML = String(html`${header('Gaji & pengeluaran')}<div class="scr">${setup(s.settings)}</div>`); return; }
    const pct = Math.min(100, Math.round((s.spent / s.salary) * 100));
    const cats = Object.entries(s.by_category);
    root.innerHTML = String(html`${header('Gaji & pengeluaran', { sub: `${d(pr.start)} – ${d(pr.end)} · ${pr.left_days} hari ke gajian`,
      right: html`<button class="ib box" data-act="add" aria-label="Tambah transaksi">${icon('plus', 18)}</button>` })}
      <div class="scr">
        ${s.plan ? plan(s.plan) : ''}
        <div class="card"><div class="row sb"><span class="k">Terpakai</span><span class="mono">${rupiah(s.spent, true)} / ${rupiah(s.salary, true)}</span></div>
          <div class="bar" style="height:10px"><i class="${pct > 90 ? 'amber' : ''}" style="width:${pct}%"></i></div>
          <div class="row sb small"><span>sisa ${rupiah(s.left, true)}</span><span>laju: ${rupiah(s.pace, true)} sampai gajian${s.pace > s.salary ? ' — melebihi gaji' : ''}</span></div></div>
        ${emergency(s.emergency)}
        ${s.pots.length ? html`<span class="sec">Pos anggaran</span>${s.pots.map((p) => html`<div class="card ${p.level === 'over' ? 'red' : p.level === 'warn' ? 'amber' : ''}">
          <div class="row sb"><span class="ttl">${p.name}</span><span class="mono" style="font-size:13px">${rupiah(p.spent, true)}${p.amount ? ` / ${rupiah(p.amount, true)}` : ''}</span></div>
          ${p.amount ? html`<div class="bar"><i class="${p.level === 'ok' ? 'green' : 'amber'}" style="width:${Math.min(100, p.pct)}%"></i></div><span class="small">${p.pct}% · ${p.categories.join(', ')}${p.last ? ` · periode lalu ${rupiah(p.last, true)}` : ''}</span>` : html`<span class="small">${p.unplanned ? 'pengeluaran yang belum masuk pos mana pun' : ''}</span>`}</div>`)}`
          : html`<div class="card"><p class="sub">Belum ada pos anggaran. Minta JARVIS menyusun alokasi dari pengeluaranmu.</p></div>`}
        ${!s.plan ? html`<button class="btn block" data-act="plan">${icon('bolt', 16)} Susun alokasi gaji (otak berat)</button>` : ''}
        ${cats.length ? html`<div class="card"><span class="k">Per kategori</span>${cats.map(([k, v]) => html`<div class="row" style="font-size:13px"><span style="width:110px;color:var(--tx2)">${k}</span>
          <div class="bar grow" style="height:8px"><i style="width:${Math.round(100 * v / cats[0][1])}%"></i></div><span class="mono" style="min-width:70px;text-align:right">${rupiah(v, true)}</span></div>`)}</div>` : ''}
        <span class="sec">Transaksi</span>
        ${s.recent.length ? html`<div class="list">${s.recent.map((t) => html`<div class="li"><div class="grow"><div class="row sb"><span style="font-size:14px">${t.merchant}</span>
          <span class="mono" style="color:var(--${t.direction === 'in' ? 'green' : 'tx'})">${t.direction === 'in' ? '+' : '−'}${rupiah(t.amount)}</span></div>
          <div class="row sb small"><span>${new Date(t.at).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })} · ${t.app || SRC[t.source]}</span>
          <button class="chip" style="height:26px;font-size:12px" data-act="cat" data-id="${t.id}" data-c="${t.category}">${t.category}${t.labeled_by === 'ai' ? ' · AI' : ''}</button></div></div></div>`)}</div>`
          : html`<div class="card"><span class="small">Belum ada transaksi periode ini.</span></div>`}
        <details class="card"><summary class="small">Pengaturan gaji</summary>${setup(s.settings)}</details>
      </div>`);
    return on('notify', (e) => { if (e.route === '#/gaji') render(); });
  },
  actions: {
    async savesettings() {
      const f = $('#setf'); if (!f.reportValidity()) return;
      const v = Object.fromEntries(new FormData(f).entries());
      const em = Number(v.emergency_saved || 0);
      await put('/api/v1/app/settings/money', { salary: Number(v.salary), payday: Number(v.payday), goals: v.goals || '', emergency_months: Number(v.emergency_months || 6),
        ...(em !== Number(cur?.settings?.emergency_saved || 0) ? { emergency_saved: em, emergency_at: new Date().toISOString().slice(0, 10) } : {}) });
      toast('Tersimpan'); render();
    },
    async plan() { toast('Otak berat menyusun alokasi…'); await post('/api/v1/app/money/plan'); render(); },
    async apply(b) {
      const pots = cur.plan.pos.map((p, i) => ({ ...p, amount: Number(document.querySelector(`[data-pot="${i}"]`)?.value || p.amount) }));
      await post(`/api/v1/app/money/plan/${b.dataset.id}/apply`, { pots });
      toast('Alokasi dipakai untuk periode ini'); render();
    },
    async cat(b) {
      const v = await sheet(String(html`<span class="ttl">Kategori</span><div class="chips" style="flex-wrap:wrap">${cur.categories.map((c) => html`<button class="chip ${c === b.dataset.c ? 'on' : ''}" data-close="${c}">${c}</button>`)}</div>
        <button class="btn danger sm" data-close="__del">Hapus transaksi</button>`));
      if (!v) return;
      if (v === '__del') await del(`/api/v1/app/money/tx/${b.dataset.id}`); else await put(`/api/v1/app/money/tx/${b.dataset.id}`, { category: v });
      render();
    },
    async add() {
      const v = await sheet(String(html`<form><span class="ttl">Tambah transaksi</span>
        <label class="field">Nominal<input name="amount" type="number" min="1" required></label><label class="field">Untuk / dari<input name="merchant" required maxlength="60"></label>
        <label class="field">Jenis<select name="direction"><option value="out">Pengeluaran</option><option value="in">Pemasukan</option></select></label>
        <label class="field">Kategori<select name="category"><option value="">otomatis</option>${cur.categories.map((c) => html`<option>${c}</option>`)}</select></label>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Simpan</button></div></form>`));
      if (!v?.amount) return;
      await post('/api/v1/app/money/tx', { amount: Number(v.amount), merchant: v.merchant, direction: v.direction, category: v.category });
      render();
    },
  },
};
