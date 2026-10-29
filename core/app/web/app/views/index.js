// Every screen of the app, by route name (#/<name>/…). Each module exports {tab?, feature?, render(root, route), actions?}.
import bangun from './bangun.js';
import beranda from './beranda.js';
import brief from './brief.js';
import butuh from './butuh.js';
import catatan from './catatan.js';
import fitur from './fitur.js';
import halaman from './halaman.js';
import hijriah from './hijriah.js';
import ingatan from './ingatan.js';
import kontrol from './kontrol.js';
import misi from './misi.js';
import notfound from './notfound.js';
import obrolan from './obrolan.js';
import quran from './quran.js';
import sholat from './sholat.js';

export const VIEWS = { bangun, beranda, brief, butuh, catatan, fitur, halaman, hijriah, ingatan, kontrol, misi, notfound, obrolan, quran, sholat };
