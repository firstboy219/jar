// The desk's "Pekerja" area (ADR-058): every worker JARVIS has running (and what finished in the last hour), the model it is using, and the
// owner's hands on it — stop / start, switch the model, and say something straight to it. It follows the server's state (the desk poll).

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn, title) => { const b = el('button', cls, text); b.dataset.gesture = 'ok'; if (title) b.title = title; b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(ev); }); return b; };
const STATUS = { queued: 'antre', running: 'bekerja', completed: 'selesai', failed: 'gagal', stopped: 'dihentikan', cancelled: 'dibatalkan' };
const DOT = { queued: 'queued', running: 'running', completed: 'completed', failed: 'failed', stopped: 'cancelled', cancelled: 'cancelled' };

/** "deepseek/deepseek-v4.1-flash" → "deepseek-v4.1-flash" (the vendor prefix only takes room on a narrow card). */
export const shortModel = (m) => String(m || '').replace(/^[^/]+\//, '').replace(/:free$/, ' (gratis)') || '—';
/** 75 → "1m15s". */
export const dur = (s) => (s < 60 ? `${s}d` : s < 3600 ? `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}d` : `${Math.floor(s / 3600)}j${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`);

/** Which brain a task went to, as a chip: "🪶 Jar (ringan)", "OpenJarvis (berat)" or "Hermes" — the one that governs (pure; unit-tested). */
export const laneLabel = (runtime) => (runtime === 'ringan' ? '🪶 Jar (ringan)' : runtime === 'openjarvis' ? 'OpenJarvis (berat)' : 'Hermes');

/** One line about the load of the lanes (pure; unit-tested). */
export function loadText(l) {
  if (!l) return '';
  const q = (l.hermes_queued || 0) + (l.openjarvis_queued || 0);
  return `Hermes mengatur — jar (ringan) ${l.light_running}${l.openjarvis_on ? ` · OpenJarvis (berat) ${l.openjarvis_running}` : ''}`
    + ` · Hermes ${l.hermes_running}/${l.slots}${l.hermes_queued ? ` (+${l.hermes_queued} antre)` : ''}${q && !l.hermes_queued ? ` · ${q} antre` : ''}`;
}

export function createWorkersCard({ box, api, toast }) {
  let list = [], lanesInfo = null, open = null, mode = '', shown = '', models = null, busy = false;
  const kind = el('div', 'kind', 'meja · pekerja'), head = el('div', 'title', 'Pekerja'), body = el('div', 'wbody');
  box.replaceChildren(kind, head, body);
  box.classList.add('workerscard');

  async function act(fn, ok) {
    if (busy) return;
    busy = true;
    try { await fn(); if (ok) toast(ok); } catch (err) { toast(err.message || 'Gagal', true); } finally { busy = false; }
  }

  async function loadModels() {
    if (models) return models;
    try { models = (await api.req('GET', '/api/v1/workers/models')).models; } catch { models = []; }
    return models;
  }

  function modelEditor(w) {
    const wrap = el('div', 'wedit');
    wrap.append(el('div', 'snippet', `Model utama untuk SEMUA pekerja kategori "${w.category}" (berlaku mulai panggilan berikutnya, juga yang sedang jalan). `
      + `Cadangan: ${w.chain.slice(1).map(shortModel).join(', ') || '—'}.`));
    const i = el('input'); i.placeholder = 'cari model, mis. deepseek, qwen, gpt'; i.setAttribute('list', 'wmodels'); i.autocomplete = 'off'; i.spellcheck = false;
    i.addEventListener('keydown', (e) => e.stopPropagation());
    const dl = document.getElementById('wmodels') || Object.assign(el('datalist'), { id: 'wmodels' });
    if (!dl.isConnected) document.body.append(dl);
    loadModels().then((ms) => { dl.replaceChildren(...ms.map((m) => { const o = el('option'); o.value = m.id; o.label = `${m.name}${m.free ? ' · gratis' : ` · $${m.price_out}/jt`}`; return o; })); });
    const go = button('Pakai', 'pbtn', () => act(async () => {
      const model = i.value.trim();
      if (!model) throw new Error('Isi nama model dulu');
      let r = await api.req('PUT', '/api/v1/composition/model', { category: w.category, model });
      if (r.needs_confirmation) {
        if (!confirm(r.say)) return;
        r = await api.req('PUT', '/api/v1/composition/model', { category: w.category, model, confirmed: true });
      }
      mode = ''; open = null; toast(`Model ${w.category}: ${shortModel(r.main)}${r.price ? ` · ${r.price}` : ''}`); shown = '';
    }));
    const row = el('div', 'pctl'); row.append(i, go);
    wrap.append(row);
    return wrap;
  }

  function sayBox(w) {
    const form = el('form', 'wsay');
    const i = el('input'); i.placeholder = 'Tulis pesan untuk pekerja ini…'; i.autocomplete = 'off'; i.maxLength = 2000;
    i.addEventListener('keydown', (e) => e.stopPropagation());
    form.append(i, button('Kirim', 'pbtn', () => {}));
    form.lastChild.type = 'submit';
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = i.value.trim();
      if (!text) return;
      act(async () => { await api.req('POST', `/api/v1/workers/${w.task_id}/say`, { text }); i.value = ''; }, 'Terkirim — pekerja membacanya sebelum langkah berikutnya.');
    });
    if (!w.can_say) form.append(el('div', 'snippet', 'Pekerja ini tidak sedang berjalan atau tidak bisa disela.'));
    return form;
  }

  function row(w) {
    const r = el('div', `wrow ${w.status}`);
    const top = el('div', 'wtop');
    top.append(el('span', `dot ${DOT[w.status] || 'queued'}`), el('b', 'wtitle', w.title), el('span', 'wtime', `${STATUS[w.status] || w.status} · ${dur(w.seconds)}`));
    const meta = el('div', 'wmeta');
    meta.append(el('span', 'chip', w.category || '—'), el('span', 'chip', laneLabel(w.runtime)),
      el('span', 'chip wmodel', shortModel(w.model)), ...(w.cost ? [el('span', 'chip', `$${w.cost.toFixed(4)}`)] : []));
    if (w.lane_note) meta.children[1].title = w.lane_note;
    if (w.model && w.main && w.model !== w.main) meta.lastChild.title = `Utama kategori ini: ${w.main}`;
    const ctl = el('div', 'pctl');
    if (w.can_stop) ctl.append(button('■ Stop', 'pbtn wstop', () => act(() => api.req('POST', `/api/v1/workers/${w.task_id}/stop`), 'Dihentikan.')));
    if (w.can_start) ctl.append(button('▶ Mulai', 'pbtn wgo', () => act(() => api.req('POST', `/api/v1/workers/${w.task_id}/start`), 'Dimulai lagi.')));
    if (!w.locked) ctl.append(button('⚙ Model', 'pbtn', () => { open = open === w.task_id && mode === 'model' ? null : w.task_id; mode = 'model'; shown = ''; render(); }));
    ctl.append(button('💬 Pesan', 'pbtn', () => { open = open === w.task_id && mode === 'say' ? null : w.task_id; mode = 'say'; shown = ''; render(); }));
    r.append(top, meta, ctl);
    if (w.error && (w.status === 'failed' || w.status === 'stopped')) r.append(el('div', 'snippet wbad', w.error));
    if (open === w.task_id) r.append(mode === 'model' ? modelEditor(w) : sayBox(w));
    return r;
  }

  function render() {
    body.replaceChildren();
    const active = list.filter((w) => w.can_stop).length;
    head.textContent = active ? `Pekerja — ${active} bekerja` : 'Pekerja';
    const lane = el('div', 'wlanes');
    lane.append(el('span', 'muted', loadText(lanesInfo)));
    if (lanesInfo) lane.append(button(lanesInfo.light_on ? '🪶 Jalur ringan: aktif' : '🪶 Jalur ringan: mati', 'pbtn', () => act(
      () => api.req('PUT', '/api/v1/workers/lanes', { light: !lanesInfo.light_on }), lanesInfo.light_on ? 'Jalur ringan dimatikan — semua lewat Hermes.' : 'Jalur ringan menyala.'),
      'Pencarian sederhana dijawab detik-an oleh model murah, tanpa sesi Hermes'));
    body.append(lane);
    if (!list.length) { body.append(el('div', 'snippet', 'Belum ada pekerja. Minta Jarvis mengerjakan sesuatu — ia muncul di sini lengkap dengan modelnya.')); return; }
    for (const w of list) body.append(row(w));
  }

  return {
    /** The server's workers list. Rebuilds only when something changed, and never while the owner is typing in it. */
    update(next, lanes) {
      list = next || [];
      lanesInfo = lanes || lanesInfo;
      const key = JSON.stringify(list.map((w) => [w.task_id, w.status, w.model, w.can_say, w.runtime, Math.floor(w.seconds / 10)])) + open + mode + JSON.stringify(lanesInfo);
      if (key === shown || body.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return;
      shown = key; render();
    },
  };
}
