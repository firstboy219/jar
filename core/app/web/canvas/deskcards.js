// The desk's feature cards (ADR-054): the player (music / sound / video JARVIS puts on the screen) and the meeting recorder, as cards on the
// infinite canvas — what "putar lagu" and "mulai rapat" show here. They are driven by the server's state (the desk poll), so a reload, the
// phone app and a browser all show the same thing; the camera flies to a card when it appears (app.js).
import { mmss, playerSource, stopRaised } from './lib.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn) => { const b = el('button', cls, text); b.dataset.gesture = 'ok'; b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(ev); }); return b; };
const field = (label, value = '', ph = '') => {
  const w = el('label', 'mfield'), i = el('input'); i.value = value; i.placeholder = ph; i.autocomplete = 'off';
  i.addEventListener('keydown', (e) => e.stopPropagation());   // typing never triggers a desk shortcut
  w.append(el('span', null, label), i); return { w, i };
};
const check = (label) => { const w = el('label', 'mcheck'), c = el('input'); c.type = 'checkbox'; w.append(c, el('span', null, label)); return { w, c }; };

// ---------------------------------------------------------------- player

export function createPlayerCard({ box, api, send, toast }) {
  let id = null, mediaUrl = null, watcher = null, ended = false;
  box.replaceChildren();
  const kind = el('div', 'kind', 'meja · pemutar'), head = el('div', 'title'), sub = el('div', 'snippet'), body = el('div', 'pbody'), ctl = el('div', 'pctl');
  box.append(kind, head, sub, body, ctl);

  function teardown() {
    clearInterval(watcher); watcher = null;
    if (mediaUrl) { URL.revokeObjectURL(mediaUrl); mediaUrl = null; }
    body.replaceChildren(); ctl.replaceChildren(); id = null; ended = false;
  }
  const event = (name) => send({ type: 'stage_event', id, event: name });

  async function blobUrl(url) {
    const r = await fetch(url, { headers: { Authorization: `Bearer ${api.token}` } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return URL.createObjectURL(await r.blob());
  }

  async function mount(p, mine) {
    const src = playerSource(p);
    if (p.cover_url?.startsWith('https://') && src.kind !== 'youtube' && src.kind !== 'video') { const c = el('img', 'pcover'); c.src = p.cover_url; c.alt = ''; body.append(c); }
    if (src.kind === 'youtube') {
      const f = el('iframe', 'pframe'); f.src = `/embed/youtube/${src.id}?autoplay=1`;
      f.allow = 'autoplay; encrypted-media; fullscreen'; f.allowFullscreen = true; f.title = p.title;
      body.append(f);
      watcher = setInterval(() => {   // our own embed page tells its state in its title (the same trick the phone uses)
        let t = ''; try { t = f.contentDocument?.title || ''; } catch { /* not ours yet */ }
        if (t === 'ended' && !ended) { ended = true; event('ended'); }
        else if (t.startsWith('error:')) sub.textContent = 'Pemutar YouTube tidak bisa memutar ini.';
      }, 1000);
    } else if (src.kind === 'audio' || src.kind === 'video') {
      const m = el(src.kind === 'video' ? 'video' : 'audio', 'pmedia'); m.controls = true; m.playsInline = true; m.preload = 'auto';
      body.append(m);
      try { m.src = src.auth ? await blobUrl(src.url) : src.url; } catch (err) { if (id === mine) sub.textContent = `Tidak bisa memuat: ${err.message}`; return; }
      if (id !== mine) { if (src.auth) URL.revokeObjectURL(m.src); return; }
      if (src.auth) mediaUrl = m.src;
      m.addEventListener('ended', () => event('ended'));
      m.play().catch(() => toast('Ketuk ▶ pada pemutar untuk mulai memutar.'));
    } else body.append(el('div', 'snippet', 'Jenis ini belum bisa diputar di meja.'));
  }

  return {
    /** The server's player (or null). Returns whether the card should be on the desk. */
    update(p) {
      if (!p) { if (id) teardown(); return false; }
      if (p.id !== id) {
        teardown(); id = p.id;
        head.textContent = p.title || '(tanpa judul)'; sub.textContent = p.artist || p.caption || '';
        const pl = p.playlist, pos = pl && Number.isFinite(pl.index) && Number.isFinite(pl.total) ? `${pl.index + 1}/${pl.total}` : '';
        if (pl) ctl.append(button('⏮', 'pbtn', () => event('prev')), el('span', 'plabel', `${pl.name || 'Playlist'} ${pos}`.trim()), button('⏭', 'pbtn', () => event('next')));
        ctl.append(button('✕ Tutup', 'pbtn pclose', () => event('closed')));
        mount(p, id);
      }
      return true;
    },
  };
}

// ---------------------------------------------------------------- meeting

/** Records in a browser: one independent WebM/Opus file per minute (a MediaRecorder file is only playable from its first piece), uploaded as
 *  they are made, then "finish" so the server writes the minutes. In the phone app the phone's own recorder does this (the server tells it). */
function browserRecorder(api) {
  let stream = null, rec = null, cut = null, id = null, n = 0, t0 = 0, stopping = false, ctx = null, analyser = null, buf = null, pending = [];
  const mime = () => ['audio/webm;codecs=opus', 'audio/webm'].find((t) => window.MediaRecorder?.isTypeSupported(t));
  const guard = (e) => { e.preventDefault(); e.returnValue = ''; };

  async function put(k, blob) {
    for (let a = 0; a < 4; a++) {
      try {
        const r = await fetch(`/api/v1/meetings/${id}/chunks/${k}?ext=webm`, { method: 'PUT', headers: { Authorization: `Bearer ${api.token}` }, body: blob });
        if (r.ok) return;
      } catch { /* network: try again */ }
      await new Promise((ok) => setTimeout(ok, 1500 * 2 ** a));
    }
    throw new Error(`potongan ${k} gagal diunggah`);
  }
  function cycle() {
    const parts = [];
    rec = new MediaRecorder(stream, { mimeType: mime(), audioBitsPerSecond: 32000 });
    rec.ondataavailable = (e) => { if (e.data.size) parts.push(e.data); };
    rec.onstop = () => {
      if (parts.length) pending.push(put(n++, new Blob(parts, { type: 'audio/webm' })));
      if (!stopping) cycle(); else done();
    };
    rec.start();
    cut = setTimeout(() => { if (rec.state === 'recording') rec.stop(); }, 60_000);
  }
  let finished = null;
  async function done() {
    try {
      await Promise.all(pending);
      await api.req('POST', `/api/v1/meetings/${id}/finish`, { duration_s: (Date.now() - t0) / 1000, chunks: n });
      finished?.resolve();
    } catch (err) { finished?.reject(err); }
    release();
  }
  function release() {
    clearTimeout(cut); stream?.getTracks().forEach((t) => t.stop()); ctx?.close().catch(() => {});
    removeEventListener('beforeunload', guard);
    stream = rec = ctx = analyser = null; id = null; pending = [];
  }
  return {
    get active() { return !!id; },
    get id() { return id; },
    get level() {
      if (!analyser) return 0;
      analyser.getByteTimeDomainData(buf);
      let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
      return Math.min(1, peak / 64);
    },
    async start(body) {
      if (!window.MediaRecorder || !mime()) throw new Error('Browser ini belum bisa merekam suara. Pakai aplikasi JARVIS di HP.');
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: true, channelCount: 1 } });
      try {
        const m = await api.req('POST', '/api/v1/meetings', body);
        id = m.id; n = 0; t0 = Date.now(); stopping = false; pending = [];
      } catch (err) { stream.getTracks().forEach((t) => t.stop()); throw err; }
      ctx = new AudioContext(); analyser = ctx.createAnalyser(); analyser.fftSize = 512; buf = new Uint8Array(analyser.fftSize);
      ctx.createMediaStreamSource(stream).connect(analyser);
      addEventListener('beforeunload', guard);
      cycle();
      return id;
    },
    stop() {
      if (!id || stopping) return Promise.resolve();
      stopping = true; clearTimeout(cut);
      return new Promise((resolve, reject) => { finished = { resolve, reject }; if (rec?.state === 'recording') rec.stop(); else done(); });
    },
  };
}

export function createMeetingCard({ box, api, toast, embedded }) {
  const recorder = browserRecorder(api);
  let key = null, seenStop = null, skew = 0, m = null, busy = false, draft = null, dismissed = new Set();
  const kind = el('div', 'kind', 'meja · rapat'), head = el('div', 'title'), body = el('div', 'mbody');
  box.replaceChildren(kind, head, body);
  let timer = null, level = null;
  const serverNow = () => Date.now() / 1000 + skew;

  function render() {
    body.replaceChildren(); level = null; timer = null;
    kind.textContent = 'meja · rapat';
    if (m.state === 'waiting') {
      head.textContent = 'Siap merekam rapat';
      const d = draft || { title: m.title, participants: (m.participants || []).join(', '), agenda: m.agenda, confidential: m.confidential };
      const title = field('Judul', d.title, 'mis. Rapat anggaran'), who = field('Peserta', d.participants, 'nama, pisahkan koma'), agenda = field('Agenda', d.agenda, 'topik / istilah (opsional)');
      const conf = check('Rahasia (diproses hanya di server sendiri)'); conf.c.checked = !!d.confidential;
      const ok = check('Semua peserta sudah tahu dan setuju rapat ini direkam.');
      const go = button('● Mulai rekam', 'mgo', () => start({ title: title.i.value, participants: who.i.value, agenda: agenda.i.value, confidential: conf.c.checked }));
      go.disabled = true; ok.c.addEventListener('change', () => { go.disabled = !ok.c.checked; });
      body.append(title.w, who.w, agenda.w, conf.w, ok.w, go, el('div', 'snippet', embedded ? 'HP yang merekam (mikrofon aplikasi).' : 'Browser ini yang merekam (mikrofon komputer).'));
      if (busy) { go.disabled = true; go.textContent = 'Menunggu HP mulai merekam…'; }
    } else if (m.state === 'recording') {
      head.textContent = m.title || 'Rapat';
      kind.textContent = '● MEREKAM'; kind.classList.add('rec');
      timer = el('div', 'mtimer', mmss(serverNow() - m.started_at));
      const meter = el('div', 'mmeter'), fill = el('i'); meter.append(fill); level = fill;
      const stop = button('■ Stop & buat notulen', 'mstop', stopNow);
      const row = el('div', 'pctl'); row.append(button('⭐ Tandai penting', 'pbtn', mark));
      body.append(timer, ...(recorder.active ? [meter] : []), el('div', 'snippet', `Potongan terunggah: ${m.chunks ?? 0}${m.confidential ? ' · rahasia' : ''}`), row, stop);
      if (!recorder.active) body.append(el('div', 'snippet', embedded ? 'Direkam oleh HP ini.' : 'Direkam oleh perangkat lain (HP).'));
    } else if (m.state === 'processing') {
      head.textContent = m.title || 'Rapat';
      body.append(el('div', 'mstatus', { queued: 'Antre untuk diproses…', transcribing: 'Menyalin suara menjadi teks…', summarizing: 'Menyusun notulen…' }[m.status] || 'Memproses…'),
        el('div', 'snippet', 'JARVIS akan mengabari kalau notulennya siap.'));
    } else if (m.state === 'done') {
      head.textContent = m.title || 'Rapat'; kind.textContent = 'meja · rapat selesai';
      body.append(el('div', 'mstatus ok', 'Notulen siap.'));
      if (m.document_id) body.append(button('Buka notulen (.docx)', 'mgo', () => openDoc(m.document_id, m.title)));
      body.append(button('Sembunyikan', 'pbtn', () => { dismissed.add(key); box.hidden = true; }));
    } else {
      head.textContent = m.title || 'Rapat'; kind.textContent = 'meja · rapat gagal';
      body.append(el('div', 'mstatus bad', m.error || 'Rapat ini gagal diproses.'), button('Sembunyikan', 'pbtn', () => { dismissed.add(key); box.hidden = true; }));
    }
    if (m.state !== 'recording') kind.classList.remove('rec');
  }

  async function start(f) {
    const body = { title: f.title.trim(), confidential: f.confidential, consent: true, agenda: f.agenda.trim(),
      participants: f.participants.split(',').map((s) => s.trim()).filter(Boolean) };
    draft = f; busy = true; render();
    try {
      if (embedded) {
        const r = await api.req('POST', '/api/v1/meetings/start-request', body);
        if (!r.delivered) throw new Error('HP belum tersambung ke JARVIS — buka menu Rapat di aplikasi.');
        setTimeout(() => { if (busy) { busy = false; toast('HP belum mulai merekam. Cek izin mikrofon di aplikasi, atau buka menu Rapat.', true); if (m?.state === 'waiting') render(); } }, 15000);
      } else { await recorder.start(body); busy = false; toast('Merekam. Semua suara di sekitar komputer ini ikut terekam.'); }
    } catch (err) { busy = false; toast(err.message || 'Gagal memulai rekaman', true); if (m?.state === 'waiting') render(); }
  }
  async function stopNow() {
    try {
      if (recorder.active) { await recorder.stop(); toast('Rekaman selesai. Notulen sedang dibuat.'); }
      else { const r = await api.req('POST', '/api/v1/meetings/stop-request'); toast(r.stopping ? 'Perintah berhenti dikirim.' : 'Tidak ada rekaman yang berjalan.', !r.stopping); }
    } catch (err) { toast(err.message, true); }
  }
  async function mark() {
    const id = m?.id || recorder.id;
    if (!id) return;
    try { await api.req('POST', `/api/v1/meetings/${id}/marks`, { t: Math.max(0, serverNow() - m.started_at), note: 'penting' }); toast(`Ditandai di menit ${mmss(serverNow() - m.started_at)}`); }
    catch (err) { toast(err.message, true); }
  }
  async function openDoc(docId, title) {
    try {
      const r = await fetch(`/api/v1/documents/${docId}`, { headers: { Authorization: `Bearer ${api.token}` } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const a = el('a'); a.href = URL.createObjectURL(await r.blob()); a.download = `Notulen — ${title || 'rapat'}.docx`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    } catch (err) { toast(err.message, true); }
  }

  setInterval(() => {   // the running clock and the microphone level: no server round trip needed
    if (timer && m?.state === 'recording') timer.textContent = mmss(serverNow() - m.started_at);
    if (level) level.style.width = `${Math.round(Math.max(0.03, recorder.level) * 100)}%`;
  }, 250);

  return {
    /** The server's meeting card state (or null) and the server clock. Returns {show, key} — key changes when there is something new to look at. */
    update(next, now) {
      if (Number.isFinite(now)) skew = now - Date.now() / 1000;
      if (!next || dismissed.has(next.key)) { m = null; key = null; return { show: false, key: null }; }
      if (seenStop == null) seenStop = next.stop_seq;
      else if (stopRaised(seenStop, next.stop_seq)) { seenStop = next.stop_seq; if (recorder.active) stopNow(); }
      m = next;
      if (m.state === 'recording' || m.state === 'processing') busy = false;
      const fresh = next.key !== key || (m.state === 'recording' && !!body.querySelector('.mmeter') !== recorder.active);
      if (fresh) { if (next.key !== key) draft = null; key = next.key; render(); }
      return { show: true, key };
    },
  };
}
