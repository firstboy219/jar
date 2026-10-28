import { test } from 'node:test';
import assert from 'node:assert/strict';
import { orderText, stagesOf } from '../projectscard.js';
import { leftText } from '../choicepopup.js';

test('a role waits for the one before it, or works with it', () => {
  assert.deepEqual(stagesOf([{}, {}, { after_prev: true }, { after_prev: true }, {}]), [0, 0, 1, 2, 2]);
  assert.deepEqual(stagesOf([{ after_prev: true }]), [0]);
  assert.deepEqual(stagesOf([]), []);
});

test('the order is said in words', () => {
  const roles = [{}, { after_prev: true, ask_owner: true, start_offset_min: 5 }, { after_prev: true }, {}];
  assert.equal(orderText(roles, 0), '① mulai pertama');
  assert.equal(orderText(roles, 1), '② setelah ① selesai, tanya aku dulu → 5 mnt sebelum jam pilihan');
  assert.equal(orderText(roles, 2), '③ setelah ② selesai');
  assert.equal(orderText(roles, 3), '③ bersamaan dengan ③');
  assert.equal(orderText([{}, { after_prev: true, ask_owner: true, start_offset_min: null }], 1), '② setelah ① selesai, tanya aku dulu');
});

test('the time left to pick is said in minutes or hours', () => {
  assert.equal(leftText(540), '9 mnt'); assert.equal(leftText(8100), '2 j 15 mnt'); assert.equal(leftText(-5), '0 mnt');
});
