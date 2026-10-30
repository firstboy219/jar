// Sumber API (mockup 36): where the business numbers come from — per source the address, the key (kept encrypted, never shown again), and
// per number where it is in the API's answer; pasted API documentation fills the form in; "Uji" reads it once and shows what came back.
import { $, $$, del, get, go, header, html, icon, loading, post, put, render, sheet, toast } from '../core.js';
import { val } from './bisnis.js';

const AUTH = [['none', 'Tanpa kunci'], ['bearer', 'Bearer token'], ['header', 'Header (mis. X-API-Key)'], ['query', 'Parameter URL'], ['basic', 'Basic (user:password)']];
const AGG = [['sum', 'jumlahkan'], ['count', 'hitung item'], ['value', 'ambil nilai'], ['avg', 'rata-rata'], ['max', 'terbesar'], ['min', 'terkecil']];
const blankEp = () => ({ metric: 'penjualan', label: '', unit: '', method: 'GET', path: '', params: {}, items: '', value: '', filter: '', agg: 'sum', mode: 'today', date: '', split: '' });
let meta = null, form = null, tested = null;

const ago = (s) => { if (!s) return 'belum'; const m = Math.round((Date.now() - new Date(s)) / 60000); return m < 1 ? 'baru saja' : m < 60 ? `${m} mnt lalu` : m < 1440 ? `${Math.round(m / 60)} jam lalu` : `${Math.round(m / 1440)} hari lalu`; };
const paramsText = (p) => Object.entries(p || {}).map(([k, v]) => `${k}=${v}`).join('\n');
const parseParams = (t) => Object.fromEntries(String(t || '').split('\n').map((l) => l.trim()).filter((l) => l.includes('=')).map((l) => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim()]));
const parseHeaders = (t) => Object.fromEntries(String(t || '').split('\n').map((l) => l.trim()).filter((l) => l.includes(':')).map((l) => [l.slice(0, l.indexOf(':')).trim(), l.slice(l.indexOf(':') + 1).trim()]).filter(([k]) => /^[\w-]{1,60}$/.test(k)));
const opt = (pairs, cur) => pairs.map(([v, l]) => html`<option value="${v}" ${v === cur ? 'selected' : ''}>${l}</option>`);

function epBlock(e, i) {
  const t = tested?.[i];
  return html`<div class="card" data-ep="${i}" style="background:var(--bg)">
    <div class="row sb"><span class="k">Angka ${i + 1}</span><button type="button" class="ib sm" data-act="rmep" data-i="${i}" aria-label="Hapus angka">${icon('close', 14)}</button></div>
    <div class="g2"><label class="field">Nama angka<input name="metric" list="metrics" value="${e.metric}" required pattern="[a-z0-9_]{2,40}"></label>
      <label class="field">Mode<select name="mode">${opt([['today', 'nilai hari ini'], ['series', 'banyak hari (riwayat)']], e.mode)}</select></label></div>
    <div class="g2"><label class="field">Label (angka lain)<input name="label" value="${e.label}" placeholder="mis. Toko aktif"></label>
      <label class="field">Satuan<select name="unit">${opt([['', 'otomatis'], ['rp', 'Rupiah'], ['n', 'jumlah'], ['%', 'persen']], e.unit)}</select></label></div>
    <div class="row" style="gap:8px"><label class="field" style="width:96px">Metode<select name="method">${opt([['GET', 'GET'], ['POST', 'POST']], e.method)}</select></label>
      <label class="field grow">Path endpoint<input name="path" value="${e.path}" required placeholder="/v1/orders"></label></div>
    <label class="field">Parameter (satu per baris, nama=nilai · tanggal: {today} {from} {to} {from_ts} {to_ts})<textarea name="params" style="min-height:60px" placeholder="date={today}&#10;status=all">${paramsText(e.params)}</textarea></label>
    <div class="g2"><label class="field">Daftar / nilai di JSON<input name="items" value="${e.items}" placeholder="data.orders"></label>
      <label class="field">Nilai per item<input name="value" value="${e.value}" placeholder="total_amount (kosong = hitung item)"></label></div>
    <div class="g2"><label class="field">Cara hitung<select name="agg">${opt(AGG, e.agg)}</select></label>
      <label class="field">Saring<input name="filter" value="${e.filter}" placeholder="status!=cancelled"></label></div>
    <div class="g2"><label class="field">Tanggal per item<input name="date" value="${e.date}" placeholder="created_at"></label>
      <label class="field">Per kanal (opsional)<input name="split" value="${e.split}" placeholder="marketplace"></label></div>
    ${t ? (t.ok ? html`<div class="card green"><span class="small">${t.days ? `${t.days} hari terbaca` : `Hasil: ${val(t.value, e.unit || 'n')}`} · ${t.rows ?? 0} item${Object.keys(t.split || {}).length ? ` · kanal: ${Object.keys(t.split).join(', ')}` : ''}</span>
        <details><summary class="small">Contoh jawaban API</summary><pre class="mono" style="font-size:11px;white-space:pre-wrap;max-height:200px;overflow:auto">${t.sample}</pre></details></div>`
      : html`<div class="card red"><span class="small">${t.error}</span></div>`) : ''}
  </div>`;
}

function editor(f) {
  return html`${header(f.id ? `Ubah ${f.name}` : 'Sumber baru')}
    <div class="scr">
      <details class="card cyan" ${f.id ? '' : 'open'}><summary class="ttl" style="cursor:pointer">${icon('file', 14)} Tempel dokumentasi API → isi otomatis</summary>
        <div style="display:flex;flex-direction:column;gap:10px;margin-top:10px">
        <textarea id="doc" class="inp" style="min-height:120px" placeholder="Tempel bagian dokumentasi API (endpoint, contoh respons)…"></textarea>
        <button type="button" class="btn" data-act="autofill">${icon('bolt', 16)} Isi formulir dari dokumentasi</button>
        <span class="small">Dibaca otak ringan lewat alur master. Jangan tempel kunci rahasianya di sini.</span></div></details>
      <form id="srcf" style="display:flex;flex-direction:column;gap:12px">
        <div class="card">
          <div class="g2"><label class="field">Bisnis<input name="business" list="bizlist" value="${f.business}" required></label>
            <label class="field">Nama sumber<input name="name" value="${f.name}" required placeholder="Autotoko API"></label></div>
          <label class="field">Alamat dasar API<input name="base_url" value="${f.base_url}" required placeholder="https://api.autotoko.id"></label>
          <div class="g2"><label class="field">Kunci<select name="auth_type">${opt(AUTH, f.auth.type)}</select></label>
            <label class="field">Nama header/parameter<input name="auth_name" value="${f.auth.name || ''}" placeholder="X-API-Key"></label></div>
          <label class="field">Kunci API / token ${f.key_hint ? html`<span class="mono">(tersimpan ${f.key_hint} — kosongkan bila tidak diganti)</span>` : ''}<input name="key" type="password" autocomplete="off" placeholder="${f.key_hint ? '••••••••' : 'tempel kunci API'}"></label>
          <details><summary class="small">Header tambahan (opsional)</summary><label class="field">Satu per baris: Nama: nilai<textarea name="headers" class="inp" style="min-height:70px" placeholder="X-Tenant-Id: renature&#10;Accept: application/json">${Object.entries(f.headers || {}).map(([k, v]) => `${k}: ${v}`).join('\n')}</textarea></label></details>
          <div class="g2"><label class="field">Baca tiap (menit)<input name="poll_min" type="number" min="5" max="1440" value="${f.poll_min}"></label>
            <label class="field">Status<select name="paused">${opt([['', 'aktif'], ['1', 'dijeda']], f.status === 'paused' ? '1' : '')}</select></label></div>
          <span class="small">${icon('lock', 12)} Kunci disimpan terenkripsi dengan kunci brankas JARVIS dan tidak pernah ditampilkan lagi.</span>
        </div>
        ${f.endpoints.map(epBlock)}
        <button type="button" class="btn" data-act="addep">${icon('plus', 16)} Tambah angka</button>
        <datalist id="metrics">${meta.metrics.map((m) => html`<option value="${m.metric}">${m.label}</option>`)}</datalist>
        <datalist id="bizlist">${meta.businesses.map((b) => html`<option value="${b}">`)}</datalist>
        <div class="btns"><button type="button" class="btn lg" data-act="test">Uji koneksi</button><button type="button" class="btn primary lg" data-act="save">Simpan</button></div>
        ${f.id ? html`<button type="button" class="btn danger" data-act="remove">Hapus sumber</button>` : ''}
      </form></div>`;
}

function collect() {
  const f = $('#srcf');
  if (!f) return form;
  const g = (n) => f.elements[n]?.value ?? '';
  form = { ...form, business: g('business').trim(), name: g('name').trim(), base_url: g('base_url').trim(), auth: { type: g('auth_type'), name: g('auth_name').trim() },
    key: g('key'), poll_min: Number(g('poll_min')) || 15, paused: g('paused') === '1', headers: parseHeaders(g('headers')) };
  form.endpoints = $$('[data-ep]', f).map((b) => {
    const q = (n) => b.querySelector(`[name=${n}]`)?.value ?? '';
    return { metric: q('metric').trim().toLowerCase(), label: q('label').trim(), unit: q('unit'), method: q('method'), path: q('path').trim(), params: parseParams(q('params')),
      items: q('items').trim(), value: q('value').trim(), filter: q('filter').trim(), agg: q('agg'), mode: q('mode'), date: q('date').trim(), split: q('split').trim() };
  });
  return form;
}

function payload(f) {
  return { business: f.business, name: f.name, base_url: f.base_url, auth: f.auth, key: f.key || '', headers: f.headers || {}, poll_min: f.poll_min, paused: !!f.paused,
    endpoints: f.endpoints.map((e) => ({ ...e, unit: e.unit || undefined })) };
}

export default {
  tab: 'beranda',
  feature: 'sumber',
  async render(root, route) {
    root.innerHTML = String(html`${header('Sumber API')}<div class="scr">${loading()}</div>`);
    meta = await get('/api/v1/app/bisnis/sources');
    const which = route.params[0];
    if (which) {
      if (!form || String(form.id || 'new') !== which) {
        const s = meta.sources.find((x) => String(x.id) === which);
        form = s ? { ...s, key: '' } : { id: null, business: route.query.b || meta.businesses[0] || '', name: '', base_url: '', auth: { type: 'header', name: 'X-API-Key' }, key: '', poll_min: 15, status: 'active', endpoints: [blankEp()] };
        tested = null;
      }
      root.innerHTML = String(editor(form));
      return;
    }
    form = null;
    root.innerHTML = String(html`${header('Sumber API', { right: html`<a class="ib box" href="#/sumber/new" aria-label="Tambah sumber">${icon('plus', 18)}</a>` })}
      <div class="scr">
        ${meta.sources.length ? meta.sources.map((s) => html`<div class="card ${s.fails >= 3 ? 'red' : ''}">
          <div class="row sb"><span class="ttl">${s.name}</span><span class="tag ${s.status === 'paused' ? '' : s.last_error ? 'amber' : 'green'}">${s.status === 'paused' ? 'dijeda' : s.last_error ? 'bermasalah' : 'aktif'}</span></div>
          <span class="small">${s.business} · ${s.base_url} · ${s.endpoints.length} angka · tiap ${s.poll_min} mnt · kunci ${s.key_hint || 'tidak ada'}</span>
          <span class="small">Terakhir berhasil: ${ago(s.last_ok)}${s.backfilled ? ` · riwayat terisi ${ago(s.backfilled)}` : ''}</span>
          ${s.last_error ? html`<span class="small t-amber2">${s.last_error}</span>` : ''}
          <div class="chips"><button class="chip" data-act="sync" data-id="${s.id}">${icon('repeat', 13)} Baca sekarang</button>
            ${s.endpoints.some((e) => e.mode === 'series') ? html`<button class="chip" data-act="history" data-id="${s.id}">${icon('clock', 13)} Isi riwayat 180 hari</button>` : ''}
            <button class="chip" data-act="testsaved" data-id="${s.id}">Uji</button><a class="chip" href="#/sumber/${s.id}">Ubah</a></div></div>`)
          : html`<div class="card"><p class="sub">Belum ada sumber. Tambahkan API Autotoko dan Renature: alamat, kunci, dan di mana angka penjualan/pesanan/dikemas/pencairan ada di jawabannya.</p></div>`}
        <a class="btn primary block" href="#/sumber/new">${icon('plus', 16)} Tambah sumber API</a>
        <p class="small" style="padding:0 4px">Dibaca otomatis lewat alur master sebagai skill tanpa AI. Hanya alamat https publik.</p>
      </div>`);
  },
  actions: {
    addep() { collect(); form.endpoints.push(blankEp()); tested = null; render(); },
    rmep(b) { collect(); form.endpoints.splice(Number(b.dataset.i), 1); tested = null; render(); },
    async autofill() {
      const text = $('#doc').value.trim();
      if (text.length < 20) return toast('Tempel dokumentasinya dulu', true);
      collect();
      toast('Membaca dokumentasi…');
      const g = await post('/api/v1/app/bisnis/sources/autofill', { text });
      form = { ...form, name: form.name || g.name, base_url: g.base_url || form.base_url, auth: g.auth?.type ? g.auth : form.auth, endpoints: g.endpoints.length ? g.endpoints : form.endpoints };
      tested = null; render();
      if (g.catatan) toast(g.catatan);
    },
    async test() {
      const f = collect();
      toast('Menguji…');
      const r = await post('/api/v1/app/bisnis/sources/test', { ...payload(f), id: form.id || null });
      tested = r.results; render();
    },
    async save() {
      const f = collect();
      if (!$('#srcf').reportValidity()) return;
      const s = f.id ? await put(`/api/v1/app/bisnis/sources/${f.id}`, payload(f)) : await post('/api/v1/app/bisnis/sources', payload(f));
      toast(f.id ? 'Tersimpan' : 'Tersimpan — membaca angka pertama…');
      form = null; go(`#/bisnis?b=${encodeURIComponent(s.business)}`);
    },
    async remove() {
      if ((await sheet(String(html`<p>Hapus sumber ${form.name}? Angka yang sudah tersimpan tetap ada.</p><div class="btns"><button class="btn" data-close="">Batal</button><button class="btn danger" data-close="y">Hapus</button></div>`))) !== 'y') return;
      await del(`/api/v1/app/bisnis/sources/${form.id}`); form = null; go('#/sumber');
    },
    async sync(b) { const r = await post(`/api/v1/app/bisnis/sources/${b.dataset.id}/sync`); toast(r.status === 'done' ? 'Terbaca' : `Gagal: ${r.error || ''}`, r.status !== 'done'); render(); },
    async history(b) { toast('Mengisi riwayat…'); const r = await post(`/api/v1/app/bisnis/sources/${b.dataset.id}/sync?full=true`); toast(r.status === 'done' ? 'Riwayat terisi' : `Gagal: ${r.error || ''}`, r.status !== 'done'); render(); },
    async testsaved(b) {
      const r = await post(`/api/v1/app/bisnis/sources/${b.dataset.id}/test`);
      await sheet(String(html`<span class="ttl">Hasil uji</span>${r.results.map((x) => html`<div class="card ${x.ok ? 'green' : 'red'}"><span class="small"><b>${x.metric}</b>: ${x.ok ? (x.days ? `${x.days} hari` : val(x.value, 'n')) : x.error}</span></div>`)}<button class="btn" data-close="">Tutup</button>`));
    },
  },
};
