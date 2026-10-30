// Film bioskop (mockup 31): what plays today at the cinemas near him — each film with its rating, genre, length, cheapest ticket and the show
// times still ahead per cinema; which cinemas (and which city) are his choice.
import { get, header, html, icon, loading, on, openWeb, post, put, render, sheet, toast } from '../core.js';
import { rupiah } from '../lib.js';

let cur = null, where = 'rumah', day = 0;
const localDate = () => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`; };
const dayLong = (n) => (n === 0 ? 'hari ini' : n === 1 ? 'besok' : new Date(Date.now() + n * 86400000).toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'short' }));
const DAYS = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];
const dayLabel = (n) => (n === 0 ? 'Hari ini' : n === 1 ? 'Besok' : DAYS[new Date(Date.now() + n * 86400000).getDay()] + ' ' + new Date(Date.now() + n * 86400000).getDate());

export default {
  tab: 'beranda',
  feature: 'bioskop',
  async render(root, route) {
    root.innerHTML = String(html`${header('Film bioskop')}<div class="scr">${loading()}<p class="small" style="text-align:center">Membaca jadwal hari ini…</p></div>`);
    where = route.query.where || where;
    day = route.query.day != null ? Number(route.query.day) || 0 : 0;
    const d = cur = await get(`/api/v1/app/cinema?where=${where}&day=${day}${route.query.refresh ? '&refresh=true' : ''}`);
    if (route.query.refresh && day) history.replaceState(null, '', `#/bioskop?day=${day}&where=${where}`);   // one retry, not one per repaint
    const dayChips = html`<div class="chips">${[0, 1, 2, 3, 4, 5, 6].map((n) => html`<a class="chip ${n === day ? 'on' : ''}" href="#/bioskop?day=${n}&where=${where}">${dayLabel(n)}</a>`)}</div>`;
    if (d.error && !d.films.length) {
      root.innerHTML = String(html`${header('Film bioskop', { sub: d.date })}<div class="scr">${dayChips}<div class="card red"><span class="k" style="color:var(--red-t)">Jadwal ${dayLong(day)} belum terbaca</span>
        <span class="small">${d.error}</span>
        <span class="small">Bila situsnya minta verifikasi "bukan robot", buka sekali di HP lalu Selesai — berikutnya JARVIS bisa membacanya sendiri.</span>
        <div class="chips">${[['21cineplex', 'https://21cineplex.com/'], ['CGV', 'https://www.cgv.id/'], ['Cinépolis', 'https://www.cinepolis.co.id/']].map(([l, u]) => html`<button class="chip" data-act="site" data-u="${u}">${icon('lock', 12)} Buka ${l} di HP</button>`)}</div>
        <a class="btn" href="#/bioskop?day=${day}&where=${where}&refresh=1">${icon('repeat', 16)} Coba lagi</a></div></div>`);
      return;
    }
    if (d.loading) {
      root.innerHTML = String(html`${header('Film bioskop', { sub: d.date })}<div class="scr">${dayChips}<div class="card violet"><div class="row sb"><span class="k violet">Membuka situs bioskop di HP-mu</span><span class="dot violet live"></span></div>
        <span class="small">Jadwal ${dayLong(day)} dibaca langsung dari 21cineplex/CGV/Cinépolis lewat HP (server diblokir situsnya). Biasanya 1–2 menit.</span></div></div>`);
      const off = on('cinema', () => render());
      const t = setInterval(() => render(), 20000);
      return () => { off(); clearInterval(t); };
    }
    if (d.waiting) {
      root.innerHTML = String(html`${header('Film bioskop')}<div class="scr"><a class="card violet" href="#/misi/${d.task_id}"><span class="k violet">Hermes mencari jadwal dengan browser</span><span class="small">Halaman jadwal tidak terbaca langsung — ketuk untuk melihat.</span></a></div>`);
      return;
    }
    root.innerHTML = String(html`${header('Film bioskop', { sub: `${d.city.replace(/(^|-)\w/g, (m) => m.toUpperCase()).replace('-', ' ')}${d.date ? ` · ${d.date}` : ''}`, right: html`<button class="ib box" data-act="picks" aria-label="Pilih bioskop">${icon('gear', 18)}</button>` })}
      <div class="scr">
        ${dayChips}
        ${(d.errors || []).length ? html`<span class="small t-amber2">${d.errors.join(' · ')}</span>` : ''}
        <div class="chips"><a class="chip ${where === 'rumah' ? 'on' : ''}" href="#/bioskop?where=rumah&day=${day}">Dekat rumah</a><a class="chip ${where === 'kantor' ? 'on' : ''}" href="#/bioskop?where=kantor&day=${day}">Dekat kantor${d.office_city ? ` · ${d.office_city}` : ''}</a></div>
        <div class="chips">${d.cinemas.map((c) => html`<span class="chip">${c.name} · ${c.films}</span>`)}</div>
        ${d.films.length ? d.films.map((f) => html`<div class="card">
          <div class="row top" style="gap:12px">${f.poster ? html`<img src="${f.poster}" alt="" referrerpolicy="no-referrer" style="width:64px;height:96px;object-fit:cover;border-radius:8px;flex:none">` : ''}
            <div class="grow" style="display:flex;flex-direction:column;gap:4px"><span class="ttl">${f.title}</span>
              <span class="small">${[f.rating, f.genre, f.minutes ? `${f.minutes} menit` : ''].filter(Boolean).join(' · ')}</span>
              <span class="small">berikutnya <b class="mono" style="color:var(--cyan-t)">${f.next.replace(':', '.')}</b>${f.cheapest ? ` · mulai ${rupiah(f.cheapest)}` : ''}</span></div></div>
          ${f.at.map((a) => html`<div><span class="small" style="color:var(--tx)">${a.cinema} · ${a.type}${a.price ? ` · ${rupiah(a.price)}` : ''}</span>
            <div class="chips" style="flex-wrap:wrap;margin-top:4px">${a.times.map((t) => html`<button class="tag cyan mono" data-act="book" data-f="${f.title}" data-c="${a.cinema}" data-t="${t}" style="cursor:pointer;border:0">${t.replace(':', '.')}</button>`)}</div></div>`)}</div>`)
          : html`<div class="card"><p class="sub">Tidak ada pertunjukan ${day ? 'di hari itu' : 'tersisa hari ini'} di bioskop pilihanmu.</p></div>`}
        ${d.films.length ? html`<span class="small" style="padding:0 4px">Ketuk jam tayang untuk memesan: JARVIS memilih kursi di situs bioskop lewat HP, lalu berhenti di halaman masuk akun/bayar.</span>` : ''}
        ${(d.presale || []).length ? html`<span class="sec">Pre-sale</span><div class="list">${d.presale.map((p) => html`<a class="li click" href="${p.url || '#/bioskop'}" target="_blank" rel="noopener">
          ${p.poster ? html`<img src="${p.poster}" alt="" style="width:36px;height:54px;object-fit:cover;border-radius:6px">` : ''}<div class="grow"><div style="font-size:14px">${p.title}</div><div class="small">${p.day} · ${p.cinema}</div></div></a>`)}</div>` : ''}
        <a class="btn block" href="#/bioskop?refresh=1&where=${where}&day=${day}">${icon('repeat', 16)} Baca ulang</a>
        <p class="small" style="padding:0 4px">Sumber: ${d.source}. Dibaca tanpa AI lewat alur master; bila halamannya berubah, Hermes mencarinya dengan browser.</p>
      </div>`);
  },
  actions: {
    site(b) { openWeb(b.dataset.u); },
    async book(b) {
      const v = await sheet(String(html`<form><span class="ttl">${b.dataset.f}</span><span class="small">${b.dataset.c} · ${dayLong(day)} ${b.dataset.t.replace(':', '.')}</span>
        <label class="field">Jumlah kursi<input name="seats" type="number" min="1" max="8" value="2"></label>
        <span class="small">JARVIS membuka situs bioskop di browser HP, memilih kursi berdampingan, lalu berhenti di halaman masuk akun/pembayaran — kamu yang masuk & bayar.</span>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Pesan di HP</button></div></form>`));
      if (!v) return;
      const r = await post('/api/v1/app/cinema/book', { film: b.dataset.f, cinema: b.dataset.c, date: day ? cur.date : localDate(), time: b.dataset.t, seats: Number(v.seats) || 2 });
      toast(`Membuka ${r.site} di HP…`); location.hash = `#/misi/${r.task_id}`;
    },
    async picks() {
      const v = await sheet(String(html`<form><span class="ttl">Bioskop pilihan</span><label class="field">Kota<input name="city" value="${cur.city}"></label>
        <div style="display:flex;flex-direction:column;gap:6px;max-height:300px;overflow:auto">${(cur.all || []).map((c) => html`<label class="row" style="gap:8px;font-size:14px"><input type="checkbox" name="c_${c.slug}" ${cur.picks.includes(c.slug) ? 'checked' : ''}> ${c.name} <span class="small">${c.chain}</span></label>`)}</div>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Simpan</button></div></form>`));
      if (!v) return;
      await put('/api/v1/app/cinema/picks', { city: v.city || '', cinemas: Object.keys(v).filter((k) => k.startsWith('c_')).map((k) => k.slice(2)), where });
      toast('Tersimpan'); render();
    },
  },
};
