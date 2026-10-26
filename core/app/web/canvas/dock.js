// The desk's own conversation panel (Blueprint v4 Fase 8, ADR-052): chat, microphone, camera and screen sharing on the main page, over
// the same WebSocket the phone uses (/ws). The server does the hearing (speech recognition, voice complements) and the thinking;
// this file only captures, sends and shows. In the Android app (embedded) the phone's own microphone, camera and screen sharing stay
// native, so only the chat is shown here.
import { Vad, downsample, pcm16ToBase64, panelOpen, panelValue } from './lib.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { /* private mode */ } return null; };
const FRAME_MAX_W = 1024, FRAME_EVERY_MS = 1500, FRAME_FRESH_MS = 9000;

export function initDock({ api, toast, embedded }) {
  let ws = null, connected = false, retry = 0, pingTimer = null, wantOpen = true;
  let sessionId = LS('jarvis_desk_session') || `meja-${Math.random().toString(36).slice(2, 10)}`;
  LS('jarvis_desk_session', sessionId);
  let jarvisBubble = null, typing = false;
  let ttsOn = LS('jarvis_desk_tts') ? LS('jarvis_desk_tts') === 'on' : !embedded;
  const media = { mic: null, cam: null, scr: null, frame: null, seq: 0 };

  // ---------- layout ----------
  const dock = el('div', 'dock');
  const head = el('div', 'dockhead');
  const dot = el('span', 'dot'), title = el('b', null, 'Percakapan');
  const buttons = el('span', 'dockbtns');
  const mk = (glyph, tip, fn) => { const b = el('button', 'dbtn', glyph); b.title = tip; b.dataset.gesture = 'ok'; b.addEventListener('click', fn); buttons.append(b); return b; };
  const micBtn = embedded ? null : mk('🎤', 'Mikrofon: bicara dengan Jarvis', () => toggleMic());
  const camBtn = embedded ? null : mk('📷', 'Kamera: tunjukkan sesuatu ke Jarvis', () => toggleCamera());
  const scrBtn = embedded || !navigator.mediaDevices?.getDisplayMedia ? null : mk('🖥', 'Bagikan layar ke Jarvis', () => toggleScreen());
  const ttsBtn = mk('🔊', 'Suara balasan Jarvis (di browser ini)', () => setTts(!ttsOn));
  mk('⟳', 'Percakapan baru', () => newConversation());
  const minBtn = mk('💬', 'Ciutkan / buka', () => setOpen(!wantOpen));
  minBtn.classList.add('minimizer');
  // penanda pesan baru saat panel ditutup
  const penandaDot = el('span', 'dot penanda');
  minBtn.appendChild(penandaDot);
  head.append(dot, title, buttons);
  const log = el('div', 'dockmsgs');
  const statusLine = el('div', 'dockstatus');
  const meter = el('div', 'meter'); const meterFill = el('i'); meter.append(meterFill); meter.hidden = true;
  const form = el('form', 'dockform');
  const input = el('input'); input.placeholder = 'Tulis ke Jarvis…'; input.autocomplete = 'off'; input.maxLength = 8000;
  const send = el('button', null, 'Kirim'); send.type = 'submit'; send.dataset.gesture = 'ok';
  form.append(input, send);
  dock.append(head, log, statusLine, meter, form);
  const previews = el('div', 'previews');
  document.body.append(previews, dock);
  setTts(ttsOn);
  setOpen(panelOpen(LS('jarvis_desk_dock')));
  // the conversation survives a reload and a trip to another tab of the app (kept in this browser only)
  const keep = () => LS(`jarvis_desk_log_${sessionId}`, JSON.stringify([...log.children].slice(-40).map((n) => ({ who: n.classList.contains('user') ? 'user' : 'jarvis', text: n.textContent }))));
  const history = (() => { try { return JSON.parse(LS(`jarvis_desk_log_${sessionId}`) || '[]'); } catch { return []; } })();
  const saved = history.slice(-40);
  for (const m of saved) log.append(el('div', `msg ${m.who}`, m.text));
  if (!saved.length) addMsg('jarvis', 'Halo! Aku di sini. Tulis atau bicara — apa yang kukerjakan kamu lihat langsung di meja ini.', true);
  log.scrollTop = log.scrollHeight;

  function setOpen(on) {
    wantOpen = on;
    const isClosed = !on;
    dock.classList.toggle('closed', isClosed);
    dock.classList.toggle('minimized', isClosed);
    if (on) penandaDot.classList.remove('visible', 'blink');   // dibaca: penanda hilang saat dibuka
    minBtn.title = on ? 'Ciutkan panel chat' : 'Buka panel chat';
    LS('jarvis_desk_dock', panelValue(on));   // posisi panel kembali sama setelah refresh
  }
  function setTts(on) {
    ttsOn = on; LS('jarvis_desk_tts', on ? 'on' : 'off'); ttsBtn.classList.toggle('on', on);
    if (!on) window.speechSynthesis?.cancel();
  }

  // ---------- messages ----------
  function addMsg(who, text, quiet = false) {
    const m = el('div', `msg ${who}`, text);
    log.append(m); log.scrollTop = log.scrollHeight; keep();
    if (!quiet && !wantOpen) penandaDot.classList.add('visible', 'blink');   // pesan baru saat panel ditutup
    return m;
  }
  function setStatus(text) { statusLine.textContent = text || ''; statusLine.hidden = !text; }
  function setTyping(on) { typing = on; if (!on) setStatus(media.mic ? '🎤 Mendengarkan…' : ''); else if (!statusLine.textContent || statusLine.textContent.startsWith('🎤')) setStatus('Jarvis berpikir…'); }
  function newConversation() {
    sessionId = `meja-${Math.random().toString(36).slice(2, 10)}`; LS('jarvis_desk_session', sessionId);
    log.replaceChildren(); jarvisBubble = null; setTyping(false); addMsg('jarvis', 'Percakapan baru dimulai.', true); keep();
  }

  // ---------- the socket ----------
  function wsUrl() { return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`; }
  function connect() {
    if (!api.token) return void setTimeout(connect, 2000);   // not signed in yet
    ws = new WebSocket(wsUrl());
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: api.token }));
    ws.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch { /* ignore a malformed frame */ } };
    ws.onclose = () => { connected = false; dot.className = 'dot'; clearInterval(pingTimer); setTimeout(connect, Math.min(1000 * 2 ** retry++, 15000)); };
    ws.onerror = () => ws.close();
  }
  function post(obj) { if (ws?.readyState === 1 && connected) { ws.send(JSON.stringify(obj)); return true; } toast('Belum tersambung ke Jarvis — coba sebentar lagi.', true); return false; }

  function handle(ev) {
    const mine = !ev.session_id || ev.session_id === sessionId;
    switch (ev.type) {
      case 'auth_ok': connected = true; retry = 0; dot.className = 'dot completed'; pingTimer = setInterval(() => ws.readyState === 1 && ws.send('{"type":"ping"}'), 25000); break;
      case 'thought': if (mine) setStatus(`💭 ${ev.text}`.slice(0, 160)); break;
      case 'tool': if (mine) setStatus(`🔧 ${ev.title || ev.name}${ev.label ? `: ${ev.label}` : ''}`.slice(0, 160)); break;
      case 'delta': if (mine) { if (!jarvisBubble) jarvisBubble = addMsg('jarvis', ''); jarvisBubble.textContent += ev.text; log.scrollTop = log.scrollHeight; } break;
      case 'say': if (mine) speak(ev.speech || ev.text); break;
      case 'reply':
        if (!mine) break;
        if (ev.text) { if (!jarvisBubble) jarvisBubble = addMsg('jarvis', ev.text); else jarvisBubble.textContent = ev.text; if (!ev.spoken) speak(ev.speech || ev.text); }
        else if (jarvisBubble && !jarvisBubble.textContent) jarvisBubble.remove();
        jarvisBubble = null; setTyping(false); log.scrollTop = log.scrollHeight; keep(); break;
      case 'transcript':
        if (!mine) break;
        if (ev.text) addMsg('user', `🎤 ${ev.text}`); else if (ev.error) toast(ev.error, true);
        if (ev.text) setTyping(true); break;
      case 'report': addMsg('jarvis', `🔔 ${ev.text}`); post({ type: 'report_spoken', report_id: ev.id }); speak(ev.speech || ev.text); break;
      case 'proactive': case 'announce': addMsg('jarvis', `🔔 ${ev.text}`); speak(ev.speech || ev.text); break;
      case 'error': if (mine) { toast(ev.message || 'Terjadi kesalahan', true); setTyping(false); jarvisBubble = null; } break;
      default: break;   // tasks, stage, brain… the desk itself shows those
    }
  }

  function sendChat(text) {
    const frame = freshFrame();
    if (!post({ user_command: text, session_id: sessionId, ...(frame ? { screen: frame.b64, image_source: frame.source } : {}) })) return;
    addMsg('user', text + (frame ? `  ${frame.source === 'screen' ? '🖥' : '📷'}` : ''), true);
    jarvisBubble = null; setTyping(true);
  }
  form.addEventListener('submit', (e) => { e.preventDefault(); const t = input.value.trim(); if (t) { sendChat(t); input.value = ''; } });
  input.addEventListener('keydown', (e) => e.stopPropagation());   // typing never triggers a desk shortcut

  // ---------- voice out ----------
  function speak(text) {
    if (!ttsOn || !text || !('speechSynthesis' in window)) return;
    const u = new SpeechSynthesisUtterance(String(text).slice(0, 600)); u.lang = 'id-ID';
    const v = speechSynthesis.getVoices().find((x) => x.lang?.toLowerCase().startsWith('id'));
    if (v) u.voice = v;
    speechSynthesis.speak(u);
  }
  const speakingNow = () => 'speechSynthesis' in window && speechSynthesis.speaking;

  // ---------- microphone ----------
  async function toggleMic() {
    if (media.mic) return stopMic();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
      const ctx = new AudioContext();
      await ctx.audioWorklet.addModule('worklet.js');
      const src = ctx.createMediaStreamSource(stream), node = new AudioWorkletNode(ctx, 'jarvis-capture');
      src.connect(node);
      const m = { stream, ctx, node, vad: new Vad(), muted: false };
      node.port.onmessage = (e) => onAudio(m, e.data);
      media.mic = m; micBtn.classList.add('on'); meter.hidden = false; setStatus('🎤 Mendengarkan…');
    } catch (err) { toast(`Mikrofon tidak bisa dipakai: ${err.message || err.name}`, true); }
  }
  function stopMic() {
    const m = media.mic; if (!m) return;
    m.node.disconnect(); m.stream.getTracks().forEach((t) => t.stop()); m.ctx.close();
    media.mic = null; micBtn.classList.remove('on'); meter.hidden = true; meterFill.style.width = '0'; setStatus('');
  }
  function onAudio(m, chunk) {
    if (speakingNow()) { m.vad = new Vad(); meterFill.style.width = '0'; return; }   // Jarvis is talking: do not hear itself
    const pcm = m.vad.push(downsample(chunk, m.ctx.sampleRate, 16000));
    meterFill.style.width = `${Math.min(100, Math.round(m.vad.level * 600))}%`;
    meter.classList.toggle('hot', m.vad.active);
    if (pcm && post({ type: 'utterance', audio: pcm16ToBase64(pcm), seq: ++media.seq, session_id: sessionId, ...(freshFrame() ? { screen: freshFrame().b64, image_source: freshFrame().source } : {}) })) setStatus('🎤 Menerjemahkan…');
  }

  // ---------- camera + screen: the latest frame goes along with what is said or typed ----------
  function previewTile(kind, stream) {
    const t = el('div', `tile ${kind}`); const v = el('video'); v.muted = true; v.playsInline = true; v.autoplay = true; v.srcObject = stream;
    const x = el('button', null, '✕'); x.title = 'Berhenti membagikan'; x.addEventListener('click', () => (kind === 'screen' ? stopScreen() : stopCamera()));
    t.append(v, el('span', 'tag', kind === 'screen' ? '● Layar dibagikan ke Jarvis' : '● Kamera dibagikan ke Jarvis'), x);
    previews.append(t); return { tile: t, video: v };
  }
  async function toggleCamera() {
    if (media.cam) return stopCamera();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } } });
      media.cam = { stream, ...previewTile('camera', stream) }; camBtn.classList.add('on'); startFrames();
    } catch (err) { toast(`Kamera tidak bisa dipakai: ${err.message || err.name}`, true); }
  }
  function stopCamera() { const c = media.cam; if (!c) return; c.stream.getTracks().forEach((t) => t.stop()); c.tile.remove(); media.cam = null; camBtn.classList.remove('on'); stopFrames(); }
  async function toggleScreen() {
    if (media.scr) return stopScreen();
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
      media.scr = { stream, ...previewTile('screen', stream) }; scrBtn.classList.add('on');
      stream.getVideoTracks()[0].addEventListener('ended', stopScreen); startFrames();
    } catch (err) { if (err.name !== 'NotAllowedError') toast(`Layar tidak bisa dibagikan: ${err.message || err.name}`, true); }
  }
  function stopScreen() { const s = media.scr; if (!s) return; s.stream.getTracks().forEach((t) => t.stop()); s.tile.remove(); media.scr = null; scrBtn?.classList.remove('on'); stopFrames(); }

  let frameTimer = null;
  const canvas = document.createElement('canvas');
  function grab() {
    const src = media.scr || media.cam;
    if (!src || src.video.readyState < 2 || !src.video.videoWidth) return;
    const w = Math.min(FRAME_MAX_W, src.video.videoWidth), h = Math.round((src.video.videoHeight * w) / src.video.videoWidth);
    canvas.width = w; canvas.height = h;
    canvas.getContext('2d').drawImage(src.video, 0, 0, w, h);
    media.frame = { b64: canvas.toDataURL('image/jpeg', 0.6).split(',')[1], source: media.scr ? 'screen' : 'camera', at: Date.now() };
  }
  function startFrames() { if (!frameTimer) { frameTimer = setInterval(grab, FRAME_EVERY_MS); setTimeout(grab, 400); } }
  function stopFrames() { if (!media.cam && !media.scr) { clearInterval(frameTimer); frameTimer = null; media.frame = null; } }
  const freshFrame = () => (media.frame && Date.now() - media.frame.at < FRAME_FRESH_MS ? media.frame : null);

  connect();
  return { say: speak, send: sendChat, raw: post };
}
