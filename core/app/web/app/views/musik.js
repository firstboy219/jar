// Musik (owner 2026-10-31: "siapkan management lagunya seperti Spotify"): his COLLECTION of downloaded songs played from local files (all,
// shuffled, from a song on; liked; deleted; into a playlist), FINDING new songs (a mood or a search → a list he ticks → downloaded into the
// collection), and his PLAYLISTS. Everything plays in the phone's music service (every screen, screen off, lock-screen controls).
import { $, del, get, header, html, icon, loading, on, post, put, render, sheet, toast } from '../core.js';
import { itemCard, needActions } from '../needsui.js';

const MOOD_ICON = { fokus: 'bulb', semangat: 'bolt', olahraga: 'heart', santai: 'coffee', tidur: 'moon' };
const STATUS = { antri: ['amber', 'menunggu unduh'], unduh: ['cyan', 'mengunduh…'], gagal: ['red', 'gagal'] };
let st = null, lib = null, tab = 'koleksi', q = '', onlyLiked = false;
const mmss = (s) => (s ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '');
const mb = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round((b || 0) / 1e6)} MB`);

function visible() {   // what "Putar semua" / a tapped song plays: the list as he sees it
  const k = q.trim().toLowerCase();
  return lib.songs.filter((s) => (!onlyLiked || s.liked) && (!k || `${s.title} ${s.artist}`.toLowerCase().includes(k)));
}

function collection() {
  const songs = visible();
  const ready = songs.filter((s) => s.status === 'siap');
  const d = lib.downloader;
  return html`
    <div class="card" style="gap:6px"><div class="row sb"><span class="k cyan">Koleksi</span><span class="small">${lib.count} lagu siap · ${mb(lib.bytes)}</span></div>
      ${lib.waiting ? html`<span class="small">${icon('repeat', 12)} ${lib.waiting} lagu sedang/menunggu diunduh…</span>` : ''}
      ${!d.cookies && !d.converter ? html`<span class="small" style="color:var(--amber-t)">Tanpa cookies YouTube, lagu dicari di SoundCloud (tidak semua ada). Agar semua lagu bisa diunduh langsung dari YouTube, unggah cookies di bagian Pengunduh.</span>` : ''}
      <div class="btns"><button class="btn primary" data-act="playall" ${ready.length ? '' : 'disabled'}>${icon('play', 16)} Putar semua</button>
        <button class="btn" data-act="shuffleall" ${ready.length ? '' : 'disabled'}>${icon('repeat', 16)} Acak</button></div></div>
    <div class="row" style="gap:8px"><label class="cmd grow" style="height:42px">${icon('search', 16, 'var(--mu)')}<input id="libq" value="${q}" placeholder="Cari di koleksi…"></label>
      <button class="chip ${onlyLiked ? 'on' : ''}" data-act="liked">♥ Disukai</button></div>
    ${songs.length ? html`<div class="list" id="libl">${songs.map((s) => html`<div class="li ${s.status === 'siap' ? 'click' : ''}" data-name="${`${s.title} ${s.artist}`.toLowerCase()}" ${s.status === 'siap' ? html`data-act="playone" data-id="${s.id}"` : ''} style="gap:10px">
      ${s.cover ? html`<img src="${s.cover}" alt="" loading="lazy" referrerpolicy="no-referrer" style="width:52px;height:30px;object-fit:cover;border-radius:6px;flex:0 0 52px">` : html`<span class="ico">${icon('music', 16)}</span>`}
      <div class="grow" style="min-width:0"><div style="font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.title}</div>
        <div class="small">${s.artist}${s.duration_s ? ` · ${mmss(s.duration_s)}` : ''}${s.plays ? ` · ${s.plays}× diputar` : ''}
          ${STATUS[s.status] ? html` · <span style="color:var(--${STATUS[s.status][0]}-t)">${STATUS[s.status][1]}</span>` : ''}</div>
        ${s.status === 'gagal' && s.error ? html`<div class="small" title="${s.error}" style="color:var(--red-t);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${/cookies/.test(s.error) ? 'tidak ada di SoundCloud — perlu cookies YouTube' : s.error}</div>` : ''}</div>
      ${s.status === 'gagal' ? html`<button class="chip" data-act="retry" data-id="${s.id}">Ulangi</button>` : ''}
      <button class="ib sm" data-act="like" data-id="${s.id}" aria-label="${s.liked ? 'Batal suka' : 'Suka'}" style="color:${s.liked ? 'var(--red)' : 'var(--mu)'}">${s.liked ? '♥' : '♡'}</button>
      <button class="ib sm" data-act="songmenu" data-id="${s.id}" aria-label="Pilihan lagu">⋯</button></div>`)}</div>`
      : html`<div class="card"><p class="sub">${lib.songs.length ? 'Tidak ada lagu yang cocok.' : 'Koleksimu masih kosong. Buka tab Cari lagu: pilih suasana atau cari penyanyi, centang lagunya — JARVIS mengunduhnya ke sini.'}</p></div>`}
    <details class="card"><summary class="small">Pengunduh</summary>
      <p class="small">YouTube menolak alamat server ini tanpa sesi masuk, jadi pengunduh memakai cookies akun YouTube-mu (sebaiknya akun cadangan — akun yang dipakai dari server bisa dibatasi YouTube).
        Pasang ekstensi browser <b>"Get cookies.txt LOCALLY"</b>, buka youtube.com dalam keadaan masuk, ekspor cookies.txt, lalu tempel isinya di sini. Disimpan terenkripsi.</p>
      <span class="small">Status: ${d.converter ? 'converter aktif · ' : ''}${d.cookies ? `cookies terpasang${d.since ? ` (${new Date(d.since).toLocaleDateString('id-ID')})` : ''}` : 'cookies belum ada'}</span>
      <form id="ckf" style="display:flex;flex-direction:column;gap:8px"><textarea name="text" rows="4" placeholder="# Netscape HTTP Cookie File …" style="font-family:var(--f-mono);font-size:11px"></textarea>
        <div class="btns"><button class="btn sm primary" data-act="cookies">Simpan cookies</button>${d.cookies ? html`<button type="button" class="btn sm" data-act="nocookies">Hapus cookies</button>` : ''}</div></form></details>`;
}

function finder(s) {
  const u = s.usual;
  return html`
    ${s.pick ? itemCard({ kind: 'lagu', id: s.pick.id, title: `Pilih lagu: ${s.pick.query}`, sub: `${s.pick.options.length} lagu · centang yang mau disimpan ke koleksi`, icon: 'music', options: s.pick.options }) : ''}
    <button class="card violet" data-act="mood" data-m="${u.mood}" style="text-align:left;cursor:pointer"><span class="k violet">Untuk jam segini</span>
      <span class="ttl" style="font-size:20px">${icon(MOOD_ICON[u.mood] || 'music', 20)} ${u.mood}</span><span class="small">${u.why} · ketuk untuk menyusun daftar lagunya</span></button>
    <div class="g3">${Object.keys(s.moods).map((m) => html`<button class="tile" data-act="mood" data-m="${m}" style="padding:14px 8px;display:flex;flex-direction:column;align-items:center;gap:6px;background:var(--s1);border:1px solid var(--bd);border-radius:14px;cursor:pointer">
      ${icon(MOOD_ICON[m] || 'music', 22)}<span style="font-size:13px">${m}</span></button>`)}</div>
    <form class="cmd" id="mq" style="display:flex"><input name="q" placeholder="Penyanyi, judul, atau gaya — mis. lagu galau 2000-an" style="flex:1"><button class="ib sm" data-act="search" aria-label="Cari">${icon('search', 18)}</button></form>
    <form class="card" id="mp3f" style="gap:8px"><span class="k cyan">Tempel link YouTube / YouTube Music</span>
      <div class="row" style="gap:8px"><input name="url" inputmode="url" placeholder="music.youtube.com/watch?v=… atau youtu.be/…" style="flex:1;min-width:0">
        <button class="btn sm" data-act="mp3">Simpan ke koleksi</button></div></form>
    <details class="card"><summary class="small">Permintaan tiap suasana</summary>
      <form id="moodf" style="display:flex;flex-direction:column;gap:8px">${Object.entries(s.moods).map(([m, v]) => html`<label class="field">${m}<input name="${m}" value="${v}"></label>`)}
      <button class="btn" data-act="savemoods">Simpan</button></form>
      <span class="small">Tulis bebas, mis. "lagu indo seperti Tulus, Hindia". JARVIS menyusun ±20 lagu nyata dari sini.</span></details>`;
}

function lists(s) {
  return html`${s.playlists.length ? html`<div class="list">${s.playlists.map((p) => html`<div class="li" style="gap:10px"><span class="ico violet">${icon('list', 18)}</span>
      <div class="grow"><div class="ttl">${p.name}</div><div class="small">${p.count ?? p.songs ?? ''} lagu · lagu yang ada di koleksi diputar dari file lokal</div></div>
      <button class="ib sm" data-act="playlist" data-n="${p.name}" aria-label="Putar">${icon('play', 16)}</button><button class="ib sm" data-act="shuffle" data-n="${p.name}" aria-label="Acak">${icon('repeat', 16)}</button></div>`)}</div>`
    : html`<div class="card"><p class="sub">Belum ada playlist. Dari Koleksi, ketuk ⋯ pada lagu → Tambah ke playlist.</p></div>`}`;
}

export default {
  tab: 'beranda',
  feature: 'musik',
  async render(root, route) {
    if (route?.query?.pilih) tab = 'cari';
    root.innerHTML = String(html`${header('Musik')}<div class="scr">${loading()}</div>`);
    [st, lib] = await Promise.all([get('/api/v1/app/music'), get('/api/v1/app/music/library')]);
    const s = st;
    root.innerHTML = String(html`${header('Musik', { sub: s.now ? `diputar: ${s.now.title}` : `${lib.count} lagu di koleksi` })}
      <div class="scr">
        <div class="chips">${[['koleksi', `Koleksi (${lib.count})`], ['cari', 'Cari lagu'], ['playlist', 'Playlist']].map(([k, v]) => html`<button class="chip ${tab === k ? 'on' : ''}" data-act="tab" data-t="${k}">${v}</button>`)}</div>
        ${s.now ? html`<div class="card amber" style="gap:6px"><div class="row sb"><div style="min-width:0"><span class="k amber">Sedang diputar</span><div class="ttl">${s.now.title}</div><div class="small">${s.now.artist || ''}</div></div></div>
          <div class="btns"><button class="btn sm" data-act="ctl" data-a="prev" aria-label="Sebelumnya">⏮</button><button class="btn sm" data-act="ctl" data-a="stop" aria-label="Berhenti">${icon('stop', 14)}</button><button class="btn sm" data-act="ctl" data-a="next" aria-label="Berikutnya">⏭</button></div></div>` : ''}
        ${tab === 'koleksi' ? collection() : tab === 'cari' ? finder(s) : lists(s)}
      </div>`);
    $('#libq', root)?.addEventListener('input', (e) => {   // filter the rows in place (no reload while typing)
      q = e.target.value; const k = q.trim().toLowerCase();
      root.querySelectorAll('#libl [data-name]').forEach((r) => { r.hidden = !!k && !r.dataset.name.includes(k); });
    });
    const offs = [on('stage', (e) => { if (['music', 'audio'].includes(e.panel)) setTimeout(render, 400); }), on('music_library', () => setTimeout(render, 300))];
    return () => offs.forEach((f) => f());
  },
  actions: {
    ...needActions,   // ticking the songs (and Batal) right here
    tab(b) { tab = b.dataset.t; render(); },
    liked() { onlyLiked = !onlyLiked; render(); },
    async playall() { const ids = visible().filter((s) => s.status === 'siap').map((s) => s.id); const r = await post('/api/v1/app/music/library/play', { ids }); toast(`▶ ${r.playing} · ${r.total} lagu`); },
    async shuffleall() { const ids = visible().filter((s) => s.status === 'siap').map((s) => s.id); const r = await post('/api/v1/app/music/library/play', { ids, shuffle: true }); toast(`🔀 ${r.playing}`); },
    async playone(b, e) {
      if (e?.target?.closest('[data-act="like"],[data-act="songmenu"],[data-act="retry"]')) return;
      const ids = visible().filter((s) => s.status === 'siap').map((s) => s.id);
      const r = await post('/api/v1/app/music/library/play', { ids, start: ids.indexOf(Number(b.dataset.id)) });
      toast(`▶ ${r.playing}`);
    },
    async like(b, e) { e?.stopPropagation?.(); await post(`/api/v1/app/music/library/${b.dataset.id}/like`); render(); },
    async retry(b, e) { e?.stopPropagation?.(); await post(`/api/v1/app/music/library/${b.dataset.id}/retry`); toast('Diunduh ulang'); render(); },
    async songmenu(b, e) {
      e?.stopPropagation?.();
      const s = lib.songs.find((x) => String(x.id) === b.dataset.id);
      const names = st.playlists.map((p) => p.name);
      const v = await sheet(String(html`<div style="display:flex;flex-direction:column;gap:10px"><span class="ttl">${s.title}</span><span class="small">${s.artist}</span>
        ${names.map((n) => html`<button class="btn" data-close="pl:${n}">${icon('plus', 14)} Tambah ke ${n}</button>`)}
        <button class="btn" data-close="new">${icon('plus', 14)} Playlist baru…</button>
        <button class="btn danger" data-close="del">Hapus dari koleksi (file ikut dihapus)</button><button class="btn" data-close="">Batal</button></div>`));
      if (!v) return;
      if (v === 'del') { await del(`/api/v1/app/music/library/${s.id}`); toast('Dihapus dari koleksi'); render(); return; }
      let name = v.startsWith('pl:') ? v.slice(3) : null;
      if (v === 'new') {
        const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:10px"><label class="field">Nama playlist<input name="n" required maxlength="80"></label><button class="btn primary">Buat & tambahkan</button></form>`));
        if (!r?.n) return; name = r.n;
      }
      await post(`/api/v1/app/music/library/${s.id}/playlist`, { name }); toast(`Ditambahkan ke ${name}`); render();
    },
    async cookies(b, e) {
      e?.preventDefault();
      const text = new FormData($('#ckf')).get('text');
      if (!text) return toast('Tempel isi cookies.txt dulu.', true);
      try { await put('/api/v1/app/music/library/cookies', { text }); toast('Cookies tersimpan — lagu yang gagal diunduh ulang'); render(); }
      catch (err) { toast(err.message || 'Gagal menyimpan', true); }
    },
    async nocookies() { await del('/api/v1/app/music/library/cookies'); toast('Cookies dihapus'); render(); },
    async mood(b) { toast(`Menyusun daftar lagu ${b.dataset.m}… (±20 detik)`); const r = await post('/api/v1/app/music/play', { mood: b.dataset.m }); toast(`${r.count} lagu — centang yang mau disimpan`); tab = 'cari'; render(); },
    async search(b, e) { e?.preventDefault(); const v = new FormData($('#mq')).get('q'); if (!v) return; toast('Menyusun daftar lagu…'); const r = await post('/api/v1/app/music/play', { query: v }); toast(`${r.count} lagu — centang yang mau disimpan`); render(); },
    async playlist(b) { const r = await post('/api/v1/app/music/playlist', { name: b.dataset.n }); toast(`▶ ${r.song?.title || r.playing || 'diputar'}`); },
    async shuffle(b) { const r = await post('/api/v1/app/music/playlist', { name: b.dataset.n, shuffle: true }); toast(`🔀 ${r.song?.title || r.playing || 'diputar'}`); },
    async mp3(b, e) {
      e?.preventDefault();
      const url = new FormData($('#mp3f')).get('url');
      if (!url) return toast('Tempel link YouTube dulu.', true);
      try { const r = await post('/api/v1/app/music/library/link', { url }); toast(`${r.title} masuk koleksi — sedang diunduh`); tab = 'koleksi'; render(); }
      catch (err) { toast(err.message || 'Gagal', true); }
    },
    async ctl(b) { await post(`/api/v1/app/music/${b.dataset.a}`); setTimeout(render, 600); },
    async savemoods(b, e) { e?.preventDefault(); await put('/api/v1/app/settings/music', { moods: Object.fromEntries(new FormData($('#moodf')).entries()) }); toast('Tersimpan'); render(); },
  },
};
