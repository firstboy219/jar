// "Ambil alih" in the app (ADR-053/056, as on the desk): the owner steers a mission's browser — a robot check, a sign-in — from the phone or
// a browser. The takeover window (takeover-window.js) is connected to the live video (/api/v1/canvas/live/ws) for one mission.
import { createTakeover } from './takeover-window.js';
import { get, store, toast } from './core.js';

let tk = null, ws = null, poll = null, watch = null;

function stop() {
  clearInterval(poll); clearInterval(watch); poll = watch = null;
  try { ws?.close(); } catch { /* gone */ }
  ws = null;
}

export function takeOver(mission) {
  stop();
  tk = tk || createTakeover({ send: (m) => { if (ws?.readyState === 1) ws.send(JSON.stringify(m)); }, toast: (t, bad) => toast(t, bad) });
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/canvas/live/ws`);
  ws.binaryType = 'blob';
  ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: store.get() }));
  ws.onmessage = async (m) => {
    if (typeof m.data !== 'string') {   // task id (4 bytes) + frame number (4 bytes) + the JPEG
      const head = new DataView(await m.data.slice(0, 4).arrayBuffer());
      tk.frame(head.getUint32(0), m.data.slice(8, m.data.size, 'image/jpeg'));
      return;
    }
    const msg = JSON.parse(m.data);
    if (msg.type === 'auth_ok') {
      ws.send(JSON.stringify({ type: 'watch', context: 'utama' }));
      tk.open({ task_id: mission.id, title: mission.title, page_title: mission.station?.page_title, url: mission.station?.url });
    } else if (msg.type === 'control') tk.reply(msg);
    else if (msg.type === 'error') { toast('Sesi berakhir — masuk ulang', true); tk.close(); stop(); }
  };
  ws.onclose = () => { if (tk.isOpen()) { toast('Sambungan layar terputus.', true); tk.close(); } stop(); };
  poll = setInterval(async () => {   // paused or finished: the window says so (and closes when the mission is over)
    try { const t = await get(`/api/v1/app/missions/${mission.id}`); tk.update({ ...(t.station || {}), task_id: t.id, status: t.status }); } catch { /* next time */ }
  }, 4000);
  watch = setInterval(() => { if (!tk.isOpen()) stop(); }, 1000);
}
