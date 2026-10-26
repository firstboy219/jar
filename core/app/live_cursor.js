// The "hands" of the desk (ADR-051 addendum): drawn INSIDE the shared browser so the owner sees what the worker does on a page —
// a cursor that glides to where it clicks, a ripple on each click, an outline around what it types into. Injected by core
// (live.py, DevTools: Page.addScriptToEvaluateOnNewDocument) into every top-level page of the shared Chromium; nothing here is sent
// anywhere and nothing here changes the page: one closed shadow root, aria-hidden, pointer-events: none, removed from layout.
(() => {
  if (window.top !== window || window.__jarvisHands) return;
  const state = { x: -50, y: -50, shown: false };
  window.__jarvisHands = { state: () => ({ ...state }) };
  let host, root, cursor, tag;

  function build() {
    if (host || !document.documentElement) return;
    host = document.createElement('div');
    host.setAttribute('aria-hidden', 'true');
    host.style.cssText = 'all:initial;position:fixed;inset:0;z-index:2147483647;pointer-events:none;contain:strict;';
    root = host.attachShadow({ mode: 'closed' });
    root.innerHTML = `<style>
      .c{position:fixed;left:0;top:0;width:26px;height:26px;transition:transform .22s cubic-bezier(.2,.8,.2,1);will-change:transform;opacity:0}
      .c.on{opacity:1}
      .c svg{filter:drop-shadow(0 1px 2px rgba(0,0,0,.6))}
      .tag{position:absolute;left:20px;top:20px;font:600 10px/1 system-ui,sans-serif;letter-spacing:1px;color:#031018;background:#67e8f9;padding:3px 6px;border-radius:6px;white-space:nowrap}
      .r{position:fixed;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;border:3px solid #f43f5e;animation:rip .55s ease-out forwards}
      @keyframes rip{from{transform:scale(.4);opacity:1}to{transform:scale(4.2);opacity:0}}
      .f{position:fixed;border:3px solid #67e8f9;border-radius:6px;box-shadow:0 0 14px #67e8f9;animation:fo 1.1s ease-out forwards}
      @keyframes fo{0%,60%{opacity:1}to{opacity:0}}
    </style>
    <div class="c"><svg width="26" height="26" viewBox="0 0 26 26"><path d="M3 2l17 8-7.5 2.2L9.8 20z" fill="#67e8f9" stroke="#031018" stroke-width="1.6" stroke-linejoin="round"/></svg><span class="tag">JARVIS</span></div>`;
    cursor = root.querySelector('.c');
    document.documentElement.appendChild(host);
  }
  const ready = () => { build(); return !!host; };

  function moveTo(x, y) {
    if (!ready()) return;
    state.x = x; state.y = y; state.shown = true;
    cursor.classList.add('on');
    cursor.style.transform = `translate(${Math.round(x)}px,${Math.round(y)}px)`;
  }
  function ripple(x, y) {
    if (!ready()) return;
    const r = document.createElement('div'); r.className = 'r'; r.style.left = `${x}px`; r.style.top = `${y}px`;
    root.appendChild(r); setTimeout(() => r.remove(), 700);
  }
  function outline(el) {
    if (!ready() || !el || !el.getBoundingClientRect) return;
    const b = el.getBoundingClientRect();
    if (b.width < 2 || b.height < 2 || b.width > innerWidth * 0.98 && b.height > innerHeight * 0.9) return;   // not the whole page
    const f = document.createElement('div'); f.className = 'f';
    f.style.cssText = `left:${b.left - 3}px;top:${b.top - 3}px;width:${b.width}px;height:${b.height}px`;
    root.appendChild(f); setTimeout(() => f.remove(), 1200);
  }
  const centre = (el) => { const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + Math.min(b.height / 2, 24)]; };

  // real mouse events (the worker's browser dispatches them through DevTools) …
  addEventListener('mousemove', (e) => moveTo(e.clientX, e.clientY), true);
  addEventListener('mousedown', (e) => { moveTo(e.clientX, e.clientY); ripple(e.clientX, e.clientY); }, true);
  // … and clicks made by script (no coordinates): glide to the element, then press
  addEventListener('click', (e) => {
    if (e.clientX === 0 && e.clientY === 0 && e.target && e.target.getBoundingClientRect) {
      const [x, y] = centre(e.target); moveTo(x, y); setTimeout(() => ripple(x, y), 200);
    }
  }, true);
  addEventListener('focusin', (e) => { if (e.target && e.target !== document.body) { outline(e.target); if (!state.shown) { const [x, y] = centre(e.target); moveTo(x, y); } } }, true);
  addEventListener('input', (e) => outline(e.target), true);
  addEventListener('scroll', () => { if (state.shown) cursor.classList.add('on'); }, true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build); else build();
})();
