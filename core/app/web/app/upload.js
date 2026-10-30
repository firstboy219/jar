// Files from the phone or the computer into JARVIS (ADR-087): read, sent once as an attachment (kept 30 days), referred to by id afterwards.
import { post } from './core.js';

export const MAX_BYTES = 12_000_000;

function b64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] || '');
    r.onerror = () => reject(new Error('berkas tidak terbaca'));
    r.readAsDataURL(file);
  });
}

/** Upload files; resolves with [{id, name, kind, size, …}]. */
export async function upload(files) {
  const out = [];
  for (const f of files) {
    if (f.size > MAX_BYTES) throw new Error(`${f.name} lebih dari 12 MB`);
    out.push(await post('/api/v1/attachments', { name: f.name, content_type: f.type || '', data: await b64(f) }));
  }
  return out;
}

/** Ask for files with the system picker (camera for a photo when capture is set). */
export function pick({ accept = '', multiple = false, capture = false } = {}) {
  return new Promise((resolve) => {
    const i = document.createElement('input');
    i.type = 'file'; i.accept = accept; i.multiple = multiple;
    if (capture) i.setAttribute('capture', 'environment');
    i.onchange = () => resolve([...(i.files || [])]);
    i.click();
  });
}
