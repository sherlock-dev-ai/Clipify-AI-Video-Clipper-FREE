'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const rendererRoot = path.join(__dirname, '..', 'renderer');
const repositoryRoot = path.resolve(__dirname, '..', '..', '..');
const appSource = fs.readFileSync(path.join(rendererRoot, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(rendererRoot, 'index.html'), 'utf8');
const forestTheme = fs.readFileSync(path.join(rendererRoot, 'forest-theme.css'), 'utf8');
const forestWorld = fs.readFileSync(path.join(rendererRoot, 'forest_world.js'), 'utf8');
const forestArt = fs.readFileSync(path.join(rendererRoot, 'forest-art.svg'), 'utf8');
const mainSource = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8');
const installerSource = fs.readFileSync(path.join(__dirname, '..', 'lib', 'installer.js'), 'utf8');
const productSource = fs.readFileSync(path.join(repositoryRoot, 'app.py'), 'utf8');
const requiredIds = appSource.match(/const requiredIds = \[([\s\S]*?)\];/);
assert(requiredIds, 'UI startup guard must declare its required element IDs');
assert(!requiredIds[1].includes('forest-backdrop'),
  'forest-backdrop is a CSS class, not an element ID');
assert(appSource.includes("document.querySelector('.forest-backdrop')"),
  'UI startup guard must query forest-backdrop by class');
assert(html.includes('<div class="forest-backdrop"'),
  'Installer HTML must include the forest backdrop class');
assert(html.includes('id="forest-art" class="forest-art" src="forest-art.svg"'),
  'Installer HTML must load the detailed woodland artwork');
assert(html.includes('<svg class="forest-orb" viewBox="0 0 40 40"'),
  'The forest sky must use a vector celestial marker');
assert(html.includes('class="forest-orb-sun"') && html.includes('class="forest-orb-moon"'),
  'The sun and moon must be separate shapes, not a circle painted over another');
assert(html.includes('<template id="legacy-weather">') && html.includes('</template>'),
  'The unused mountain weather scene must not be part of the rendered page');
assert(forestArt.includes('<symbol id="fern"') && forestArt.includes('<symbol id="flower"'),
  'The forest artwork must contain reusable detailed plants');
assert(forestArt.includes('class="canopy-sway"') && forestArt.includes('class="leaf-sway'),
  'Canopy branches and foliage must move gently in the wind');
assert(forestArt.includes('@media(prefers-reduced-motion:reduce)'),
  'The illustrated vegetation must respect reduced-motion preferences');
assert(forestArt.includes('id="forestTrail"') && forestArt.includes('fill="url(#forestTrail)"'),
  'The forest trail must use its dedicated subdued perspective fill');
assert(!forestArt.includes('pathClip') && !forestArt.includes('id="pathLight"'),
  'The trail must not use the former oversized textured-road treatment');
assert(forestArt.includes('M788 570') && forestArt.includes('h140'),
  'The forest trail must taper at the horizon and stay contained in the foreground');
assert(forestTheme.includes('body[data-theme="night"] .forest-orb-moon { opacity: 1; }')
  && forestTheme.includes('body[data-theme="night"] .forest-orb-sun { opacity: 0; }'),
  'The night sky must show a clean moon instead of overlaying a cutout on the sun');
assert(/\.forest-orb\s*\{[^}]*top:\s*14%;[^}]*left:\s*63%;/.test(forestTheme),
  'The sun and moon must sit in the open center clearing, not by the right trunk');
assert(!/prefers-reduced-motion:\s*reduce\)\s*\{[^}]*\.forest-world\s*\{\s*display:\s*none/s.test(forestTheme),
  'Reduced-motion preference must not hide the visible forest ambience');
assert(forestWorld.includes('timestamp - this.previousFrame < 100')
  && forestWorld.includes('this.reducedMotion ? 0.4 : 1'),
  'Reduced-motion ambience must be throttled and slowed instead of disabled');
assert(forestTheme.includes('.forest-world { position: absolute; inset: 0; display: block;')
  && !/prefers-reduced-motion:\s*reduce\)\s*\{[^}]*\.forest-world\s*\{[^}]*display:\s*none/s.test(forestTheme),
  'The animation canvas must remain visible with reduced-motion enabled');
assert(!forestWorld.includes('drawHills') && !forestWorld.includes('camera'),
  'The animation layer must not draw or scroll mountain-like background planes');
assert(forestWorld.includes('drawBees(day)') && forestWorld.includes('drawFireflies(this.currentNight)'),
  'The shared animation loop must show bees by day and fireflies at night');
assert(forestWorld.includes('document.hidden') && forestWorld.includes('prefers-reduced-motion: reduce'),
  'The forest animation loop must pause when hidden and honor reduced motion');
assert(html.includes('<div class="install-body" id="install-workspace">'),
  'Install progress and the mini-game must share the install workspace');
assert(html.includes('<div class="install-details-view install-left" id="install-details-view">'),
  'Install details must occupy the left column');
assert(html.includes('<div class="install-right runner-workspace" id="game-workspace">'),
  'The mini-game must occupy the right column beside install details');
assert((html.match(/<button\b[^>]*id="btn-game-toggle"/g) || []).length === 1,
  'The mini-game must have a single Pause/Continue control');
assert(!/id="btn-game-(?:start|restart|jump)"/.test(html),
  'Start, restart, and jump buttons must not appear in the mini-game');
assert(appSource.includes('state.game.start();'),
  'The mini-game must start automatically when the installation screen opens');
assert(appSource.includes("toggle.textContent = canPause ? 'Pause' : 'Continue'"),
  'The single mini-game control must switch between Pause and Continue');
assert(forestTheme.includes('.runner-stage { position: absolute; inset: 0;'),
  'The forest background must fill the complete mini-game area');
assert(/\.runner-card\s*\{[^}]*height:\s*100%;[^}]*flex:\s*1 1 auto;/.test(forestTheme),
  'The mini-game card must stretch to the height of its right-side workspace');
assert(forestTheme.includes('body[data-theme="night"] .forest-art'),
  'The existing night theme must darken the woodland artwork');
assert(forestTheme.includes('background: rgba(16,37,27,.76)'),
  'Installer panels must remain translucent enough to show the forest');
assert(!html.includes('install-mode-switch') && !appSource.includes('setInstallMode'),
  'The mini-game must not replace the install details in a separate mode');
assert(/\.install-body\s*\{[\s\S]*?display:\s*grid;[\s\S]*?grid-template-columns:\s*minmax\(0,\s*\.98fr\)\s+minmax\(0,\s*1\.02fr\)/.test(forestTheme),
  'Install workspace must use a two-column layout for progress and the mini-game');

const guardSource = appSource.match(/function verifyCustomUi\(\) \{[\s\S]*?\n  \}/);
assert(guardSource, 'UI startup guard function was not found');
const buildGuard = new Function('document', 'api', 'window',
  `${guardSource[0]}; return verifyCustomUi;`);
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));
const api = { rendererReady() {}, rendererError() {} };
const uiModules = {
  ClipifyForestGame: { Game() {} },
  clipifyForestWorld: { setTheme() {} },
  ClipifyDownloadWarning: { buildDownloadWarning() {} },
};

function documentWithBackdrop(present) {
  return {
    getElementById(id) { return ids.has(id) ? {} : null; },
    querySelector(selector) {
      return selector === '.forest-backdrop' && present ? {} : null;
    },
  };
}

assert.doesNotThrow(() => buildGuard(documentWithBackdrop(true), api, uiModules)());
assert.throws(
  () => buildGuard(documentWithBackdrop(false), api, uiModules)(),
  /Required custom installer UI elements are missing: forest-backdrop/
);
assert(appSource.includes("typeof window.clipifyForestWorld.setTheme !== 'function'"),
  'The installer must verify that its persistent forest world initialized');
assert(appSource.includes("localStorage.getItem('clipify.installer.theme')"),
  'The selected day/night theme must persist across setup pages and restarts');
assert(appSource.includes("$('overall-percent').textContent = 'Working'"),
  'Indeterminate runtime installs must not leave a misleading frozen percentage');
assert(appSource.includes("data.lastActivityAgoMs"),
  'Mascot idle state must use the installer engine activity timestamp');
assert(mainSource.includes("const PRODUCT_APP_ID = 'dev.sherlock.clipifyai'"),
  'Installed-app shortcut identity must be distinct from the setup identity');
assert(mainSource.includes('appUserModelId: shortcutAppId'),
  'Windows shortcuts must use the identity matching their target application');
assert(installerSource.includes("applicationType: 'product'"),
  'Application shortcuts must identify the installed Clipify AI product');
assert(productSource.includes('SetCurrentProcessExplicitAppUserModelID(PRODUCT_APP_USER_MODEL_ID)'),
  'The installed app must set the same Windows taskbar identity as its shortcuts');

console.log('PASS: startup guard accepts the packaged forest-backdrop class and reports it when absent');
