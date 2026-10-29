// Brief pagi (mockup 44): first what touches the owner, then Indonesia, the economy, the world, the markets — each item with its source.
import { get, header, html, icon, loading, post, render, speak, stopSpeaking, toast } from '../core.js';
import { laneChip } from '../ui.js';

let current = null;

function section(title, tone, rows) {
  if (!rows?.length) return '';
  return html`<div class="card ${tone === 'amber' ? 'amber' : ''}"><span class="k ${tone}">${title}</span>
    ${rows.map((r, i) => html`<div class="row top" style="gap:10px">${tone === 'amber' ? html`<span class="mono t-amber2" style="font-size:12px">${i + 1}</span>` : ''}
      <span style="font-size:13px;line-height:1.5">${r.judul ? html`<b>${r.judul}</b> ` : ''}<span style="color:var(--tx2)">${r.isi}</span>
      ${r.link ? html` <a href="${r.link}" target="_blank" rel="noopener" class="small t-cyan">· ${r.sumber}</a>` : ''}</span></div>`)}</div>`;
}

function spoken(d) {
  const parts = [d.ucapan];
  for (const r of d.perlu || []) parts.push(`${r.judul || ''}. ${r.isi}`);
  return parts.filter(Boolean).join(' ');
}

export default {
  tab: 'beranda',
  async render(root) {
    root.innerHTML = String(html`${header('Brief pagi')}<div class="scr">${loading()}</div>`);
    const { brief } = await get('/api/v1/app/brief');
    current = brief;
    if (!brief) {
      root.innerHTML = String(html`${header('Brief pagi')}<div class="scr"><div class="card"><p>Belum ada brief hari ini. Brief dibuat otomatis tiap pagi (atur jamnya di Kontrol), atau buat sekarang.</p>
        <button class="btn primary" data-act="now">Buat brief sekarang</button></div></div>`);
      return;
    }
    const d = brief.data;
    const day = new Date(`${brief.day}T00:00:00`);
    root.innerHTML = String(html`${header('Brief pagi', { sub: `${day.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long' })} · ${d.count || 0} berita dari ${brief.sources.length} sumber`, right: html`<button class="ib box" data-act="now" aria-label="Perbarui">${icon('repeat', 18)}</button>` })}
      <div class="scr">
        ${d.ucapan ? html`<p class="lead" style="padding:0 4px">${d.ucapan}</p>` : ''}
        ${section('Perlu perhatianmu', 'amber', d.perlu)}
        ${section('Indonesia', 'red', d.indonesia)}
        ${section('Ekonomi', 'green', d.ekonomi)}
        ${section('Dunia', 'cyan', d.dunia)}
        ${d.markets?.length ? html`<div class="g4" style="grid-template-columns:repeat(${Math.min(5, d.markets.length)},minmax(0,1fr))">${d.markets.map((m) => html`<div class="kpi" style="padding:8px"><span style="font-size:10px">${m.label}</span>
          <b style="font-size:12px;color:var(--${m.change == null ? 'tx' : m.change >= 0 ? 'green' : 'red'})">${m.change == null ? '–' : `${m.change > 0 ? '+' : ''}${String(m.change).replace('.', ',')}%`}</b></div>`)}</div>` : ''}
        ${d.weather ? html`<p class="small" style="padding:0 4px">${icon('rain', 14)} ${d.weather}</p>` : ''}
        <span class="small" style="padding:0 4px">Ditulis oleh ${laneChip(d.lane)} lewat alur master · sumber: ${brief.sources.join(', ')}</span>
        <div class="btns"><button class="btn primary lg" data-act="read">${icon('speaker', 18)} Bacakan</button><button class="btn lg" data-act="hush">Diam</button><a class="btn lg" href="#/obrolan">Tanya lanjut</a></div>
      </div>`);
  },
  actions: {
    read() { speak(spoken(current.data)); },
    hush() { stopSpeaking(); },
    async now() { toast('Menyusun brief… (±30 detik)'); await post('/api/v1/app/brief/now'); render(); },
  },
};
