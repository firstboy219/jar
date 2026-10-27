import { test } from 'node:test';
import assert from 'node:assert/strict';
import { teamSize, SCHEDULES } from '../projectscard.js';

test('a project team counts its workers like the server does', () => {
  assert.equal(teamSize([{ workers: 2 }, { workers: 1 }]), 3);
  assert.equal(teamSize([{ workers: 9 }, { workers: 0 }, {}]), 7);   // 1–5 each, like the server
  assert.equal(teamSize([]), 0);
  assert.deepEqual(SCHEDULES.map(([v]) => v), ['manual', 'hourly', 'daily', 'weekdays', 'weekly']);
});
