import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clampArea, AREA_MIN, AREA_MAX } from '../lib.js';

test('an area keeps a size the owner can still use', () => {
  assert.deepEqual(clampArea({ w: 500.4, h: 300.6 }), { w: 500, h: 301 });
  assert.deepEqual(clampArea({ w: 10, h: 5 }), { w: AREA_MIN.w, h: AREA_MIN.h });          // never too small to grab again
  assert.deepEqual(clampArea({ w: 99999, h: 99999 }), { w: AREA_MAX.w, h: AREA_MAX.h });
  assert.deepEqual(clampArea({ w: 400, h: null }), { w: 400, h: null });                   // no height: it grows with its content
  assert.deepEqual(clampArea({ w: 'x', h: undefined }), { w: AREA_MIN.w, h: null });
});
