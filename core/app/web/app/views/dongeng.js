// Dongeng (mockup 22): tonight's bedtime story for his child — big, warm reading text for him to read aloud (or JARVIS reads it), a new one
// any time, the themes and the child's age in settings; the stories told before.
import { $, get, header, html, icon, loading, post, put, render, speak, stopSpeaking, toast } from '../core.js';
import { laneChip } from '../ui.js';

let cur = null, story = null, size = 19;
try { size = Number(localStorage.getItem('jarvis_story_size')) || 19; } catch { /* no storage */ }

export default {
  tab: 'beranda',
  feature: 'dongeng',
  async render(root, route) {
    root.innerHTML = String(html`${header('Dongeng')}<div class="scr">${loading()}</div>`);
    const d = cur = await get('/api/v1/app/story');
    const id = route.params[0];
    story = id ? d.stories.find((s) => String(s.id) === id) : (d.tonight || null);
    const s = d.settings;
    document.body.classList.toggle('warm', !!story);
    root.innerHTML = String(html`${header(story ? story.title : 'Dongeng', { sub: story ? `${story.theme} · ±${story.data.menit} menit` : '' })}
      <div class="scr">
        ${story ? html`<div class="row sb"><span class="small">${story.data.paragraf.length} bagian</span><div class="row" style="gap:6px"><button class="chip" data-act="size" data-d="-2" aria-label="Huruf lebih kecil">A−</button><button class="chip" data-act="size" data-d="2" aria-label="Huruf lebih besar">A+</button></div></div>
          <article class="reading" id="story" style="font-family:Literata,serif;font-size:${size}px;line-height:1.75;display:flex;flex-direction:column;gap:14px">
            ${story.data.paragraf.map((p) => html`<p style="margin:0">${p}</p>`)}</article>
          ${story.data.pesan ? html`<div class="card"><span class="small">Pesan: ${story.data.pesan}</span></div>` : ''}
          <div class="btns"><button class="btn lg" data-act="read">${icon('speaker', 18)} Bacakan</button><button class="btn lg" data-act="stop">${icon('stop', 18)}</button>
            <button class="btn lg" data-act="liked" data-id="${story.id}">${icon('heart', 18)}</button></div>`
          : html`<div class="card violet"><span class="k violet">Belum ada dongeng malam ini</span><p class="sub">Dibuat otomatis jam ${s.time} saat kamu di rumah, atau buat sekarang.</p></div>`}
        <div class="chips">${s.themes.map((t) => html`<button class="chip" data-act="new" data-t="${t}">${t}</button>`)}<button class="chip cyan" data-act="new" data-t="">${icon('bolt', 13)} Dongeng baru</button></div>
        ${d.stories.length > 1 ? html`<span class="sec">Sebelumnya</span><div class="list">${d.stories.filter((x) => x.id !== story?.id).slice(0, 10).map((x) => html`<a class="li click" href="#/dongeng/${x.id}">
          <span class="ico violet">${icon('book', 16)}</span><div class="grow"><div style="font-size:14px">${x.title}</div><div class="small">${x.theme} · ${new Date(x.created_at).toLocaleDateString('id-ID', { weekday: 'short', day: 'numeric', month: 'short' })}${x.status === 'liked' ? ' · ❤' : ''}</div></div></a>`)}</div>` : ''}
        <details class="card"><summary class="small">Pengaturan</summary><form id="sf" style="display:flex;flex-direction:column;gap:8px">
          <div class="g2"><label class="field">Nama anak (opsional)<input name="child_name" value="${s.child_name}"></label><label class="field">Usia<input name="child_age" type="number" min="1" max="12" value="${s.child_age}"></label></div>
          <label class="field">Tema (pisah koma)<input name="themes" value="${s.themes.join(', ')}"></label>
          <div class="g2"><label class="field">Panjang (menit)<input name="length_min" type="number" min="2" max="15" value="${s.length_min}"></label><label class="field">Jam tawaran<input name="time" type="time" value="${s.time}"></label></div>
          <button class="btn" data-act="save">Simpan</button></form></details>
        ${story?.data ? html`<span class="small" style="padding:0 4px">Ditulis lewat alur master ${laneChip(story.data.lane)}</span>` : ''}
      </div>`);
    return () => document.body.classList.remove('warm');
  },
  actions: {
    size(b) {   // in place, so reading aloud is not interrupted
      size = Math.max(15, Math.min(30, size + Number(b.dataset.d)));
      const a = $('#story'); if (a) a.style.fontSize = `${size}px`;
      try { localStorage.setItem('jarvis_story_size', String(size)); } catch { /* no storage */ }
    },
    read() { if (story) speak(`${story.title}. ${story.data.paragraf.join(' ')}`); },
    stop() { stopSpeaking(); },
    async liked(b) { await post(`/api/v1/app/story/${b.dataset.id}/mark`, { status: 'liked' }); toast('Disimpan sebagai favorit'); },
    async new(b) { toast('Menulis dongeng…'); const r = await post('/api/v1/app/story', { theme: b.dataset.t }); location.hash = `#/dongeng/${r.id}`; },
    async save(b, e) {
      e?.preventDefault();
      const v = Object.fromEntries(new FormData($('#sf')).entries());
      await put('/api/v1/app/settings/story', { child_name: v.child_name, child_age: Number(v.child_age) || 5, themes: v.themes.split(',').map((x) => x.trim()).filter(Boolean),
        length_min: Number(v.length_min) || 5, time: v.time || '20:00' });
      toast('Tersimpan'); render();
    },
  },
};
