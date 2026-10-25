// node --test: the gesture classifier and state machine (Fase 4.0), with synthetic hands.
import test from 'node:test';
import assert from 'node:assert/strict';
import { classify, GestureMachine } from '../gestures.js';

// A synthetic right hand: wrist at (x, y); fingers extended upward unless folded; thumb tip placed explicitly.
function hand({ x = 0.5, y = 0.7, folded = [], pinch = false } = {}) {
  const lm = Array.from({ length: 21 }, () => ({ x, y, z: 0 }));
  const finger = (mcp, pip, dip, tip, dx, isFolded) => {
    lm[mcp] = { x: x + dx, y: y - 0.12, z: 0 };
    lm[pip] = { x: x + dx, y: y - 0.17, z: 0 };
    lm[dip] = { x: x + dx, y: isFolded ? y - 0.13 : y - 0.21, z: 0 };
    lm[tip] = { x: x + dx, y: isFolded ? y - 0.10 : y - 0.25, z: 0 };
  };
  finger(5, 6, 7, 8, -0.03, folded.includes('index'));
  finger(9, 10, 11, 12, 0, folded.includes('middle'));
  finger(13, 14, 15, 16, 0.03, folded.includes('ring'));
  finger(17, 18, 19, 20, 0.06, folded.includes('pinky'));
  lm[1] = { x: x - 0.06, y: y - 0.04, z: 0 }; lm[2] = { x: x - 0.08, y: y - 0.07, z: 0 }; lm[3] = { x: x - 0.09, y: y - 0.09, z: 0 };
  lm[4] = pinch ? { x: lm[8].x + 0.005, y: lm[8].y + 0.005, z: 0 } : { x: x - 0.12, y: y - 0.11, z: 0 };
  return lm;
}
const PALM = () => hand();
const POINT = (x, y) => hand({ x, y, folded: ['middle', 'ring', 'pinky'] });
const PINCH = (x, y) => hand({ x, y, folded: ['middle', 'ring', 'pinky'], pinch: true });
const FIST = () => hand({ folded: ['index', 'middle', 'ring', 'pinky'] });

test('poses are recognised from landmarks', () => {
  assert.equal(classify(PALM()), 'palm');
  assert.equal(classify(POINT()), 'point');
  assert.equal(classify(PINCH()), 'pinch');
  assert.equal(classify(FIST()), 'fist');
});

function run(m, frames, t0 = 0, dt = 33) {
  const out = [];
  frames.forEach((hands, i) => out.push(...m.step({ t: t0 + i * dt, hands })));
  return out;
}

test('nothing happens until an open palm is held still for a second', () => {
  const m = new GestureMachine();
  let ev = run(m, Array(10).fill([POINT(0.4, 0.5)]));
  assert.ok(!ev.some((e) => e.type === 'cursor'), 'inactive: no cursor');
  ev = run(m, Array(40).fill([PALM()]), 1000);
  assert.deepEqual(ev.filter((e) => e.type === 'lock'), [{ type: 'lock', active: true }]);
  ev = run(m, Array(6).fill([POINT(0.4, 0.5)]), 3000);
  assert.ok(ev.some((e) => e.type === 'cursor'));
  const c = ev.filter((e) => e.type === 'cursor').at(-1);
  assert.ok(Math.abs(c.x - 0.63) < 0.05, `mirrored x ${c.x}`);     // index tip 0.37 → mirrored 0.63
});

function activeMachine() {
  const m = new GestureMachine();
  run(m, Array(40).fill([PALM()]));
  return m;
}

test('a quick pinch is a click; a held, moved pinch is a drag', () => {
  const m = activeMachine();
  let ev = run(m, [...Array(4).fill([POINT(0.5, 0.6)]), ...Array(5).fill([PINCH(0.5, 0.6)]), ...Array(4).fill([POINT(0.5, 0.6)])], 5000);
  const types = ev.map((e) => e.type).filter((t) => t !== 'cursor');
  assert.deepEqual(types, ['press', 'release', 'click']);
  const moving = Array.from({ length: 12 }, (_, i) => [PINCH(0.5 - i * 0.02, 0.6)]);
  ev = run(m, [...Array(4).fill([PINCH(0.5, 0.6)]), ...moving, ...Array(4).fill([POINT(0.26, 0.6)])], 9000);
  const kinds = ev.map((e) => e.type);
  assert.ok(kinds.includes('press') && kinds.includes('drag') && kinds.includes('release'));
  assert.ok(!kinds.includes('click'), 'a drag is not a click');
});

test('two pinching hands zoom; a moving palm scrolls; a fist pauses until the palm hold', () => {
  const m = activeMachine();
  let ev = run(m, Array.from({ length: 8 }, (_, i) => [PINCH(0.4 - i * 0.01, 0.6), PINCH(0.6 + i * 0.01, 0.6)]), 5000);
  const zooms = ev.filter((e) => e.type === 'zoom');
  assert.ok(zooms.length > 0 && zooms.every((z) => z.factor > 1), 'hands apart → zoom factor > 1');
  ev = run(m, Array.from({ length: 10 }, (_, i) => [hand({ x: 0.3 + i * 0.03 })]), 8000);
  assert.ok(ev.some((e) => e.type === 'scroll'));
  ev = run(m, Array(5).fill([FIST()]), 10000);
  assert.ok(ev.some((e) => e.type === 'pause') && m.paused);
  ev = run(m, Array(6).fill([POINT(0.5, 0.5)]), 11000);
  assert.ok(!ev.some((e) => e.type === 'cursor'), 'paused: no cursor');
  ev = run(m, Array(40).fill([PALM()]), 12000);
  assert.ok(ev.some((e) => e.type === 'lock' && e.active) && !m.paused);
});

test('flickers do not trigger: a pose must hold several frames, and no hand for a minute switches off', () => {
  const m = activeMachine();
  const ev = run(m, [[POINT(0.5, 0.6)], [POINT(0.5, 0.6)], [PINCH(0.5, 0.6)], [POINT(0.5, 0.6)], [POINT(0.5, 0.6)], [PINCH(0.5, 0.6)], [POINT(0.5, 0.6)]], 5000);
  assert.ok(!ev.some((e) => e.type === 'press'), 'one-frame pinches are noise');
  m.step({ t: 6000, hands: [POINT(0.5, 0.6)] });
  const off = m.step({ t: 6000 + 61000, hands: [] });
  assert.deepEqual(off, [{ type: 'lock', active: false, reason: 'idle' }]);
});
