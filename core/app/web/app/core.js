// The app's runtime (ADR-087): the owner's token, the API, the one live connection, the router, and what the phone adds (JarvisHost).
import { svg } from './icons.js';
import { esc, html, parseRoute, raw, takeToken } from './lib.js';

export { html, raw, esc, svg };

// ---------- the owner's token: handed over by the app in the fragment, shared with the desk and notes pages in a browser ----------
const TOKEN_KEY = 'jarvis_canvas_token';
const taken = takeToken(location.hash);
export const embedded = taken.embedded || /JarvisApp/.test(navigator.userAgent) || !!window.JarvisHost;
export const store = {
  get() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } },
  set(v) { try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ } },
};
if (taken.token) store.set(taken.token);
if (taken.token || taken.embedded) history.replaceState(null, '', location.pathname + location.search + (taken.rest ? `#${taken.rest}` : '#/'));
if (embedded) document.documentElement.classList.add('in-app');

// ---------- API ----------
export class ApiError extends Error { constructor(msg, status) { super(msg); this.status = status; } }
let onAuthNeeded = () => {};
export function whenAuthNeeded(fn) { onAuthNeeded = fn; }

export async function api(method, path, body, opts = {}) {
  const headers = { Authorization: `Bearer ${store.get()}` };
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const r = await fetch(path, { method, headers, body: payload });
  if (r.status === 401 || r.status === 403) { onAuthNeeded(r.status === 403); throw new ApiError('perlu masuk sebagai pemilik', r.status); }
  const isJson = r.headers.get('content-type')?.includes('json');
  const data = isJson ? await r.json() : (opts.blob ? await r.blob() : await r.text());
  if (!r.ok) {
    const d = isJson ? data?.detail : data;
    throw new ApiError((typeof d === 'string' ? d : JSON.stringify(d)) || `HTTP ${r.status}`, r.status);
  }
  return data;
}
export const get = (p) => api('GET', p);
export const post = (p, b = {}) => api('POST', p, b);
export const put = (p, b = {}) => api('PUT', p, b);
export const del = (p) => api('DELETE', p);
export const patch = (p, b = {}) => api('PATCH', p, b);

// ---------- the live connection (the same /ws the phone and the desk use) ----------
const listeners = new Map();   // type → Set(fn)
let ws = null, connected = false, retry = 0, pingTimer = null;
const outbox = [];
export function on(type, fn) { if (!listeners.has(type)) listeners.set(type, new Set()); listeners.get(type).add(fn); return () => listeners.get(type)?.delete(fn); }
function fire(ev) {
  for (const t of [ev.type, '*']) for (const fn of listeners.get(t) || []) { try { fn(ev); } catch (e) { console.error(e); } }
}
export function connect() {
  if (!store.get()) return void setTimeout(connect, 2000);
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: store.get(), caps: embedded ? [] : ['web_app'] }));
  ws.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    if (ev.type === 'auth_ok') {
      connected = true; retry = 0;
      clearInterval(pingTimer); pingTimer = setInterval(() => ws?.readyState === 1 && ws.send('{"type":"ping"}'), 25000);
      while (outbox.length) ws.send(outbox.shift());
    }
    fire(ev);
  };
  ws.onclose = () => { connected = false; clearInterval(pingTimer); fire({ type: 'offline' }); setTimeout(connect, Math.min(1000 * 2 ** retry++, 15000)); };
  ws.onerror = () => ws.close();
}
export function send(obj) {
  const s = JSON.stringify(obj);
  if (ws?.readyState === 1 && connected) ws.send(s); else outbox.push(s);
}
export const isOnline = () => connected;

// ---------- what only the phone can do (the APK's JarvisHost bridge); on the web each has a fallback ----------
export const host = {
  has: (name) => !!(window.JarvisHost && typeof window.JarvisHost[name] === 'function'),
  call(name, ...args) {
    if (this.has(name)) { try { return window.JarvisHost[name](...args.map((a) => (typeof a === 'object' ? JSON.stringify(a) : a))); } catch (e) { console.error(e); } }
    return undefined;
  },
};

// ---------- small UI helpers ----------
export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];

export function toast(text, bad = false) {
  const t = document.createElement('div');
  t.className = `toast${bad ? ' bad' : ''}`;
  t.textContent = text;
  $('#toasts').append(t);
  setTimeout(() => t.remove(), 4200);
}

/** A bottom sheet with arbitrary content; resolves with what the content's [data-close=value] buttons say. */
export function sheet(content, { onOpen } = {}) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'sheetwrap';
    wrap.innerHTML = `<div class="scrim"></div><section class="sheet" role="dialog" aria-modal="true"><div class="grab"></div>${content}</section>`;
    document.body.append(wrap);
    const close = (v) => { wrap.remove(); resolve(v); };
    wrap.querySelector('.scrim').addEventListener('click', () => close(null));
    wrap.addEventListener('click', (e) => { const b = e.target.closest('[data-close]'); if (b) close(b.dataset.close); });
    wrap.addEventListener('submit', (e) => { e.preventDefault(); const f = e.target; close(Object.fromEntries(new FormData(f).entries())); });
    onOpen?.(wrap, close);
  });
}

export const icon = (name, size, stroke) => raw(svg(name, size, stroke));

export function header(title, { back = true, sub = '', right = '' } = {}) {
  return html`<header class="hdr">
    ${back ? html`<button class="ib" data-act="back" aria-label="Kembali">${icon('back')}</button>` : ''}
    <div class="hdr-t"><span class="t">${title}</span>${sub ? html`<span class="s">${sub}</span>` : ''}</div>
    ${raw(String(right || ''))}</header>`;
}

export function empty(text, sub = '') {
  return html`<div class="empty"><p>${text}</p>${sub ? html`<p class="muted">${sub}</p>` : ''}</div>`;
}

export function loading() { return raw('<div class="loading"><span></span><span></span><span></span></div>'); }

export function errorBox(e, retryAct = 'reload') {
  return html`<div class="card red"><b>Gagal memuat</b><p class="muted">${e?.message || e}</p><button class="btn" data-act="${retryAct}">Coba lagi</button></div>`;
}

// ---------- the router ----------
const views = new Map();
let current = null, cleanup = null;
export function view(name, mod) { views.set(name, mod); }
export function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }

/** Open one of the approved apps on the phone (Pluang, Gojek, …); on the web, say where to do it. */
export function openApp(name, label = name) {
  if (host.has('openApp') && host.call('openApp', name)) return true;
  toast(host.has('openApp') ? `${label} belum terpasang di HP ini.` : `Buka ${label} di HP-mu.`, true);
  return false;
}

/** Talk it over with JARVIS: Obrolan opens and the question (with what it is about) is sent. */
export function discuss(text) { sessionStorage.setItem('jarvis_app_pending', text); go('#/obrolan'); }
export function back() { if (history.length > 1) history.back(); else go('#/'); }

export async function render() {
  const route = parseRoute(location.hash);
  const mod = views.get(route.name) || views.get('notfound');
  if (typeof cleanup === 'function') { try { cleanup(); } catch { /* ignore */ } }
  cleanup = null;
  current = route;
  const root = $('#view');
  root.scrollTop = 0; window.scrollTo(0, 0);
  root.dataset.view = route.name;
  document.body.dataset.view = route.name;
  for (const a of $$('#nav a')) a.classList.toggle('on', a.dataset.tab === (mod?.tab || route.name));
  try {
    cleanup = await mod.render(root, route);
  } catch (e) {
    console.error(e);
    root.innerHTML = String(html`${header('JARVIS')}<div class="scr">${errorBox(e)}</div>`);
  }
  if (mod?.feature !== false) post('/api/v1/app/opened', { feature: mod?.feature || route.name }).catch(() => {});
}
export const route = () => current;

// one click handler for the whole app: [data-act] → the view's actions, [data-go] → a route, [data-native] → the phone
document.addEventListener('click', async (e) => {
  const a = e.target.closest('[data-act],[data-go],[data-native]');
  if (!a) return;
  if (a.dataset.go) { e.preventDefault(); return go(a.dataset.go); }
  if (a.dataset.native) { e.preventDefault(); return openNative(a.dataset.native); }
  const act = a.dataset.act;
  if (act === 'back') return back();
  if (act === 'reload') return render();
  const mod = views.get(current?.name);
  if (mod?.actions?.[act]) {
    e.preventDefault();
    a.disabled = true;
    try { await mod.actions[act](a, e); } catch (err) { toast(err.message || String(err), true); } finally { a.disabled = false; }
  }
});

/** Read text aloud: the phone's own voice in the app, the browser's voice on the web. */
export function speak(text) {
  const t = String(text || '').trim();
  if (!t) return;
  if (host.has('speak')) return host.call('speak', t);
  if (!window.speechSynthesis) return toast('Browser ini tidak bisa membacakan.', true);
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(t);
  u.lang = 'id-ID';
  const v = window.speechSynthesis.getVoices().find((x) => x.lang?.startsWith('id'));
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}
export function stopSpeaking() { if (host.has('stopSpeaking')) host.call('stopSpeaking'); else window.speechSynthesis?.cancel(); }

/** A feature only the phone can do. On the web: say so. */
export function openNative(what) {
  if (what === 'talk') { if (host.has('talk')) return host.call('talk'); return go('#/obrolan?mic=1'); }
  if (host.has('open')) return host.call('open', what);
  toast('Fitur ini dijalankan di aplikasi JARVIS di HP.');
}
