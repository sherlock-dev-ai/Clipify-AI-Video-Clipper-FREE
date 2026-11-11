'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const asar = require('@electron/asar');

const [packageRootArg, sourceRootArg, qaSlugArg = ''] = process.argv.slice(2);
if (!packageRootArg || !sourceRootArg) {
  throw new Error('Usage: node verify_packaged_ui.js <win-unpacked> <installer-app-source> [qa-install-slug]');
}

const packageRoot = path.resolve(packageRootArg);
const sourceRoot = path.resolve(sourceRootArg);
const resourcesRoot = path.join(packageRoot, 'resources');
const archivePath = path.join(resourcesRoot, 'app.asar');
if (!fs.existsSync(archivePath)) throw new Error(`Packaged Electron archive is missing: ${archivePath}`);

const archiveFiles = new Set(asar.listPackage(archivePath).map((name) =>
  String(name).replace(/\\/g, '/').replace(/^\/+/, '')
));
const rendererFiles = [
  'index.html', 'style.css', 'forest-theme.css', 'forest-art.svg', 'forest_world.js', 'forest_game.js', 'app.js',
  'download_warning.js', 'logo-round.png', 'logo.png',
];
const appFiles = [
  'main.js', 'preload.js',
  'lib/startup.js', 'lib/detect.js', 'lib/installer.js',
  'lib/filesystem.js', 'lib/uninstall.js', 'lib/music.js',
  ...rendererFiles.map((name) => `renderer/${name}`),
];

for (const file of appFiles) {
  assert(archiveFiles.has(file), `Custom UI package is missing app.asar entry: ${file}`);
  const packaged = asar.extractFile(archivePath, file);
  const sourcePath = path.join(sourceRoot, file);
  assert(fs.existsSync(sourcePath), `Source counterpart is missing: ${sourcePath}`);
  assert(packaged.equals(fs.readFileSync(sourcePath)), `Packaged file differs from current source: ${file}`);
}

const approvedIcon = path.resolve(sourceRoot, '..', '..', 'icon.png');
assert(fs.existsSync(approvedIcon), 'Approved Clipify AI icon is missing: ' + approvedIcon);
for (const name of ['logo.png', 'logo-round.png']) {
  assert(asar.extractFile(archivePath, 'renderer/' + name).equals(fs.readFileSync(approvedIcon)),
    'Packaged installer brand mark is not the approved icon: ' + name);
}
const packagedIcon = path.join(resourcesRoot, 'icon.ico');
assert(fs.readFileSync(packagedIcon).equals(fs.readFileSync(path.join(sourceRoot, 'build', 'icon.ico'))),
  'Packaged Windows icon differs from current source icon');

const metadata = JSON.parse(asar.extractFile(archivePath, 'package.json').toString('utf8'));
const sourceMetadata = JSON.parse(fs.readFileSync(path.join(sourceRoot, 'package.json'), 'utf8'));
for (const key of ['name', 'productName', 'version', 'main']) {
  assert.strictEqual(metadata[key], sourceMetadata[key], `Packaged application metadata differs at ${key}`);
}
if (qaSlugArg) {
  assert.strictEqual(metadata.clipifyQaInstallSlug, qaSlugArg,
    'QA package is missing its build-specific isolated app target');
}

const requiredResources = [
  'catalog.json', 'icon.ico', 'payload/Clipify AI.exe', 'payload/main.exe',
  'payload/python311.dll',
];
for (const file of requiredResources) {
  const target = path.join(resourcesRoot, ...file.split('/'));
  assert(fs.existsSync(target), `Packaged Electron resources are missing: ${file}`);
}
assert(!fs.existsSync(path.join(resourcesRoot, 'payload', 'narrate clips')),
  'Packaged payload contains user-provided narration footage');

const html = asar.extractFile(archivePath, 'renderer/index.html').toString('utf8');
assert(html.includes('<div class="forest-backdrop"'),
  'Custom installer HTML is missing the forest backdrop class');
assert(html.includes('id="forest-art" class="forest-art" src="forest-art.svg"'),
  'Custom installer HTML is missing the layered woodland artwork');
const rendererApp = asar.extractFile(archivePath, 'renderer/app.js').toString('utf8');
const requiredIdsMatch = rendererApp.match(/const requiredIds = \[([\s\S]*?)\];/);
assert(requiredIdsMatch && !requiredIdsMatch[1].includes('forest-backdrop'),
  'Forest backdrop is a CSS class and must not be checked as an element ID');
assert(rendererApp.includes("document.querySelector('.forest-backdrop')"),
  'Custom UI startup must verify the forest backdrop by its CSS class');
for (const effect of ['forest_world.js', 'forest_game.js', 'download_warning.js', 'app.js']) {
  assert(html.includes(`src="${effect}"`), `Custom installer HTML does not load ${effect}`);
}
const modelScreen = /data-screen="models"/.test(html) && /id="model-grid"/.test(html);
assert(modelScreen, 'Custom model-selection screen is missing from the packaged HTML');
assert((html.match(/class="step" data-step=/g) || []).length === 5, 'The five-stage setup rail is incomplete');
assert(html.includes('id="forest-game"'), 'The optional forest game is missing from the packaged HTML');
assert(html.includes('id="forest-world"'), 'The persistent forest canvas is missing from the packaged HTML');
assert(html.includes('<template id="legacy-weather">'),
  'The old mountain weather scene must remain inert and outside the rendered installer');
assert(html.includes('id="install-workspace"') && html.includes('id="game-workspace"'),
  'The install details and right-side mini-game workspace are missing');
assert(html.indexOf('id="install-details-view"') < html.indexOf('id="game-workspace"'),
  'The mini-game must appear beside, not instead of, install details');
assert(!html.includes('install-mode-switch'),
  'The install view must not switch between details and the mini-game');
assert((html.match(/<button\b[^>]*id="btn-game-toggle"/g) || []).length === 1,
  'The packaged mini-game must have one Pause/Continue control');
assert(!/id="btn-game-(?:start|restart|jump)"/.test(html),
  'The packaged mini-game must not have Start, Restart, or Jump buttons');
assert((html.match(/<button\b[^>]*id="btn-game-toggle"/g) || []).length === 1,
  'The packaged mini-game must have one Pause/Continue control');
assert(!/id="btn-game-(?:start|restart|jump)"/.test(html),
  'The packaged mini-game must not have Start, Restart, or Jump buttons');
const mainSource = asar.extractFile(archivePath, 'main.js').toString('utf8');
assert(mainSource.includes('app.setAppUserModelId(WINDOWS_APP_ID)'), 'Windows taskbar app identity is not assigned');
assert(mainSource.includes('mainWindow.setAppDetails({ appId: WINDOWS_APP_ID'), 'Window taskbar details are not assigned');
assert(mainSource.includes('appUserModelId: shortcutAppId') && mainSource.includes("const PRODUCT_APP_ID = 'dev.sherlock.clipifyai'"),
  'Windows shortcuts do not receive the matching installed-app identity');

console.log(JSON.stringify({
  result: 'PASS',
  archivePath,
  appAsarEntries: appFiles.length,
  rendererAssets: rendererFiles,
  qaInstallSlug: metadata.clipifyQaInstallSlug || null,
  verifiedResources: requiredResources,
}, null, 2));
