// Al-Qur'an (mockup 47): where the owner read up to, his khatam progress, the surahs, and a reader that plays the murottal verse by
// verse (highlighted), repeats for memorising, and marks the last verse read. Text and translation: Kemenag (equran.id), never AI.
// The translation can be read aloud — after each verse or on its own — always by the phone's (or the browser's) own voice, never an AI
// voice (owner 2026-10-30). "Konteks": where and when the surah came down, what the Prophet ﷺ was going through, and the Kemenag tafsir.
import { $, get, header, host, html, icon, loading, post, put, render, sheet, toast } from '../core.js';

const MODES = { arab: 'Murottal', both: 'Murottal + arti', arti: 'Arti saja' };
let player = null, playing = -1, repeat = 1, surahNo = null, surahName = '', ayat = [], showArti = true, mode = 'arab', speakGen = 0;

/** The translation in the device's own voice (Android's text-to-speech in the app, the browser's speech elsewhere): resolves when said. */
function sayLocal(text) {
  const gen = speakGen;
  return new Promise((resolve) => {
    if (host.has('speakLocal')) {
      const tok = `q${Date.now()}${Math.random().toString(36).slice(2, 6)}`;
      host.call('speakLocal', text, tok);
      const t = setInterval(() => {
        if (gen !== speakGen) { clearInterval(t); resolve(false); } else if (host.call('spoken', tok)) { clearInterval(t); resolve(true); }
      }, 250);
    } else if ('speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'id-ID';
      const v = speechSynthesis.getVoices().find((x) => (x.lang || '').toLowerCase().startsWith('id'));
      if (v) u.voice = v;
      u.onend = () => resolve(gen === speakGen); u.onerror = () => resolve(false);
      speechSynthesis.speak(u);
    } else { toast('Perangkat ini tidak punya suara bawaan untuk membacakan terjemahan.', true); resolve(false); }
  });
}

function hush() {
  speakGen += 1;
  if (host.has('stopSpeaking')) host.call('stopSpeaking');
  try { window.speechSynthesis?.cancel(); } catch { /* none */ }
}

/** One verse's recitation, repeated for memorising; resolves when done (false when it cannot be played). */
function recite(url) {
  return new Promise((resolve) => {
    let n = 0;
    player = new Audio(url);
    player.onended = () => { n += 1; if (n < repeat) { player.currentTime = 0; player.play(); } else resolve(true); };
    player.onerror = () => resolve(false);
    player.play().catch(() => { toast('Audio tidak bisa diputar.', true); resolve(false); });
  });
}

const spokenArti = (a) => String(a.arti || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

function stop() { player?.pause(); player = null; playing = -1; hush(); document.querySelectorAll('.ayah.on').forEach((e) => e.classList.remove('on')); }

function playFrom(i) {
  stop();
  playing = i;
  next();
}
async function next() {
  const a = ayat[playing];
  if (!a) { stop(); return; }
  const gen = speakGen;
  document.querySelectorAll('.ayah.on').forEach((e) => e.classList.remove('on'));
  const el = document.getElementById(`a${a.n}`);
  el?.classList.add('on'); el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  if (mode !== 'arti') {
    if (!a.audio || !(await recite(a.audio))) { if (gen === speakGen) stop(); return; }
    if (gen !== speakGen) return;
  }
  if (mode !== 'arab') {
    await sayLocal(mode === 'arti' ? `Ayat ${a.n}. ${spokenArti(a)}` : spokenArti(a));
    if (gen !== speakGen) return;
  }
  playing += 1;
  if (playing < ayat.length) next(); else stop();
}

function contextView(c) {
  const p = c.surah.periode || {};
  return html`<div style="display:flex;flex-direction:column;gap:12px">
    <span class="k green">Konteks · ${c.surah.latin} ${c.surah.nomor}:${c.ayah}</span>
    <div class="card green"><div class="row wrap" style="gap:6px"><span class="tag green">Surah ${c.surah.tempat === 'Mekah' ? 'Makkiyah' : 'Madaniyah'}</span>
      <span class="tag">turun di ${c.surah.tempat}</span><span class="tag">urutan turun ke-${c.surah.urutan} dari 114</span></div>
      <span class="k muted" style="margin-top:6px">Masa Rasulullah saw saat itu · ${p.nama}${p.tahun ? ` (${p.tahun})` : ''}</span>
      <p class="sub" style="margin:0">${p.nabi}</p>
      <span class="small">Gambaran umum periode menurut sirah, diperkirakan dari urutan turun surah — bukan riwayat khusus ayat ini.</span></div>
    <div class="card violet" id="qsum"><span class="k violet">Sebab turun ayat ini</span>${summaryView(c.ringkasan)}</div>
    ${c.tafsir ? html`<details class="card" open><summary class="k muted">Tafsir Kemenag ayat ${c.ayah} (teks asli)</summary><p class="sub" style="white-space:pre-wrap;margin:8px 0 0">${c.tafsir}</p></details>` : ''}
    ${c.surah.pengantar ? html`<details class="card"><summary class="k muted">Pengantar Surah ${c.surah.latin} (Kemenag)</summary><p class="sub" style="white-space:pre-wrap;margin:8px 0 0">${c.surah.pengantar}</p></details>` : ''}
    <span class="small">Sumber: ${c.sumber}. Teks Al-Qur'an, terjemahan, dan tafsir tidak ditulis AI.</span>
    <button class="btn" data-close="">Tutup</button></div>`;
}

function summaryView(r) {
  if (!r) return html`<p class="small" data-wait>Membaca Tafsir Kemenag…</p>`;
  if (!r.ada) return html`<p class="sub" style="margin:0">Tafsir Kemenag tidak menyebut sebab turun khusus untuk ayat ini.</p>${r.peristiwa ? html`<p class="sub" style="margin:0">${r.peristiwa}</p>` : ''}
    <span class="small">Ringkasan dari teks Tafsir Kemenag di bawah — tidak menambah riwayat.</span>`;
  return html`<p class="sub" style="margin:0">${r.sebab}</p>
    ${r.peristiwa ? html`<p class="sub" style="margin:0"><b>Rasulullah saw saat itu:</b> ${r.peristiwa}</p>` : ''}
    ${r.waktu ? html`<p class="sub" style="margin:0"><b>Waktu/tempat:</b> ${r.waktu}</p>` : ''}
    ${r.riwayat ? html`<span class="small">Riwayat yang disebut tafsir: ${r.riwayat}</span>` : ''}
    <span class="small">Ringkasan (AI) hanya dari teks Tafsir Kemenag di bawah — bacalah teks aslinya.</span>`;
}

async function reader(root, n, startAyah, autoplay) {
  const [s, qs] = await Promise.all([get(`/api/v1/app/quran/surah/${n}`), get('/api/v1/app/settings/quran')]);
  surahNo = n; surahName = s.latin; ayat = s.ayat; showArti = qs.translation !== false; mode = MODES[qs.read_mode] ? qs.read_mode : 'arab';
  root.innerHTML = String(html`${header(s.latin, { sub: `${s.arti} · ${s.jumlah} ayat · ${s.tempat} · ${s.qari}`, right: html`<span class="ar" style="font-size:24px;padding-right:12px;color:var(--green-t)">${s.nama}</span>` })}
    <div class="scr">
      <div class="chips"><button class="chip cyan" data-act="play" data-i="0">${icon('play', 14)} Dengarkan dari awal</button>
        <button class="chip ${repeat > 1 ? 'cyan' : ''}" data-act="repeat">${repeat > 1 ? `ulang ${repeat}× (hafalan)` : 'ulang 1×'}</button>
        <button class="chip" data-act="stop">${icon('stop', 14)} Berhenti</button>
        <button class="chip ${showArti ? 'cyan' : ''}" data-act="arti">${showArti ? '✓ terjemahan' : '+ terjemahan'}</button></div>
      <div class="chips" role="radiogroup" aria-label="Yang dibacakan">${Object.entries(MODES).map(([k, v]) => html`<button class="chip ${mode === k ? 'cyan' : ''}" data-act="mode" data-m="${k}" role="radio" aria-checked="${mode === k}">${icon(k === 'arab' ? 'quran' : 'speaker', 13)} ${v}</button>`)}</div>
      <span class="small" style="margin-top:-6px">Terjemahan Kemenag dibacakan suara bawaan ${host.has('speakLocal') ? 'HP' : 'perangkat'} — bukan suara AI.</span>
      ${n !== 1 && n !== 9 ? html`<p class="ar" style="text-align:center">بِسْمِ اللّٰهِ الرَّحْمٰنِ الرَّحِيْمِ</p>` : ''}
      ${s.ayat.map((a, i) => html`<div class="card ayah" id="a${a.n}" style="gap:10px">
        <div class="row sb wrap" style="gap:6px"><span class="tag green">${n}:${a.n} · juz ${a.juz}</span>
          <div class="row wrap" style="gap:4px;justify-content:flex-end"><button class="ib sm" data-act="play" data-i="${i}" aria-label="Putar dari ayat ini">${icon('play', 14)}</button>
          <button class="ib sm" data-act="sayArti" data-i="${i}" aria-label="Bacakan terjemahan ayat ini">${icon('speaker', 14)}</button>
          <button class="btn sm" data-act="ctx" data-a="${a.n}">Konteks</button>
          <button class="btn sm" data-act="mark" data-a="${a.n}" aria-label="Tandai sampai ayat ini">Tandai</button></div></div>
        <p class="ar">${a.arab}</p>
        <p class="small" style="font-style:italic">${a.latin}</p>
        <p class="sub arti" ${showArti ? '' : 'hidden'}>${a.arti}</p></div>`)}
      <div class="btns">${s.nomor > 1 ? html`<a class="btn" href="#/quran/${s.nomor - 1}">← Surah sebelumnya</a>` : ''}${s.nomor < 114 ? html`<a class="btn" href="#/quran/${s.nomor + 1}">Surah berikutnya →</a>` : ''}</div>
    </div>`);
  const style = document.createElement('style');
  style.textContent = '.ayah.on{border-color:var(--green);background:var(--green-bg)}';
  root.append(style);
  if (startAyah) setTimeout(() => $(`#a${startAyah}`)?.scrollIntoView({ block: 'center' }), 50);
  if (autoplay) setTimeout(() => playFrom(Math.max(0, ayat.findIndex((a) => a.n === (startAyah || 1)))), 300);
}

export default {
  tab: 'beranda',
  feature: 'quran',
  async render(root, route) {
    stop();
    root.innerHTML = String(html`${header("Al-Qur'an")}<div class="scr">${loading()}</div>`);
    if (route.params[0]) { await reader(root, Number(route.params[0]), Number(route.query.ayah) || 0, !!route.query.play); return () => stop(); }
    const { progress: p, surahs, qari } = await get('/api/v1/app/quran');
    root.innerHTML = String(html`${header("Al-Qur'an")}<div class="scr">
      ${p.last ? html`<a class="card green pad" href="#/quran/${p.last.surah}?ayah=${p.last.ayah}" style="border-width:1.5px;border-color:var(--green)">
        <div class="row sb"><div style="display:flex;flex-direction:column;gap:4px"><span class="k green">Terakhir dibaca</span>
          <span style="font:600 22px var(--f-head)">${p.last.latin} · ayat ${p.last.ayah}</span><span class="small">Surah ${p.last.surah} · Juz ${p.last.juz} · halaman ±${p.last.page}</span></div>
          <span class="ar" style="font-size:30px;color:var(--green-t)">${p.last.nama}</span></div>
        <div class="btns"><span class="btn green">Lanjut baca</span><button class="btn" data-act="listen" data-s="${p.last.surah}" data-a="${p.last.ayah}">${icon('play', 16)} Dengarkan</button></div></a>`
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
    repeat(b) {   // in place: re-rendering would stop the recitation
      repeat = repeat === 1 ? 3 : 1;
      b.classList.toggle('cyan', repeat > 1); b.textContent = repeat > 1 ? `ulang ${repeat}× (hafalan)` : 'ulang 1×';
    },
    async arti(b) {
      showArti = !showArti;
      document.querySelectorAll('.arti').forEach((e) => { e.hidden = !showArti; });
      b.classList.toggle('cyan', showArti); b.textContent = showArti ? '✓ terjemahan' : '+ terjemahan';
      await put('/api/v1/app/settings/quran', { translation: showArti });
    },
    mode(b) {   // in place, like the repeat chip: re-rendering would stop the recitation
      mode = b.dataset.m;
      document.querySelectorAll('[data-act="mode"]').forEach((x) => { const on = x.dataset.m === mode; x.classList.toggle('cyan', on); x.setAttribute('aria-checked', String(on)); });
      put('/api/v1/app/settings/quran', { read_mode: mode }).catch(() => {});
    },
    async sayArti(b) {
      stop();
      const a = ayat[Number(b.dataset.i)];
      if (a) { document.getElementById(`a${a.n}`)?.classList.add('on'); await sayLocal(spokenArti(a)); document.getElementById(`a${a.n}`)?.classList.remove('on'); }
    },
    async ctx(b) {
      const n = Number(b.dataset.a);
      let c;
      try { c = await get(`/api/v1/app/quran/context/${surahNo}/${n}`); } catch (e) { toast(e.message || 'Konteks belum bisa diambil.', true); return; }
      sheet(String(contextView(c)), {
        async onOpen(wrap) {
          if (c.ringkasan || !c.tafsir) { if (!c.tafsir) wrap.querySelector('#qsum').innerHTML = String(html`<span class="k violet">Sebab turun ayat ini</span><p class="small">Tafsir ayat ini belum tersedia.</p>`); return; }
          try {
            const r = await post(`/api/v1/app/quran/context/${surahNo}/${n}/summary`);
            const box = wrap.querySelector('#qsum');
            if (box) box.innerHTML = String(html`<span class="k violet">Sebab turun ayat ini</span>${summaryView(r)}`);
          } catch (e) {
            const w = wrap.querySelector('#qsum [data-wait]');
            if (w) w.textContent = 'Ringkasan belum bisa dibuat sekarang — coba lagi nanti. Teks tafsir lengkapnya ada di bawah.';
          }
        },
      });
    },
    listen(b, e) { e?.preventDefault(); e?.stopPropagation(); location.hash = `#/quran/${b.dataset.s}?ayah=${b.dataset.a}&play=1`; },
    async mark(b) { const p = await post('/api/v1/app/quran/read', { surah: surahNo, ayah: Number(b.dataset.a) }); toast(`Ditandai: ${surahNo}:${b.dataset.a} · khatam ${p.pct}%`); },
  },
};
