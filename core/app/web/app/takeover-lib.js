// Pure helpers of the takeover window (ADR-053): where a pointer is on the mission's page, keys, taps and scrolling. Unit-tested.

/** Where on the page, 0–1 each way, a pointer over the video is (the video fills its rectangle exactly). */
export function pageFraction(rect, clientX, clientY) {
  const c = (v) => Math.min(1, Math.max(0, v));
  return { x: c((clientX - rect.left) / (rect.width || 1)), y: c((clientY - rect.top) / (rect.height || 1)) };
}

/** The biggest size, keeping the picture's shape, that fits the stage. */
export function fitSize(stageW, stageH, picW, picH) {
  if (!picW || !picH) return { w: stageW, h: stageH };
  const s = Math.min(stageW / picW, stageH / picH);
  return { w: Math.floor(picW * s), h: Math.floor(picH * s) };
}

const NAMED_KEYS = new Set(['Backspace', 'Tab', 'Enter', 'Escape', 'Delete', 'Home', 'End', 'PageUp', 'PageDown', 'ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown']);

/** A keyboard event → what to send to the page, or null: shortcuts (except select-all), composition and keys a page has no use for
 *  are left alone — pasting and phone keyboards go through text instead. */
export function keyToInput(e) {
  if (e.isComposing || e.key === 'Unidentified' || e.key === 'Process' || e.key === 'Dead') return null;
  if (e.ctrlKey || e.metaKey) return e.key.toLowerCase() === 'a' ? { t: 'key', key: 'a', code: 'KeyA', ctrl: true } : null;
  if (!NAMED_KEYS.has(e.key) && e.key.length !== 1) return null;
  return { t: 'key', key: e.key, code: e.code || '', shift: !!e.shiftKey, alt: !!e.altKey };
}

/** A finger that barely moved and lifted quickly is a tap (a click); anything else drags the page. */
export function touchIntent(dx, dy, ms) {
  return Math.hypot(dx, dy) < 10 && ms < 450 ? 'tap' : 'scroll';
}

/** Screen pixels dragged over the video → page pixels to scroll (the video is smaller or larger than the page). */
export function scrollDelta(screenPx, rectWidth, picWidth) {
  return Math.round(screenPx * ((picWidth || rectWidth) / (rectWidth || 1)));
}
