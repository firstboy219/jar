import test from 'node:test';
import assert from 'node:assert/strict';
import { cardScale, diffCards, ease, matchCards, spiralGalaxy, starField, contextLabel } from '../lib.js';

test('the galaxy is deterministic, finite and disk-shaped', () => {
  const a = spiralGalaxy(2000), b = spiralGalaxy(2000);
  assert.deepEqual(a.positions, b.positions);
  let maxY = 0, maxR = 0;
  for (let i = 0; i < 2000; i++) {
    const [x, y, z] = a.positions.slice(i * 3, i * 3 + 3);
    assert.ok(Number.isFinite(x + y + z));
    maxY = Math.max(maxY, Math.abs(y)); maxR = Math.max(maxR, Math.hypot(x, z));
  }
  assert.ok(maxY < 100 && maxR > 1200, `thin and wide (y ${maxY}, r ${maxR})`);
  assert.equal(starField(100).length, 300);
});

test('cards shrink with distance and become stars far away', () => {
  assert.ok(cardScale(300) > cardScale(900));
  assert.equal(cardScale(5000), null);
  assert.equal(cardScale(10), 1.6);
  assert.equal(cardScale(0), null);
});

test('search, diff, easing, labels', () => {
  const cards = [{ id: 1, title: 'Laporan omzet', x: 0, y: 0, z: 0 }, { id: 2, title: 'Rapat tim', snippet: 'bahas omzet', x: 1, y: 1, z: 1 }];
  assert.deepEqual(matchCards(cards, 'omzet').map((c) => c.id), [1, 2]);
  assert.deepEqual(matchCards(cards, 'lap').map((c) => c.id), [1]);
  assert.deepEqual(matchCards(cards, ' '), []);
  const d = diffCards(cards, [{ ...cards[0], x: 5 }, { id: 3, title: 'Baru' }]);
  assert.deepEqual([d.added.map((c) => c.id), d.removed.map((c) => c.id), d.moved.map((c) => c.id)], [[3], [2], [1]]);
  assert.equal(ease(0), 0); assert.equal(ease(1), 1); assert.equal(ease(0.5), 0.5);
  assert.equal(contextLabel({ context: 'company:renature', title: 'PT Renature' }), '🏢 PT Renature');
});
