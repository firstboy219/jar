// The desk's "Akun Google" card (ADR-057): the owner connects Gmail + Calendar by logging in to Google from the phone; JARVIS then puts
// the account into n8n by itself. Google's page opens in the phone's browser (Google refuses to sign in inside an app's WebView: the app
// sends every outside address to the browser).

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const button = (text, cls, fn) => { const b = el('button', cls, text); b.dataset.gesture = 'ok'; b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(ev); }); return b; };
const field = (label, ph, secret) => {
  const w = el('label', 'mfield'), i = el('input'); i.placeholder = ph; i.autocomplete = 'off'; i.spellcheck = false; if (secret) i.type = 'password';
  i.addEventListener('keydown', (e) => e.stopPropagation());
  w.append(el('span', null, label), i); return { w, i };
};

export function createGoogleCard({ box, api, toast, embedded }) {
  let st = null, shown = '', waiting = 0;
  const kind = el('div', 'kind', 'meja · akun google'), head = el('div', 'title', 'Akun Google'), body = el('div', 'sbody');
  box.replaceChildren(kind, head, body);
  box.classList.add('showcard');

  async function load() {
    try { st = await api.req('GET', '/api/v1/google'); } catch { st = null; box.hidden = true; return; }   // not the owner's device
    box.hidden = false;
    const key = JSON.stringify(st);
    if (key !== shown) { shown = key; render(); }
  }

  async function connect() {
    try {
      const { url } = await api.req('POST', '/api/v1/google/start');
      waiting = Date.now();
      if (embedded) location.href = url;   // the app opens it in the phone's browser
      else window.open(url, '_blank', 'noopener');
      toast('Login di halaman Google, izinkan Gmail dan Kalender, lalu kembali ke sini.');
    } catch (err) { toast(err.message, true); }
  }

  function render() {
    body.replaceChildren();
    if (!st.configured) {
      head.textContent = 'Hubungkan Google — sekali saja';
      body.append(el('div', 'snippet', 'Google butuh "kunci aplikasi" (OAuth client) milikmu sendiri. Buat sekali di console.cloud.google.com → '
        + 'APIs & Services → Credentials → Create credentials → OAuth client ID → Web application, lalu isi Authorized redirect URI dengan:'));
      const uri = el('div', 'sread', st.redirect_uri);
      const id = field('Client ID', '….apps.googleusercontent.com'), sec = field('Client secret', 'GOCSPX-…', true);
      body.append(uri, el('div', 'snippet', 'Aktifkan juga Gmail API dan Google Calendar API. Di "OAuth consent screen", publikasikan aplikasinya '
        + '(In production) supaya login tidak kedaluwarsa tiap 7 hari.'), id.w, sec.w,
      button('Simpan & lanjut login', 'mgo', async () => {
        try { st = await api.req('PUT', '/api/v1/google/client', { client_id: id.i.value, client_secret: sec.i.value }); shown = JSON.stringify(st); render(); await connect(); }
        catch (err) { toast(err.message, true); }
      }));
      return;
    }
    if (!st.connected) {
      head.textContent = 'Akun Google belum terhubung';
      body.append(el('div', 'snippet', 'Login sekali dari HP: Jarvis bisa membaca email baru, menyiapkan balasan, dan membuat acara kalender lewat n8n. '
        + 'Mengirim email atau membuat acara tetap menunggu persetujuanmu.'),
      button('🔑 Hubungkan akun Google', 'mgo', connect));
      if (waiting) body.append(el('div', 'snippet', 'Menunggu login selesai di halaman Google…'));
      return;
    }
    head.textContent = st.email;
    body.append(el('div', `mstatus ${st.error ? 'bad' : 'ok'}`, st.error || (st.flows_on ? 'Terhubung — Gmail & Kalender aktif di n8n.' : 'Terhubung.')));
    const row = el('div', 'pctl');
    row.append(button('Login ulang', 'pbtn', connect), button('Putuskan', 'pbtn', async () => {
      if (!confirm('Putuskan akun Google dari JARVIS? Alur Gmail/Kalender di n8n akan dimatikan.')) return;
      try { st = await api.req('DELETE', '/api/v1/google'); shown = ''; await load(); toast('Akun Google diputus.'); } catch (err) { toast(err.message, true); }
    }));
    body.append(row);
    if (waiting) { waiting = 0; toast(`Akun Google ${st.email} terhubung.`); }
  }

  load();
  setInterval(() => { if (!document.hidden && (!st?.connected || waiting)) load(); }, 5000);
  addEventListener('focus', load);
  return { reload: load, get allowed() { return st != null; } };
}
