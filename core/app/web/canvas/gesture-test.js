// The gesture prototype page (Fase 4.0): measures what the Gate asks — latency, false triggers — on the owner's device.
import { classify, startHandTracking } from './gestures.js';

const $ = (s) => document.querySelector(s);
const CONNECTIONS = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];
let tracker = null, started = 0, falseTriggers = 0, hits = 0;
const ctx = $('#overlay').getContext('2d');

function log(text) {
  const line = document.createElement('div');
  line.textContent = `${new Date().toLocaleTimeString('id-ID')}  ${text}`;
  $('#log').prepend(line);
  while ($('#log').childElementCount > 120) $('#log').lastChild.remove();
}

function draw(hands) {
  ctx.clearRect(0, 0, 640, 480);
  for (const lm of hands) {
    ctx.strokeStyle = '#67e8f9'; ctx.lineWidth = 3;
    for (const [a, b] of CONNECTIONS) { ctx.beginPath(); ctx.moveTo(lm[a].x * 640, lm[a].y * 480); ctx.lineTo(lm[b].x * 640, lm[b].y * 480); ctx.stroke(); }
    ctx.fillStyle = '#f472b6';
    for (const p of lm) { ctx.beginPath(); ctx.arc(p.x * 640, p.y * 480, 4, 0, 7); ctx.fill(); }
  }
}

function onEvent(e, machine) {
  const pad = $('#pad').getBoundingClientRect();
  const dot = $('#dot');
  if (e.type === 'cursor') { dot.hidden = false; dot.style.left = `${e.x * pad.width}px`; dot.style.top = `${e.y * pad.height}px`; }
  if (e.type === 'press') dot.classList.add('down');
  if (e.type === 'release') dot.classList.remove('down');
  if (e.type === 'click') {
    // the pad maps to the four targets below it: left→right quarters
    const target = $('#targets').children[Math.min(3, Math.floor(e.x * 4))];
    target.classList.add('hit'); setTimeout(() => target.classList.remove('hit'), 400);
    hits++; $('#hits').textContent = hits;
  }
  if (e.type !== 'cursor' && e.type !== 'drag') log(`${e.type}${e.factor ? ' ×' + e.factor.toFixed(2) : ''}${e.active !== undefined ? (e.active ? ' AKTIF' : ' mati') : ''}`);
  $('#st').textContent = machine.active ? (machine.paused ? 'JEDA' : 'AKTIF') : 'menunggu telapak ditahan';
}

$('#start').addEventListener('click', async () => {
  if (tracker) { tracker.stop(); tracker = null; $('#start').textContent = 'Nyalakan kamera'; $('#stage').classList.remove('on'); $('#st').textContent = 'kamera mati'; return; }
  $('#start').textContent = 'Memuat model…';
  try {
    tracker = await startHandTracking($('#video'), onEvent, (s, m, hands) => {
      $('#fps').textContent = s.fps.toFixed(0);
      $('#lat').firstChild.textContent = `${s.latencyMs.toFixed(0)} ms `;
      $('#pose').textContent = hands.length ? hands.map((h) => classify(h)).join(' / ') : 'tidak ada tangan';
      draw(hands);
    });
    started = Date.now();
    $('#start').textContent = 'Matikan kamera';
    $('#stage').classList.add('on');
    log('kamera menyala (di perangkat ini saja)');
  } catch (err) { $('#start').textContent = 'Nyalakan kamera'; log(`gagal: ${err.message}`); }
});
$('#false').addEventListener('click', () => { falseTriggers++; update(); log('salah picu dicatat'); });
$('#reset').addEventListener('click', () => { falseTriggers = 0; hits = 0; started = Date.now(); $('#hits').textContent = 0; update(); });
function update() {
  const min = started ? (Date.now() - started) / 60000 : 0;
  $('#fp').firstChild.textContent = `${falseTriggers}${min > 0.5 ? ` (${(falseTriggers / min * 10).toFixed(1)} per 10 menit)` : ''} `;
  $('#dur').textContent = started ? `${Math.floor(min)}:${String(Math.floor((min % 1) * 60)).padStart(2, '0')}` : '0:00';
}
setInterval(update, 1000);
