import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shortcutFor, filterSlash, numberOf, hiddenByToggles, dueLabel, groupTasks, parseLines, pageTree, nextPriority } from '../lib.js';

test('markdown shortcuts turn a block into its type', () => {
  assert.deepEqual(shortcutFor('# Judul'), { type: 'h1', rest: 'Judul' });
  assert.deepEqual(shortcutFor('### x'), { type: 'h3', rest: 'x' });
  assert.deepEqual(shortcutFor('- beli susu'), { type: 'bullet', rest: 'beli susu' });
  assert.deepEqual(shortcutFor('1. pertama'), { type: 'number', rest: 'pertama' });
  assert.deepEqual(shortcutFor('[] tugas'), { type: 'todo', rest: 'tugas', checked: false });
  assert.deepEqual(shortcutFor('[x] beres'), { type: 'todo', rest: 'beres', checked: true });
  assert.equal(shortcutFor('>> lipat').type, 'toggle');
  assert.equal(shortcutFor('> kutip').type, 'quote');
  assert.equal(shortcutFor('--- ').type, 'divider');
  assert.equal(shortcutFor('#tanpaspasi'), null);
  assert.equal(shortcutFor('biasa saja'), null);
});

test('the slash menu filters by name, hint and key', () => {
  assert.equal(filterSlash('').length, 12);
  assert.ok(filterSlash('tug').some((x) => x.type === 'todo'));
  assert.deepEqual(filterSlash('h2').map((x) => x.type), ['h2']);
  assert.ok(filterSlash('kode').some((x) => x.type === 'code'));
  assert.equal(filterSlash('zzz').length, 0);
});

test('numbered lists count per level and restart after other blocks', () => {
  const b = [{ type: 'number' }, { type: 'number' }, { type: 'bullet', indent: 1 }, { type: 'number' }, { type: 'p' }, { type: 'number' }];
  assert.deepEqual([0, 1, 3, 5].map((i) => numberOf(b, i)), [1, 2, 3, 1]);
});

test('a closed toggle hides what is indented under it', () => {
  const b = [{ type: 'toggle' }, { type: 'p', indent: 1 }, { type: 'p', indent: 2 }, { type: 'p' }, { type: 'toggle', open: true }, { type: 'p', indent: 1 }];
  assert.deepEqual([...hiddenByToggles(b)], [1, 2]);
});

test('due dates read like people say them, tasks group like a planner', () => {
  const today = new Date(2026, 9, 26);
  assert.equal(dueLabel('2026-10-26', today), 'Hari ini');
  assert.equal(dueLabel('2026-10-27', today), 'Besok');
  assert.equal(dueLabel('2026-10-25', today), 'Kemarin');
  assert.equal(dueLabel('2026-10-29', today), '3 hari lagi');
  assert.equal(dueLabel('2026-11-03', today), 'Sel, 3 Nov');
  assert.equal(dueLabel('2027-01-05', today), 'Sel, 5 Jan 2027');
  const g = groupTasks([{ text: 'a', due: '2026-10-20' }, { text: 'b', due: '2026-10-26' }, { text: 'c', due: '2026-10-27' },
    { text: 'd', due: '2026-10-30' }, { text: 'e', due: '2026-12-01' }, { text: 'f' }, { text: 'g', checked: true }], today);
  assert.deepEqual(g.map((x) => [x.key, x.items.map((i) => i.text).join('')]),
    [['overdue', 'a'], ['today', 'b'], ['tomorrow', 'c'], ['week', 'd'], ['later', 'e'], ['nodate', 'f'], ['done', 'g']]);
});

test('pasted text becomes blocks, code fences stay whole', () => {
  const b = parseLines('# Rencana\n- satu\n  - dua\n2. langkah\n[ ] tugas\n```\nx = 1\n\ny\n```\nbiasa');
  assert.deepEqual(b.map((x) => x.type), ['h1', 'bullet', 'bullet', 'number', 'todo', 'code', 'p']);
  assert.equal(b[2].indent, 1); assert.equal(b[5].text, 'x = 1\n\ny');
});

test('pages nest under their parent; priority cycles', () => {
  const t = pageTree([{ id: 'a' }, { id: 'b', parent_id: 'a' }, { id: 'c', parent_id: 'gone' }, { id: 'd', parent_id: 'b' }]);
  assert.deepEqual(t.map((x) => `${x.page.id}${x.depth}`), ['a0', 'b1', 'd2', 'c0']);
  assert.deepEqual([0, 1, 2, 3].map(nextPriority), [1, 2, 3, 0]);
});
