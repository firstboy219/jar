import { test } from 'node:test';
import assert from 'node:assert/strict';
import { laneLabel, loadText } from '../workerscard.js';

test('the lane of a task is a short label', () => {
  assert.equal(laneLabel('ringan'), '🪶 Jar (ringan)');
  assert.equal(laneLabel('openjarvis'), 'OpenJarvis (berat)');
  assert.equal(laneLabel('hermes'), 'Hermes');
  assert.equal(laneLabel(undefined), 'Hermes');
});

test('the load of the lanes is one line', () => {
  const l = { slots: 4, hermes_running: 3, hermes_queued: 2, openjarvis_running: 1, openjarvis_queued: 0, light_running: 1, openjarvis_on: true };
  assert.equal(loadText(l), 'Hermes mengatur — jar (ringan) 1 · OpenJarvis (berat) 1 · Hermes 3/4 (+2 antre)');
  assert.equal(loadText({ ...l, hermes_queued: 0, openjarvis_on: false }), 'Hermes mengatur — jar (ringan) 1 · Hermes 3/4');
  assert.equal(loadText(null), '');
});
