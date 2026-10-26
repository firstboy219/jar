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

test('the app passes its device token in the fragment and the viewer takes it out', async () => {
  const { takeAppParams } = await import('../lib.js');
  assert.deepEqual(takeAppParams('#t=abc%2B123&app=1'), { token: 'abc+123', embedded: true, rest: '' });
  assert.deepEqual(takeAppParams('#kartu=12&t=xyz&app=1'), { token: 'xyz', embedded: true, rest: '#kartu=12' });
  assert.deepEqual(takeAppParams('#kartu=7'), { token: '', embedded: false, rest: '#kartu=7' });
  assert.deepEqual(takeAppParams(''), { token: '', embedded: false, rest: '' });
});

test('the desk follows the owner\'s new task once, and never grabs the camera from a hand', async () => {
  const { shouldFollow, frameNeedsFetch, ago, PANELS } = await import('../lib.js');
  const base = { follow: true, idleMs: 9000, kind: 'owner', status: 'running', seen: false };
  assert.equal(shouldFollow(base), true);
  assert.equal(shouldFollow({ ...base, seen: true }), false);          // once per task
  assert.equal(shouldFollow({ ...base, idleMs: 1500 }), false);        // the owner just touched the screen
  assert.equal(shouldFollow({ ...base, follow: false }), false);
  assert.equal(shouldFollow({ ...base, kind: 'routine' }), false);     // background chores do not steal the view
  assert.equal(shouldFollow({ ...base, status: 'completed' }), false);
  assert.equal(frameNeedsFetch(3, 4, true), true);
  assert.equal(frameNeedsFetch(4, 4, true), false);
  assert.equal(frameNeedsFetch(0, 0, false), false);
  assert.equal(ago(5), '5 dtk');
  assert.equal(ago(150), '3 mnt');
  assert.equal(ago(7200), '2.0 jam');
  assert.deepEqual(Object.keys(PANELS).sort(), ['meeting', 'n8n', 'player', 'prompts', 'storage']);
});

test('standard views, fitting and the command line', async () => {
  const { VIEWS, shortestAngle, boundsOf, fitDistance, orthoHeight, snapValue, distance3, cssCubeMatrix, parseCommand, clampPhi } = await import('../lib.js');
  assert.deepEqual(Object.keys(VIEWS).sort(), ['back', 'bottom', 'front', 'iso', 'left', 'right', 'top']);
  assert.ok(VIEWS.top.phi > 0 && VIEWS.bottom.phi < Math.PI);                      // never exactly on the pole (the up vector would flip)
  assert.equal(clampPhi(-1), 0.02);
  assert.ok(Math.abs(shortestAngle(0.1, 2 * Math.PI - 0.1) - (-0.1)) < 1e-9);       // back round the short side
  const b = boundsOf([{ x: 0, y: 0, z: 0 }, { x: 1000, y: 0, z: 0 }]);
  assert.equal(b.x, 500); assert.equal(b.radius, 500);
  assert.equal(boundsOf([]).radius, 600);
  assert.ok(fitDistance(500, 60, 1.6) > 500 && fitDistance(500, 60, 0.5) > fitDistance(500, 60, 1.6));   // a narrow screen needs more room
  assert.ok(Math.abs(orthoHeight(1000, 60) - 2 * 1000 * Math.tan(Math.PI / 6)) < 1e-9);
  assert.equal(snapValue(137, 50), 150); assert.equal(snapValue(137, 0), 137);
  assert.equal(distance3({ x: 0, y: 0, z: 0 }, { x: 3, y: 4, z: 0 }).d, 5);
  assert.equal(cssCubeMatrix([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]), 'matrix3d(1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1)');
  assert.deepEqual(parseCommand('top'), { name: 'view', view: 'top' });
  assert.deepEqual(parseCommand('  Depan '), { name: 'view', view: 'front' });
  assert.deepEqual(parseCommand('zoom e'), { name: 'extents' });
  assert.deepEqual(parseCommand('ortho'), { name: 'projection', mode: 'ortho' });
  assert.deepEqual(parseCommand('layer tugas off'), { name: 'layer', layer: 'tugas', on: false });
  assert.deepEqual(parseCommand('layer yang ditampilkan'), { name: 'layer', layer: 'yang ditampilkan', on: null });
  assert.deepEqual(parseCommand('view save kerja'), { name: 'saveView', as: 'kerja' });
  assert.deepEqual(parseCommand('view kerja'), { name: 'namedView', as: 'kerja' });
  assert.deepEqual(parseCommand('ukur'), { name: 'tool', tool: 'measure' });
  assert.deepEqual(parseCommand('cari laporan bulanan'), { name: 'find', query: 'laporan bulanan' });
  assert.equal(parseCommand('ngawur').name, 'unknown'); assert.equal(parseCommand('').name, 'none');
});

test('voice: resample, PCM16 and the voice activity detector', async () => {
  const { downsample, floatToPcm16, pcm16ToBase64, Vad } = await import('../lib.js');
  assert.equal(downsample(new Float32Array(48000), 48000, 16000).length, 16000);
  assert.equal(downsample(new Float32Array(100), 16000, 16000).length, 100);
  const pcm = floatToPcm16(Float32Array.from([0, 1, -1, 2]));
  assert.deepEqual([...pcm], [0, 32767, -32768, 32767]);                              // clipped, never wrapped
  assert.equal(pcm16ToBase64(Int16Array.from([1, 2])), Buffer.from(new Uint8Array(Int16Array.from([1, 2]).buffer)).toString('base64'));
  const vad = new Vad();
  const tone = (secs, amp) => Float32Array.from({ length: Math.round(16000 * secs) }, (_, i) => amp * Math.sin(i / 8));
  const quiet = (secs) => Float32Array.from({ length: Math.round(16000 * secs) }, () => (Math.random() - 0.5) * 0.002);
  const out = [];
  for (const chunk of [quiet(1), tone(1, 0.3), quiet(1.2), quiet(0.5)]) {
    for (let i = 0; i < chunk.length; i += 1700) { const u = vad.push(chunk.subarray(i, i + 1700)); if (u) out.push(u); }   // odd chunk size on purpose
  }
  assert.equal(out.length, 1);
  const secs = out[0].length / 16000;
  assert.ok(secs > 1.0 && secs < 1.7, `utterance ${secs}s`);                           // the second of speech + pre-roll, not the silence
  const clicks = new Vad(); const got = [];
  for (const chunk of [quiet(1), tone(0.1, 0.4), quiet(1.5)]) { const u = clicks.push(chunk); if (u) got.push(u); }
  assert.equal(got.length, 0);                                                          // a 100 ms click is not an utterance
});

test('the view cube shows the face you are looking at: each standard view puts its face toward the viewer', async () => {
  const THREE = await import('../vendor/three.module.min.js');
  const { VIEWS, cssCubeMatrix } = await import('../lib.js');
  const normals = { top: [0, -1, 0], bottom: [0, 1, 0], front: [0, 0, 1], back: [0, 0, -1], right: [1, 0, 0], left: [-1, 0, 0] };   // CSS space (y down)
  const cam = new THREE.PerspectiveCamera(60, 1.6, 1, 80000);
  for (const [view, n] of Object.entries(normals)) {
    const { theta, phi } = VIEWS[view], r = 1000;
    cam.position.set(r * Math.sin(phi) * Math.sin(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.cos(theta));
    cam.lookAt(0, 0, 0); cam.updateMatrixWorld(); cam.matrixWorldInverse.copy(cam.matrixWorld).invert();
    const m = cssCubeMatrix(cam.matrixWorldInverse.elements).replace('matrix3d(', '').replace(')', '').split(',').map(Number);
    const z = m[2] * n[0] + m[6] * n[1] + m[10] * n[2];                       // the z component of the face normal after the cube's rotation
    assert.ok(z > 0.95, `${view}: face normal z = ${z.toFixed(3)}`);          // pointing at the viewer
  }
});

test('a live video frame carries its task and number in front of the picture', async () => {
  const { parseFrameHeader } = await import('../lib.js');
  const buf = new Uint8Array([0, 0, 1, 2, 0, 0, 0, 7, 0xff, 0xd8]).buffer;
  assert.deepEqual(parseFrameHeader(buf), { task: 258, seq: 7, offset: 8 });
  assert.deepEqual([...new Uint8Array(buf.slice(8))], [0xff, 0xd8]);
});

import { fitSize, keyToInput, pageFraction, scrollDelta, touchIntent } from '../lib.js';

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

test('desk feature cards: timer text, what plays a panel, the voice stop signal', async () => {
  const { mmss, playerSource, stopRaised, PANELS } = await import('../lib.js');
  assert.equal(mmss(0), '00:00'); assert.equal(mmss(754), '12:34'); assert.equal(mmss(3725), '1:02:05'); assert.equal(mmss(-5), '00:00');
  assert.deepEqual(playerSource({ panel: 'video', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ' }), { kind: 'youtube', id: 'dQw4w9WgXcQ' });
  assert.deepEqual(playerSource({ panel: 'video', url: 'https://youtu.be/dQw4w9WgXcQ' }), { kind: 'youtube', id: 'dQw4w9WgXcQ' });
  assert.deepEqual(playerSource({ panel: 'music', url: '/api/v1/media/abc' }), { kind: 'audio', url: '/api/v1/media/abc', auth: true });
  assert.deepEqual(playerSource({ panel: 'video', url: 'https://cdn.example.com/a.mp4' }), { kind: 'video', url: 'https://cdn.example.com/a.mp4', auth: false });
  assert.equal(playerSource({ panel: 'music', url: 'http://plain.example.com/a.mp3' }).kind, 'none');
  assert.equal(playerSource({ panel: 'music', url: 'javascript:alert(1)' }).kind, 'none');
  assert.equal(playerSource({}).kind, 'none');
  assert.equal(stopRaised(null, 3), false); assert.equal(stopRaised(2, 2), false); assert.equal(stopRaised(2, 3), true);
  assert.ok(PANELS.player && PANELS.meeting);
});
