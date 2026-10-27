import { test } from 'node:test';
import assert from 'node:assert/strict';
import { barLayout, blocksOf, chartOf, fmtNum, inline, lineLayout, niceScale, numericColumns, parseMarkdown, parseNumber, pieSlices, safeUrl } from '../resultmd.js';

test('Indonesian and plain numbers are read, text is not', () => {
  assert.equal(parseNumber('Rp1.900.000'), 1900000);
  assert.equal(parseNumber('25 jt'), 25);
  assert.equal(parseNumber('1,5'), 1.5);
  assert.equal(parseNumber('1.234,56'), 1234.56);
  assert.equal(parseNumber('1,234.56'), 1234.56);
  assert.equal(parseNumber('12%'), 12);
  assert.equal(parseNumber('-3'), -3);
  assert.equal(parseNumber('3.5'), 3.5);
  assert.equal(parseNumber('1.900'), 1900);
  for (const bad of ['PT Maju Jaya', '', '—', null, 'siap dilamar']) assert.equal(parseNumber(bad), null);
});

test('markdown becomes headings, paragraphs, lists, tables, images, code', () => {
  const b = parseMarkdown('# Hasil\n\nSatu baris\nlanjut\n\n- a\n- b\n\n1. x\n2. y\n\n| PT | Gaji |\n|---|---:|\n| A | 25 jt |\n| B | 30 jt |\n\n![logo](https://a.b/c.png)\n\n```\ncode()\n```');
  assert.deepEqual(b.map((x) => x.type), ['heading', 'para', 'list', 'list', 'table', 'image', 'code']);
  assert.equal(b[1].text, 'Satu baris lanjut');
  assert.equal(b[2].ordered, false); assert.equal(b[3].ordered, true);
  assert.deepEqual(b[4].head, ['PT', 'Gaji']); assert.deepEqual(b[4].rows, [['A', '25 jt'], ['B', '30 jt']]);
  assert.equal(b[5].url, 'https://a.b/c.png'); assert.equal(b[6].text, 'code()');
  assert.deepEqual(parseMarkdown('| a | b |\n| 1 | 2 |').map((x) => x.type), ['para'], 'a table needs its --- line');
  assert.deepEqual(parseMarkdown('| a | b |\n|---|---|\n| 1 |')[0].rows, [['1', '']], 'a short row is padded');
});

test('inline spans: bold, italic, code, links — and only http(s) links', () => {
  const s = inline('lihat **penting** dan *miring* `x` [situs](https://a.b/c) atau https://d.e/f. selesai');
  assert.deepEqual(s.map((x) => x.t), ['text', 'b', 'text', 'i', 'text', 'code', 'text', 'link', 'text', 'link', 'text']);
  assert.equal(s[9].url, 'https://d.e/f');     // trailing "." is not part of the link
  assert.deepEqual(inline('[x](javascript:alert(1))').map((x) => x.t), ['text']);
  assert.equal(safeUrl('javascript:alert(1)'), null); assert.equal(safeUrl('data:text/html,x'), null); assert.equal(safeUrl('https://a.b'), 'https://a.b');
});

test('a numeric column of a table can be drawn, the label column and text columns cannot', () => {
  const t = { title: 'Lowongan', head: ['PT', 'Gaji', 'Status'], rows: [['A', 'Rp25.000.000', 'ok'], ['B', '30 jt', 'ok'], ['C', '?', 'tunggu']] };
  assert.deepEqual(numericColumns(t), [{ col: 1, name: 'Gaji' }]);
  const c = chartOf(t, 1);
  assert.deepEqual(c.labels, ['A', 'B']); assert.deepEqual(c.values, [25000000, 30]);   // the row without a number is left out
  assert.equal(c.title, 'Gaji — Lowongan');
  assert.deepEqual(numericColumns({ head: ['a', 'b'], rows: [['x', '1']] }), [], 'one row is no chart');
});

test('a structured result and its text become blocks in reading order', () => {
  const b = blocksOf({ ringkasan: 'Dua lowongan', poin: ['p1'], tabel: [{ judul: 'T', kolom: ['a', 'b'], baris: [['1', '2']] }],
    grafik: [{ judul: 'G', jenis: 'pie', label: ['x', 'y'], nilai: [1, 2], satuan: 'jt' }], gambar: [{ url: 'https://a.b/c.png', keterangan: 'k' }, { url: 'javascript:1' }],
    tautan: [{ teks: 'L', url: 'https://a.b' }, { teks: 'bad', url: 'ftp://x' }] }, 'Catatan **panjang**');
  assert.deepEqual(b.map((x) => x.type), ['summary', 'list', 'table', 'chart', 'image', 'links', 'notes']);
  assert.equal(b[3].kind, 'pie'); assert.equal(b[3].unit, 'jt'); assert.equal(b[5].items.length, 1);
  assert.equal(b[6].collapsed, true);                                            // notes fold away behind a real structure
  assert.deepEqual(blocksOf({}, 'hanya teks').map((x) => [x.type, x.collapsed]), [['notes', false]]);
  assert.deepEqual(blocksOf(null, ''), []);
});

test('chart geometry: nice axis, bars from the zero line, line points, pie shares', () => {
  const sc = niceScale(23); assert.equal(sc.max, 50); assert.equal(sc.ticks[0], 0); assert.equal(sc.ticks.at(-1), 50);
  assert.equal(niceScale(0).max, 1); assert.equal(niceScale(4).max, 5); assert.equal(niceScale(95).max, 100);
  const bars = barLayout([10, 20, 5], 300, 200);
  assert.equal(bars.bars.length, 3); assert.ok(bars.bars[1].h > bars.bars[0].h && bars.bars[0].h > bars.bars[2].h);
  assert.ok(bars.bars.every((b) => Math.abs(b.y + b.h - bars.zero) < 1e-9), 'positive bars stand on the zero line');
  const neg = barLayout([10, -10], 300, 200);
  assert.ok(neg.bars[1].y >= neg.zero - 1e-9 && neg.bars[0].y + neg.bars[0].h <= neg.zero + 1e-9);
  const line = lineLayout([0, 10], 100, 50);
  assert.deepEqual(line.points[0], [0, 50]); assert.equal(line.points[1][0], 100);
  const pie = pieSlices([1, 1, 2]);
  assert.deepEqual(pie.map((p) => p.share), [0.25, 0.25, 0.5]); assert.ok(Math.abs(pie[2].end - Math.PI * 2) < 1e-9);
  assert.equal(fmtNum(1234567), '1.234.567'); assert.equal(fmtNum(2.5), '2,5');
});
