// Film bioskop (mockup 31): what plays today at the cinemas near him — each film with its rating, genre, length, cheapest ticket and the show
// times still ahead per cinema; which cinemas (and which city) are his choice.
import { get, header, html, icon, loading, put, render, sheet, toast } from '../core.js';
import { rupiah } from '../lib.js';

let cur = null;

export default {
  tab: 'beranda',
  feature: 'bioskop',
  async render(root, route) {
    root.innerHTML = String(html`${header('Film bioskop')}<div class="scr">${loading()}<p class="small" style="text-align:center">Membaca jadwal hari ini…</p></div>`);
    const d = cur = await get(`/api/v1/app/cinema${route.query.refresh ? '?refresh=true' : ''}`);
    if (d.waiting) {
      root.innerHTML = String(html`${header('Film bioskop')}<div class="scr"><a class="card violet" href="#/misi/${d.task_id}"><span class="k violet">Hermes mencari jadwal dengan browser</span><span class="small">Halaman jadwal tidak terbaca langsung — ketuk untuk melihat.</span></a></div>`);
      return;
    }
    root.innerHTML = String(html`${header('Film bioskop', { sub: `${d.city.replace(/(^|-)\w/g, (m) => m.toUpperCase()).replace('-', ' ')}${d.date ? ` · ${d.date}` : ''}`, right: html`<button class="ib box" data-act="picks" aria-label="Pilih bioskop">${icon('gear', 18)}</button>` })}
      <div class="scr">
        <div class="chips">${d.cinemas.map((c) => html`<span class="chip">${c.name} · ${c.films}</span>`)}</div>
        ${d.films.length ? d.films.map((f) => html`<div class="card">
          <div class="row top" style="gap:12px">${f.poster ? html`<img src="${f.poster}" alt="" referrerpolicy="no-referrer" style="width:64px;height:96px;object-fit:cover;border-radius:8px;flex:none">` : ''}
            <div class="grow" style="display:flex;flex-direction:column;gap:4px"><span class="ttl">${f.title}</span>
              <span class="small">${[f.rating, f.genre, f.minutes ? `${f.minutes} menit` : ''].filter(Boolean).join(' · ')}</span>
              <span class="small">berikutnya <b class="mono" style="color:var(--cyan-t)">${f.next.replace(':', '.')}</b>${f.cheapest ? ` · mulai ${rupiah(f.cheapest)}` : ''}</span></div></div>
          ${f.at.map((a) => html`<div><span class="small" style="color:var(--tx)">${a.cinema} · ${a.type}${a.price ? ` · ${rupiah(a.price)}` : ''}</span>
            <div class="chips" style="flex-wrap:wrap;margin-top:4px">${a.times.map((t) => html`<span class="tag cyan mono">${t.replace(':', '.')}</span>`)}</div></div>`)}</div>`)
          : html`<div class="card"><p class="sub">Tidak ada pertunjukan tersisa hari ini di bioskop pilihanmu.</p></div>`}
        ${(d.presale || []).length ? html`<span class="sec">Pre-sale</span><div class="list">${d.presale.map((p) => html`<a class="li click" href="${p.url || '#/bioskop'}" target="_blank" rel="noopener">
          ${p.poster ? html`<img src="${p.poster}" alt="" style="width:36px;height:54px;object-fit:cover;border-radius:6px">` : ''}<div class="grow"><div style="font-size:14px">${p.title}</div><div class="small">${p.day} · ${p.cinema}</div></div></a>`)}</div>` : ''}
        <a class="btn block" href="#/bioskop?refresh=1">${icon('repeat', 16)} Baca ulang</a>
        <p class="small" style="padding:0 4px">Sumber: ${d.source}. Dibaca tanpa AI lewat alur master; bila halamannya berubah, Hermes mencarinya dengan browser.</p>
      </div>`);
  },
  actions: {
    async picks() {
      const v = await sheet(String(html`<form><span class="ttl">Bioskop pilihan</span><label class="field">Kota<input name="city" value="${cur.city}"></label>
        <div style="display:flex;flex-direction:column;gap:6px;max-height:300px;overflow:auto">${(cur.all || []).map((c) => html`<label class="row" style="gap:8px;font-size:14px"><input type="checkbox" name="c_${c.slug}" ${cur.picks.includes(c.slug) ? 'checked' : ''}> ${c.name} <span class="small">${c.chain}</span></label>`)}</div>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Simpan</button></div></form>`));
      if (!v) return;
      await put('/api/v1/app/cinema/picks', { city: v.city || '', cinemas: Object.keys(v).filter((k) => k.startsWith('c_')).map((k) => k.slice(2)) });
      toast('Tersimpan'); render();
    },
  },
};
