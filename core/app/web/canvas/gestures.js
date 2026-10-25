// Hand gestures for the 3D canvas (Blueprint v4 Fase 4.0, ADR-049). Runs entirely on the device: MediaPipe finds 21
// landmarks per hand in the browser, this file turns them into NAVIGATION events. Frames are never stored or sent.
// Gestures can only point, select, move, zoom, scroll and pause — never approve, delete, send or pay.
//
//   telapak terbuka ditahan ±1 dtk  aktifkan / kunci mode gestur      satu jari menunjuk   kursor
//   cubit (jempol+telunjuk)         klik; tahan lalu geser = seret     dua tangan mencubit  zoom
//   telapak terbuka digeser         gulir / geser pandangan            kepalan              jeda
//
// The pure parts (classify, GestureMachine) are unit-tested with node (core/tests/test_canvas_js.py).

const WRIST = 0, THUMB_TIP = 4, INDEX_PIP = 6, INDEX_TIP = 8, MIDDLE_MCP = 9, MIDDLE_PIP = 10, MIDDLE_TIP = 12,
  RING_PIP = 14, RING_TIP = 16, PINKY_PIP = 18, PINKY_TIP = 20;

export const TUNING = {
  pinchIn: 0.32,        // thumb–index distance / hand size below this = pinch (hysteresis: out above pinchOut)
  pinchOut: 0.45,
  stableFrames: 3,      // a pose must hold this many frames before it acts (false triggers)
  holdMs: 1000,         // open palm held still this long toggles the gesture lock
  stillPx: 0.035,       // "still" = palm centre moved less than this (normalised) during the hold
  clickMs: 350,         // a pinch released within this, without moving, is a click
  clickMove: 0.03,
  smoothing: 0.45,      // cursor EMA
  idleOffMs: 60000,     // no hand for a minute → the lock turns itself off
  scrollGain: 2.2,
};

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/** Which fingers are extended, and how pinched — from one hand's 21 landmarks (normalised image coords). Pure. */
export function features(lm) {
  const size = dist(lm[WRIST], lm[MIDDLE_MCP]) || 1e-6;
  const ext = (tip, pip) => dist(lm[tip], lm[WRIST]) > dist(lm[pip], lm[WRIST]) * 1.1;
  return {
    size,
    index: ext(INDEX_TIP, INDEX_PIP), middle: ext(MIDDLE_TIP, MIDDLE_PIP), ring: ext(RING_TIP, RING_PIP), pinky: ext(PINKY_TIP, PINKY_PIP),
    pinch: dist(lm[THUMB_TIP], lm[INDEX_TIP]) / size,
    tip: { x: lm[INDEX_TIP].x, y: lm[INDEX_TIP].y },
    pinchPoint: { x: (lm[THUMB_TIP].x + lm[INDEX_TIP].x) / 2, y: (lm[THUMB_TIP].y + lm[INDEX_TIP].y) / 2 },
    palm: { x: (lm[WRIST].x + lm[MIDDLE_MCP].x) / 2, y: (lm[WRIST].y + lm[MIDDLE_MCP].y) / 2 },
  };
}

/** 'pinch' | 'point' | 'palm' | 'fist' | 'other'. wasPinching gives the pinch its hysteresis. Pure. */
export function classify(lm, wasPinching = false) {
  const f = features(lm);
  if (f.pinch < (wasPinching ? TUNING.pinchOut : TUNING.pinchIn)) return 'pinch';
  const n = [f.index, f.middle, f.ring, f.pinky].filter(Boolean).length;
  if (n === 4) return 'palm';
  if (f.index && n === 1) return 'point';
  if (n === 0) return 'fist';
  return 'other';
}

/**
 * Frames in, navigation events out. step({t, hands: [landmarks21, ...]}) → [{type, ...}].
 * Coordinates out are normalised 0..1 of the view, mirrored (the camera faces the user). Pure apart from its own state.
 */
export class GestureMachine {
  constructor(tuning = {}) {
    this.k = { ...TUNING, ...tuning };
    this.active = false;
    this.paused = false;
    this.cursor = null;
    this.pose = [];          // per hand: {pose, frames}
    this.pressed = null;     // {t, x, y, moved}
    this.hold = null;        // {t, x, y}
    this.lastHand = 0;
    this.zoomDist = null;
    this.lastPalm = null;
  }

  _stable(i, pose) {
    const p = this.pose[i] || { pose: null, frames: 0 };
    this.pose[i] = p.pose === pose ? { pose, frames: p.frames + 1 } : { pose, frames: 1 };
    return this.pose[i].frames >= this.k.stableFrames ? pose : null;   // a pose acts only once it held
  }

  step({ t, hands }) {
    const out = [];
    const k = this.k;
    if (!hands || hands.length === 0) {
      this.pose = [];
      this.hold = null;
      this.zoomDist = null;
      this.lastPalm = null;
      if (this.pressed) { out.push({ type: 'release' }); this.pressed = null; }
      if (this.active && this.lastHand && t - this.lastHand > k.idleOffMs) {
        this.active = false;
        out.push({ type: 'lock', active: false, reason: 'idle' });
      }
      return out;
    }
    this.lastHand = t;
    const poses = hands.map((lm, i) => {
      const was = this.pose[i] && this.pose[i].pose === 'pinch';
      return this._stable(i, classify(lm, was));
    });
    const feats = hands.map(features);
    const mirror = (p) => ({ x: 1 - p.x, y: p.y });

    // open palm held still → toggle the lock (works whether active or not; it is the only way in)
    if (hands.length === 1 && poses[0] === 'palm') {
      const c = feats[0].palm;
      if (!this.hold) this.hold = { t, x: c.x, y: c.y, fired: false };
      const still = Math.hypot(c.x - this.hold.x, c.y - this.hold.y) < k.stillPx;
      if (!still) this.hold = { t, x: c.x, y: c.y, fired: false };
      else if (!this.hold.fired && t - this.hold.t >= k.holdMs) {
        this.hold.fired = true;
        this.active = !this.active || this.paused;
        this.paused = false;
        out.push({ type: 'lock', active: this.active });
        return out;
      }
    } else {
      this.hold = null;
    }
    if (!this.active || this.paused) return out;

    // fist → pause (until the palm hold again)
    if (poses.every((p) => p === 'fist')) {
      this.paused = true;
      if (this.pressed) { out.push({ type: 'release' }); this.pressed = null; }
      out.push({ type: 'pause' });
      return out;
    }

    // two hands pinching → zoom by how their distance changes
    if (hands.length === 2 && poses[0] === 'pinch' && poses[1] === 'pinch') {
      const d = dist(feats[0].pinchPoint, feats[1].pinchPoint);
      if (this.zoomDist) out.push({ type: 'zoom', factor: d / this.zoomDist });
      this.zoomDist = d;
      return out;
    }
    this.zoomDist = null;

    const i = poses.findIndex((p) => p === 'pinch' || p === 'point' || p === 'palm');
    if (i < 0) return out;
    const pose = poses[i];
    const f = feats[i];
    if (pose === 'palm') {   // moving open palm → scroll
      const c = f.palm;
      if (this.lastPalm) out.push({ type: 'scroll', dx: -(c.x - this.lastPalm.x) * k.scrollGain, dy: (c.y - this.lastPalm.y) * k.scrollGain });
      this.lastPalm = c;
      return out;
    }
    this.lastPalm = null;
    const raw = mirror(pose === 'pinch' ? f.pinchPoint : f.tip);
    this.cursor = this.cursor ? { x: this.cursor.x + (raw.x - this.cursor.x) * k.smoothing, y: this.cursor.y + (raw.y - this.cursor.y) * k.smoothing } : raw;
    out.push({ type: 'cursor', x: this.cursor.x, y: this.cursor.y });
    if (pose === 'pinch' && !this.pressed) {
      this.pressed = { t, x: this.cursor.x, y: this.cursor.y, moved: false };
      out.push({ type: 'press', x: this.cursor.x, y: this.cursor.y });
    } else if (pose === 'pinch' && this.pressed) {
      if (Math.hypot(this.cursor.x - this.pressed.x, this.cursor.y - this.pressed.y) > k.clickMove) this.pressed.moved = true;
      if (this.pressed.moved) out.push({ type: 'drag', x: this.cursor.x, y: this.cursor.y });
    } else if (pose !== 'pinch' && this.pressed) {
      const quick = t - this.pressed.t <= k.clickMs && !this.pressed.moved;
      out.push({ type: 'release' });
      if (quick) out.push({ type: 'click', x: this.cursor.x, y: this.cursor.y });
      this.pressed = null;
    }
    return out;
  }
}

/**
 * Camera + MediaPipe → GestureMachine → onEvent. Returns {stop(), stats}. Browser only.
 * The camera runs only while this is on; nothing of the video leaves the page.
 */
export async function startHandTracking(video, onEvent, onStats = () => {}) {
  const base = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14';
  const { FilesetResolver, HandLandmarker } = await import(`${base}/vision_bundle.mjs`);
  const fileset = await FilesetResolver.forVisionTasks(`${base}/wasm`);
  const options = (delegate) => ({
    baseOptions: { modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task', delegate },
    runningMode: 'VIDEO', numHands: 2, minHandDetectionConfidence: 0.6, minTrackingConfidence: 0.5,
  });
  let landmarker;
  try { landmarker = await HandLandmarker.createFromOptions(fileset, options('GPU')); }
  catch { landmarker = await HandLandmarker.createFromOptions(fileset, options('CPU')); }
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: 640, height: 480 }, audio: false });
  video.srcObject = stream;
  await video.play();
  const machine = new GestureMachine();
  const stats = { fps: 0, latencyMs: 0, frames: 0, events: 0 };
  let running = true, lastVideoTime = -1, lastFpsT = performance.now(), fpsFrames = 0;
  const loop = () => {
    if (!running) return;
    if (video.currentTime !== lastVideoTime) {
      lastVideoTime = video.currentTime;
      const t0 = performance.now();
      const res = landmarker.detectForVideo(video, t0);
      const events = machine.step({ t: t0, hands: res.landmarks || [] });
      for (const e of events) onEvent(e, machine);
      const ms = performance.now() - t0;             // camera frame in hand → event out (model + classifier)
      stats.latencyMs = stats.latencyMs ? stats.latencyMs * 0.9 + ms * 0.1 : ms;
      stats.frames++; fpsFrames++; stats.events += events.length;
      if (t0 - lastFpsT > 1000) { stats.fps = fpsFrames * 1000 / (t0 - lastFpsT); fpsFrames = 0; lastFpsT = t0; onStats(stats, machine, res.landmarks || []); }
    }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  return {
    stats, machine,
    stop() {
      running = false;
      stream.getTracks().forEach((tr) => tr.stop());
      video.srcObject = null;
      landmarker.close();
    },
  };
}
