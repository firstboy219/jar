// Penyimpanan (owner 2026-10-31: "manager storage sehingga saya tahu mana saja yg bisa dihapus atau dizip"): the server's disk, every
// space user grouped — what is safe to remove (and what it costs), what is zipped instead, what stays and why — and the cleanup he ticks,
// approved with the phone's lock. The host measures every 6 hours and on "Ukur ulang".
import { get, header, html, icon, loading, on, post, render, toast } from '../core.js';
import { withPassword } from '../needsui.js';

const gb = (b) => (b >= 1024 ** 3 ? `${(b / 1024 ** 3).toLocaleString('id-ID', { maximumFractionDigits: 1 })} GB`
  : `${Math.round(b / 1024 ** 2).toLocaleString('id-ID')} MB`);
const ago = (s) => (s < 120 ? 'baru saja' : s < 7200 ? `${Math.round(s / 60)} menit lalu` : `${Math.round(s / 3600)} jam lalu`);
const TAG = { hapus: ['green', 'bisa dihapus'], zip: ['cyan', 'bisa dizip'] };

function row(it) {
  const t = TAG[it.action];
  const can = it.action && it.bytes > 0;
  return html`<label class="row top" style="gap:10px;padding:8px 0;border-top:1px solid var(--bd)">
    ${it.action ? html`<input type="checkbox" name="it" value="${it.id}" ${can ? '' : 'disabled'} ${can && it.action === 'hapus' ? 'checked' : ''} style="margin-top:3px">`
      : html`<span style="width:16px;color:var(--tx2)">${icon('lock', 14)}</span>`}
    <div class="grow"><div class="row sb" style="gap:8px"><b style="font-size:14px">${it.label}</b><span class="mono" style="white-space:nowrap">${gb(it.bytes)}</span></div>
      <span class="small">${t ? html`<span class="tag ${t[0]}" style="margin-right:6px">${t[1]}</span>` : html`<span class="tag muted" style="margin-right:6px">disimpan</span>`}${it.note}</span></div></label>`;
}

export default {
  tab: 'fitur',
  async render(root) {
    root.innerHTML = String(html`${header('Penyimpanan')}<div class="scr">${loading()}</div>`);
    const d = await get('/api/v1/app/storage');
    const st = d.state;
    const right = html`<button class="ib box" data-act="scan" aria-label="Ukur ulang">${icon('repeat', 18)}</button>`;
    if (!st) {
      root.innerHTML = String(html`${header('Penyimpanan', { right })}<div class="scr"><div class="card">
        ${d.host_missing ? html`<p>Pengukur di server belum terpasang. Jalankan sekali di server:</p><code class="small">sudo cp infra/systemd/jarvis-storage.* /etc/systemd/system/ &amp;&amp; sudo systemctl daemon-reload &amp;&amp; sudo systemctl enable --now jarvis-storage.path</code>`
          : html`<p>${d.pending ? 'Server sedang mengukur penyimpanan… (±2 menit)' : 'Belum ada ukuran penyimpanan.'}</p>${d.pending ? '' : html`<button class="btn primary" data-act="scan">Ukur sekarang</button>`}`}
      </div></div>`);
      return on('storage', () => render());
    }
    const disk = st.disk, usedPct = Math.round((disk.used / disk.total) * 100);
    const last = st.last;
    root.innerHTML = String(html`${header('Penyimpanan', { sub: `diukur ${ago(d.age_s)}${d.pending ? ' · sedang diproses…' : ''}`, right })}
      <div class="scr">
        <div class="card ${d.low ? 'red' : ''}" style="gap:10px">
          <div class="row sb"><span class="k ${d.low ? 'red' : 'cyan'}">Disk server</span><span class="mono">${gb(disk.used)} / ${gb(disk.total)}</span></div>
          <div class="bar"><i class="${usedPct > 85 ? '' : usedPct > 70 ? 'amber' : 'green'}" style="width:${usedPct}%;${usedPct > 85 ? 'background:var(--red)' : ''}"></i></div>
          <div class="g3"><div class="kpi" style="padding:8px"><span style="font-size:10px">Kosong</span><b style="font-size:14px">${gb(disk.free)}</b></div>
            <div class="kpi" style="padding:8px"><span style="font-size:10px">Bisa dihapus</span><b style="font-size:14px;color:var(--green-t)">${gb(d.can_free)}</b></div>
            <div class="kpi" style="padding:8px"><span style="font-size:10px">Bisa dizip</span><b style="font-size:14px">${gb(d.can_zip)}</b></div></div>
          ${d.host_missing ? html`<span class="small" style="color:var(--amber-t)">Server belum memproses permintaan — pengukur (jarvis-storage.path) belum terpasang?</span>` : ''}
        </div>
        ${last?.items?.length ? html`<div class="card green" style="gap:4px"><span class="k green">Terakhir dibersihkan · ${new Date(last.at * 1000).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
          <span class="small">${gb(last.freed || 0)} lega: ${last.items.map((i) => `${i.label}${i.ok ? '' : ' (gagal)'}`).join(', ')}</span></div>` : ''}
        <form id="clean" style="display:flex;flex-direction:column;gap:12px">
          ${d.groups.map((g) => html`<div class="card" style="gap:0"><div class="row sb" style="padding-bottom:6px"><span class="k">${g.name}</span><span class="mono small">${gb(g.bytes)}</span></div>
            ${g.items.map(row)}
            ${g.name === 'Data JARVIS' && d.music?.ready ? html`<a class="small t-cyan" href="#/musik" style="padding-top:8px">${icon('music', 12)} Koleksi musik: ${d.music.ready} lagu · ${gb(d.music.bytes)} — kelola per lagu</a>` : ''}</div>`)}
          <button class="btn primary lg" data-act="clean" ${d.pending ? 'disabled' : ''}>${icon('lock', 16)} Bersihkan yang dicentang</button>
          <span class="small" style="text-align:center">Hanya yang ditandai “bisa dihapus/dizip” yang bisa dipilih; disetujui dengan PIN/sidik jari HP. Data JARVIS tidak pernah tersentuh.</span>
        </form>
      </div>`);
    return on('storage', () => render());
  },
  actions: {
    async scan() { await post('/api/v1/app/storage/scan'); toast('Server mengukur ulang… (±2 menit)'); setTimeout(render, 1500); },
    async clean(b, e) {
      e?.preventDefault();
      const items = [...document.querySelectorAll('#clean input[name=it]:checked')].map((x) => x.value);
      if (!items.length) return toast('Centang dulu yang ingin dibersihkan.', true);
      const r = await withPassword(`Bersihkan ${items.length} item penyimpanan`, (password) => post('/api/v1/app/storage/clean', { items, password }),
        { kicker: 'Penyimpanan', button: 'Setujui &amp; bersihkan', note: '' });
      if (!r) return;
      toast('Server membersihkan… kamu diberi tahu berapa GB yang lega.');
      render();
    },
  },
};
