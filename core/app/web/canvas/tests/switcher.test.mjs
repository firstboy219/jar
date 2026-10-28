import { test } from 'node:test';
import assert from 'node:assert/strict';
import { nextIndex, pagesFrom } from '../switcher.js';

const d = {
  stations: [{ task_id: 7, status: 'running', browsing: true, title: 'Apply job' }, { task_id: 8, status: 'completed', browsing: true, title: 'x' },
    { task_id: 9, status: 'running', browsing: false, has_frame: false, title: 'thinking only' }],
  player: { id: 'p', title: 'Lagu' },
  cards: { video: { id: 'v', title: 'Kucing' }, web: { title: 'Kompas' }, map: null, draft: { title: 'Balas Budi' } },
  meeting: { state: 'recording', title: 'Rapat UAT' },
  workers: [{ status: 'running' }, { status: 'completed' }, { status: 'queued' }],
  devteam: { jobs: [{ status: 'done' }] },
};

test('only what is active becomes a page, worker browsers first', () => {
  const ids = pagesFrom(d, { projects: true }).map((p) => p.id);
  assert.deepEqual(ids, ['station:7', 'video', 'player', 'web', 'draft', 'meeting', 'projects', 'workers']);
  const w = pagesFrom(d).find((p) => p.id === 'workers');
  assert.equal(w.sub, '2 bekerja'); assert.equal(w.icon, '👷');
  assert.ok(!pagesFrom(d).some((p) => p.id === 'projects'));                      // no project at work, none pinned
  assert.ok(pagesFrom(d, { pinned: 'projects' }).some((p) => p.id === 'projects'));  // asked for from the top bar
  assert.ok(pagesFrom({ ...d, devteam: { jobs: [{ status: 'coding' }] } }).some((p) => p.id === 'devteam'));
  assert.ok(!pagesFrom({ ...d, meeting: { state: 'done' } }).some((p) => p.id === 'meeting'));
  assert.deepEqual(pagesFrom({}), []);
  assert.deepEqual(pagesFrom(null), []);
});

test('the page shown stays, or moves to the one that just appeared', () => {
  const p = (...ids) => ids.map((id) => ({ id }));
  assert.equal(nextIndex(['a', 'b'], p('a', 'b', 'c'), 'b'), 1);       // still there
  assert.equal(nextIndex(['a', 'b'], p('a', 'c'), 'b'), 1);            // gone: the new one
  assert.equal(nextIndex(['a', 'b', 'c'], p('a', 'b'), 'c'), 1);       // gone, nothing new: the nearest
  assert.equal(nextIndex([], p('x'), undefined), 0);
  assert.equal(nextIndex(['a'], [], 'a'), 0);
});

test('the search and the ✕ of a page', async () => {
  const { matches, closeKind } = await import('../switcher.js');
  const page = { title: 'Halaman web', sub: 'Kompas — berita hari ini', kind: 'web' };
  assert.ok(matches(page, 'kompas berita')); assert.ok(matches(page, '')); assert.ok(!matches(page, 'youtube'));
  assert.equal(closeKind({ kind: 'web' }), 'close'); assert.equal(closeKind({ kind: 'player' }), 'close');
  assert.equal(closeKind({ kind: 'station' }), 'stop'); assert.equal(closeKind({ kind: 'workers' }), 'hide');
  assert.equal(closeKind({ kind: 'meeting' }), null);    // a recording is stopped on its own page, never by a ✕
});
