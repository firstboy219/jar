// JARVIS app v2 (ADR-087): wires the shell — sign-in, the command dock, the nav icons, the live connection and every screen.
import { $, $$, connect, go, post, render, store, svg, toast, view, whenAuthNeeded } from './core.js';
import { VIEWS } from './views/index.js';

for (const [name, mod] of Object.entries(VIEWS)) view(name, mod);

function paintIcons(root = document) {
  for (const el of $$('[data-icon]', root)) if (!el.firstChild) el.innerHTML = svg(el.dataset.icon, el.closest('#nav') ? 22 : 20);
}
paintIcons();

// sign-in for a browser (the app passes its device token itself)
whenAuthNeeded((notOwner) => {
  $('#login').hidden = false;
  $('#loginmsg').textContent = notOwner ? 'Perangkat ini bukan perangkat pemilik. Masuk dengan password admin.' : 'Masukkan password admin untuk memakai aplikasi ini di browser.';
});
$('#loginform').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pw = e.target.password.value;
  try {
    const r = await fetch('/api/v1/devices/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: pw, device_name: 'Aplikasi JARVIS (web)' }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'gagal');
    store.set(d.token);
    e.target.password.value = '';
    $('#login').hidden = true;
    connect();
    render();
  } catch (err) { $('#loginmsg').textContent = err.message; }
});

// the command dock: a feature's name opens it, anything else goes to JARVIS (Obrolan)
$('#dock').addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = $('#cmd').value.trim();
  if (!q) return;
  $('#cmd').value = '';
  const { findFeature } = await import('./views/fitur.js');
  const f = await findFeature(q).catch(() => null);
  if (f) return f.route.startsWith('native:') ? import('./core.js').then((c) => c.openNative(f.route.slice(7))) : go(f.route);
  sessionStorage.setItem('jarvis_app_pending', q);
  go('#/obrolan');
});

new MutationObserver(() => paintIcons($('#view'))).observe($('#view'), { childList: true, subtree: true });
window.addEventListener('hashchange', render);
// the phone tells the page to open a screen (a notification tapped, a habit's offer) through JarvisHost → window.__jarvisGo
window.__jarvisGo = (hash) => go(hash);
if (!store.get()) $('#login').hidden = false;
connect();
render();
// report the phone's place to the server while the page is open on the web (the APK reports it natively, in the background)
if (!window.JarvisHost && navigator.geolocation && location.protocol === 'https:') {
  const send = () => navigator.geolocation.getCurrentPosition((p) => post('/api/v1/app/location', { lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: p.coords.accuracy }).catch(() => {}), () => {}, { maximumAge: 300000, timeout: 10000 });
  send(); setInterval(send, 10 * 60 * 1000);
}
window.addEventListener('error', (e) => { if (String(e.message).includes('import')) toast('Sebagian aplikasi gagal dimuat — tarik untuk memuat ulang.', true); });
