import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clock, turns, chunkOf, MEETING_STATUS } from '../meetings.js';

test('meeting clock, transcript turns and audio pieces', () => {
  assert.equal(clock(5), '0:05'); assert.equal(clock(754), '12:34'); assert.equal(clock(3725), '1:02:05'); assert.equal(clock(null), '0:00');
  const t = turns([{ speaker: 'Rina', start: 0, end: 4, text: 'Halo' }, { speaker: 'Rina', start: 4.5, end: 8, text: 'semua.' },
    { speaker: 'Budi', start: 8, end: 12, text: 'Siap.' }, { speaker: 'Rina', start: 30, end: 33, text: 'Lanjut.' }]);
  assert.deepEqual(t.map((x) => `${x.speaker}:${x.text}`), ['Rina:Halo semua.', 'Budi:Siap.', 'Rina:Lanjut.']);
  assert.equal(t[0].end, 8);
  assert.deepEqual([0, 59.9, 60, 125].map(chunkOf), [0, 0, 1, 2]);
  for (const s of ['recording', 'queued', 'transcribing', 'summarizing', 'done', 'failed']) assert.ok(MEETING_STATUS[s]);
});
