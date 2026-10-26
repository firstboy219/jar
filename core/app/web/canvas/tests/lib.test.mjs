import test from 'node:test';
import assert from 'node:assert/strict';
import { diffCards, ease, matchCards, contextLabel } from '../lib.js';

test('search, diff, easing, labels', () => {
  const cards = [{ id: 1, title: 'Laporan omzet', x: 0, y: 0, z: 0 }, { id: 2, title: 'Rapat tim', snippet: 'bahas omzet', x: 1, y: 1, z: 1 }];
  assert.deepEqual(matchCards(cards, 'omzet').map((c) => c.id), [1, 2]);
  assert.deepEqual(matchCards(cards, 'lap').map((c) => c.id), [1]);
  assert.deepEqual(matchCards(cards, ' '), []);
  const d = diffCards(cards, [{ ...cards[0], x: 5 }, { id: 3, title: 'Baru' }]);
  assert.deepEqual([d.added.map((c) => c.id), d.removed.map((c) => c.id), d.moved.map((c) => c.id)], [[3], [2], [1]]);
  assert.equal(ease(0), 0); assert.equal(ease(1), 1); assert.equal(ease(0.5), 0.5);
  assert.equal(contextLabel({ context: 'company:renature', title: 'PT Renature' }), '🏢 PT Renature');
  assert.equal(contextLabel({ context: 'utama', title: 'Utama' }), 'Utama');
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
  assert.deepEqual(Object.keys(PANELS).sort(), ['doc', 'draft', 'google', 'image', 'map', 'meeting', 'n8n', 'player', 'prompts', 'storage', 'text', 'video', 'web', 'workers']);
  // no two desk panels overlap (each is at most ~520 units tall)
  const r = Object.entries(PANELS).map(([n, p]) => ({ n, x: p.x, y: p.y, w: p.w, h: 520 }));
  for (const a of r) for (const b of r) if (a.n < b.n) {
    const apart = a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
    assert.ok(apart || Math.abs(a.y - b.y) >= 520, `${a.n} overlaps ${b.n}`);
  }
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

test('board: zooming keeps the point under the cursor in place, and is bounded', async () => {
  const { toScreen, toWorld, zoomAt, panBy, clampZoom, MIN_ZOOM, MAX_ZOOM } = await import('../lib.js');
  const vp = { w: 1000, h: 600 }, v = { cx: 120, cy: -40, k: 1 };
  const p = toWorld(v, vp, 700, 200);
  const z = zoomAt(v, vp, 2, 700, 200);
  const back = toScreen(z, vp, p.x, p.y);
  assert.ok(Math.abs(back.x - 700) < 1e-9 && Math.abs(back.y - 200) < 1e-9 && z.k === 2);
  assert.equal(zoomAt(v, vp, 1e9, 10, 10).k, MAX_ZOOM); assert.equal(zoomAt(v, vp, 1e-9, 10, 10).k, MIN_ZOOM); assert.equal(clampZoom(0), MIN_ZOOM);
  const q = toWorld(panBy(v, 100, -50), vp, 500, 300);
  assert.deepEqual([q.x, q.y], [20, 10]);                                     // dragging the paper right shows what was to the left
});

test('board: fitting a rect centres it in the free area and never zooms past the cap', async () => {
  const { fitRect, toScreen, rectsBounds } = await import('../lib.js');
  const vp = { w: 1000, h: 600 };
  const r = { x: 0, y: 0, w: 4000, h: 1000 };
  const v = fitRect(r, vp, { pad: 50 });
  assert.ok(Math.abs(v.k - 0.225) < 1e-9);
  const c = toScreen(v, vp, 2000, 500);
  assert.ok(Math.abs(c.x - 500) < 1e-6 && Math.abs(c.y - 300) < 1e-6);
  assert.equal(fitRect({ x: 0, y: 0, w: 10, h: 10 }, vp).k, 1.25);          // a tiny thing is not blown up
  const free = fitRect(r, vp, { pad: 50, inset: { left: 200 } });
  assert.ok(Math.abs(toScreen(free, vp, 2000, 500).x - 600) < 1e-6);         // the middle of what the left panel leaves free
  assert.deepEqual(rectsBounds([{ x: 0, y: 0, w: 10, h: 10 }, { x: 20, y: -5, w: 10, h: 10 }]), { x: 0, y: -5, w: 30, h: 15 });
  assert.equal(rectsBounds([]), null);
});

test('board: a mouse wheel zooms, a trackpad scroll pans, a pinch zooms', async () => {
  const { wheelIntent } = await import('../lib.js');
  assert.equal(wheelIntent({ deltaY: 100, deltaX: 0, deltaMode: 0 }), 'zoom');      // notched wheel
  assert.equal(wheelIntent({ deltaY: 3, deltaX: 0, deltaMode: 1 }), 'zoom');
  assert.equal(wheelIntent({ deltaY: 7.5, deltaX: 0, deltaMode: 0 }), 'pan');        // trackpad: fractional
  assert.equal(wheelIntent({ deltaY: 4, deltaX: 3, deltaMode: 0 }), 'pan');          // trackpad: sideways
  assert.equal(wheelIntent({ deltaY: -8, deltaX: 0, deltaMode: 0, ctrlKey: true }), 'zoom');   // pinch
});

test('board: smart guides pull an edge or a middle line onto a neighbour, within a tolerance', async () => {
  const { snapRect, snapValue } = await import('../lib.js');
  const others = [{ x: 100, y: 100, w: 200, h: 100 }];
  const a = snapRect({ x: 303, y: 400, w: 50, h: 50 }, others, 6);            // left edge 3 away from the other's right edge
  assert.equal(a.dx, -3); assert.equal(a.dy, 0); assert.equal(a.guides.length, 1); assert.equal(a.guides[0].axis, 'x'); assert.equal(a.guides[0].at, 300);
  const b = snapRect({ x: 160, y: 143, w: 80, h: 10 }, others, 6);            // middle lines: x 200 meets 200, y 148 meets 150
  assert.deepEqual([b.dx, b.dy], [0, 2]);
  assert.deepEqual(snapRect({ x: 1000, y: 1000, w: 10, h: 10 }, others, 6), { dx: 0, dy: 0, guides: [] });
  assert.equal(snapValue(137, 50), 150); assert.equal(snapValue(137, 0), 137);
});

test('board: align and distribute', async () => {
  const { alignRects, distributeRects, rectsIntersect, rectContains } = await import('../lib.js');
  const rs = [{ x: 0, y: 0, w: 100, h: 50 }, { x: 300, y: 80, w: 40, h: 40 }, { x: 150, y: 200, w: 60, h: 20 }];
  assert.deepEqual(alignRects(rs, 'left').map((r) => r.x), [0, 0, 0]);
  assert.deepEqual(alignRects(rs, 'right').map((r) => r.x), [240, 300, 280]);
  assert.deepEqual(alignRects(rs, 'vcenter').map((r) => r.y), [85, 90, 100]);
  const d = distributeRects(rs, 'h');                                          // equal gaps of 70 between the three
  assert.equal(d[0].x, 0); assert.equal(d[1].x, 300); assert.ok(Math.abs(d[2].x - 170) < 1e-9);
  assert.deepEqual(distributeRects(rs.slice(0, 2), 'h'), rs.slice(0, 2));
  assert.ok(rectsIntersect(rs[0], { x: 90, y: 40, w: 50, h: 50 })); assert.ok(!rectsIntersect(rs[0], { x: 100, y: 0, w: 5, h: 5 }));
  assert.ok(rectContains({ x: 0, y: 0, w: 500, h: 500 }, rs[1])); assert.ok(!rectContains(rs[0], rs[1]));
});

test('board: resizing from a handle keeps the opposite side still, respects the minimum, and the shape on request', async () => {
  const { resizeRect } = await import('../lib.js');
  const r = { x: 100, y: 100, w: 200, h: 100 };
  assert.deepEqual(resizeRect(r, 'se', 50, 20), { x: 100, y: 100, w: 250, h: 120 });
  assert.deepEqual(resizeRect(r, 'nw', 30, 10), { x: 130, y: 110, w: 170, h: 90 });          // the south-east corner stays at (300, 200)
  assert.deepEqual(resizeRect(r, 'e', -500, 0), { x: 100, y: 100, w: 60, h: 100 });          // never smaller than the minimum
  const sq = resizeRect(r, 'se', 100, 0, { ratio: true });
  assert.ok(Math.abs(sq.w / sq.h - 2) < 1e-9);
  const c = resizeRect(r, 'e', 40, 0, { center: true });
  assert.deepEqual(c, { x: 60, y: 100, w: 280, h: 100 });
});

test('board: a connector leaves and enters through the facing sides and points its arrows along the curve', async () => {
  const { connectorPath, miniMapFit } = await import('../lib.js');
  const a = { x: 0, y: 0, w: 100, h: 60 }, b = { x: 400, y: 20, w: 100, h: 60 };
  const c = connectorPath(a, b);
  assert.deepEqual(c.from, { x: 100, y: 30 }); assert.deepEqual(c.to, { x: 400, y: 50 });
  assert.ok(c.d.startsWith('M 100 30 C '));
  assert.ok(Math.abs(c.endAngle) < 0.2);                                       // arriving from the left: the arrow points right
  assert.ok(Math.abs(Math.abs(c.startAngle) - Math.PI) < 0.2);                 // leaving to the right: an arrow at the start points left
  const below = connectorPath(a, { x: 10, y: 400, w: 80, h: 40 });
  assert.deepEqual(below.from, { x: 50, y: 60 }); assert.deepEqual(below.to, { x: 50, y: 400 });
  const up = connectorPath(below && { x: 10, y: 400, w: 80, h: 40 }, a);
  assert.deepEqual(up.from, { x: 50, y: 400 });
  const m = miniMapFit({ x: 0, y: 0, w: 1000, h: 500 }, { w: 200, h: 120 }, 0);
  assert.ok(Math.abs(m.s - 0.2) < 1e-9 && Math.abs(m.oy - 10) < 1e-9);
});

test('workers card: short model names and durations', async () => {
  const { shortModel, dur } = await import('../workerscard.js');
  assert.equal(shortModel('deepseek/deepseek-v4.1-flash'), 'deepseek-v4.1-flash');
  assert.equal(shortModel('nvidia/nemotron-3-ultra-550b-a55b:free'), 'nemotron-3-ultra-550b-a55b (gratis)');
  assert.equal(shortModel('qwen-lokal'), 'qwen-lokal');
  assert.equal(shortModel(''), '—');
  assert.equal(dur(45), '45d'); assert.equal(dur(75), '1m15d'); assert.equal(dur(3725), '1j02m');
});
