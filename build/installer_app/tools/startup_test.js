'use strict';

const assert = require('assert');
const path = require('path');
const { REQUIRED_RENDERER_FILES, requiredStartupFiles, findMissingStartupFiles } = require('../lib/startup');

const appPath = path.resolve('fixture-app.asar');
const resourcesPath = path.resolve('fixture-resources');
const required = requiredStartupFiles(appPath, resourcesPath);
assert(REQUIRED_RENDERER_FILES.includes('index.html'));
assert(REQUIRED_RENDERER_FILES.includes('app.js'));
assert(REQUIRED_RENDERER_FILES.includes('forest-theme.css'));
assert(REQUIRED_RENDERER_FILES.includes('forest-art.svg'));
assert(REQUIRED_RENDERER_FILES.includes('forest_world.js'));
assert(REQUIRED_RENDERER_FILES.includes('forest_game.js'));
assert(required.some((entry) => entry.label === 'payload/main.exe'));
assert(required.some((entry) => entry.label === 'resources/icon.ico'));

const exists = new Set(required.map((entry) => entry.path));
const mockFs = { existsSync: (candidate) => exists.has(candidate) };
assert.deepStrictEqual(findMissingStartupFiles(mockFs, appPath, resourcesPath), []);
exists.delete(path.join(appPath, 'renderer', 'app.js'));
exists.delete(path.join(resourcesPath, 'payload', 'main.exe'));
assert.deepStrictEqual(
  findMissingStartupFiles(mockFs, appPath, resourcesPath),
  ['renderer/app.js', 'payload/main.exe']
);

console.log('PASS startup preflight accepts complete custom UI/runtime package');
console.log('PASS startup preflight names missing UI and worker assets');
