// The owner's pick between a project's stages (ADR-079): a popup with the options the earlier workers found; picking one starts the next
// stage (now, or N minutes before the option's time). In the phone app the native dialog does this; here it is the desk's (browser) version.
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

/** How long is left, as people say it ("2 j 15 mnt", "9 mnt"); pure and unit-tested. */
export function leftText(seconds) {
  const m = Math.max(0, Math.round(Number(seconds) / 60));
  return m >= 60 ? `${Math.floor(m / 60)} j ${m % 60} mnt` : `${m} mnt`;
}

/** Open the pick popup for choice `c` ({id, title, prompt, options:[{i,label,detail,waktu}], expires_in_s}); onDone() after it was answered. */
export function openChoice({ api, toast }, c, onDone) {
  document.querySelector(`.chpop[data-id="${c.id}"]`)?.remove();
  const ov = el('div', 'rvoverlay chpop'); ov.dataset.id = String(c.id);
  const bar = el('div', 'rvbar'); bar.append(el('b', 'rvname', `🔔 ${c.title}`));
  const later = el('button', 'pbtn', 'Nanti'); later.type = 'button'; later.addEventListener('click', () => ov.remove()); bar.append(later);
  const body = el('div', 'rvbody');
  body.append(el('div', 'rvsummary', c.prompt || 'Pilih salah satu:'));
  body.append(el('div', 'muted', `Berlaku ${leftText(c.expires_in_s)} lagi.`));
  for (const o of c.options || []) {
    const b = el('button', 'chopt'); b.type = 'button'; b.dataset.gesture = 'ok';
    b.append(el('b', null, o.label), ...(o.detail ? [el('span', 'muted', o.detail)] : []), ...(o.waktu ? [el('span', 'chip', `🕒 ${o.waktu} WIB`)] : []));
    b.addEventListener('click', async () => {
      for (const x of body.querySelectorAll('.chopt')) x.disabled = true;
      try {
        const r = await api.req('POST', `/api/v1/choices/${c.id}/answer`, { option: o.i });
        toast(r.state === 'timer' ? `Oke — dijadwalkan jam ${new Date(r.start_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })} WIB.` : 'Oke — langkah berikutnya dimulai.');
        ov.remove(); onDone?.();
      } catch (err) { toast(err.message, true); for (const x of body.querySelectorAll('.chopt')) x.disabled = false; }
    });
    body.append(b);
  }
  ov.append(bar, body);
  document.body.append(ov);
}
