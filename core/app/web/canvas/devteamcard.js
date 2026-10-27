// The desk's Tim Dev area (ADR-059): a dashed frame holding the three dev workers — bisan (analyst), coder (developer), qaqa (QA) — with
// what each is doing right now (the live steps of its task), its model, a word to it while it works, and the team's latest requests.
import { dur, shortModel } from './workerscard.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn, title) => { const b = el('button', cls, text); b.dataset.gesture = 'ok'; if (title) b.title = title; b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(ev); }); return b; };
const typing = (i) => i.addEventListener('keydown', (e) => e.stopPropagation());

export const JOB_STATUS = {
  analysing: 'bisan menulis spesifikasi', coding: 'coder membangun', testing: 'diuji penguji otomatis', reviewing: 'qaqa memeriksa',
  awaiting_owner: 'menunggu persetujuanmu', done: 'selesai', failed: 'berhenti', cancelled: 'dibatalkan', needs_human: 'butuh pengembang manusia',
};
/** Which member a job is with right now (pure; unit-tested). */
export const jobHolder = (status) => ({ analysing: 'bisan', coding: 'coder', reviewing: 'qaqa' }[status] || '');

export function createDevTeamCard({ box, api, toast }) {
  let data = null, shown = '', sayOpen = '', busy = false;
  box.classList.add('devteam');
  const head = el('div', 'dthead'), title = el('div', 'dttitle', 'Tim Dev'), sub = el('div', 'snippet', 'bisan menganalisis → coder membangun → penguji otomatis → qaqa memeriksa → kamu menyetujui');
  head.append(el('div', 'kind', 'meja · tim dev'), title, sub);
  const row = el('div', 'dtmembers'), jobs = el('div', 'dtjobs');
  const form = el('form', 'dtask');
  const input = el('textarea'); input.rows = 2; input.placeholder = 'Minta tim dev… mis. "panel chat bisa diciutkan jadi tombol bulat"'; typing(input);
  const send = button('Kirim ke tim', 'mgo', () => {}); send.type = 'submit';
  form.append(input, send);
  box.replaceChildren(head, row, form, jobs);

  async function act(fn, ok) {
    if (busy) return;
    busy = true;
    try { await fn(); if (ok) toast(ok); shown = ''; } catch (err) { toast(err.message || 'Gagal', true); } finally { busy = false; }
  }
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (text.length < 8) { toast('Tulis permintaannya lebih jelas.', true); return; }
    act(async () => { await api.req('POST', '/api/v1/devteam/jobs', { text }); input.value = ''; }, 'Diterima — bisan mulai menulis spesifikasi.');
  });

  function member(m, station) {
    const c = el('div', `dtmember ${m.busy ? 'busy' : 'idle'}`);
    const top = el('div', 'dttop');
    top.append(el('span', 'dtavatar', m.icon), el('div', 'dtname'));
    top.lastChild.append(el('b', null, m.name), el('span', null, m.role));
    top.append(el('span', `dot ${m.busy ? 'running' : 'completed'}`));
    c.append(top);
    const meta = el('div', 'wmeta');
    meta.append(el('span', 'chip wmodel', shortModel(m.model)));
    if (m.job) meta.append(el('span', 'chip', `permintaan #${m.job}`));
    if (m.busy && m.seconds != null) meta.append(el('span', 'chip', dur(m.seconds)));
    c.append(meta);
    if (m.busy) {
      c.append(el('div', 'dtnow', m.task_title || 'bekerja…'));
      const steps = (station?.steps || []).slice(-4);
      if (steps.length) {
        const ul = el('ul', 'steps');
        ul.append(...steps.map((s) => el('li', s.status === 'running' ? 'now' : '', `${s.icon} ${s.text}${s.n > 1 ? ` ×${s.n}` : ''}`)));
        c.append(ul);
      }
      if (station?.thought) c.append(el('div', 'thought', `💭 ${station.thought}`));
    } else c.append(el('div', 'snippet dtlast', m.last ? m.last : 'Menunggu pekerjaan.'));
    const ctl = el('div', 'pctl');
    if (m.can_say) ctl.append(button('💬 Pesan', 'pbtn', () => { sayOpen = sayOpen === m.id ? '' : m.id; shown = ''; render(); }));
    c.append(ctl);
    if (sayOpen === m.id && m.can_say) {
      const f = el('form', 'wsay'), i = el('input'); i.placeholder = `Pesan untuk ${m.name}…`; i.maxLength = 2000; typing(i);
      const go = button('Kirim', 'pbtn', () => {}); go.type = 'submit';
      f.append(i, go);
      f.addEventListener('submit', (e) => {
        e.preventDefault();
        const text = i.value.trim();
        if (text) act(() => api.req('POST', `/api/v1/workers/${m.task_id}/say`, { text }), `Terkirim ke ${m.name}.`);
      });
      c.append(f);
    }
    return c;
  }

  function job(j) {
    const r = el('div', `dtjob ${j.status}`);
    const holder = jobHolder(j.status);
    r.append(el('b', null, `#${j.id} ${j.request}`));
    const meta = el('div', 'wmeta');
    meta.append(el('span', 'chip', JOB_STATUS[j.status] || j.status), el('span', 'chip', `putaran ${j.round}/${data.max_rounds}`));
    if (j.change_id) meta.append(el('span', 'chip', `perubahan #${j.change_id}`));
    if (holder) meta.append(el('span', 'chip wmodel', `di ${holder}`));
    r.append(meta);
    if (j.note) r.append(el('div', 'snippet', j.note));
    if (j.review && ['coding', 'failed', 'awaiting_owner'].includes(j.status)) r.append(el('div', 'snippet dtreview', `qaqa: ${j.review}`));
    if (['analysing', 'coding', 'testing', 'reviewing'].includes(j.status)) {
      r.append(button('Batalkan', 'pbtn', () => { if (confirm(`Batalkan permintaan #${j.id}?`)) act(() => api.req('POST', `/api/v1/devteam/jobs/${j.id}/cancel`), 'Dibatalkan.'); }));
    }
    return r;
  }

  let stations = [];
  function render() {
    const byTask = new Map(stations.map((s) => [s.task_id, s]));
    row.replaceChildren(...data.members.map((m) => member(m, byTask.get(m.task_id))));
    const working = data.members.filter((m) => m.busy).length;
    title.textContent = working ? `Tim Dev — ${working} bekerja` : 'Tim Dev';
    jobs.replaceChildren(el('div', 'slabel', 'Permintaan terbaru'), ...(data.jobs.length ? data.jobs.map(job) : [el('div', 'snippet', 'Belum ada. Tulis permintaan di atas, atau bilang ke Jarvis "tim dev, tolong …".')]));
  }

  return {
    update(next, liveStations) {
      if (!next) return;
      data = next; stations = liveStations || [];
      const steps = data.members.map((m) => (stations.find((s) => s.task_id === m.task_id)?.steps || []).length);
      const key = JSON.stringify([data.members.map((m) => [m.task_id, m.busy, m.model, Math.floor((m.seconds || 0) / 10)]), steps,
        data.jobs.map((j) => [j.id, j.status, j.round]), sayOpen]);
      if (key === shown || (box.contains(document.activeElement) && /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName))) return;
      shown = key; render();
    },
  };
}
