// Shared pieces of the app's screens: a structured result (ADR-075 "hasil"), a bar chart, a live screen, a lane chip, a toggle.
import { api, html, icon } from './core.js';
import { LANE_LABEL, LANE_TONE, pct } from './lib.js';

export function laneChip(lane, why = '') {
  if (!lane) return '';
  const t = LANE_TONE[lane] || 'cyan';
  return html`<span class="tag ${t}" title="${why}">${LANE_LABEL[lane] || lane}</span>`;
}

export function bars(labels, values, unit = '', color = 'cyan') {
  const max = Math.max(...values.map((v) => Math.abs(Number(v) || 0)), 1);
  return html`<div style="display:flex;flex-direction:column;gap:8px">${labels.map((l, i) => html`
    <div class="row" style="font-size:13px"><span style="width:84px;color:var(--tx2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l}</span>
      <div class="bar grow" style="height:8px"><i style="width:${pct(Math.abs(values[i]), max)}%;background:var(--${i === 0 ? color : 'bd2'})"></i></div>
      <span class="mono" style="min-width:44px;text-align:right">${fmtNum(values[i])}${unit ? ` ${unit}` : ''}</span></div>`)}</div>`;
}

export function columns(labels, values, unit = '', highlightLast = true) {
  const max = Math.max(...values.map((v) => Number(v) || 0), 1);
  return html`<div role="img" aria-label="${labels.map((l, i) => `${l} ${values[i]}${unit}`).join(', ')}" style="display:grid;grid-template-columns:repeat(${labels.length},minmax(0,1fr));gap:8px;align-items:end;height:150px">
    ${labels.map((l, i) => html`<div style="display:flex;flex-direction:column;align-items:center;gap:4px;justify-content:flex-end;height:100%">
      <span class="mono" style="font-size:10px;color:var(--mu)">${fmtNum(values[i])}</span>
      <div style="width:100%;height:${Math.max(2, Math.round(110 * (Number(values[i]) || 0) / max))}px;border-radius:4px 4px 0 0;background:var(--${highlightLast && i === labels.length - 1 ? 'amber' : 'cyan'})"></div>
      <span style="font-size:11px;color:var(--tx2)">${l}</span></div>`)}</div>`;
}

export const fmtNum = (v) => (typeof v === 'number' ? (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('id-ID') : String(Math.round(v * 10) / 10).replace('.', ',')) : String(v ?? ''));

/** The structured result a worker handed back: summary, points, tables, charts, pictures, links. */
export function resultView(data, text = '') {
  if (!data || !Object.keys(data).length) return text ? html`<div class="card"><p style="white-space:pre-wrap">${text}</p></div>` : '';
  return html`
    ${data.ringkasan ? html`<div class="card green"><span class="k green">Kesimpulan</span><p>${data.ringkasan}</p>
      ${(data.tautan || []).length || data.keyakinan ? html`<span class="small">${(data.tautan || []).length ? `${data.tautan.length} sumber` : ''}${(data.tautan || []).length && data.keyakinan ? ' · ' : ''}${data.keyakinan ? `keyakinan ${data.keyakinan}` : ''}</span>` : ''}</div>` : ''}
    ${(data.grafik || []).map((g) => html`<div class="card"><span class="k muted">${g.judul || 'Grafik'}</span>${g.jenis === 'line' ? columns(g.label, g.nilai, g.satuan, false) : bars(g.label, g.nilai, g.satuan)}</div>`)}
    ${(data.tabel || []).map((t) => html`<div class="sec"><span>${t.judul || ''}</span></div><div class="tblbox"><table class="tbl"><thead><tr>${t.kolom.map((c) => html`<th scope="col">${c}</th>`)}</tr></thead>
      <tbody>${t.baris.map((r) => html`<tr>${r.map((c) => html`<td>${c}</td>`)}</tr>`)}</tbody></table></div>`)}
    ${data.poin ? html`<div class="card"><ul style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:4px">${data.poin.map((p) => html`<li>${p}</li>`)}</ul></div>` : ''}
    ${(data.gambar || []).length ? html`<div class="g2">${data.gambar.map((g) => html`<figure style="margin:0"><img src="${g.url}" alt="${g.keterangan}" style="width:100%;border-radius:12px"><figcaption class="small">${g.keterangan}</figcaption></figure>`)}</div>` : ''}
    ${(data.tautan || []).length ? html`<div class="chips wrap" style="flex-wrap:wrap">${data.tautan.map((t) => html`<a class="chip" href="${t.url}" target="_blank" rel="noopener">${t.teks}</a>`)}</div>` : ''}
    ${text ? html`<details class="card"><summary class="small">Teks lengkap</summary><p style="white-space:pre-wrap">${text}</p></details>` : ''}`;
}

/** A worker's live browser picture (the desk's frame), refreshed while it runs. Returns a stop function. */
export function liveFrame(img, taskId, everyMs = 1500) {
  let alive = true, last = null;
  const tick = async () => {
    if (!alive || !document.body.contains(img)) return;
    try {
      const b = await api('GET', `/api/v1/canvas/live/${taskId}/frame`, undefined, { blob: true });
      if (b instanceof Blob && b.size) { const u = URL.createObjectURL(b); img.src = u; if (last) URL.revokeObjectURL(last); last = u; }
    } catch { /* no frame yet */ }
    setTimeout(tick, everyMs);
  };
  tick();
  return () => { alive = false; if (last) URL.revokeObjectURL(last); };
}

export function toggle(on, act, data = '') {
  return html`<button class="switch ${on ? 'on' : ''}" role="switch" aria-checked="${on ? 'true' : 'false'}" data-act="${act}" ${data}><i></i></button>`;
}

export function statusPill(status) {
  const m = { running: ['violet', 'Berjalan'], queued: ['cyan', 'Antre'], completed: ['green', 'Selesai'], failed: ['red', 'Gagal'], stopped: ['amber', 'Dijeda'],
    cancelled: ['muted', 'Dibatalkan'], waiting: ['amber', 'Menunggu'], done: ['green', 'Selesai'] }[status] || ['muted', status];
  return html`<span class="pill" style="background:var(--${m[0]}-bg, var(--s2));color:var(--${m[0]}-t, var(--tx2))"><span class="dot ${m[0]} ${status === 'running' ? 'live' : ''}"></span>${m[1]}</span>`;
}

export { icon };
