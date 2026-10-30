import test from 'node:test';
import assert from 'node:assert/strict';
import { fitSize, keyToInput, pageFraction, scrollDelta, touchIntent } from '../takeover-lib.js';

test('takeover: a pointer over the video becomes a place on the page, clamped to its edges', () => {
  const r = { left: 100, top: 50, width: 400, height: 250 };
  assert.deepEqual(pageFraction(r, 300, 175), { x: 0.5, y: 0.5 });
  assert.deepEqual(pageFraction(r, 90, 999), { x: 0, y: 1 });
});

test('takeover: the video keeps its shape inside the stage', () => {
  assert.deepEqual(fitSize(1000, 500, 1100, 700), { w: 785, h: 500 });
  assert.deepEqual(fitSize(500, 1000, 1100, 700), { w: 500, h: 318 });
  assert.deepEqual(fitSize(300, 200, 0, 0), { w: 300, h: 200 });
});

test('takeover: letters and editing keys go to the page; shortcuts, composition and function keys do not', () => {
  assert.deepEqual(keyToInput({ key: 'A', code: 'KeyA', shiftKey: true }), { t: 'key', key: 'A', code: 'KeyA', shift: true, alt: false });
  assert.equal(keyToInput({ key: 'Enter', code: 'Enter' }).key, 'Enter');
  assert.equal(keyToInput({ key: 'c', ctrlKey: true }), null);                       // no copy/cut: pasting goes through text
  assert.equal(keyToInput({ key: 'a', ctrlKey: true }).ctrl, true);                  // select-all, to replace what a field holds
  assert.equal(keyToInput({ key: 'F5' }), null);
  assert.equal(keyToInput({ key: 'Unidentified' }), null);                           // phone keyboards: the text input takes over
  assert.equal(keyToInput({ key: 'a', isComposing: true }), null);
});

test('takeover: a quick small touch is a click, a drag scrolls the page by page pixels', () => {
  assert.equal(touchIntent(2, 3, 120), 'tap');
  assert.equal(touchIntent(2, 3, 900), 'scroll');
  assert.equal(touchIntent(0, 40, 100), 'scroll');
  assert.equal(scrollDelta(100, 400, 1100), 275);
});
