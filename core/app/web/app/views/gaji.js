// Gaji & pengeluaran (mockup 38): this pay period — spent against the salary, what is realised and what is not yet (ticked right in the
// list), his zakat, his emergency fund wherever it sits (likuid / semi-likuid / tidak likuid), spending per category, the transactions.
import { $, del, get, header, html, icon, loading, on, post, put, render, sheet, toast } from '../core.js';
import { pick, upload } from '../upload.js';
import { rupiah } from '../lib.js';

let cur = null, txf = 'semua';   // the transaction list: semua | belum | sudah
const d = (s) => new Date(`${String(s).slice(0, 10)}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });
const SRC = { notif: 'notifikasi', manual: 'manual', jarvis: 'JARVIS', email: 'struk email', struk: 'foto struk' };

function setup(s) {
  return html`<form class="card cyan" id="setf"><span class="k cyan">Atur gaji</span>
    <div class="g2"><label class="field">Gaji bersih per bulan<input name="salary" type="number" min="0" step="50000" value="${s.salary || ''}" required></label>
      <label class="field">Tanggal gajian<input name="payday" type="number" min="1" max="31" value="${s.payday}" required></label></div>
    <label class="field">Tujuan keuangan (opsional)<input name="goals" value="${s.goals}" placeholder="mis. dana darurat 6× gaji, DP rumah 2028"></label>
    <label class="field">Target dana darurat (× pengeluaran bulanan)<input name="emergency_months" type="number" min="1" max="24" value="${s.emergency_months}"></label>
    <label class="field">Cara hitung zakat<select name="zakat_method"><option value="neto" ${s.zakat_method !== 'bruto' ? 'selected' : ''}>Neto — gaji dikurangi tagihan & cicilan utang</option>
      <option value="bruto" ${s.zakat_method === 'bruto' ? 'selected' : ''}>Bruto — 2,5% gaji kotor (cara BAZNAS)</option></select></label>
    <button class="btn primary" data-act="savesettings">Simpan</button>
    <span class="small">Pengeluaran dicatat otomatis dari notifikasi GoPay & bank di HP (izin baca notifikasi). Notifikasi berisi OTP/PIN tidak pernah dibaca.</span></form>`;
}

// zakat penghasilan: the owner's rule (neto: salary minus bills and debt instalments; or bruto), the nisab, and where the rule comes from
function zakat(z) {
  if (!z || !z.salary) return '';
  return html`<div class="card ${z.due ? 'green' : ''}" style="gap:6px"><div class="row sb"><span class="k green">Zakat penghasilan</span><b class="mono">${z.due ? rupiah(z.amount) : 'belum wajib'}</b></div>
    <span class="small">${z.method === 'neto' ? html`2,5% × (gaji ${rupiah(z.salary, true)} − tagihan & cicilan utang ${rupiah(z.deducted, true)}) = 2,5% × ${rupiah(z.base, true)}`
      : html`2,5% × gaji kotor ${rupiah(z.salary, true)}`}</span>
    ${z.method === 'neto' ? html`<span class="small">Tagihan & cicilan = transaksi berkategori "tagihan" dan "cicilan & utang" periode ini (sudah atau belum dibayar).</span>` : ''}
    <span class="small">Nisab ${rupiah(z.nisab)}/bulan (85 g emas)${z.due ? '' : ' — penghasilan bersih di bawah nisab: dihitung tahunan, sedekah tetap baik'}.</span>
    <details><summary class="small">Sumber aturan</summary>${z.sources.map((x) => html`<a class="small t-cyan" href="${x.url}" target="_blank" rel="noopener" style="display:block">· ${x.label}</a>`)}</details></div>`;
}

const LIQ_TONE = { likuid: 'green', semi_likuid: 'amber', tidak_likuid: 'violet' };
const LIQ_NOTE = { likuid: 'siap dipakai hari ini', semi_likuid: 'bisa dicairkan dalam beberapa hari kerja', tidak_likuid: 'terkunci sampai jatuh tempo / kena penalti' };

// his emergency fund wherever it sits, by liquidity, against the target — and what is usable right away
function emergency(e) {
  if (!e) return '';
  const months = (v) => String(v).replace('.', ',');
  return html`<div class="card ${e.pct >= 100 ? 'green' : 'cyan'}" style="gap:8px">
    <div class="row sb"><span class="k ${e.pct >= 100 ? 'green' : 'cyan'}">Dana darurat hari ini</span><b class="mono">${rupiah(e.saved)}</b></div>
    ${e.target ? html`<div class="bar"><i class="${e.pct >= 100 ? 'green' : ''}" style="width:${e.pct}%"></i></div>
      <span class="small">target ${e.months}× pengeluaran ≈ ${rupiah(e.target, true)} · cukup ${months(e.covers_months)} bulan · siap pakai ${months(e.ready_months)} bulan</span>` : ''}
    <div class="g3">${Object.entries(e.liquidity).map(([k, label]) => html`<div class="kpi" style="padding:8px"><span style="font-size:10px;color:var(--${LIQ_TONE[k]}-t)">${label}</span>
      <b style="font-size:13px">${rupiah(e.by[k] || 0, true)}</b><span class="small" style="font-size:10px">${LIQ_NOTE[k]}</span></div>`)}</div>
    ${e.assets.length ? html`<div class="list">${e.assets.map((a) => html`<div class="li ${a.id ? 'click' : ''}" ${a.id ? html`data-act="asset" data-id="${a.id}"` : ''}>
      <span class="tag ${LIQ_TONE[a.liquidity]}" style="flex:0 0 auto">${e.liquidity[a.liquidity]}</span>
      <div class="grow" style="min-width:0"><div style="font-size:14px">${a.name}</div><div class="small">${e.kinds[a.kind]?.label || a.kind}${a.note ? ` · ${a.note}` : ''}</div></div>
      <span class="mono" style="font-size:13px">${rupiah(a.amount, true)}</span></div>`)}</div>` : html`<span class="small">Belum ada aset. Tambahkan tabungan, e-wallet, reksa dana pasar uang, emas, saham, atau deposito yang kamu siapkan untuk darurat.</span>`}
    <div class="btns"><button class="btn sm" data-act="asset">${icon('plus', 14)} Tambah aset</button>
      <button class="btn sm ${e.pluang ? 'cyan' : ''}" data-act="pluangem">${e.pluang ? '✓ ' : ''}Hitung portofolio Pluang</button></div>
    ${e.saved_this_period ? html`<span class="small">${rupiah(e.saved_this_period, true)} masuk tabungan periode ini — perbarui saldo asetnya bila perlu.</span>` : ''}</div>`;
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
        <div class="card"><div class="row sb"><span class="k">Terpakai</span><span class="mono">${rupiah(s.spent, true)} / ${rupiah(s.salary, true)}</span></div>
          <div class="bar" style="height:10px"><i class="${pct > 90 ? 'amber' : ''}" style="width:${pct}%"></i></div>
          <div class="row sb small"><span>sisa ${rupiah(s.left, true)}</span><span>laju: ${rupiah(s.pace, true)} sampai gajian${s.pace > s.salary ? ' — melebihi gaji' : ''}</span></div></div>
        ${emergency(s.emergency)}
        ${zakat(s.zakat)}
        ${cats.length ? html`<div class="card"><span class="k">Per kategori</span>${cats.map(([k, v]) => html`<div class="row" style="font-size:13px"><span style="width:110px;color:var(--tx2)">${k}</span>
          <div class="bar grow" style="height:8px"><i style="width:${Math.round(100 * v / cats[0][1])}%"></i></div><span class="mono" style="min-width:70px;text-align:right">${rupiah(v, true)}</span></div>`)}</div>` : ''}
        <div class="row sb"><span class="sec">Transaksi</span><button class="btn sm" data-act="receipt">${icon('camera', 14)} Struk dari foto/galeri</button></div>
        ${s.pending?.n ? html`<div class="card amber" style="gap:4px"><div class="row sb"><span class="k amber">Belum direalisasi · ${s.pending.n}</span>
          <span class="mono" style="font-size:13px">${s.pending.out ? `−${rupiah(s.pending.out, true)}` : ''}${s.pending.in ? ` +${rupiah(s.pending.in, true)}` : ''}</span></div>
          <span class="small">Rencana yang belum terjadi — tidak dihitung ke terpakai & pos sampai ditandai sudah. Sisa setelah semuanya: ${rupiah((s.left || 0) - s.pending.out + s.pending.in, true)}.</span></div>` : ''}
        <div class="chips">${[['semua', 'Semua'], ['belum', `Belum${s.pending?.n ? ` (${s.pending.n})` : ''}`], ['sudah', 'Sudah direalisasi']].map(([k, v]) => html`<button class="chip ${txf === k ? 'on' : ''}" data-act="txfilter" data-f="${k}">${v}</button>`)}</div>
        ${s.recent.filter((t) => txf === 'semua' || (txf === 'belum' ? !t.realized : t.realized)).length ? html`<div class="list">${s.recent.filter((t) => txf === 'semua' || (txf === 'belum' ? !t.realized : t.realized)).map((t) => html`<div class="li click" data-act="edittx" data-id="${t.id}" role="button" aria-label="Ubah transaksi ${t.merchant}" style="${t.realized ? '' : 'opacity:.85'}"><div class="grow"><div class="row sb"><span style="font-size:14px">${t.merchant}${t.note ? html` <span class="small">· ${t.note}</span>` : ''}</span>
          <span class="mono" style="color:var(--${t.direction === 'in' ? 'green' : 'tx'})">${t.direction === 'in' ? '+' : '−'}${rupiah(t.amount)}</span></div>
          <div class="row sb small"><span>${new Date(t.at).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })} · ${t.app || SRC[t.source]}</span>
          <span class="row" style="gap:6px"><button class="chip ${t.realized ? 'green' : 'amber'}" style="height:26px;font-size:12px" data-act="realize" data-id="${t.id}" data-v="${t.realized ? '0' : '1'}"
            aria-label="${t.realized ? 'Tandai belum direalisasi' : 'Tandai sudah direalisasi'}">${t.realized ? '✓ sudah' : '○ belum'}</button>
          <button class="chip" style="height:26px;font-size:12px" data-act="cat" data-id="${t.id}" data-c="${t.category}">${t.category}${t.labeled_by === 'ai' ? ' · AI' : ''}</button></span></div></div></div>`)}</div>`
          : html`<div class="card"><span class="small">Belum ada transaksi periode ini.</span></div>`}
        <details class="card"><summary class="small">Pengaturan gaji</summary>${setup(s.settings)}</details>
      </div>`);
    return on('notify', (e) => { if (e.route === '#/gaji') render(); });
  },
  actions: {
    async savesettings() {
      const f = $('#setf'); if (!f.reportValidity()) return;
      const v = Object.fromEntries(new FormData(f).entries());
      await put('/api/v1/app/settings/money', { salary: Number(v.salary), payday: Number(v.payday), goals: v.goals || '', emergency_months: Number(v.emergency_months || 6),
        zakat_method: v.zakat_method === 'bruto' ? 'bruto' : 'neto' });
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
    async edittx(b, e) {   // every field of a transaction: amount, for/from, in/out, date & time, category, note, realised — or delete it
      if (e?.target?.closest('[data-act="cat"],[data-act="realize"]')) return;   // the chips have their own quick actions
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
        <label class="row" style="gap:8px;font-size:14px"><input type="checkbox" name="realized" ${t.realized ? 'checked' : ''} style="width:20px;height:20px;flex:0 0 20px"> Sudah direalisasi</label>
        <span class="small">Sumber: ${t.app || SRC[t.source] || t.source}</span>
        <div class="btns"><button type="button" class="btn danger" data-close="__del" style="flex:0 0 90px">Hapus</button><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Simpan</button></div></form>`));
      if (!v) return;
      if (v === '__del') { await del(`/api/v1/app/money/tx/${t.id}`); toast('Transaksi dihapus'); render(); return; }
      try {
        await put(`/api/v1/app/money/tx/${t.id}`, { amount: Number(v.amount), merchant: v.merchant, direction: v.direction, category: v.category, at: v.at, note: v.note || '', realized: !!v.realized });
        toast('Transaksi diperbarui'); render();
      } catch (err) { toast(err.message || 'Gagal menyimpan', true); }
    },
    txfilter(b) { txf = b.dataset.f; render(); },
    async realize(b, e) {   // right in the list: realised ↔ not yet (counted in spending only once realised)
      e?.stopPropagation?.();
      const v = b.dataset.v === '1';
      await put(`/api/v1/app/money/tx/${b.dataset.id}`, { realized: v });
      toast(v ? 'Sudah direalisasi' : 'Ditandai belum direalisasi'); render();
    },
    async asset(b) {   // an emergency-fund asset: add or change (or remove)
      const e = cur.emergency, a = b.dataset.id ? e.assets.find((x) => String(x.id) === b.dataset.id) : null;
      const v = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:10px"><span class="ttl">${a ? 'Ubah aset dana darurat' : 'Tambah aset dana darurat'}</span>
        <label class="field">Nama<input name="name" value="${a?.name || ''}" required maxlength="60" placeholder="mis. Tabungan BCA darurat, RDPU Bibit, Emas Antam"></label>
        <div class="g2"><label class="field">Jenis<select name="kind">${Object.entries(e.kinds).map(([k, x]) => html`<option value="${k}" ${(a?.kind || 'tabungan') === k ? 'selected' : ''}>${x.label}</option>`)}</select></label>
          <label class="field">Likuiditas<select name="liquidity"><option value="">ikut jenisnya</option>${Object.entries(e.liquidity).map(([k, x]) => html`<option value="${k}" ${a && a.liquidity === k && a.liquidity !== e.kinds[a.kind]?.liquidity ? 'selected' : ''}>${x}</option>`)}</select></label></div>
        <label class="field">Nilai sekarang (Rp)<input name="amount" type="number" min="0" step="1000" value="${a ? Math.round(a.amount) : ''}" required></label>
        <label class="field">Catatan<input name="note" value="${a?.note || ''}" maxlength="200" placeholder="opsional, mis. jatuh tempo Mar 2027"></label>
        <span class="small">Likuid: siap dipakai (tunai, tabungan, e-wallet) · Semi-likuid: dicairkan dalam beberapa hari (reksa dana pasar uang, emas, saham) · Tidak likuid: terkunci sampai jatuh tempo (deposito).</span>
        <div class="btns">${a ? html`<button type="button" class="btn danger" data-close="__del" style="flex:0 0 90px">Hapus</button>` : ''}<button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Simpan</button></div></form>`));
      if (!v) return;
      if (v === '__del') { await del(`/api/v1/app/money/emergency/${a.id}`); toast('Aset dihapus'); render(); return; }
      const body = { name: v.name, kind: v.kind, liquidity: v.liquidity || null, amount: Number(v.amount || 0), note: v.note || '' };
      try { if (a) await put(`/api/v1/app/money/emergency/${a.id}`, body); else await post('/api/v1/app/money/emergency', body); toast('Dana darurat diperbarui'); render(); }
      catch (err) { toast(err.message || 'Gagal menyimpan', true); }
    },
    async pluangem() { await put('/api/v1/app/settings/money', { emergency_pluang: !cur.emergency.pluang }); render(); },
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
        <label class="field">Tanggal & jam (WIB)<input name="at" type="datetime-local" value="${new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 16)}"></label>
        <label class="row" style="gap:8px;font-size:14px"><input type="checkbox" name="realized" checked style="width:20px;height:20px;flex:0 0 20px"> Sudah direalisasi</label>
        <span class="small" style="margin-top:-6px">Hapus centang untuk rencana atau tagihan yang belum dibayar — tidak dihitung sampai ditandai sudah.</span>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Simpan</button></div></form>`));
      if (!v?.amount) return;
      try { await post('/api/v1/app/money/tx', { amount: Number(v.amount), merchant: v.merchant, direction: v.direction, category: v.category, at: v.at || null, realized: !!v.realized }); }
      catch (err) { toast(err.message || 'Gagal menyimpan', true); return; }
      render();
    },
  },
};
