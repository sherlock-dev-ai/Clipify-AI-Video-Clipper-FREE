'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const listeners = new Map();
const frameCallbacks = new Map();
let nextFrameId = 1;
const context = new Proxy({
  createLinearGradient() { return { addColorStop() {} }; },
  createRadialGradient() { return { addColorStop() {} }; },
}, {
  get(target, key) { return key in target ? target[key] : () => {}; },
  set(target, key, value) { target[key] = value; return true; },
});
const documentStub = { body: { dataset: { theme: 'forest' } }, activeElement: null };
const windowStub = {
  devicePixelRatio: 1,
  addEventListener(name, fn) { listeners.set(`window:${name}`, fn); },
  removeEventListener(name) { listeners.delete(`window:${name}`); },
};
const canvas = {
  width: 880,
  height: 270,
  getContext: () => context,
  getBoundingClientRect: () => ({ width: 880, height: 270 }),
  addEventListener(name, fn) { listeners.set(`canvas:${name}`, fn); },
  removeEventListener(name) { listeners.delete(`canvas:${name}`); },
  focus() { documentStub.activeElement = this; },
};
const sandbox = {
  window: windowStub,
  document: documentStub,
  localStorage: { getItem: () => '0', setItem() {} },
  requestAnimationFrame(callback) {
    const id = nextFrameId++;
    frameCallbacks.set(id, callback);
    return id;
  },
  cancelAnimationFrame(id) { frameCallbacks.delete(id); },
  Math,
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'renderer', 'forest_game.js'), 'utf8'), sandbox,
  { filename: 'forest_game.js' });

const labels = [];
const game = new windowStub.ClipifyForestGame.Game(
  canvas, { textContent: '' }, { textContent: '' }, { textContent: '', dataset: {} },
  (state) => labels.push(state),
);
assert.strictEqual(game.state, 'ready');
game.setVisible(true);
game.start();
assert.strictEqual(game.state, 'playing');
assert.strictEqual(game.jump(), true, 'grounded player should jump');
assert.strictEqual(game.jump(), false, 'player cannot gain repeated mid-air jumps');
game.spawnIn = 100;
for (let frame = 0; frame < 90; frame += 1) game.update(1 / 60);
assert.strictEqual(game.player.grounded, true, 'gravity should return the player to the ground');

const hazardTypes = new Set();
game.elapsed = 20;
for (let index = 0; index < 70; index += 1) {
  game.spawnObstacle();
  hazardTypes.add(game.obstacles.at(-1).type);
}
for (const type of ['log', 'roots', 'rocks', 'thorns', 'branch', 'trap']) {
  assert(hazardTypes.has(type), `expected a generated ${type} hazard`);
}

game.obstacles = [{ type: 'trap', x: game.player.x + 15, width: 74, height: 24 }];
game.player.grounded = true;
assert.strictEqual(game.hasCollision(), true, 'a grounded player should collide with a floor trap');
assert.strictEqual(game.jump(), true);
game.update(0.05);
assert.strictEqual(game.hasCollision(), false, 'a jump should clear the trap collision window');

game.obstacles = [{ type: 'log', x: game.player.x + 12, width: 60, height: 24 }];
game.player.grounded = true;
game.player.bottom = game.groundY;
game.player.velocityY = 0;
game.update(0.01);
assert.strictEqual(game.state, 'gameover', 'overlapping a fallen log should end the run');
assert(labels.includes('gameover'));
game.restart();
assert.strictEqual(game.state, 'playing', 'restart should start a clean new run');
assert.strictEqual(game.score, 0);
game.pause();
assert.strictEqual(game.state, 'paused');
game.resume();
assert.strictEqual(game.state, 'playing');
game.setVisible(false);
assert.strictEqual(game.state, 'paused', 'leaving the game panel should preserve the run safely');
game.destroy();

console.log('PASS runner states, grounded jump, gravity, six hazard types, trap dodge, collision, restart, and pause');
