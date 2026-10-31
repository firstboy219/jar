// Gaji & pengeluaran (mockup 38): this pay period — spent against the salary, each pot of his allocation (80% warning), spending per
// category, the latest transactions (recorded from GoPay/bank notifications; category fixable) — and next period's proposed allocation.
import { $, del, get, header, html, icon, loading, on, post, put, render, sheet, toast } from '../core.js';
import { pick, upload } from '../upload.js';
import { rupiah } from '../lib.js';
import { laneChip } from '../ui.js';

let cur = null;
const d = (s) => new Date(`${String(s).slice(0, 10)}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });
const SRC = { notif: 'notifikasi', manual: 'manual', jarvis: 'JARVIS', email: 'struk email', struk: 'foto struk' };

function setup(s) {
  return html`<form class="card cyan" id="setf"><span class="k cyan">Atur gaji</span>
    <div class="g2"><label class="field">Gaji bersih per bulan<input name="salary" type="number" min="0" step="50000" value="${s.salary || ''}" required></label>
      <label class="field">Tanggal gajian<input name="payday" type="number" min="1" max="31" value="${s.payday}" required></label></div>
    <label class="field">Tujuan keuangan (opsional)<input name="goals" value="${s.goals}" placeholder="mis. dana darurat 6× gaji, DP rumah 2028"></label>
    <div class="g2"><label class="field">Dana darurat sekarang<input name="emergency_saved" type="number" min="0" step="100000" value="${s.emergency_saved || 0}"></label>
      <label class="field">Target (× pengeluaran bulanan)<input name="emergency_months" type="number" min="1" max="24" value="${s.emergency_months}"></label></div>
    <label class="field">Cara hitung zakat<select name="zakat_method"><option value="neto" ${s.zakat_method !== 'bruto' ? 'selected' : ''}>Neto — gaji dikurangi tagihan & cicilan utang</option>
      <option value="bruto" ${s.zakat_method === 'bruto' ? 'selected' : ''}>Bruto — 2,5% gaji kotor (cara BAZNAS)</option></select></label>
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

// zakat penghasilan: the owner's rule (neto: salary minus bills and debt instalments; or bruto), the nisab, and where the rule comes from
function zakat(z, pots) {
  if (!z || !z.salary) return '';
  const pot = pots.find((p) => (p.categories || []).includes('zakat & sedekah'));
  const off = z.due && (!pot || Math.round(pot.amount) < z.amount);
  return html`<div class="card ${z.due ? 'green' : ''}" style="gap:6px"><div class="row sb"><span class="k green">Zakat penghasilan</span><b class="mono">${z.due ? rupiah(z.amount) : 'belum wajib'}</b></div>
    <span class="small">${z.method === 'neto' ? html`2,5% × (gaji ${rupiah(z.salary, true)} − tagihan & cicilan utang ${rupiah(z.deducted, true)}) = 2,5% × ${rupiah(z.base, true)}`
      : html`2,5% × gaji kotor ${rupiah(z.salary, true)}`}</span>
    <span class="small">Nisab ${rupiah(z.nisab)}/bulan (85 g emas)${z.due ? '' : ' — penghasilan bersih di bawah nisab: dihitung tahunan, sedekah tetap baik'}.</span>
    ${pot ? html`<span class="small">Pos "${pot.name}": ${rupiah(pot.amount, true)}${off ? ' — kurang dari zakatnya' : ''}</span>` : ''}
    ${off ? html`<button class="btn sm green" data-act="zakatpot">Samakan pos zakat (${rupiah(z.amount, true)})</button>` : ''}
    <details><summary class="small">Sumber aturan</summary>${z.sources.map((x) => html`<a class="small t-cyan" href="${x.url}" target="_blank" rel="noopener" style="display:block">· ${x.label}</a>`)}</details></div>`;
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
        ${zakat(s.zakat, s.settings.pots || [])}
        ${s.pots.length ? html`<span class="sec">Pos anggaran</span>${s.pots.map((p) => html`<div class="card ${p.level === 'over' ? 'red' : p.level === 'warn' ? 'amber' : ''}">
          <div class="row sb"><span class="ttl">${p.name}</span><span class="mono" style="font-size:13px">${rupiah(p.spent, true)}${p.amount ? ` / ${rupiah(p.amount, true)}` : ''}</span></div>
          ${p.amount ? html`<div class="bar"><i class="${p.level === 'ok' ? 'green' : 'amber'}" style="width:${Math.min(100, p.pct)}%"></i></div><span class="small">${p.pct}% · ${p.categories.join(', ')}${p.last ? ` · periode lalu ${rupiah(p.last, true)}` : ''}</span>` : html`<span class="small">${p.unplanned ? 'pengeluaran yang belum masuk pos mana pun' : ''}</span>`}</div>`)}`
          : html`<div class="card"><p class="sub">Belum ada pos anggaran. Minta JARVIS menyusun alokasi dari pengeluaranmu.</p></div>`}
        <div class="btns">${s.pots.length ? html`<button class="btn" data-act="editpots">${icon('brush', 16)} Ubah alokasi</button>` : html`<button class="btn" data-act="editpots">${icon('plus', 16)} Buat alokasi sendiri</button>`}
          ${!s.plan ? html`<button class="btn" data-act="plan">${icon('bolt', 16)} Susun dengan JARVIS</button>` : ''}</div>
        ${cats.length ? html`<div class="card"><span class="k">Per kategori</span>${cats.map(([k, v]) => html`<div class="row" style="font-size:13px"><span style="width:110px;color:var(--tx2)">${k}</span>
          <div class="bar grow" style="height:8px"><i style="width:${Math.round(100 * v / cats[0][1])}%"></i></div><span class="mono" style="min-width:70px;text-align:right">${rupiah(v, true)}</span></div>`)}</div>` : ''}
        <div class="row sb"><span class="sec">Transaksi</span><button class="btn sm" data-act="receipt">${icon('camera', 14)} Struk dari foto/galeri</button></div>
        ${s.recent.length ? html`<div class="list">${s.recent.map((t) => html`<div class="li click" data-act="edittx" data-id="${t.id}" role="button" aria-label="Ubah transaksi ${t.merchant}"><div class="grow"><div class="row sb"><span style="font-size:14px">${t.merchant}${t.note ? html` <span class="small">· ${t.note}</span>` : ''}</span>
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
        zakat_method: v.zakat_method === 'bruto' ? 'bruto' : 'neto',
        ...(em !== Number(cur?.settings?.emergency_saved || 0) ? { emergency_saved: em, emergency_at: new Date().toISOString().slice(0, 10) } : {}) });
      toast('Tersimpan'); render();
    },
    async receipt() {   // photos of receipts (camera or the gallery): read by JARVIS' eyes, recorded unless already there
      const files = await pick({ accept: 'image/*', multiple: true });
      if (!files.length) return;
      toast(`Membaca ${files.length} struk…`);
      const got = await upload(files);
      const r = await post('/api/v1/app/money/receipts', { attachment_ids: got.map((f) => f.id) });
      const ok = r.receipts.filter((x) => x.id), dup = r.receipts.filter((x) => x.duplicate), bad = r.receipts.filter((x) => x.error);
      toast([ok.length && `${ok.length} dicatat`, dup.length && `${dup.length} sudah tercatat`, bad.length && `${bad.length} tidak terbaca: ${bad[0].error}`].filter(Boolean).join(' · '), !!bad.length && !ok.length);
      render();
    },
    async zakatpot() {   // the zakat pot set to the zakat his rule gives (made when there is none)
      const pots = (cur.settings.pots || []).map((p) => ({ name: p.name, amount: p.amount, categories: [...(p.categories || [])] }));
      const pot = pots.find((p) => p.categories.includes('zakat & sedekah'));
      if (pot) pot.amount = cur.zakat.amount; else pots.unshift({ name: 'Zakat & sedekah', amount: cur.zakat.amount, categories: ['zakat & sedekah'] });
      await put('/api/v1/app/money/pots', { pots }); toast('Pos zakat disamakan'); render();
    },
    async editpots() {   // his allocation by hand: rename, change amounts, which categories each pot covers, add or remove pots
      const pots = (cur.settings.pots || []).map((p) => ({ name: p.name, amount: p.amount, categories: [...(p.categories || [])] }));
      const row = (p, i) => html`<div class="card" data-row="${i}" style="gap:8px;background:var(--bg2)">
        <div class="row" style="gap:8px"><input class="inp grow" name="name" value="${p.name}" placeholder="Nama pos (mis. Makan)" maxlength="40" style="min-width:0">
          <input class="inp mono" name="amount" type="number" min="0" step="50000" value="${p.amount || ''}" placeholder="Rp" style="width:120px;text-align:right">
          <button type="button" class="ib sm" data-del="${i}" aria-label="Hapus pos">${icon('close', 14)}</button></div>
        <div class="chips" style="flex-wrap:wrap">${cur.categories.map((c) => html`<label class="chip" style="cursor:pointer"><input type="checkbox" name="cat" value="${c}" ${p.categories.includes(c) ? 'checked' : ''} style="margin-right:4px">${c}</label>`)}</div></div>`;
      const body = () => html`<span class="k cyan">Ubah alokasi gaji</span>
        <div id="potrows" style="display:flex;flex-direction:column;gap:10px;max-height:55vh;overflow:auto">${pots.map(row)}</div>
        <div class="row sb"><button type="button" class="btn sm" data-addpot="1">${icon('plus', 14)} Tambah pos</button><span class="mono small" id="pottotal"></span></div>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button type="button" class="btn primary" data-savepots="1">Simpan alokasi</button></div>`;
      const read = (wrap) => [...wrap.querySelectorAll('[data-row]')].map((r) => ({ name: r.querySelector('[name=name]').value.trim(),
        amount: Number(r.querySelector('[name=amount]').value || 0), categories: [...r.querySelectorAll('[name=cat]:checked')].map((x) => x.value) }));
      const total = (wrap) => { const t = read(wrap).reduce((a, p) => a + p.amount, 0); wrap.querySelector('#pottotal').textContent = `Total ${rupiah(t)} / ${rupiah(cur.salary)}${t > cur.salary ? ' — melebihi gaji' : ''}`; };
      await sheet(String(html`<div style="display:flex;flex-direction:column;gap:12px" id="potsheet">${body()}</div>`), { onOpen(wrap, close) {
        const box = wrap.querySelector('#potsheet');
        const redraw = () => { const keep = read(wrap); pots.splice(0, pots.length, ...keep); box.innerHTML = String(body()); total(wrap); };
        total(wrap);
        wrap.addEventListener('input', () => total(wrap));
        wrap.addEventListener('click', async (e) => {
          if (e.target.closest('[data-addpot]')) { redraw(); pots.push({ name: '', amount: 0, categories: [] }); box.innerHTML = String(body()); total(wrap); }
          const d = e.target.closest('[data-del]');
          if (d) { const keep = read(wrap); keep.splice(Number(d.dataset.del), 1); pots.splice(0, pots.length, ...keep); box.innerHTML = String(body()); total(wrap); }
          if (e.target.closest('[data-savepots]')) {
            const out = read(wrap).filter((p) => p.name);
            try { await put('/api/v1/app/money/pots', { pots: out }); toast('Alokasi disimpan'); close(null); render(); } catch (err) { toast(err.message || 'Gagal menyimpan', true); }
          }
        });
      } });
    },
    async plan() { toast('Otak berat menyusun alokasi…'); await post('/api/v1/app/money/plan'); render(); },
    async apply(b) {
      const pots = cur.plan.pos.map((p, i) => ({ ...p, amount: Number(document.querySelector(`[data-pot="${i}"]`)?.value || p.amount) }));
      await post(`/api/v1/app/money/plan/${b.dataset.id}/apply`, { pots });
      toast('Alokasi dipakai untuk periode ini'); render();
    },
    async edittx(b, e) {   // every field of a transaction: amount, for/from, in/out, date & time, category, note — or delete it
      if (e?.target?.closest('[data-act="cat"]')) return;   // the category chip has its own quick picker
      const t = cur.recent.find((x) => String(x.id) === b.dataset.id);
      if (!t) return;
      const local = new Date(new Date(t.at).getTime() + 7 * 3600e3).toISOString().slice(0, 16);   // WIB for the field
      const v = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:10px"><span class="ttl">Ubah transaksi</span>
        <label class="field">Nominal<input name="amount" type="number" min="1" step="1" value="${Math.round(t.amount)}" required></label>
        <label class="field">Untuk / dari<input name="merchant" value="${t.merchant}" required maxlength="60"></label>
        <div class="g2"><label class="field">Jenis<select name="direction"><option value="out" ${t.direction === 'out' ? 'selected' : ''}>Pengeluaran</option><option value="in" ${t.direction === 'in' ? 'selected' : ''}>Pemasukan</option></select></label>
          <label class="field">Kategori<select name="category">${cur.categories.map((c) => html`<option ${c === t.category ? 'selected' : ''}>${c}</option>`)}</select></label></div>
        <label class="field">Tanggal & jam (WIB)<input name="at" type="datetime-local" value="${local}" required></label>
        <label class="field">Catatan<input name="note" value="${t.note || ''}" maxlength="300" placeholder="opsional"></label>
        <span class="small">Sumber: ${t.app || SRC[t.source] || t.source}</span>
        <div class="btns"><button type="button" class="btn danger" data-close="__del" style="flex:0 0 90px">Hapus</button><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Simpan</button></div></form>`));
      if (!v) return;
      if (v === '__del') { await del(`/api/v1/app/money/tx/${t.id}`); toast('Transaksi dihapus'); render(); return; }
      try {
        await put(`/api/v1/app/money/tx/${t.id}`, { amount: Number(v.amount), merchant: v.merchant, direction: v.direction, category: v.category, at: v.at, note: v.note || '' });
        toast('Transaksi diperbarui'); render();
      } catch (err) { toast(err.message || 'Gagal menyimpan', true); }
    },
    async cat(b, e) {
      e?.stopPropagation?.();
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
