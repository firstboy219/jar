// Every screen of the app, by route name (#/<name>/…). Each module exports {tab?, feature?, render(root, route), actions?}.
import beranda from './beranda.js';
import butuh from './butuh.js';
import catatan from './catatan.js';
import fitur from './fitur.js';
import halaman from './halaman.js';
import ingatan from './ingatan.js';
import kontrol from './kontrol.js';
import misi from './misi.js';
import notfound from './notfound.js';
import obrolan from './obrolan.js';

export const VIEWS = { beranda, butuh, catatan, fitur, halaman, ingatan, kontrol, misi, notfound, obrolan };
