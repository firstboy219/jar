// Obrolan (mockup 3): the conversation with JARVIS over the same live connection as the phone — replies stream in, a task asked here
// shows its progress and opens as a mission, results come back as cards.
import { $, get, header, host, html, icon, on, post, render, send, speak, toast } from '../core.js';
import { pick, upload } from '../upload.js';
import { clock } from '../lib.js';

const SKEY = 'jarvis_app_session';
const sid = () => {
  let s = ''; try { s = localStorage.getItem(SKEY) || ''; } catch { /* private mode */ }
  if (!s) { s = `app-${Math.random().toString(36).slice(2, 10)}`; try { localStorage.setItem(SKEY, s); } catch { /* ignore */ } }
  return s;
};

let log, typing, bubble = null, files = [];
const bars = new Map();
const ROUTE = { core: 'perintah langsung · tanpa AI', assistant: 'otak percakapan', blocked: 'ditahan', silent: '' };

function chips(list) {   // quick replies under JARVIS' last answer
  log.querySelector('.qchips')?.remove();
  if (!list.length) return;
  const d = document.createElement('div');
  d.className = 'chips qchips';
  d.innerHTML = String(html`${list.map(([label, act, val]) => html`<button class="chip" data-act="${act}" data-v="${val || label}">${label}</button>`)}`);
  log.append(d);
}

function reportCard(ev) {
  const m = document.createElement('div');
  m.className = 'msg jarvis card';
  m.innerHTML = String(html`<span class="k violet">${icon('check', 13)} Hasil misi</span><span class="sub" style="white-space:pre-wrap">${ev.text}</span>
    <div class="row" style="gap:6px;flex-wrap:wrap">${ev.task_id ? html`<a class="chip" href="#/misi/${ev.task_id}">Buka laporan</a>` : ''}<button class="chip" data-act="readText" data-v="${ev.text}">${icon('speaker', 13)} Bacakan</button></div>`);
  log.append(m);
  m.scrollIntoView({ block: 'end' });
}

function add(role, text, at) {
  const m = document.createElement('div');
  m.className = `msg ${role}`;
  m.textContent = text;
  if (at) m.title = clock(at);
  log.append(m);
  m.scrollIntoView({ block: 'end' });
  return m;
}

function setTyping(text) { typing.textContent = text || ''; typing.hidden = !text; }

function progress(ev) {
  let b = bars.get(ev.task_id);
  if (!b) {
    const m = document.createElement('a');
    m.className = 'msg jarvis card';
    m.href = `#/misi/${ev.task_id}`;
    m.innerHTML = String(html`<span class="ttl">${ev.title || 'Misi'}</span><div class="bar thin"><i class="violet" style="width:3%"></i></div><span class="small"></span>`);
    log.append(m);
    b = { m, fill: m.querySelector('i'), line: m.querySelector('.small') };
    bars.set(ev.task_id, b);
  }
  if (ev.pct == null) { b.fill.style.width = '100%'; b.fill.className = 'red'; b.line.textContent = ev.text; return; }
  b.fill.style.width = `${Math.max(3, Math.min(100, ev.pct))}%`;
  b.line.textContent = `${Math.round(ev.pct)}% · ${ev.text} · ketuk untuk lihat misinya`;
  b.m.scrollIntoView({ block: 'end' });
}

function say(text) {
  const t = String(text || '').trim() || (files.length ? 'Tolong lihat lampiran ini.' : '');
  if (!t) return false;
  add('user', files.length ? `${t}\n📎 ${files.map((f) => f.name).join(', ')}` : t);
  send({ user_command: t, session_id: sid(), ...(files.length ? { attachments: files.map((f) => f.id) } : {}) });
  files = []; paintFiles();
  bubble = null;
  chips([]);
  setTyping('JARVIS berpikir…');
  return true;
}

function paintFiles() {
  const el = document.getElementById('chatfiles');
  if (el) el.innerHTML = String(html`${files.map((f, i) => html`<span class="chip">📎 ${f.name}<button type="button" class="ib sm" data-act="unattach" data-i="${i}" aria-label="Buang">${icon('close', 12)}</button></span>`)}`);
}

function listenWeb() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Browser ini tidak mendukung suara. Pakai aplikasi JARVIS di HP, atau ketik.', true); return; }
  const r = new SR();
  r.lang = 'id-ID'; r.interimResults = false;
  setTyping('🎤 Mendengarkan…');
  r.onresult = (e) => say(e.results[0][0].transcript);
  r.onerror = () => setTyping('');
  r.onend = () => { if (typing.textContent.startsWith('🎤')) setTyping(''); };
  r.start();
}

export default {
  tab: 'obrolan',
  async render(root, route) {
    root.innerHTML = String(html`${header('Obrolan', { back: false, sub: 'percakapan dengan JARVIS', right: html`<button class="btn sm" data-act="fresh">Topik baru</button>` })}
      <div class="chat" id="log"></div><p class="typing" id="typing" hidden></p>
      <div class="chips" id="chatfiles" style="padding:0 16px"></div>
      <form class="chatbar" id="chatf" autocomplete="off">
        <button type="button" class="ib box" data-act="attach" aria-label="Lampirkan berkas" style="width:48px;height:48px;flex:none">${icon('upload', 18)}</button>
        <label class="cmd" style="height:48px"><input id="chatin" placeholder="Balas JARVIS…" enterkeyhint="send"></label>
        <button type="button" class="mic" style="width:48px;height:48px" data-act="mic" aria-label="Bicara">${icon('mic', 20)}</button>
      </form>`);
    log = $('#log', root); typing = $('#typing', root); bars.clear(); bubble = null;
    try {
      const { messages } = await get(`/api/v1/app/chat/history?session_id=${encodeURIComponent(sid())}`);
      if (!messages.length) add('sys', 'Tanya, minta, atau ajak ngobrol apa saja. Pekerjaan panjang jadi misi yang bisa kamu pantau.');
      for (const m of messages) add(m.role === 'user' ? 'user' : 'jarvis', m.content, m.created_at);
    } catch { add('sys', 'Riwayat belum bisa dimuat.'); }
    $('#chatf', root).addEventListener('submit', (e) => { e.preventDefault(); const i = $('#chatin', root); if (say(i.value)) i.value = ''; });
    const pending = sessionStorage.getItem('jarvis_app_pending');
    if (pending) { sessionStorage.removeItem('jarvis_app_pending'); say(pending); }
    if (route.query.mic) listenWeb();
    const mine = (ev) => !ev.session_id || ev.session_id === sid();
    const offs = [
      on('thought', (ev) => mine(ev) && setTyping(`💭 ${ev.text}`.slice(0, 140))),
      on('tool', (ev) => mine(ev) && setTyping(`🔧 ${ev.title || ev.name}${ev.label ? `: ${ev.label}` : ''}`.slice(0, 140))),
      on('delta', (ev) => { if (!mine(ev)) return; if (!bubble) bubble = add('jarvis', ''); bubble.textContent += ev.text; bubble.scrollIntoView({ block: 'end' }); }),
      on('reply', (ev) => {
        if (!mine(ev)) return;
        if (ev.text) {
          if (!bubble) bubble = add('jarvis', ev.text); else bubble.textContent = ev.text;
          if (ROUTE[ev.route]) { const s = document.createElement('span'); s.className = 'small'; s.textContent = ROUTE[ev.route]; s.style.display = 'block'; bubble.append(s); }
          chips([['Ringkas', 'quick', 'Ringkas jawabanmu tadi jadi 2 kalimat.'], ['Lebih detail', 'quick', 'Jelaskan lebih detail.'], ['Bacakan', 'readText', ev.text], ['Jadikan tugas', 'toTask', ev.text]]);
        }
        bubble = null; setTyping('');
      }),
      on('transcript', (ev) => { if (mine(ev) && ev.text) { add('user', `🎤 ${ev.text}`); setTyping('JARVIS berpikir…'); } }),
      on('progress', (ev) => { if (ev.session_id === sid()) progress(ev); }),
      on('report', (ev) => reportCard(ev)),
      on('proactive', (ev) => add('jarvis', `🔔 ${ev.text}`)),
      on('error', (ev) => { if (mine(ev)) { setTyping(''); toast(ev.message || 'Terjadi kesalahan', true); bubble = null; } }),
    ];
    return () => offs.forEach((f) => f());
  },
  actions: {
    fresh() {
      try { localStorage.removeItem(SKEY); } catch { /* ignore */ }
      render();
    },
    mic() { if (host.has('talk')) host.call('talk'); else listenWeb(); },
    async attach() {
      const picked = await pick({ multiple: true, accept: 'image/*,.pdf,.docx,.xlsx,.pptx,.txt,.csv' });
      if (!picked.length) return;
      toast('Mengunggah…');
      files = [...files, ...(await upload(picked.slice(0, 5 - files.length)))].slice(0, 5);
      paintFiles();
    },
    unattach(b) { files.splice(Number(b.dataset.i), 1); paintFiles(); },
    quick(b) { say(b.dataset.v); },
    readText(b) { speak(b.dataset.v); },
    async toTask(b) { await post('/api/v1/notes/tasks', { text: String(b.dataset.v).split('\n')[0].slice(0, 300) }); toast('Masuk ke Catatan sebagai tugas'); },
  },
};
