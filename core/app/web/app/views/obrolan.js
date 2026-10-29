// Obrolan (mockup 3): the conversation with JARVIS over the same live connection as the phone — replies stream in, a task asked here
// shows its progress and opens as a mission, results come back as cards.
import { $, get, header, host, html, icon, on, render, send, toast } from '../core.js';
import { clock } from '../lib.js';

const SKEY = 'jarvis_app_session';
const sid = () => {
  let s = ''; try { s = localStorage.getItem(SKEY) || ''; } catch { /* private mode */ }
  if (!s) { s = `app-${Math.random().toString(36).slice(2, 10)}`; try { localStorage.setItem(SKEY, s); } catch { /* ignore */ } }
  return s;
};

let log, typing, bubble = null;
const bars = new Map();

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
  const t = String(text || '').trim();
  if (!t) return false;
  add('user', t);
  send({ user_command: t, session_id: sid() });
  bubble = null;
  setTyping('JARVIS berpikir…');
  return true;
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
      <form class="chatbar" id="chatf" autocomplete="off">
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
      on('reply', (ev) => { if (!mine(ev)) return; if (ev.text) { if (!bubble) bubble = add('jarvis', ev.text); else bubble.textContent = ev.text; } bubble = null; setTyping(''); }),
      on('transcript', (ev) => { if (mine(ev) && ev.text) { add('user', `🎤 ${ev.text}`); setTyping('JARVIS berpikir…'); } }),
      on('progress', (ev) => { if (ev.session_id === sid()) progress(ev); }),
      on('report', (ev) => add('jarvis', `🔔 ${ev.text}`)),
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
  },
};
