// Cek berita (was Brief pagi; owner 2026-10-31): not a list of news but what the situation is, the themes behind it with their indicators
// and reasons (each linked to its news), what it means for him, and the opportunities he could take — with the market numbers it rests on.
import { get, header, html, icon, loading, post, render, speak, stopSpeaking, toast } from '../core.js';
import { laneChip } from '../ui.js';

let current = null;
const MOOD = { positif: ['green', 'Cenderung positif'], campuran: ['amber', 'Campuran'], waspada: ['red', 'Perlu waspada'] };
const KIND = { emas: 'Emas', saham_as: 'Saham AS', kripto: 'Kripto', reksa_dana: 'Reksa dana', tabungan: 'Tabungan', bisnis: 'Bisnis', karier: 'Karier',
  belanja: 'Belanja', lainnya: 'Lainnya' };
const SURE = { tinggi: 'green', sedang: 'amber', rendah: 'muted' };

const src = (r) => (r.link ? html` <a href="${r.link}" target="_blank" rel="noopener" class="small t-cyan">· ${r.sumber}</a>` : '');

function theme(t) {
  return html`<div class="card" style="gap:8px"><span class="k cyan">${t.judul}</span>
    ${t.kesimpulan ? html`<p class="sub" style="margin:0">${t.kesimpulan}</p>` : ''}
    ${t.indikator?.length ? html`<div style="display:flex;flex-direction:column;gap:4px">${t.indikator.map((i) => html`<div class="row sb" style="gap:8px;font-size:13px">
      <span>${icon('chart', 12)} ${i.nama}${i.arti ? html` <span class="small">— ${i.arti}</span>` : ''}</span><span class="mono" style="white-space:nowrap">${i.nilai}</span></div>`)}</div>` : ''}
    ${t.alasan?.length ? html`<details><summary class="small">Alasan (${t.alasan.length})</summary><div style="display:flex;flex-direction:column;gap:4px;margin-top:6px">
      ${t.alasan.map((r) => html`<span class="small">• ${r.isi}${src(r)}</span>`)}</div></details>` : ''}
    ${t.dampak ? html`<span class="small" style="color:var(--amber-t)">${icon('wallet', 12)} Bagimu: ${t.dampak}</span>` : ''}</div>`;
}

function chance(p) {
  return html`<div class="card green" style="gap:6px"><div class="row sb top" style="gap:8px"><b style="font-size:14px">${p.aksi}</b>
      <span class="tag ${SURE[p.yakin] || 'muted'}" style="white-space:nowrap">yakin ${p.yakin}</span></div>
    <span class="small">${KIND[p.kaitan] || p.kaitan} · ${p.horizon}</span>
    ${p.kenapa ? html`<span class="sub">${p.kenapa}</span>` : ''}
    ${p.risiko ? html`<span class="small" style="color:var(--red-t)">Risiko: ${p.risiko}</span>` : ''}</div>`;
}

function spoken(d) {
  return [d.ucapan || d.situasi, ...(d.peluang || []).slice(0, 2).map((p) => `Peluang: ${p.aksi}. ${p.kenapa}`)].filter(Boolean).join(' ');
}

export default {
  tab: 'beranda',
  async render(root) {
    root.innerHTML = String(html`${header('Cek berita')}<div class="scr">${loading()}</div>`);
    const { brief } = await get('/api/v1/app/brief');
    current = brief;
    const old = brief && !brief.data?.situasi && !brief.data?.tema;   // a list-style brief from before: make a fresh analysis
    if (!brief || old) {
      root.innerHTML = String(html`${header('Cek berita')}<div class="scr"><div class="card"><p>Belum ada analisis berita hari ini. JARVIS membuatnya otomatis tiap pagi
        (atur jamnya di Kontrol): situasi saat ini, indikator dan alasannya, serta peluang untuk keuanganmu.</p>
        <button class="btn primary" data-act="now">Analisis sekarang</button></div></div>`);
      return;
    }
    const d = brief.data;
    const day = new Date(`${brief.day}T00:00:00`);
    const mood = MOOD[d.suasana] || MOOD.campuran;
    root.innerHTML = String(html`${header('Cek berita', { sub: `${day.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long' })} · ${d.count || 0} berita dari ${brief.sources.length} sumber`, right: html`<button class="ib box" data-act="now" aria-label="Analisis ulang">${icon('repeat', 18)}</button>` })}
      <div class="scr">
        <div class="card ${mood[0]}" style="gap:8px"><div class="row sb"><span class="k ${mood[0]}">Situasi saat ini</span><span class="tag ${mood[0]}">${mood[1]}</span></div>
          ${d.judul ? html`<b style="font-size:17px;line-height:1.35">${d.judul}</b>` : ''}<p class="sub" style="margin:0">${d.situasi}</p></div>
        ${d.markets?.length ? html`<div class="sec"><span>Indikator pasar</span></div>
          <div class="g3">${d.markets.map((m) => html`<div class="kpi" style="padding:8px"><span style="font-size:10px">${m.label}</span>
            <b style="font-size:13px">${m.last != null ? Number(m.last).toLocaleString('id-ID', { maximumFractionDigits: 2 }) : '–'}</b>
            <span class="small" style="color:var(--${m.change == null ? 'tx2' : m.change >= 0 ? 'green' : 'red'})">${m.change == null ? '' : `${m.change > 0 ? '+' : ''}${String(m.change).replace('.', ',')}% 5h`}</span></div>`)}</div>` : ''}
        ${d.tema?.length ? html`<div class="sec"><span>Kenapa begitu</span></div>${d.tema.map(theme)}` : ''}
        ${d.peluang?.length ? html`<div class="sec"><span>Peluang untukmu</span></div>${d.peluang.map(chance)}
          <span class="small" style="padding:0 4px">Bahan pertimbangan dari berita & angka di atas, bukan perintah beli/jual. Investasi tetap lewat persetujuanmu dan batas di menu Investasi.</span>` : ''}
        ${d.waspada?.length ? html`<div class="card red" style="gap:6px"><span class="k red">Waspadai</span>${d.waspada.map((r) => html`<span class="small">• ${r.isi}${src(r)}</span>`)}</div>` : ''}
        ${d.weather ? html`<p class="small" style="padding:0 4px">${icon('rain', 14)} ${d.weather}</p>` : ''}
        <span class="small" style="padding:0 4px">Dianalisis oleh ${laneChip(d.lane)} lewat alur master · sumber: ${brief.sources.join(', ')}</span>
        <div class="btns"><button class="btn primary lg" data-act="read">${icon('speaker', 18)} Bacakan</button><button class="btn lg" data-act="hush">Diam</button><a class="btn lg" href="#/obrolan">Tanya lanjut</a></div>
      </div>`);
  },
  actions: {
    read() { speak(spoken(current.data)); },
    hush() { stopSpeaking(); },
    async now() { toast('Menganalisis berita & pasar… (±1 menit)'); await post('/api/v1/app/brief/now'); render(); },
  },
};
