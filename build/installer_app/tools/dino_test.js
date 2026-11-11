'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const context = new Proxy({}, {
  get(target, key) {
    if (key === 'createLinearGradient') return () => ({ addColorStop() {} });
    if (key in target) return target[key];
    return () => {};
  },
  set(target, key, value) { target[key] = value; return true; },
});
const canvas = {
  width: 520,
  height: 180,
  getContext: () => context,
  getBoundingClientRect: () => ({ width: 520, height: 180 }),
  addEventListener() {},
};
const windowStub = {
  devicePixelRatio: 1,
  addEventListener() {},
  requestAnimationFrame: () => 1,
  cancelAnimationFrame() {},
};
const documentStub = { body: { dataset: { weather: 'morning' } } };
const mathStub = Object.create(Math);
mathStub.random = () => 0.1;
const sandbox = {
  window: windowStub,
  document: documentStub,
  localStorage: { getItem: () => null, setItem() {} },
  Math: mathStub,
};
const source = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'dino.js'), 'utf8');
vm.runInNewContext(source, sandbox, { filename: 'dino.js' });
const Runner = windowStub.ClipifyRunner.Runner;
const runner = new Runner(canvas, { textContent: '' }, { textContent: '' });
runner.running = true;

runner.doJump();
assert.strictEqual(runner.player.jumpsUsed, 1, 'first jump should launch from the ground');
runner.doJump();
assert.strictEqual(runner.player.jumpsUsed, 2, 'second press in the air should bundle/double jump');
const secondJumpVelocity = runner.player.vy;
runner.doJump();
assert.strictEqual(runner.player.jumpsUsed, 2, 'a third in-air jump must not be granted');
assert.strictEqual(runner.player.vy, secondJumpVelocity, 'third press must not change trajectory');

runner.player.y = 148 - runner.player.h;
runner.player.vy = 30;
runner.player.grounded = false;
runner.player.jumpsUsed = 2;
runner.spawnIn = 10000;
runner.update(16.67);
assert.strictEqual(runner.player.grounded, true);
assert.strictEqual(runner.player.jumpsUsed, 0, 'landing should refresh the double-jump allowance');

runner.player.y = 148 - runner.player.h;
runner.player.vy = 0;
runner.player.grounded = true;
runner.player.jumpsUsed = 0;
runner.obstacles = [];
runner.speed = 8.6;
runner.score = 30000;
runner.spawnIn = 0;
runner.update(16.67);
const firstHazard = runner.obstacles[0];
assert(firstHazard && ['bee', 'bush', 'rock'].includes(firstHazard.kind));
let secondHazard = null;
for (let frame = 0; frame < 90 && !secondHazard; frame += 1) {
  runner.update(16.67);
  secondHazard = runner.obstacles.find((obstacle) => obstacle !== firstHazard) || null;
}
assert(secondHazard, 'a later obstacle should spawn');
assert(Math.abs(secondHazard.x - firstHazard.x) >= 500,
  'speed-scaled spawn gap should prevent an impossible stacked hazard pair');

console.log('PASS double jump, landing reset, explicit bee, and speed-scaled hazard separation');
