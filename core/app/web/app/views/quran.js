// Al-Qur'an (mockup 47): where the owner read up to, his khatam progress, the surahs, and a reader that plays the murottal verse by
// verse (highlighted), repeats for memorising, and marks the last verse read. Text and translation: Kemenag (equran.id), never AI.
import { $, get, header, html, icon, loading, post, put, render, toast } from '../core.js';

let player = null, queue = [], playing = -1, repeat = 1, reps = 0, surahNo = null, ayat = [];

function stop() { player?.pause(); player = null; playing = -1; queue = []; document.querySelectorAll('.ayah.on').forEach((e) => e.classList.remove('on')); }

function playFrom(i) {
  stop();
  queue = ayat.slice(i);
  playing = i; reps = 0;
  next();
}
function next() {
  const a = ayat[playing];
  if (!a || !a.audio) { stop(); return; }
  document.querySelectorAll('.ayah.on').forEach((e) => e.classList.remove('on'));
  const el = document.getElementById(`a${a.n}`);
  el?.classList.add('on'); el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  player = new Audio(a.audio);
  player.onended = () => { reps += 1; if (reps < repeat) { player.currentTime = 0; player.play(); return; } reps = 0; playing += 1; if (playing < ayat.length) next(); else stop(); };
  player.play().catch(() => toast('Audio tidak bisa diputar.', true));
}

async function reader(root, n, startAyah) {
  const s = await get(`/api/v1/app/quran/surah/${n}`);
  surahNo = n; ayat = s.ayat;
  root.innerHTML = String(html`${header(s.latin, { sub: `${s.arti} · ${s.jumlah} ayat · ${s.tempat} · ${s.qari}`, right: html`<span class="ar" style="font-size:24px;padding-right:12px;color:var(--green-t)">${s.nama}</span>` })}
    <div class="scr">
      <div class="chips"><button class="chip cyan" data-act="play" data-i="0">${icon('play', 14)} Dengarkan dari awal</button>
        <button class="chip ${repeat > 1 ? 'cyan' : ''}" data-act="repeat">${repeat > 1 ? `ulang ${repeat}× (hafalan)` : 'ulang 1×'}</button>
        <button class="chip" data-act="stop">${icon('stop', 14)} Berhenti</button></div>
      ${n !== 1 && n !== 9 ? html`<p class="ar" style="text-align:center">بِسْمِ اللّٰهِ الرَّحْمٰنِ الرَّحِيْمِ</p>` : ''}
      ${s.ayat.map((a, i) => html`<div class="card ayah" id="a${a.n}" style="gap:10px">
        <div class="row sb"><span class="tag green">${n}:${a.n} · juz ${a.juz}</span>
          <div class="row" style="gap:4px"><button class="ib sm" data-act="play" data-i="${i}" aria-label="Putar dari ayat ini">${icon('play', 14)}</button>
          <button class="btn sm" data-act="mark" data-a="${a.n}">Tandai sampai sini</button></div></div>
        <p class="ar">${a.arab}</p>
        <p class="small" style="font-style:italic">${a.latin}</p>
        <p class="sub">${a.arti}</p></div>`)}
      <div class="btns">${s.nomor > 1 ? html`<a class="btn" href="#/quran/${s.nomor - 1}">← Surah sebelumnya</a>` : ''}${s.nomor < 114 ? html`<a class="btn" href="#/quran/${s.nomor + 1}">Surah berikutnya →</a>` : ''}</div>
    </div>`);
  const style = document.createElement('style');
  style.textContent = '.ayah.on{border-color:var(--green);background:var(--green-bg)}';
  root.append(style);
  if (startAyah) setTimeout(() => $(`#a${startAyah}`)?.scrollIntoView({ block: 'center' }), 50);
}

export default {
  tab: 'beranda',
  feature: 'quran',
  async render(root, route) {
    stop();
    root.innerHTML = String(html`${header("Al-Qur'an")}<div class="scr">${loading()}</div>`);
    if (route.params[0]) { await reader(root, Number(route.params[0]), Number(route.query.ayah) || 0); return () => stop(); }
    const { progress: p, surahs, qari } = await get('/api/v1/app/quran');
    root.innerHTML = String(html`${header("Al-Qur'an")}<div class="scr">
      ${p.last ? html`<a class="card green pad" href="#/quran/${p.last.surah}?ayah=${p.last.ayah}" style="border-width:1.5px;border-color:var(--green)">
        <div class="row sb"><div style="display:flex;flex-direction:column;gap:4px"><span class="k green">Terakhir dibaca</span>
          <span style="font:600 22px var(--f-head)">${p.last.latin} · ayat ${p.last.ayah}</span><span class="small">Surah ${p.last.surah} · Juz ${p.last.juz} · halaman ±${p.last.page}</span></div>
          <span class="ar" style="font-size:30px;color:var(--green-t)">${p.last.nama}</span></div>
        <span class="btn green block">Lanjut baca</span></a>`
        : html`<div class="card green"><span class="k green">Mulai</span><p class="sub">Pilih surah. Tandai ayat terakhir yang kamu baca — JARVIS mengingatnya.</p></div>`}
      <div class="card"><div class="row sb"><span class="k muted">Khatam ke-${(p.khatam || 0) + 1}</span><span class="mono">${p.pct ?? 0}%</span></div>
        <div class="bar"><i class="green" style="width:${p.pct ?? 0}%"></i></div>
        <span class="small">${p.per_day_pages ? `Target ${p.target_date}: ±${p.per_day_pages} halaman per hari. ` : ''}${p.streak ? `${p.streak} hari berturut-turut.` : ''}</span>
        <div class="row" style="gap:8px"><label class="field grow">Target khatam<input type="date" id="target" value="${p.target_date || ''}"></label>
          <label class="field grow">Qari<select id="qari">${Object.entries(qari).map(([k, v]) => html`<option value="${k}" ${k === p.qari ? 'selected' : ''}>${v}</option>`)}</select></label></div></div>
      <div class="sec"><span>Rutin</span></div>
      <div class="chips">${(p.routines || []).map((r) => html`<a class="chip" href="#/quran/${r.surah}">${surahs[r.surah - 1]?.latin} · ${r.days.length === 7 ? 'tiap hari' : r.days.map((d) => ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'][d]).join(',')} ${r.time}</a>`)}</div>
      <div class="sec"><span>Surah</span></div>
      <label class="cmd" style="height:44px"><input id="qs" placeholder="Cari surah…"></label>
      <div class="list" id="slist">${surahs.map((s) => html`<a class="li click" href="#/quran/${s.nomor}" data-name="${s.latin.toLowerCase()} ${s.arti.toLowerCase()} ${s.nomor}">
        <span class="mono" style="width:28px;color:var(--mu)">${s.nomor}</span><div class="grow"><div class="ttl">${s.latin}</div><div class="small">${s.arti} · ${s.ayat} ayat</div></div><span class="ar" style="font-size:20px">${s.nama}</span></a>`)}</div>
    </div>`);
    $('#qs', root).addEventListener('input', (e) => { const q = e.target.value.toLowerCase(); for (const a of root.querySelectorAll('#slist a')) a.hidden = q && !a.dataset.name.includes(q); });
    $('#target', root).addEventListener('change', async (e) => { await put('/api/v1/app/settings/quran', { target_date: e.target.value }); render(); });
    $('#qari', root).addEventListener('change', async (e) => { await put('/api/v1/app/settings/quran', { qari: e.target.value }); toast('Qari diganti.'); });
    return () => stop();
  },
  actions: {
    play(b) { playFrom(Number(b.dataset.i)); },
    stop() { stop(); },
    repeat() { repeat = repeat === 1 ? 3 : 1; render(); },
    async mark(b) { const p = await post('/api/v1/app/quran/read', { surah: surahNo, ayah: Number(b.dataset.a) }); toast(`Ditandai: ${surahNo}:${b.dataset.a} · khatam ${p.pct}%`); },
  },
};
