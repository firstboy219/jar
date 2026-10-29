// Kopi (mockup 40): "Mau kopi?" — the promos JARVIS found in Kopi Kenangan and Qpon (his usual first, within his price limit); one tap and
// JARVIS orders it in the app and pays with GoPay (he types the PIN); this month's coffee spending.
import { $, get, header, html, icon, loading, on, post, put, render, toast } from '../core.js';
import { rupiah } from '../lib.js';

let cur = null;

export default {
  tab: 'beranda',
  feature: 'kopi',
  async render(root) {
    root.innerHTML = String(html`${header('Kopi')}<div class="scr">${loading()}</div>`);
    const s = cur = await get('/api/v1/app/coffee');
    const o = s.offer, st = s.settings;
    const live = o && o.fresh;
    root.innerHTML = String(html`${header('Kopi', { sub: `bulan ini ${rupiah(s.month_total, true)} untuk kopi` })}
      <div class="scr">
        ${live && o.status === 'checking' ? html`<div class="card violet"><div class="row sb"><span class="k violet">Mengecek promo di HP</span><span class="dot violet live"></span></div>
          <span class="small">${(o.result?.pending || []).map((a) => ({ kopikenangan: 'Kopi Kenangan', qpon: 'Qpon' }[a] || a)).join(' & ')}…</span></div>` : ''}
        ${live && o.status === 'offered' ? html`<div class="card amber"><span class="k amber">Mau kopi?</span>
            ${o.best.length ? o.best.map((p, i) => html`<div class="row sb" style="gap:8px"><div class="grow"><div style="font-size:14px;font-weight:600">${p.menu}</div>
              <div class="small">${p.label}${p.merchant && p.merchant !== p.label ? ` · ${p.merchant}` : ''}${p.voucher ? ` · ${p.voucher}` : ''}${p.syarat ? ` · ${p.syarat}` : ''}</div></div>
              <div style="text-align:right"><div class="mono">${rupiah(p.harga, true)}</div>${p.hemat_pct ? html`<div class="small" style="text-decoration:line-through">${rupiah(p.harga_normal, true)}</div>` : ''}</div>
              <button class="btn sm primary" data-act="order" data-i="${i}">Pesan</button></div>`) : html`<span class="small">Tidak ada promo di bawah ${rupiah(st.max_price, true)} hari ini.</span>`}
            ${st.usual ? html`<button class="btn" data-act="usual">${icon('coffee', 16)} ${st.usual} seperti biasa</button>` : ''}
            <button class="btn ghost sm" data-act="decline">Tidak dulu</button></div>` : ''}
        ${live && o.status === 'ordering' ? html`<div class="card cyan"><span class="k cyan">Memesan ${o.choice?.menu || ''}</span><span class="small">JARVIS sedang memesan di ${o.choice?.label || 'aplikasi'}. Ketik PIN GoPay sendiri saat diminta.</span></div>` : ''}
        ${o && o.status === 'ordered' ? html`<div class="card green"><span class="k green">Dipesan</span><span class="sub">${o.result?.order?.pesanan || o.choice?.menu}</span>
          <span class="small">${[o.result?.order?.outlet, o.result?.order?.kode && `#${o.result.order.kode}`, o.result?.order?.siap].filter(Boolean).join(' · ')}</span></div>` : ''}
        ${o && o.status === 'failed' && live ? html`<div class="card red"><span class="small">${(o.result?.errors || []).join('; ') || o.result?.order?.catatan || 'Gagal'}</span></div>` : ''}
        ${!live || ['declined', 'ordered', 'failed', 'expired'].includes(o.status) ? html`<button class="btn primary block" data-act="check">${icon('search', 16)} Cek promo kopi sekarang</button>` : ''}
        <form class="card" id="cf"><span class="k">Kopiku</span>
          <label class="field">Biasanya pesan<input name="usual" value="${st.usual}" placeholder="mis. Kopi Kenangan Mantan"></label>
          <div class="g2"><label class="field">Gula<input name="sugar" value="${st.sugar}"></label><label class="field">Batas harga<input name="max_price" type="number" min="10000" step="1000" value="${st.max_price}"></label></div>
          <div class="g2"><label class="field">Ambil di<select name="pickup"><option value="1" ${st.pickup ? 'selected' : ''}>Pick up</option><option value="" ${st.pickup ? '' : 'selected'}>Diantar</option></select></label>
            <label class="field">Outlet<input name="outlet" value="${st.outlet}" placeholder="terdekat"></label></div>
          <button class="btn" data-act="save">Simpan</button>
          <span class="small">Tiap hari kerja 14.30 di kantor JARVIS mengecek promo lalu bertanya. Bayar dengan GoPay — PIN kamu yang ketik.</span></form>
        ${s.history.length ? html`<span class="sec">Riwayat</span><div class="list">${s.history.map((h) => html`<div class="li"><div class="grow"><div style="font-size:14px">${h.choice?.menu || '-'}</div>
          <div class="small">${new Date(h.created_at).toLocaleDateString('id-ID', { weekday: 'short', day: 'numeric', month: 'short' })} · ${h.choice?.label || ''}</div></div>
          <span class="mono">${h.result?.order?.total ? rupiah(Number(h.result.order.total), true) : ''}</span></div>`)}</div>` : ''}
      </div>`);
    return on('notify', (e) => { if (e.route === '#/kopi') render(); });
  },
  actions: {
    async check() { await post('/api/v1/app/coffee/check'); toast('JARVIS mengecek promo di HP…'); render(); },
    async order(b) { await post(`/api/v1/app/coffee/${cur.offer.id}/order`, { index: Number(b.dataset.i) }); toast('Memesan… ketik PIN GoPay saat diminta'); render(); },
    async usual() { await post(`/api/v1/app/coffee/${cur.offer.id}/order`, { custom: cur.settings.usual }); toast('Memesan yang biasa…'); render(); },
    async decline() { await post(`/api/v1/app/coffee/${cur.offer.id}/decline`); render(); },
    async save() {
      const v = Object.fromEntries(new FormData($('#cf')).entries());
      await put('/api/v1/app/settings/coffee', { usual: v.usual, sugar: v.sugar, max_price: Number(v.max_price) || 75000, pickup: !!v.pickup, outlet: v.outlet });
      toast('Tersimpan'); render();
    },
  },
};
