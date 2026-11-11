'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const callbacks = new Map();
const listeners = new Map();
const motionListeners = new Map();
let nextId = 1;
let motionMatches = false;
const gradient = { addColorStop() {} };
const context = new Proxy({
  createLinearGradient: () => gradient,
  createRadialGradient: () => gradient,
}, {
  get(target, key) { return key in target ? target[key] : () => {}; },
  set(target, key, value) { target[key] = value; return true; },
});
const canvas = {
  width: 1, height: 1,
  getContext: () => context,
  getBoundingClientRect: () => ({ width: 1280, height: 720 }),
};
const windowStub = {
  devicePixelRatio: 1,
  addEventListener(name, fn) { listeners.set(`window:${name}`, fn); },
  removeEventListener(name) { listeners.delete(`window:${name}`); },
  matchMedia() {
    return {
      matches: motionMatches,
      addEventListener(name, fn) { motionListeners.set(name, fn); },
      removeEventListener(name) { motionListeners.delete(name); },
    };
  },
};
const documentStub = {
  body: { dataset: { theme: 'forest' } },
  hidden: false,
  readyState: 'loading',
  addEventListener(name, fn) { listeners.set(`document:${name}`, fn); },
  removeEventListener(name) { listeners.delete(`document:${name}`); },
};
const sandbox = {
  window: windowStub,
  document: documentStub,
  requestAnimationFrame(callback) { const id = nextId++; callbacks.set(id, callback); return id; },
  cancelAnimationFrame(id) { callbacks.delete(id); },
  Math,
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'renderer', 'forest_world.js'), 'utf8'), sandbox,
  { filename: 'forest_world.js' });
const World = windowStub.ClipifyForestWorldApi.World;
const world = new World(canvas);
function runFrame(time) {
  const callback = callbacks.get(world.frameId);
  assert(callback, 'one animation frame should be queued while visible');
  callbacks.delete(world.frameId);
  callback(time);
}

assert(world.drawnFrames > 0, 'scene should draw immediately');
assert(world.lastParticleCounts.leaves >= 20, 'falling leaves should be visible in both themes');
assert.strictEqual(world.lastParticleCounts.bees, 4, 'daytime bees should be present');
assert.strictEqual(world.lastParticleCounts.fireflies, 0, 'fireflies should be absent during the day');
const leafY = world.leaves[0].y;
runFrame(1000);
assert(world.clock > 0, 'the shared animation clock should advance');
assert.notStrictEqual(world.leaves[0].y, leafY, 'leaves should fall rather than scrolling the whole forest');
const frameCount = world.drawnFrames;
const queuedFrame = world.frameId;
world.schedule();
assert.strictEqual(world.frameId, queuedFrame, 'theme and navigation must not create duplicate animation loops');
world.setTheme(true);
assert.strictEqual(world.targetNight, 1);
for (let time = 1050; time < 2600; time += 50) runFrame(time);
assert(world.currentNight > 0.8, 'night transition should reach the night palette smoothly');
assert(world.drawnFrames > frameCount, 'the same loop should redraw during a theme transition');
assert.strictEqual(world.lastParticleCounts.bees, 0, 'daytime bees should disappear at night');
assert.strictEqual(world.lastParticleCounts.fireflies, 14, 'nighttime fireflies should appear');
world.setTheme(false);
for (let time = 2650; time < 4200; time += 50) runFrame(time);
assert(world.currentNight < 0.2, 'day transition should return to the daylight palette');
documentStub.hidden = true;
listeners.get('document:visibilitychange')();
assert.strictEqual(world.frameId, 0, 'the animation loop should stop when its window is hidden');
documentStub.hidden = false;
listeners.get('document:visibilitychange')();
assert(world.frameId > 0, 'the animation loop should resume when its window returns');
world.destroy();
assert.strictEqual(listeners.has('window:resize'), false, 'destroy should release resize listener');
assert.strictEqual(motionListeners.has('change'), false, 'destroy should release motion-preference listener');

motionMatches = true;
const staticWorld = new World(canvas);
assert(staticWorld.frameId > 0, 'reduced-motion mode should keep a throttled ambience frame');
const staticLeafY = staticWorld.leaves[0].y;
function runStaticFrame(time) {
  const callback = callbacks.get(staticWorld.frameId);
  assert(callback, 'reduced-motion ambience should keep one frame queued');
  callbacks.delete(staticWorld.frameId);
  callback(time);
}
runStaticFrame(1000);
const firstReducedFrameCount = staticWorld.drawnFrames;
runStaticFrame(1050);
assert.strictEqual(staticWorld.drawnFrames, firstReducedFrameCount,
  'reduced-motion ambience should throttle redraws instead of running at full speed');
runStaticFrame(1100);
assert.notStrictEqual(staticWorld.leaves[0].y, staticLeafY,
  'reduced-motion mode should retain gentle ambient movement');
staticWorld.setTheme(true);
assert.strictEqual(staticWorld.currentNight, 1, 'reduced-motion theme changes should remain immediate');
staticWorld.destroy();

console.log('PASS forest particles, day/night wildlife, reduced-motion lifecycle, and listener cleanup');
