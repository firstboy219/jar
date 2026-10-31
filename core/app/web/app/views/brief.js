// Cek berita (was Brief pagi; owner 2026-10-31): not a list of news but what the situation is — three points first, each theme as a chain
// of cause and effect with its indicators and reasons (each linked to its news), 2–3 scenarios for the coming months — and then the brain in
// his place: three plans for 1–3 months (safe, balanced, bold). The one he picks becomes week-by-week tasks in Catatan.
import { get, header, html, icon, loading, on, post, render, sheet, speak, stopSpeaking, toast } from '../core.js';
import { laneChip } from '../ui.js';

let current = null, planTab = null;
const MOOD = { positif: ['green', 'Cenderung positif'], campuran: ['amber', 'Campuran'], waspada: ['red', 'Perlu waspada'] };
const KIND = { emas: 'Emas', saham_as: 'Saham AS', kripto: 'Kripto', reksa_dana: 'Reksa dana', tabungan: 'Tabungan', bisnis: 'Bisnis', karier: 'Karier',
  belanja: 'Belanja', lainnya: 'Lainnya' };
const SURE = { tinggi: 'green', sedang: 'amber', rendah: 'muted' };
const LIKELY = { besar: 'red', sedang: 'amber', kecil: 'muted' };
const STYLE = { aman: ['green', 'Aman'], seimbang: ['cyan', 'Seimbang'], berani: ['violet', 'Berani'] };
const FEEL = { 'sangat takut': 'red', takut: 'amber', netral: 'muted', optimis: 'green', euforia: 'violet' };
const TECH = { 'beli kuat': 'green', beli: 'green', netral: 'muted', jual: 'red', 'jual kuat': 'red' };
const ECON = /harga|emas|saham|ihsg|rupiah|dolar|bansos|pajak|bbm|pertalite|gaji|bunga|kredit|pinjol|bitcoin|kripto|crypto|investasi|bank|ekonomi|inflasi|phk|lowongan|cpns|tarif|listrik|um[rp]|thr|bpjs|ojk|\bbi\b|pluang|reksa|obligasi|properti|kpr|cicilan/i;
const ARAH = { untung: ['green', 'menguntungkanmu'], rugi: ['red', 'merugikanmu'], campuran: ['amber', 'campuran'] };
const STAGES = [['kumpul', 'Pengumpul data', 'Satu worker per sumber, berjalan bersamaan — tanpa AI'], ['analisa', 'Analis', 'Menyimpulkan situasi dari data publik'],
  ['jadi-kamu', 'Jadi kamu', 'Mengumpulkan data tentangmu lalu membandingkannya dengan hasil analis']];
const pct = (v) => (v == null ? '' : `${v > 0 ? '+' : ''}${String(v).replace('.', ',')}%`);

const src = (r) => (r.link ? html` <a href="${r.link}" target="_blank" rel="noopener" class="small t-cyan">· ${r.sumber}</a>` : '');
const dayOf = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' });

function chain(links) {
  return html`<div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px">${links.map((c, i) => html`${i ? html`<span style="color:var(--mu)">${icon('right', 11)}</span>` : ''}
    <span class="tag ${i === links.length - 1 ? 'amber' : 'muted'}" style="white-space:normal;text-align:left">${c}</span>`)}</div>`;
}

function theme(t) {
  return html`<div class="card" style="gap:8px"><span class="k cyan">${t.judul}</span>
    ${t.kesimpulan ? html`<p class="sub" style="margin:0">${t.kesimpulan}</p>` : ''}
    ${t.rantai?.length ? chain(t.rantai) : ''}
    ${t.indikator?.length ? html`<div style="display:flex;flex-direction:column;gap:4px">${t.indikator.map((i) => html`<div class="row sb" style="gap:8px;font-size:13px">
      <span>${icon('chart', 12)} ${i.nama}${i.arti ? html` <span class="small">— ${i.arti}</span>` : ''}</span><span class="mono" style="white-space:nowrap">${i.nilai}</span></div>`)}</div>` : ''}
    ${t.alasan?.length ? html`<details><summary class="small">Alasan & sumber (${t.alasan.length})</summary><div style="display:flex;flex-direction:column;gap:4px;margin-top:6px">
      ${t.alasan.map((r) => html`<span class="small">• ${r.isi}${src(r)}</span>`)}</div></details>` : ''}
    ${t.dampak ? html`<span class="small" style="color:var(--${(ARAH[t.arah] || ['amber'])[0]}-t)">${icon('wallet', 12)} Bagimu${t.arah ? ` (${ARAH[t.arah][1]})` : ''}: ${t.dampak}</span>` : ''}</div>`;
}

function scenario(s) {
  return html`<div class="card" style="gap:6px"><div class="row sb top" style="gap:8px"><b style="font-size:14px">${s.nama}</b>
      <span class="tag ${LIKELY[s.kemungkinan]}" style="white-space:nowrap">kemungkinan ${s.kemungkinan}</span></div>
    ${s.isi ? html`<span class="sub">${s.isi}</span>` : ''}
    ${s.tanda ? html`<span class="small">${icon('eye', 12)} Tandanya: ${s.tanda}</span>` : ''}</div>`;
}

function plan(p, i) {
  const st = STYLE[p.gaya] || STYLE.seimbang;
  const months = [...new Set(p.langkah.map((s) => Math.ceil(s.minggu / 4)))];
  return html`<div class="card ${st[0]}" style="gap:10px">
    <div class="row sb top" style="gap:8px"><b style="font-size:16px;line-height:1.3">${p.nama}</b><span class="tag ${st[0]}" style="white-space:nowrap">${p.bulan} bulan</span></div>
    ${p.kenapa ? html`<p class="sub" style="margin:0;font-style:italic">“${p.kenapa}”</p>` : ''}
    ${p.target ? html`<div class="row" style="gap:6px;font-size:13px">${icon('star', 13)}<span><b>Target:</b> ${p.target}</span></div>` : ''}
    ${months.map((m) => html`<div style="display:flex;flex-direction:column;gap:6px"><span class="k" style="font-size:11px">Bulan ${m}</span>
      ${p.langkah.filter((s) => Math.ceil(s.minggu / 4) === m).map((s) => html`<div class="row top" style="gap:8px;font-size:13px">
        <span class="mono small" style="flex:0 0 40px">Mg ${s.minggu}</span><span class="grow">${s.apa}</span><span class="small" style="white-space:nowrap">${KIND[s.kaitan] || ''}</span></div>`)}</div>`)}
    ${p.risiko ? html`<span class="small" style="color:var(--red-t)">Risiko: ${p.risiko}</span>` : ''}
    ${p.berhenti_jika ? html`<span class="small">${icon('alert', 12)} Berhenti/sesuaikan jika: ${p.berhenti_jika}</span>` : ''}
    ${p.dipilih ? html`<a class="btn" href="#/catatan">${icon('check', 16)} Dipilih ${dayOf(p.dipilih)} — lihat tugasnya di Catatan</a>`
      : html`<button class="btn primary" data-act="pick" data-i="${i}">${icon('check', 16)} Pilih rencana ini → tugas di Catatan</button>`}</div>`;
}

function running(r, note) {
  if (!r) return '';
  const pct = r.total ? Math.round((r.done / r.total) * 100) : 0;
  return html`<a class="card violet" href="#/catatan" style="gap:8px;text-decoration:none;color:inherit">
    <div class="row sb"><span class="k violet">Rencana yang kamu jalankan</span><span class="mono small">${r.done}/${r.total}</span></div>
    <b style="font-size:14px">${r.nama}</b><div class="bar thin"><i class="violet" style="width:${pct}%"></i></div>
    ${r.next ? html`<span class="small">Berikutnya: ${r.next.text.split(' — rencana')[0]}${r.next.due ? ` · ${dayOf(r.next.due)}` : ''}</span>` : html`<span class="small">Semua langkah selesai.</span>`}
    ${note ? html`<span class="sub" style="font-style:italic">“${note}”</span>` : ''}</a>`;
}

/** What people feel and search: the brain's read of the sentiment, the Fear & Greed number, Google Trends (economic searches first). Pure. */
export function trendsShown(trends, n = 6) {
  const econ = (t) => ECON.test(`${t.q} ${(t.news || []).join(' ')}`);
  return [...trends.filter(econ), ...trends.filter((t) => !econ(t))].slice(0, n);
}

function feeling(se, mood, trends) {
  const f = mood?.crypto_fng;
  if (!se && !f && !trends?.length) return '';
  return html`<div class="card" style="gap:8px"><div class="row sb"><span class="k">Sentimen publik & pasar</span>${se ? html`<span class="tag ${FEEL[se.label] || 'muted'}">${se.label}</span>` : ''}</div>
    ${se?.ringkas ? html`<p class="sub" style="margin:0">${se.ringkas}</p>` : ''}
    ${se?.sinyal?.length ? html`<div style="display:flex;flex-direction:column;gap:4px">${se.sinyal.map((x) => html`<span class="small">• <b>${x.sumber}</b>: ${x.isi}</span>`)}</div>` : ''}
    ${f ? html`<div style="display:flex;flex-direction:column;gap:4px"><div class="row sb small"><span>Fear & Greed kripto</span><span class="mono">${f.value}/100 · ${f.label}${f.week_ago != null ? ` (minggu lalu ${f.week_ago})` : ''}</span></div>
      <div class="bar thin"><i class="${f.value < 45 ? 'amber' : f.value > 55 ? 'green' : ''}" style="width:${f.value}%"></i></div></div>` : ''}
    ${trends?.length ? html`<span class="small">Dicari orang Indonesia hari ini (Google Trends):</span>
      <div class="chips" style="flex-wrap:wrap">${trendsShown(trends).map((t) => html`<span class="chip" style="cursor:default">${t.q}${t.traffic ? html` <span class="small">${t.traffic}</span>` : ''}</span>`)}</div>` : ''}</div>`;
}

function kpi(m) {
  return html`<div class="kpi" style="padding:8px"><span style="font-size:10px">${m.label}</span>
    <b style="font-size:13px">${m.last != null ? Number(m.last).toLocaleString('id-ID', { maximumFractionDigits: 2 }) : '–'}</b>
    <span class="small" style="color:var(--${m.change == null ? 'tx2' : m.change >= 0 ? 'green' : 'red'})">${m.change == null ? '' : `${pct(m.change)} 5h`}</span>
    ${m.tech ? html`<span class="small" style="color:var(--${TECH[m.tech.label] === 'muted' ? 'tx2' : `${TECH[m.tech.label]}-t`})">${m.tech.label}${m.tech.rsi != null ? ` · RSI ${Math.round(m.tech.rsi)}` : ''}</span>` : ''}</div>`;
}

function agenda(list) {
  if (!list?.length) return '';
  const when = (iso) => new Date(iso).toLocaleString('id-ID', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  return html`<details class="card"><summary class="small">Agenda ekonomi minggu ini (${list.length})</summary><div style="display:flex;flex-direction:column;gap:6px;margin-top:8px">
    ${list.map((a) => html`<div class="row top" style="gap:8px;font-size:13px"><span class="mono small" style="flex:0 0 112px">${when(a.at)}</span>
      <span class="grow"><b>${a.country}</b> ${a.title}${a.actual ? html` <span class="small">· hasil ${a.actual}</span>` : a.forecast ? html` <span class="small">· perkiraan ${a.forecast}</span>` : ''}</span></div>`)}</div></details>`;
}

/** The workers: collectors in parallel → the analyst → the one that is him. Live while running, kept with the brief after. */
function pipeline(steps, { live = false, error = '' } = {}) {
  const mark = (st) => (st.status === 'selesai' ? html`<span style="color:var(--green)">${icon('check', 12)}</span>` : st.status === 'gagal' ? html`<span style="color:var(--red)">${icon('close', 12)}</span>` : html`<span class="small">…</span>`);
  const body = STAGES.map(([key, title, sub], i) => {
    const mine = steps.filter((st) => st.stage === key);
    const done = mine.filter((st) => st.status !== 'jalan').length;
    const state = !mine.length ? 'menunggu' : done < mine.length ? 'berjalan' : mine.some((st) => st.status === 'gagal') && key !== 'kumpul' ? 'gagal' : 'selesai';
    return html`<div style="display:flex;flex-direction:column;gap:6px">
      <div class="row sb"><b style="font-size:14px">${i + 1} · ${title}${key === 'kumpul' && mine.length ? html` <span class="small">(${done}/${mine.length})</span>` : ''}</b>
        <span class="tag ${state === 'selesai' ? 'green' : state === 'gagal' ? 'red' : state === 'berjalan' ? 'cyan' : 'muted'}">${state}</span></div>
      <span class="small">${sub}</span>
      ${mine.length ? html`<div style="display:flex;flex-wrap:wrap;gap:6px">${mine.map((st) => html`<a class="chip" ${st.run_id ? html`href="#/alur/${st.run_id}"` : ''} style="gap:4px">${mark(st)} ${st.label.replace(/^Jadi kamu: /, '').replace(/^Analis: /, '')}${st.status === 'selesai' && st.n ? html` <span class="small">${st.n}</span>` : ''}${st.secs && st.status !== 'jalan' ? html` <span class="small">${st.secs}d</span>` : ''}</a>`)}</div>` : ''}</div>`;
  });
  return live
    ? html`<div class="card cyan" style="gap:12px"><div class="row sb"><span class="k cyan">JARVIS sedang bekerja</span><span class="small">±1–2 menit</span></div>${body}
        ${error ? html`<span class="small" style="color:var(--red-t)">${error}</span>` : ''}</div>`
    : html`<details class="card"><summary class="small">Cara kerja: ${steps.filter((st) => st.stage === 'kumpul').length} pengumpul → analis → jadi kamu</summary>
        <div style="display:flex;flex-direction:column;gap:12px;margin-top:10px">${body}</div></details>`;
}

function position(po) {
  if (!po) return '';
  return html`<div class="card" style="gap:8px"><span class="k violet">Dibanding posisimu</span><p class="sub" style="margin:0">${po.ringkas}</p>
    ${po.kuat?.length ? html`<div style="display:flex;flex-direction:column;gap:3px">${po.kuat.map((x) => html`<span class="small"><span style="color:var(--green)">${icon('check', 12)}</span> ${x}</span>`)}</div>` : ''}
    ${po.rentan?.length ? html`<div style="display:flex;flex-direction:column;gap:3px">${po.rentan.map((x) => html`<span class="small"><span style="color:var(--amber)">${icon('alert', 12)}</span> ${x}</span>`)}</div>` : ''}</div>`;
}

function chance(p) {
  return html`<div class="card green" style="gap:6px"><div class="row sb top" style="gap:8px"><b style="font-size:14px">${p.aksi}</b>
      <span class="tag ${SURE[p.yakin] || 'muted'}" style="white-space:nowrap">yakin ${p.yakin}</span></div>
    <span class="small">${KIND[p.kaitan] || p.kaitan} · ${p.horizon}</span>
    ${p.kenapa ? html`<span class="sub">${p.kenapa}</span>` : ''}
    ${p.risiko ? html`<span class="small" style="color:var(--red-t)">Risiko: ${p.risiko}</span>` : ''}</div>`;
}

function spoken(d) {
  return [d.ucapan || d.situasi, ...(d.intinya?.length ? [] : (d.peluang || []).slice(0, 2).map((p) => `Peluang: ${p.aksi}. ${p.kenapa}`))].filter(Boolean).join(' ');
}

export default {
  tab: 'beranda',
  async render(root) {
    root.innerHTML = String(html`${header('Cek berita')}<div class="scr">${loading()}</div>`);
    const { brief, running: run, progress: prog } = await get('/api/v1/app/brief');
    current = brief;
    let timer = null;
    const follow = () => on('brief', (ev) => {   // the workers, live: redraw just the progress card; the whole page once they are done
      if (!ev.running) { clearTimeout(timer); timer = setTimeout(render, 400); return; }
      const box = root.querySelector('#pipe');
      if (box) box.innerHTML = String(pipeline(ev.steps || [], { live: true }));
      else { clearTimeout(timer); timer = setTimeout(render, 300); }   // started elsewhere (the morning schedule, another device)
    });
    const live = prog?.running ? html`<div id="pipe">${pipeline(prog.steps || [], { live: true })}</div>`
      : prog?.error ? html`<div class="card amber" style="gap:6px"><span class="small">${/model|HTTP|gateway|token/i.test(prog.error) ? 'Analisis terakhir gagal: otak AI tidak bisa dihubungi.' : `Analisis terakhir gagal: ${prog.error.slice(0, 120)}`}
          ${brief ? ' Yang tampil di bawah adalah analisis sebelumnya.' : ''} Ketuk ⟳ untuk mencoba lagi.</span>
          <details><summary class="small">Detail teknis</summary><code class="small" style="word-break:break-all">${prog.error}</code></details></div>` : '';
    const old = brief && !brief.data?.situasi && !brief.data?.tema;   // a list-style brief from before: make a fresh analysis
    if (!brief || old) {
      root.innerHTML = String(html`${header('Cek berita')}<div class="scr">${live}${running(run)}${prog?.running ? '' : html`<div class="card"><p>Belum ada analisis berita hari ini. JARVIS membuatnya otomatis tiap pagi
        (atur jamnya di Kontrol): beberapa worker mengumpulkan data, satu menganalisa, satu lagi menjadi kamu dan menyusun rencana 1–3 bulan.</p>
        <button class="btn primary" data-act="now">Analisis sekarang</button></div>`}</div>`);
      return follow();
    }
    const d = brief.data;
    const day = new Date(`${brief.day}T00:00:00`);
    const mood = MOOD[d.suasana] || MOOD.campuran;
    const plans = d.rencana || [];
    if (planTab == null || planTab >= plans.length) planTab = Math.max(0, plans.findIndex((p) => p.gaya === 'seimbang'));
    root.innerHTML = String(html`${header('Cek berita', { sub: `${day.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long' })} · ${d.count || 0} berita dari ${brief.sources.length} sumber`, right: html`<button class="ib box" data-act="now" aria-label="Analisis ulang">${icon('repeat', 18)}</button>` })}
      <div class="scr">
        ${live}
        <div class="card ${mood[0]}" style="gap:8px"><div class="row sb"><span class="k ${mood[0]}">Intinya hari ini</span><span class="tag ${mood[0]}">${mood[1]}</span></div>
          ${d.judul ? html`<b style="font-size:17px;line-height:1.35">${d.judul}</b>` : ''}
          ${d.intinya?.length ? html`<ol style="margin:0;padding-left:20px;display:flex;flex-direction:column;gap:4px">${d.intinya.map((x) => html`<li style="font-size:14px">${x}</li>`)}</ol>`
            : html`<p class="sub" style="margin:0">${d.situasi}</p>`}</div>
        ${running(run, d.evaluasi_rencana)}
        ${position(d.posisi)}
        ${feeling(d.sentimen, d.mood, d.trends)}
        ${d.intinya?.length && d.situasi ? html`<details class="card"><summary class="small">Situasi lengkapnya</summary><p class="sub" style="margin:8px 0 0">${d.situasi}</p></details>` : ''}
        ${d.markets?.length ? html`<div class="sec"><span>Indikator pasar</span><span class="small">teknikal ala TradingView</span></div>
          <div class="g3">${d.markets.map(kpi)}</div>` : ''}
        ${d.holdings?.length ? html`<div class="sec"><span>Aset milikmu</span></div><div class="g3">${d.holdings.map(kpi)}</div>` : ''}
        ${agenda(d.agenda)}
        ${d.tema?.length ? html`<div class="sec"><span>Kenapa begitu</span></div>${d.tema.map(theme)}` : ''}
        ${d.skenario?.length ? html`<div class="sec"><span>1–3 bulan ke depan</span></div>${d.skenario.map(scenario)}` : ''}
        ${plans.length ? html`<div class="sec"><span>Kalau aku jadi kamu</span></div>
          <div class="chips">${plans.map((p, i) => html`<button class="chip ${i === planTab ? 'on' : ''}" data-act="tab" data-i="${i}">${(STYLE[p.gaya] || STYLE.seimbang)[1]}${p.dipilih ? ' ✓' : ''}</button>`)}</div>
          ${plan(plans[planTab], planTab)}
          <span class="small" style="padding:0 4px">Rencana dibuat seolah JARVIS jadi kamu, dari berita & datamu hari ini — kamu yang memutuskan. Investasi tetap lewat persetujuanmu dan batas di menu Investasi.</span>`
          : d.persona_error ? html`<div class="card amber"><span class="small">Worker “jadi kamu” belum memberi rencana (${d.persona_error}). Ketuk ⟳ untuk mencoba lagi.</span></div>` : ''}
        ${d.peluang?.length ? html`<details class="card"><summary class="small">Peluang cepat (${d.peluang.length})</summary><div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">${d.peluang.map(chance)}</div></details>` : ''}
        ${d.waspada?.length ? html`<div class="card red" style="gap:6px"><span class="k red">Waspadai</span>${d.waspada.map((r) => html`<span class="small">• ${r.isi}${src(r)}</span>`)}</div>` : ''}
        ${d.weather ? html`<p class="small" style="padding:0 4px">${icon('rain', 14)} ${d.weather}</p>` : ''}
        ${d.pipeline?.length ? pipeline(d.pipeline) : ''}
        <span class="small" style="padding:0 4px">Dianalisis oleh ${laneChip(d.lane)} lewat alur master · sumber: ${brief.sources.join(', ')}</span>
        <div class="btns"><button class="btn primary lg" data-act="read">${icon('speaker', 18)} Bacakan</button><button class="btn lg" data-act="hush">Diam</button><a class="btn lg" href="#/obrolan">Tanya lanjut</a></div>
      </div>`);
    return follow();
  },
  actions: {
    read() { speak(spoken(current.data)); },
    hush() { stopSpeaking(); },
    tab(b) { planTab = Number(b.dataset.i); render(); },
    async pick(b) {
      const i = Number(b.dataset.i), p = current.data.rencana[i];
      const r = await sheet(String(html`<form style="display:flex;flex-direction:column;gap:12px">
        <span class="k ${(STYLE[p.gaya] || STYLE.seimbang)[0]}">Rencana ${(STYLE[p.gaya] || STYLE.seimbang)[1].toLowerCase()} · ${p.bulan} bulan</span>
        <h3 style="margin:0;font:600 19px var(--f-head)">${p.nama}</h3>
        <p class="small" style="margin:0">Langkah yang dicentang masuk ke Tugas di Catatan, tenggatnya akhir minggunya (mulai hari ini).</p>
        <div style="display:flex;flex-direction:column;gap:8px;max-height:46vh;overflow:auto">${p.langkah.map((s, k) => html`<label class="row top" style="gap:8px;font-size:14px">
          <input type="checkbox" name="s${k}" checked style="margin-top:3px"><span class="grow">${s.apa}</span><span class="mono small">Mg ${s.minggu}</span></label>`)}</div>
        <div class="btns"><button type="button" class="btn" data-close="">Batal</button><button class="btn primary">Masukkan ke Catatan</button></div></form>`));
      if (!r || typeof r !== 'object') return;
      const keep = p.langkah.map((_, k) => k).filter((k) => r[`s${k}`]);
      if (!keep.length) return toast('Centang minimal satu langkah.', true);
      const out = await post('/api/v1/app/brief/plan', { index: i, keep });
      toast(`${out.added} tugas masuk ke Catatan — rencana “${p.nama}” mulai berjalan.`);
      render();
    },
    async now() { await post('/api/v1/app/brief/now'); toast('Worker mulai bekerja — progresnya tampil di atas.'); render(); },
  },
};
