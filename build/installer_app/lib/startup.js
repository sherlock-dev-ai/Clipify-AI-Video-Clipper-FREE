'use strict';

const path = require('path');

const REQUIRED_RENDERER_FILES = [
  'index.html',
  'style.css',
  'forest-theme.css',
  'forest-art.svg',
  'app.js',
  'forest_world.js',
  'forest_game.js',
  'download_warning.js',
  'logo-round.png',
  'logo.png',
];

function requiredStartupFiles(appPath, resourcesPath) {
  return [
    ...REQUIRED_RENDERER_FILES.map((name) => ({
      label: `renderer/${name}`,
      path: path.join(appPath, 'renderer', name),
    })),
    { label: 'resources/catalog.json', path: path.join(resourcesPath, 'catalog.json') },
    { label: 'resources/icon.ico', path: path.join(resourcesPath, 'icon.ico') },
    { label: 'payload/Clipify AI.exe', path: path.join(resourcesPath, 'payload', 'Clipify AI.exe') },
    { label: 'payload/main.exe', path: path.join(resourcesPath, 'payload', 'main.exe') },
  ];
}

function findMissingStartupFiles(fs, appPath, resourcesPath) {
  return requiredStartupFiles(appPath, resourcesPath)
    .filter((entry) => !fs.existsSync(entry.path))
    .map((entry) => entry.label);
}

module.exports = { REQUIRED_RENDERER_FILES, requiredStartupFiles, findMissingStartupFiles };
