// The desk's Proyek area (ADR-073): the owner's projects — goal, schedule, and a team of workers by role (how many, which AI model, whether they
// operate websites) — with what the latest run's workers are doing, and the schedules Jarvis made in chat (Hermes' cron jobs).
import { shortModel } from './workerscard.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn, title) => { const b = el('button', cls, text); b.type = 'button'; b.dataset.gesture = 'ok'; if (title) b.title = title; b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(ev); }); return b; };
const typing = (i) => { i.addEventListener('keydown', (e) => e.stopPropagation()); return i; };
const STATUS = { queued: 'antre', running: 'bekerja', completed: 'selesai', failed: 'gagal', stopped: 'dihentikan', cancelled: 'dibatalkan' };
export const SCHEDULES = [['manual', 'Manual'], ['hourly', 'Tiap jam'], ['daily', 'Tiap hari'], ['weekdays', 'Senin–Jumat'], ['weekly', 'Mingguan']];
const DAYS = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'];

/** Workers a project would start in one run (pure; unit-tested). */
export const teamSize = (roles) => (roles || []).reduce((n, r) => n + Math.max(1, Math.min(5, Number(r.workers) || 1)), 0);

export function createProjectsCard({ box, api, toast, onShowTask }) {
  let data = null, editing = null, shown = '', models = null;
  const head = el('div', 'kind', 'meja · proyek'), title = el('div', 'title', 'Proyek'), body = el('div', 'pjbody');
  box.replaceChildren(head, title, body);
  box.classList.add('projectscard');

  async function load() {
    if (box.hidden || editing) return;
    try { data = await api.req('GET', '/api/v1/projects'); } catch { return; }
    const key = JSON.stringify([data.projects.map((p) => [p.id, p.status, p.runs, p.next_run, p.workers.map((w) => [w.id, w.status])]), data.cron.length]);
    if (key !== shown) { shown = key; render(); }
  }
  async function act(fn, ok) {
    try { await fn(); if (ok) toast(ok); shown = ''; await load(); } catch (err) { toast(err.message || 'Gagal', true); }
  }

  function render() {
    body.replaceChildren();
    if (editing) { body.append(editor(editing)); return; }
    const top = el('div', 'pctl');
    top.append(button('＋ Proyek baru', 'mgo', () => { editing = { name: '', goal: '', schedule: 'manual', at_time: '08:00', weekday: 0, roles: [{ role: '', brief: '', workers: 1, model: '', web: false }] }; render(); }));
    body.append(top);
    if (!data?.projects.length) body.append(el('div', 'snippet', 'Belum ada proyek. Contoh: "Cari & lamar kerja" — peran Pencari (2 pekerja, operasi web) dan Penulis surat lamaran (1 pekerja), tiap hari 08:00.'));
    for (const p of data?.projects || []) body.append(project(p));
    if (data?.cron?.length) {
      body.append(el('div', 'slabel', 'Jadwal yang dibuat Jarvis lewat chat'));
      for (const c of data.cron) {
        const r = el('div', 'pjcron');
        r.append(el('b', null, c.name || c.prompt?.slice(0, 60) || 'Jadwal'), el('span', 'chip', c.schedule_display || c.schedule || ''),
          el('span', 'chip', c.enabled === false ? 'mati' : 'aktif'));
        if (c.next_run_at) r.append(el('span', 'chip', `berikutnya ${new Date(c.next_run_at).toLocaleString('id-ID', { dateStyle: 'short', timeStyle: 'short' })}`));
        body.append(r);
      }
    }
  }

  function project(p) {
    const c = el('div', `pjrow ${p.status}`);
    const top = el('div', 'pjtop');
    top.append(el('b', null, p.name), el('span', `chip ${p.status === 'active' ? '' : 'busy'}`, p.status === 'active' ? 'aktif' : 'dijeda'));
    c.append(top);
    if (p.goal) c.append(el('div', 'snippet', p.goal));
    const meta = el('div', 'wmeta');
    meta.append(el('span', 'chip', `🗓 ${p.schedule_text}`));
    if (p.next_run && p.status === 'active') meta.append(el('span', 'chip', `berikutnya ${new Date(p.next_run).toLocaleString('id-ID', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}`));
    meta.append(el('span', 'chip', `${p.runs}× jalan`));
    c.append(meta);
    const roles = el('div', 'wmeta');
    for (const r of p.roles) roles.append(el('span', 'chip wmodel', `${r.web ? '🌐 ' : ''}${r.role} ×${r.workers} · ${r.model ? shortModel(r.model) : 'model kategori'}`));
    c.append(roles);
    const ctl = el('div', 'pctl');
    ctl.append(button('▶ Jalankan', 'pbtn wgo', () => act(() => api.req('POST', `/api/v1/projects/${p.id}/run`), `Run baru "${p.name}" dimulai — pekerjanya muncul di Meja.`)),
      button(p.status === 'active' ? '⏸ Jeda' : '▶ Aktifkan jadwal', 'pbtn', () => act(() => api.req('PATCH', `/api/v1/projects/${p.id}`, { status: p.status === 'active' ? 'paused' : 'active' }))),
      button('✎ Kelola', 'pbtn', () => { editing = { ...p, roles: p.roles.map((r) => ({ ...r, model: r.model || '' })) }; render(); }),
      button('🗑', 'pbtn wstop', () => { if (confirm(`Hapus proyek "${p.name}"? Pekerja yang sedang jalan dihentikan; hasil tugas tetap ada.`)) act(() => api.req('DELETE', `/api/v1/projects/${p.id}`), 'Proyek dihapus.'); }, 'Hapus proyek'));
    c.append(ctl);
    const latest = p.workers.filter((w) => w.project_run === p.runs);
    if (latest.length) {
      c.append(el('div', 'slabel', `Run #${p.runs}`));
      for (const w of latest) {
        const r = el('div', 'pjworker');
        r.append(el('span', `dot ${w.status === 'stopped' ? 'cancelled' : w.status}`), el('b', null, w.role || w.title),
          el('span', 'chip', STATUS[w.status] || w.status), el('span', 'chip wmodel', shortModel(w.model_used || w.model_override || '')));
        if (['queued', 'running'].includes(w.status)) r.append(button('Lihat', 'pbtn', () => onShowTask(w.id), 'Lihat pekerja ini di Meja'));
        c.append(r);
        if (w.error) c.append(el('div', 'snippet wbad', w.error));
        else if (w.result && w.status === 'completed') c.append(el('div', 'snippet pjres', w.result));
      }
    }
    return c;
  }

  async function modelList() {
    if (models) return models;
    try { models = (await api.req('GET', '/api/v1/workers/models')).models; } catch { models = []; }
    return models;
  }

  function editor(p) {
    const f = el('form', 'pjedit');
    const field = (label, input) => { const w = el('label', 'mfield'); w.append(el('span', null, label), input); return w; };
    const name = typing(el('input')); name.value = p.name; name.placeholder = 'mis. Cari & lamar kerja';
    const goal = typing(el('textarea')); goal.rows = 3; goal.value = p.goal; goal.placeholder = 'Tujuan proyek, mis. melamar posisi IT Manager di Jakarta, gaji ≥ 25 jt';
    const sched = el('select'); for (const [v, t] of SCHEDULES) { const o = el('option', null, t); o.value = v; sched.append(o); } sched.value = p.schedule;
    const at = typing(el('input')); at.type = 'time'; at.value = p.at_time || '08:00';
    const day = el('select'); DAYS.forEach((d, i) => { const o = el('option', null, d); o.value = String(i); day.append(o); }); day.value = String(p.weekday ?? 0);
    const when = el('div', 'pctl'); when.append(field('Jadwal', sched), field('Jam (WIB)', at), field('Hari', day));
    const syncWhen = () => { at.parentElement.hidden = ['manual', 'hourly'].includes(sched.value); day.parentElement.hidden = sched.value !== 'weekly'; };
    sched.addEventListener('change', syncWhen);
    const dl = el('datalist'); dl.id = `pjmodels-${Math.random().toString(36).slice(2, 7)}`;
    modelList().then((ms) => dl.replaceChildren(...ms.map((m) => { const o = el('option'); o.value = m.id; o.label = `${m.name}${m.free ? ' · gratis' : ` · $${m.price_out}/jt`}`; return o; })));
    const rolesBox = el('div', 'pjroles'), total = el('div', 'snippet');
    const roles = p.roles.map((r) => ({ ...r }));
    const drawRoles = () => {
      rolesBox.replaceChildren(...roles.map((r, i) => {
        const b = el('div', 'pjrole');
        const role = typing(el('input')); role.value = r.role; role.placeholder = 'Peran, mis. Pencari lowongan'; role.addEventListener('input', () => { r.role = role.value; });
        const brief = typing(el('textarea')); brief.rows = 2; brief.value = r.brief; brief.placeholder = 'Apa yang dikerjakan peran ini, mis. buka JobStreet, cari IT Manager Jakarta, siapkan lamaran (jangan kirim)';
        brief.addEventListener('input', () => { r.brief = brief.value; });
        const n = typing(el('input')); n.type = 'number'; n.min = '1'; n.max = '5'; n.value = String(r.workers); n.addEventListener('input', () => { r.workers = Number(n.value) || 1; total.textContent = totalText(); });
        const model = typing(el('input')); model.value = r.model || ''; model.placeholder = 'default kategori (kosongkan)'; model.setAttribute('list', dl.id);
        model.addEventListener('input', () => { r.model = model.value.trim(); });
        const web = el('label', 'mcheck'), cb = el('input'); cb.type = 'checkbox'; cb.checked = !!r.web; cb.addEventListener('change', () => { r.web = cb.checked; });
        web.append(cb, el('span', null, '🌐 Operasikan situs (browser) — mis. bantu apply kerja; berhenti sebelum mengirim'));
        const row = el('div', 'pctl'); row.append(field('Jumlah pekerja', n), field('Model AI', model));
        b.append(field(`Peran ${i + 1}`, role), brief, row, web, button('Hapus peran', 'pbtn', () => { roles.splice(i, 1); drawRoles(); }));
        return b;
      }));
      total.textContent = totalText();
    };
    const totalText = () => `${teamSize(roles)} pekerja sekali jalan (maks ${data?.max_workers ?? 6}).`;
    drawRoles(); syncWhen();
    const save = button(p.id ? 'Simpan' : 'Buat proyek', 'mgo', async () => {
      const bodyOut = { name: name.value, goal: goal.value, schedule: sched.value, at_time: at.value || null, weekday: Number(day.value), roles };
      try {
        await api.req(p.id ? 'PUT' : 'POST', p.id ? `/api/v1/projects/${p.id}` : '/api/v1/projects', bodyOut);
        toast(p.id ? 'Proyek disimpan.' : 'Proyek dibuat. Tekan ▶ Jalankan untuk mulai sekarang.');
        editing = null; shown = ''; await load(); render();
      } catch (err) { toast(err.message, true); }
    });
    f.append(field('Nama proyek', name), field('Tujuan', goal), when, el('div', 'slabel', 'Tim pekerja'), rolesBox,
      button('＋ Peran', 'pbtn', () => { roles.push({ role: '', brief: '', workers: 1, model: '', web: false }); drawRoles(); }), total, dl);
    const ctl = el('div', 'pctl'); ctl.append(save, button('Batal', 'pbtn', () => { editing = null; render(); }));
    f.append(ctl);
    f.addEventListener('submit', (e) => e.preventDefault());
    return f;
  }

  load(); setInterval(load, 6000);
  return { reload: () => { shown = ''; return load(); } };
}
