import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reportChart, runVerdict } from '../resultmd.js';

test('the report chart counts finished workers per run, oldest first', () => {
  const c = reportChart([{ run: 3, completed: 2 }, { run: 1, completed: 1 }, { run: 2, completed: 0 }]);
  assert.deepEqual(c.labels, ['#1', '#2', '#3']); assert.deepEqual(c.values, [1, 0, 2]); assert.equal(c.kind, 'bar');
  assert.equal(reportChart(Array.from({ length: 12 }, (_, i) => ({ run: i + 1, completed: 1 }))).kind, 'line');
  assert.equal(reportChart(Array.from({ length: 30 }, (_, i) => ({ run: i + 1, completed: 1 }))).labels.length, 20);
});

test('a run is berjalan, berhasil, sebagian or gagal', () => {
  assert.equal(runVerdict({ busy: 1, completed: 0, failed: 0 }).text, 'berjalan');
  assert.equal(runVerdict({ busy: 0, completed: 3, failed: 0 }).text, 'berhasil');
  assert.equal(runVerdict({ busy: 0, completed: 2, failed: 1 }).text, 'sebagian');
  assert.equal(runVerdict({ busy: 0, completed: 0, failed: 2 }).text, 'gagal');
});
