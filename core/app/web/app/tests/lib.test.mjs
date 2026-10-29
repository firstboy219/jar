import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ago, clock, dur, esc, groupBy, html, parseRoute, pct, raw, rupiah, takeToken } from '../lib.js';

test('rupiah reads like the owner writes it', () => {
  assert.equal(rupiah(18900), 'Rp18.900');
  assert.equal(rupiah(14100000, true), '14,1 jt');
  assert.equal(rupiah(410000, true), '410 rb');
  assert.equal(rupiah(-1200000, true), '−1,2 jt');
  assert.equal(rupiah(120000000, true), '120 jt');
});

test('html escapes values but keeps raw markup', () => {
  assert.equal(String(html`<b>${'<x>'}</b>`), '<b>&lt;x&gt;</b>');
  assert.equal(String(html`<i>${raw('<u>ok</u>')}</i>`), '<i><u>ok</u></i>');
  assert.equal(String(html`${['a', raw('<br>')]}`), 'a<br>');
  assert.equal(String(html`${false}${null}`), '');
  assert.equal(esc(`"'&`), '&quot;&#39;&amp;');
});

test('routes, tokens and times', () => {
  assert.deepEqual(parseRoute('#/misi/12?tab=log'), { name: 'misi', params: ['12'], query: { tab: 'log' } });
  assert.equal(parseRoute('').name, 'beranda');
  assert.deepEqual(takeToken('#t=abc%3D&app=1&/misi'), { token: 'abc=', embedded: true, rest: '/misi' });
  assert.equal(clock('2026-10-29T01:12:00Z'), '08.12');
  assert.equal(dur(161), '2 mnt 41 dtk');
  assert.equal(dur(38), '38 dtk');
  assert.equal(ago(new Date(Date.now() - 300000)), '5 mnt lalu');
  assert.equal(pct(3, 0), 0);
  assert.equal(pct(58, 100), 58);
  assert.deepEqual([...groupBy([{ g: 1 }, { g: 2 }, { g: 1 }], 'g').keys()], [1, 2]);
});
