// Rapat on the web (ADR-063): the meetings the phone's Rapat tab shows — list, minutes (summary, decisions, action items, open questions),
// the transcript with its speakers (rename them, search it, play a moment), questions about the meeting, the .docx — inside Catatan.
import { dueLabel } from './lib.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn, title) => { const b = el('button', cls, text); if (title) b.title = title; b.addEventListener('click', (e) => { e.stopPropagation(); fn(e); }); return b; };

export const MEETING_STATUS = { recording: '● merekam', queued: 'antre diproses', transcribing: 'menyalin suara', summarizing: 'menyusun notulen', done: 'selesai', failed: 'gagal' };

/** 754 → "12:34", 3725 → "1:02:05". */
export function clock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
}

/** Consecutive lines of one speaker become one turn (how a transcript reads best). Pure; unit-tested. */
export function turns(segments) {
  const out = [];
  for (const s of segments || []) {
    const last = out[out.length - 1];
    if (last && last.speaker === s.speaker && s.start - last.end < 6) { last.text += ` ${s.text}`; last.end = s.end; } else out.push({ speaker: s.speaker || '?', start: s.start, end: s.end, text: s.text || '' });
  }
  return out;
}

/** Which minute-long audio piece holds second t (the recorder uploads one file a minute). */
export const chunkOf = (t) => Math.max(0, Math.floor((Number(t) || 0) / 60));

export function createMeetings({ api, toast, showView, onOpenPage }) {
  const list = document.querySelector('#meetinglist'), detail = document.querySelector('#meetingdetail');
  let audio = null;

  async function blob(path) {
    const r = await fetch(path, { headers: { Authorization: `Bearer ${api.token()}` } });
    if (!r.ok) throw new Error(r.status === 404 ? 'audionya sudah dihapus otomatis' : `HTTP ${r.status}`);
    return URL.createObjectURL(await r.blob());
  }

  async function openList() {
    showView('#meetingsview');
    document.title = 'Rapat · Catatan';
    let rows;
    try { rows = await api.req('GET', '/api/v1/meetings'); } catch (err) { list.replaceChildren(el('div', 'empty', err.message)); return; }
    if (!rows.length) { list.replaceChildren(el('div', 'empty', 'Belum ada rapat. Tekan "Mulai rapat" — rekamannya di Meja (browser ini) atau di HP.')); return; }
    list.replaceChildren(...rows.map((m) => {
      const a = el('a', `mrowcard ${m.status}`); a.href = `#meeting/${m.id}`;
      const top = el('div', 'mtop');
      top.append(el('b', null, m.title || 'Rapat'), el('span', `chip ${m.status === 'done' ? '' : 'busy'}`, MEETING_STATUS[m.status] || m.status));
      const meta = el('div', 'tmeta');
      if (m.started_at) meta.append(el('span', 'chip', `📅 ${new Date(m.started_at).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' })}`));
      if (m.duration_s) meta.append(el('span', 'chip', `⏱ ${clock(m.duration_s)}`));
      if (m.action_items) meta.append(el('span', 'chip', `☑ ${m.action_items} action item`));
      if (m.confidential) meta.append(el('span', 'chip', '🔒 rahasia'));
      a.append(top, meta);
      if (m.ringkasan) a.append(el('div', 'muted mclip', m.ringkasan));
      return a;
    }));
  }

  function section(title, items, render) {
    if (!items?.length) return [];
    return [el('h2', 'mh', title), ...items.map(render)];
  }

  async function openOne(id) {
    showView('#meetingview');
    detail.replaceChildren(el('div', 'empty', 'Memuat rapat…'));
    let m;
    try { m = await api.req('GET', `/api/v1/meetings/${id}`); } catch (err) { detail.replaceChildren(el('div', 'empty', err.message)); return; }
    document.title = `${m.title || 'Rapat'} · Rapat`;
    const s = m.summary || {}, parts = [];
    const head = el('div', 'pagehead');
    head.append(el('div', 'pageicon', '🎙'), el('h1', 'pagetitle', m.title || 'Rapat'));
    const meta = el('div', 'tmeta');
    meta.append(el('span', 'chip', MEETING_STATUS[m.status] || m.status));
    if (m.started_at) meta.append(el('span', 'chip', `📅 ${new Date(m.started_at).toLocaleString('id-ID', { dateStyle: 'full', timeStyle: 'short' })}`));
    if (m.duration_s) meta.append(el('span', 'chip', `⏱ ${clock(m.duration_s)}`));
    const who = m.context?.participants || [];
    if (who.length) meta.append(el('span', 'chip', `👥 ${who.join(', ')}`));
    head.append(meta);
    const acts = el('div', 'pageactions');
    if (m.document_id) acts.append(button('⬇ Notulen .docx', 'btn', async () => {
      try { const a = el('a'); a.href = await blob(`/api/v1/documents/${m.document_id}`); a.download = `Notulen — ${m.title || 'rapat'}.docx`; a.click(); } catch (err) { toast(err.message, true); }
    }));
    if (m.status === 'done') acts.append(button('📝 Buka di Catatan', 'btn', async () => {
      try { const p = await api.req('POST', `/api/v1/notes/meetings/${m.id}`); onOpenPage(p.id); } catch (err) { toast(err.message, true); }
    }, 'Halaman catatan rapat ini: tugasnya bisa dicentang di daftar Tugas'));
    acts.append(button('🗑', 'btn bad', async () => {
      if (!confirm(`Hapus rapat "${m.title}" beserta rekaman dan transkripnya? Tidak bisa dibatalkan.`)) return;
      try { await api.req('DELETE', `/api/v1/meetings/${m.id}`); toast('Rapat dihapus.'); location.hash = '#meetings'; } catch (err) { toast(err.message, true); }
    }, 'Hapus rapat'));
    head.append(acts);
    parts.push(head);
    if (m.status !== 'done') parts.push(el('div', 'conflict', m.status === 'failed' ? `Rapat ini gagal diproses: ${m.error || ''}` : 'Notulen sedang dibuat — muat ulang beberapa saat lagi.'));
    if (s.ringkasan) parts.push(el('h2', 'mh', 'Ringkasan'), el('p', 'mtext', s.ringkasan));
    parts.push(...section('Keputusan', s.keputusan, (k) => el('div', 'mli', `• ${k}`)));
    parts.push(...section('Action item', s.action_items, (a) => {
      const r = el('div', 'trow');
      r.append(el('div', 'ttext', a.apa || ''));
      const mt = el('div', 'tmeta');
      if (a.siapa) mt.append(el('span', 'chip who', `👤 ${a.siapa}`));
      if (a.tenggat) mt.append(el('span', 'chip', `📅 ${/^\d{4}-\d{2}-\d{2}$/.test(a.tenggat) ? dueLabel(a.tenggat) : a.tenggat}`));
      r.append(mt);
      return r;
    }));
    parts.push(...section('Pertanyaan terbuka', s.pertanyaan, (q) => el('div', 'mli', `? ${q}`)));
    if (s.topik?.length) { const tags = el('div', 'tmeta'); tags.append(...s.topik.map((t) => el('span', 'chip', `# ${t}`))); parts.push(tags); }
    if (m.status === 'done') parts.push(askBox(m));
    if (m.transcript?.length) parts.push(transcriptBox(m));
    detail.replaceChildren(...parts);
  }

  function askBox(m) {
    const box = el('div', 'mask'), f = el('form', 'quickadd'), i = el('input'); i.placeholder = 'Tanya tentang rapat ini… (mis. "apa kata Rina soal anggaran?")';
    const out = el('div', 'mtext');
    f.append(i, button('Tanya', 'btn primary', () => {}));
    f.lastChild.type = 'submit';
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const q = i.value.trim();
      if (q.length < 2) return;
      out.textContent = 'Mencari di transkrip…';
      try {
        const r = await api.req('POST', `/api/v1/meetings/${m.id}/ask`, { question: q });
        out.replaceChildren(el('p', null, r.answer), ...(r.sources || []).map((src) => button(`⏱ ${clock(src.t)} — ${src.text}`, 'msrc', () => play(m, src.t))));
      } catch (err) { out.textContent = err.message; }
    });
    box.append(el('h2', 'mh', 'Tanya rapat ini'), f, out);
    return box;
  }

  function transcriptBox(m) {
    const box = el('div', 'mtranscript');
    const tools = el('div', 'quickadd'), find = el('input'); find.placeholder = 'Cari di transkrip…';
    tools.append(find);
    const names = [...new Set(m.transcript.map((s) => s.speaker).filter(Boolean))];
    const rename = el('div', 'tmeta');
    rename.append(el('span', 'muted', 'Pembicara (klik untuk memberi nama):'), ...names.map((n) => button(`👤 ${n}`, 'chip who', async () => {
      const to = prompt(`Siapa "${n}"?`, n.startsWith('Pembicara') ? '' : n);
      if (!to || to.trim() === n) return;
      try { await api.req('POST', `/api/v1/meetings/${m.id}/speakers`, { from: n, to: to.trim() }); toast(`"${n}" sekarang "${to.trim()}". Notulennya dibuat ulang.`); openOne(m.id); }
      catch (err) { toast(err.message, true); }
    })));
    const lines = el('div', 'mlines');
    const draw = () => {
      const q = find.value.trim().toLowerCase();
      const rows = turns(m.transcript).filter((t) => !q || t.text.toLowerCase().includes(q) || t.speaker.toLowerCase().includes(q));
      lines.replaceChildren(...(rows.length ? rows.slice(0, 600).map((t) => {
        const r = el('div', 'mline');
        r.append(button(clock(t.start), 'mtime', () => play(m, t.start), 'Putar dari sini'), el('b', 'mwho', t.speaker), el('span', null, t.text));
        return r;
      }) : [el('div', 'empty', 'Tidak ada yang cocok.')]));
    };
    find.addEventListener('input', draw);
    draw();
    box.append(el('h2', 'mh', `Transkrip · ${m.transcript.length} potongan`), rename, tools, lines);
    return box;
  }

  async function play(m, t) {
    const n = chunkOf(t);
    try {
      const url = await blob(`/api/v1/meetings/${m.id}/chunks/${n}`);
      if (!audio) { audio = el('audio', 'mplayer'); audio.controls = true; document.body.append(audio); }
      if (audio.dataset.url) URL.revokeObjectURL(audio.dataset.url);
      audio.dataset.url = url; audio.src = url;
      audio.addEventListener('loadedmetadata', () => { audio.currentTime = Math.max(0, t - n * 60); audio.play().catch(() => {}); }, { once: true });
    } catch (err) { toast(err.message, true); }
  }

  async function start() {
    try { await api.req('POST', '/api/v1/meetings/want'); location.href = '/canvas/'; }   // the desk's meeting card records (consent, then Mulai rekam)
    catch (err) { toast(err.message, true); }
  }

  return { openList, openOne, start };
}
