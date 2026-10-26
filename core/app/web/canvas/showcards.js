// The desk's other feature cards (ADR-056): video, picture, document, map, web page, notes and reply drafts — one card each, always on the
// board at its own place, so "putar video", "tampilkan dokumen" or "lihat fotonya" fill a card the camera flies to. Like the player and the
// meeting recorder they follow the server's state (the desk poll), so the browser, the phone app and a reload all show the same thing.

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn) => { const b = el('button', cls, text); b.dataset.gesture = 'ok'; b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(ev); }); return b; };
const link = (text, href) => { const a = el('a', 'pbtn plink', text); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.addEventListener('click', (e) => e.stopPropagation()); return a; };
const host = (url) => { try { return new URL(url).hostname; } catch { return ''; } };

export const SHOW_CARDS = {
  image: { label: 'gambar', title: 'Gambar', hint: 'Bilang: "tampilkan foto …" — gambarnya muncul di sini.' },
  doc: { label: 'dokumen', title: 'Dokumen', hint: 'Bilang: "buka dokumen …" atau "buatkan laporan …" — isinya bisa dibaca di sini.' },
  map: { label: 'peta', title: 'Peta', hint: 'Bilang: "rute ke …" atau "di mana …" — petanya muncul di sini.' },
  web: { label: 'web', title: 'Halaman web', hint: 'Bilang: "buka berita …" — halamannya muncul di sini.' },
  text: { label: 'catatan', title: 'Catatan', hint: 'Ringkasan, daftar dan catatan dari Jarvis muncul di sini.' },
  draft: { label: 'draf balasan', title: 'Draf balasan', hint: 'Draf WhatsApp / email dari Jarvis muncul di sini — tinggal salin.' },
};

/** Copy text, also inside the phone's WebView where the async clipboard may be refused. */
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall back */ }
  const t = el('textarea'); t.value = text; t.style.position = 'fixed'; t.style.opacity = '0'; document.body.append(t); t.select();
  let ok = false; try { ok = document.execCommand('copy'); } catch { ok = false; }
  t.remove(); return ok;
}

// MapLibre (the same open map the phone app uses), loaded the first time a map is shown.
const MAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty';
let maplibre = null;
function loadMaplibre() {
  if (!maplibre) maplibre = new Promise((ok, fail) => {
    const css = el('link'); css.rel = 'stylesheet'; css.href = 'https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css'; document.head.append(css);
    const s = el('script'); s.src = 'https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js';
    s.onload = () => ok(window.maplibregl); s.onerror = () => { maplibre = null; fail(new Error('peta tidak bisa dimuat')); };
    document.head.append(s);
  });
  return maplibre;
}

/** A full-screen look at one picture; a tap anywhere closes it. */
function lightbox(src, title) {
  const o = el('div', 'lightbox'); o.dataset.gesture = 'ok';
  const img = el('img'); img.src = src; img.alt = title || '';
  o.append(img, el('div', 'lbcap', title || ''));
  o.addEventListener('click', () => o.remove());
  document.body.append(o);
}

export function createShowCard({ box, api, slot, send, toast, embedded }) {
  const spec = SHOW_CARDS[slot];
  let id = null, urls = [], map = null;
  const kind = el('div', 'kind', `meja · ${spec.label}`), head = el('div', 'title', spec.title), sub = el('div', 'snippet'), body = el('div', 'sbody'), ctl = el('div', 'pctl');
  box.replaceChildren(kind, head, sub, body, ctl);
  box.classList.add('showcard', `show-${slot}`);

  const event = (name, detail) => send({ type: 'stage_event', id, event: name, ...(detail ? { detail } : {}) });
  const own = (url) => url.startsWith('/api/v1/');
  async function blobUrl(url) {
    const r = await fetch(url, { headers: { Authorization: `Bearer ${api.token}` } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const u = URL.createObjectURL(await r.blob()); urls.push(u); return u;
  }
  const src = (url) => (own(url) ? blobUrl(url) : Promise.resolve(url));

  function idle() {
    teardown();
    head.textContent = spec.title; sub.textContent = spec.hint; box.classList.add('empty');
  }
  function teardown() {
    urls.forEach((u) => URL.revokeObjectURL(u)); urls = [];
    map?.remove(); map = null;
    body.replaceChildren(); ctl.replaceChildren(); box.classList.remove('empty');
  }

  // ---------------------------------------------------------- one renderer per kind of thing

  function pictures(items) {
    const pics = items.flatMap((i) => (i.panel === 'gallery' ? (i.items || []) : [i])).filter((p) => p.url).slice(0, 12);
    const grid = el('div', pics.length > 1 ? 'sgrid' : 'sone');
    for (const p of pics) {
      const img = el('img', 'spic'); img.alt = p.title || ''; img.loading = 'lazy'; img.dataset.gesture = 'ok';
      src(p.url).then((u) => { img.src = u; }).catch(() => { img.alt = 'gambar tidak bisa dimuat'; });
      img.addEventListener('click', (ev) => { ev.stopPropagation(); if (img.src) lightbox(img.src, p.title); });
      grid.append(img);
    }
    body.append(grid);
    if (pics.length > 1) sub.textContent = `${pics.length} gambar${sub.textContent ? ` · ${sub.textContent}` : ''}`;
  }

  async function documentView(item, mine) {
    const url = String(item.url || ''), fmt = String(item.format || url.split('.').pop() || '').toLowerCase();
    const reader = el('div', 'sread', 'Memuat isi dokumen…'); body.append(reader);
    if (url.startsWith('/api/v1/documents/')) {
      ctl.append(button('⬇ Unduh', 'pbtn', async () => {
        try { const a = el('a'); a.href = await blobUrl(url); a.download = `${item.title || 'dokumen'}.${fmt || 'docx'}`; a.click(); } catch (err) { toast(err.message, true); }
      }));
      if (fmt === 'pdf' && !embedded) ctl.append(button('Buka PDF', 'pbtn', async () => { try { window.open(await blobUrl(url), '_blank', 'noopener'); } catch (err) { toast(err.message, true); } }));
      try {
        const p = await api.req('GET', `${url}/preview`);
        if (id !== mine) return;
        reader.textContent = p.text || p.note || '(dokumen ini tidak berisi teks)';
        sub.textContent = [String(p.format || fmt).toUpperCase(), sub.textContent].filter(Boolean).join(' · ');
      } catch (err) { if (id === mine) reader.textContent = `Isi tidak bisa ditampilkan: ${err.message}`; }
    } else {
      reader.textContent = `Dokumen di ${host(url) || 'web'}.`;
      ctl.append(link('Buka dokumen ↗', url));
    }
  }

  async function mapView(item, mine) {
    const wrap = el('div', 'smap'); body.append(wrap);
    const routes = item.routes || [], markers = item.markers || [];
    if (routes.length) {
      const list = el('div', 'sroutes');
      routes.forEach((r, i) => {
        const b = button(`${i === (item.selected ?? 0) ? '● ' : ''}${r.label || `Rute ${i + 1}`} · ${r.distance_km ?? '?'} km · ${r.duration_min ?? '?'} mnt${r.traffic ? ' · macet' : ''}`, 'pbtn sroute',
          () => event('route_selected', { index: i }));
        list.append(b);
      });
      body.append(list);
    }
    try {
      const gl = await loadMaplibre();
      if (id !== mine) return;
      map = new gl.Map({ container: wrap, style: MAP_STYLE, attributionControl: { compact: true }, interactive: true });
      const pts = [...markers.map((m) => [m.lon, m.lat]), ...routes.flatMap((r) => (r.polyline || []).map(([la, lo]) => [lo, la]))];
      map.on('load', () => {
        routes.forEach((r, i) => {
          if (!r.polyline?.length) return;
          map.addSource(`r${i}`, { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: r.polyline.map(([la, lo]) => [lo, la]) } } });
          map.addLayer({ id: `r${i}`, type: 'line', source: `r${i}`, paint: { 'line-color': i === (item.selected ?? 0) ? '#22d3ee' : '#64748b', 'line-width': 5 } });
        });
        for (const m of markers) new gl.Marker({ color: '#f97316' }).setLngLat([m.lon, m.lat]).setPopup(new gl.Popup().setText(m.label || '')).addTo(map);
        if (pts.length === 1) map.jumpTo({ center: pts[0], zoom: 14 });
        else if (pts.length > 1) {
          const b = pts.reduce((acc, p) => acc.extend(p), new gl.LngLatBounds(pts[0], pts[0]));
          map.fitBounds(b, { padding: 30, duration: 0 });
        }
      });
      // the board must not pan while a finger or the mouse moves the map
      for (const t of ['pointerdown', 'wheel']) wrap.addEventListener(t, (e) => e.stopPropagation());
    } catch (err) { wrap.replaceChildren(el('div', 'snippet', err.message)); }
    const first = markers[0];
    if (first) ctl.append(link('Buka di Google Maps ↗', `https://www.google.com/maps/search/?api=1&query=${first.lat},${first.lon}`));
  }

  function webView(item) {
    const url = String(item.url || '');
    body.append(el('div', 'sweb', host(url)), el('div', 'snippet sdim', url));
    ctl.append(link(item.mode === 'login' ? 'Buka & login ↗' : 'Buka halaman ↗', url));
    if (item.mode === 'login') ctl.append(button('✓ Sudah login', 'pbtn', () => { event('login_done'); toast('Jarvis diberi tahu.'); }));
  }

  function notes(items) {
    for (const i of items) {
      if (items.length > 1 && i.title) body.append(el('b', 'ssub', i.title));
      body.append(el('div', 'sread', i.text || ''));
    }
    ctl.append(button('Salin', 'pbtn', async () => toast((await copyText(items.map((i) => i.text).join('\n\n'))) ? 'Disalin.' : 'Tidak bisa menyalin di sini.', false)));
  }

  function drafts(item) {
    sub.textContent = [item.channel === 'email' ? 'Email' : 'WhatsApp', item.to, sub.textContent].filter(Boolean).join(' · ');
    if (item.subject) body.append(el('b', 'ssub', `Subjek: ${item.subject}`));
    for (const v of item.variants || []) {
      const row = el('div', 'sdraft');
      row.append(el('div', 'slabel', v.label || 'Draf'), el('div', 'sread', v.text));
      row.append(button('Salin', 'pbtn', async () => {
        if (await copyText(v.text)) { toast('Draf disalin — tempel di aplikasinya.'); event('draft_copied'); } else toast('Tidak bisa menyalin di sini.', true);
      }));
      body.append(row);
    }
    if (item.channel !== 'email' && item.wa_phone) ctl.append(link('Buka WhatsApp ↗', `https://wa.me/${String(item.wa_phone).replace(/\D/g, '')}`));
  }

  return {
    /** The server's card (or null). The card is always on the desk; returns its key (changes when something new is on it). */
    update(c) {
      if (!c) { if (id !== '') { id = ''; idle(); } return null; }
      if (c.id === id) return id;
      teardown(); id = c.id;
      const items = c.items || [], first = items[0] || {};
      head.textContent = first.title || c.caption || spec.title;
      sub.textContent = c.caption && c.caption !== head.textContent ? c.caption : '';
      if (slot === 'image') pictures(items);
      else if (slot === 'doc') documentView(first, id);
      else if (slot === 'map') mapView(first, id);
      else if (slot === 'web') webView(first);
      else if (slot === 'text') notes(items);
      else if (slot === 'draft') drafts(first);
      ctl.append(button('✕ Kosongkan', 'pbtn pclose', () => { event('closed'); idle(); id = ''; }));
      return id;
    },
  };
}
