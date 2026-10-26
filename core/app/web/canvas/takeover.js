// "Intervensi" (ADR-053, ADR-056: any time, the worker is told to stand still): the owner takes the wheel of a worker's browser from the desk — to solve a captcha or log in when the worker is stuck.
// A full-window view of the live video; what the owner does on it (mouse, touch, wheel, keys, pasted text) goes to the same tab over the
// desk's WebSocket. Nothing typed here is kept: it is sent and forgotten.
import { fitSize, keyToInput, pageFraction, scrollDelta, touchIntent } from './lib.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const FINAL = ['completed', 'failed', 'cancelled', 'stopped'];

export function createTakeover({ send, toast }) {
  let task = null, pic = { w: 0, h: 0 }, hold = null, lastMove = 0, last = null, press = null, drawing = false;
  const root = el('div'); root.id = 'takeover'; root.hidden = true;
  const bar = el('div', 'tk-bar');
  const title = el('b', 'tk-title'), url = el('span', 'tk-url'), badge = el('span', 'livebadge', '● LANGSUNG');
  const kb = el('button', null, '⌨ Keyboard'), paste = el('button', null, '📋 Tempel teks');
  const done = el('button', 'tk-done', 'Selesai — lanjutkan Jarvis'), back = el('button', null, 'Kembalikan tanpa memberi tahu');
  bar.append(title, url, badge, kb, paste, done, back);
  const note = el('div', 'tk-note', 'Anda yang mengendalikan browser ini. Klik dan ketikan Anda langsung masuk ke halaman.');
  const stage = el('div', 'tk-stage'), cv = el('canvas', 'tk-canvas');
  stage.append(cv);
  const pasteRow = el('form', 'tk-paste'); pasteRow.hidden = true;
  const pasteIn = el('input'); pasteIn.type = 'password'; pasteIn.placeholder = 'Ketik atau tempel (kode, kata sandi) lalu Kirim'; pasteIn.autocomplete = 'off';
  pasteIn.setAttribute('data-lpignore', 'true');
  const pasteGo = el('button', null, 'Kirim'); pasteGo.type = 'submit';
  pasteRow.append(pasteIn, pasteGo);
  const kin = el('input', 'tk-input'); kin.autocapitalize = 'off'; kin.autocomplete = 'off'; kin.spellcheck = false; kin.setAttribute('aria-label', 'Ketikan ke halaman');
  root.append(bar, note, stage, pasteRow, kin);
  document.body.append(root);
  // nothing under the window (the 3D desk, its shortcuts) hears what happens in it
  for (const t of ['pointerdown', 'pointermove', 'pointerup', 'wheel', 'touchstart', 'touchmove', 'contextmenu']) root.addEventListener(t, (e) => e.stopPropagation());

  const put = (ev) => { if (task != null) send({ type: 'input', task, ev }); };
  const rect = () => cv.getBoundingClientRect();
  const at = (e) => pageFraction(rect(), e.clientX, e.clientY);

  function layout() {
    const r = stage.getBoundingClientRect(), f = fitSize(r.width, r.height, pic.w, pic.h);
    cv.style.width = `${f.w}px`; cv.style.height = `${f.h}px`;
  }
  addEventListener('resize', () => { if (!root.hidden) layout(); });

  cv.addEventListener('contextmenu', (e) => e.preventDefault());
  cv.addEventListener('pointerdown', (e) => {
    cv.setPointerCapture(e.pointerId);
    const p = at(e), now = performance.now();
    const same = last && now - last.t < 450 && Math.hypot(e.clientX - last.x, e.clientY - last.y) < 8;
    const count = same ? Math.min(3, last.c + 1) : 1;
    press = { id: e.pointerId, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, t0: now, touch: e.pointerType === 'touch', button: ['left', 'middle', 'right'][e.button] || 'left', count };
    last = { t: now, x: e.clientX, y: e.clientY, c: count };
    if (!press.touch) { put({ t: 'mouse', k: 'down', x: p.x, y: p.y, b: press.button, c: count }); kin.focus({ preventScroll: true }); }
  });
  cv.addEventListener('pointermove', (e) => {
    const now = performance.now();
    if (press?.touch && press.id === e.pointerId) {   // a finger dragging: the page scrolls under it
      const dx = press.x - e.clientX, dy = press.y - e.clientY;
      press.x = e.clientX; press.y = e.clientY;
      if (touchIntent(e.clientX - press.x0, e.clientY - press.y0, now - press.t0) === 'scroll' && now - lastMove > 30) {
        lastMove = now; const p = at(e), r = rect();
        put({ t: 'wheel', x: p.x, y: p.y, dx: scrollDelta(dx, r.width, pic.w), dy: scrollDelta(dy, r.width, pic.w) });
      }
      return;
    }
    if (e.pointerType === 'touch' || now - lastMove < 45) return;   // hovering and dragging with a mouse
    lastMove = now; const p = at(e);
    put({ t: 'mouse', k: 'move', x: p.x, y: p.y, b: press?.button || 'none' });
  });
  const lift = (e) => {
    if (!press || press.id !== e.pointerId) return;
    const p = at(e), now = performance.now();
    if (press.touch) {
      if (touchIntent(e.clientX - press.x0, e.clientY - press.y0, now - press.t0) === 'tap') {
        const q = pageFraction(rect(), press.x0, press.y0);
        put({ t: 'mouse', k: 'move', x: q.x, y: q.y, b: 'none' });
        put({ t: 'mouse', k: 'down', x: q.x, y: q.y, b: 'left', c: press.count });
        put({ t: 'mouse', k: 'up', x: q.x, y: q.y, b: 'left', c: press.count });
      }
    } else put({ t: 'mouse', k: 'up', x: p.x, y: p.y, b: press.button, c: press.count });
    press = null;
  };
  cv.addEventListener('pointerup', lift);
  cv.addEventListener('pointercancel', lift);
  cv.addEventListener('wheel', (e) => {
    e.preventDefault();
    const p = at(e), r = rect();
    put({ t: 'wheel', x: p.x, y: p.y, dx: scrollDelta(e.deltaX, r.width, pic.w), dy: scrollDelta(e.deltaY, r.width, pic.w) });
  }, { passive: false });

  // a physical keyboard speaks key by key (capture phase: the desk's own shortcuts never see these) …
  const key = (kind) => (e) => {
    if (root.hidden || e.target === pasteIn) return;
    const m = keyToInput(e);
    if (!m) return;
    e.preventDefault(); e.stopImmediatePropagation();
    put({ ...m, k: kind });
  };
  addEventListener('keydown', key('down'), true);
  addEventListener('keyup', key('up'), true);
  // … a phone keyboard speaks text, into a hidden field
  const tap = (name) => { put({ t: 'key', k: 'down', key: name, code: name }); put({ t: 'key', k: 'up', key: name, code: name }); };
  kin.addEventListener('beforeinput', (e) => {
    if (e.inputType === 'insertCompositionText') return;                    // wait for the finished word
    e.preventDefault();
    if (e.inputType === 'deleteContentBackward') tap('Backspace');
    else if (e.inputType === 'insertLineBreak' || e.inputType === 'insertParagraph') tap('Enter');
    else if (e.data) put({ t: 'text', text: e.data });
    else if (e.inputType === 'insertFromPaste' && e.dataTransfer) put({ t: 'text', text: e.dataTransfer.getData('text/plain') });
  });
  kin.addEventListener('compositionend', (e) => { if (e.data) put({ t: 'text', text: e.data }); kin.value = ''; });
  addEventListener('paste', (e) => {   // Ctrl+V anywhere in the window
    if (root.hidden || e.target === pasteIn) return;
    const text = e.clipboardData?.getData('text/plain');
    if (text) { e.preventDefault(); put({ t: 'text', text }); }
  });

  kb.addEventListener('click', () => kin.focus());
  paste.addEventListener('click', () => { pasteRow.hidden = !pasteRow.hidden; if (!pasteRow.hidden) pasteIn.focus(); });
  pasteRow.addEventListener('submit', (e) => { e.preventDefault(); if (pasteIn.value) put({ t: 'text', text: pasteIn.value }); pasteIn.value = ''; kin.focus(); });
  done.addEventListener('click', () => finish(true));
  back.addEventListener('click', () => finish(false));

  function finish(told) {
    if (task == null) return;
    send({ type: 'release', task, done: told });
    close();
  }
  function close() {
    task = null; press = null; root.hidden = true; clearInterval(hold); hold = null; pasteRow.hidden = true; pasteIn.value = '';
    document.body.classList.remove('taking');
  }

  return {
    isOpen: () => task != null,
    task: () => task,
    open(st) {
      task = st.task_id; pic = { w: 0, h: 0 };
      title.textContent = st.title; url.textContent = st.page_title || st.url || '';
      root.hidden = false; document.body.classList.add('taking');
      cv.getContext('2d').clearRect(0, 0, cv.width, cv.height);
      send({ type: 'take', task });
      hold = setInterval(() => put({ t: 'hold' }), 20000);
      layout();
    },
    /** A frame of the station being steered. */
    async frame(taskId, blob) {
      if (taskId !== task || drawing) return;
      drawing = true;
      try {
        const bmp = await createImageBitmap(blob);
        if (pic.w !== bmp.width || pic.h !== bmp.height) { pic = { w: bmp.width, h: bmp.height }; cv.width = bmp.width; cv.height = bmp.height; layout(); }
        cv.getContext('2d').drawImage(bmp, 0, 0); bmp.close();
      } catch { /* a torn frame: the next one arrives in a moment */ } finally { drawing = false; }
    },
    /** The server's answer to take / release / a refused input. */
    reply(m) {
      if (m.what === 'take' && !m.ok) { toast(m.error || 'Tidak bisa mengambil alih.', true); close(); }
      else if (m.what === 'release') toast(m.told ? 'Jarvis diberi tahu dan melanjutkan.' : 'Kendali dikembalikan ke Jarvis.');
      else if (m.what === 'input' && m.ok === false && task != null) { toast(m.error || 'Kendali dikembalikan.', true); close(); }
    },
    /** The station's latest state, from the desk's poll. */
    update(st) {
      if (!st || st.task_id !== task) return;
      url.textContent = st.page_title || st.url || '';
      note.textContent = st.paused ? 'Anda yang mengendalikan browser ini. Jarvis sudah diminta diam dan menunggu sampai Anda selesai.'
        : 'Anda yang mengendalikan browser ini. Jarvis belum tentu berhenti (pekerja ini tidak bisa dijeda) — hindari langkah yang bertabrakan.';
      if (FINAL.includes(st.status)) { toast('Tugas ini sudah selesai.'); close(); }
    },
    close,
  };
}
