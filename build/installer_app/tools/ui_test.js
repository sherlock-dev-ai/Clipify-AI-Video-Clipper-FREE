/**
 * Real UI test driver for the Clipify AI installer.
 *
 * Electron is launched with --remote-debugging-port, so this talks the Chrome
 * DevTools Protocol directly over the WebSocket that Node 22+ provides natively.
 * That means no Selenium/Playwright dependency and, more importantly, it drives
 * the *actual* renderer: real clicks on real buttons, real IPC into the real
 * main process.
 *
 * Usage:
 *   node tools/ui_test.js <scenario>
 *
 * Scenarios:
 *   flow        click the whole path: welcome -> models -> location -> install
 *   screens     report which screens exist and that Get Started actually works
 *   game        verify the dino loop advances and Space jumps
 *   cancel      start an install, then cancel it and check state
 *   space       drive insufficient-disk-space handling
 */

const SCREEN = process.env.CDP_URL || 'http://127.0.0.1:9333';

function log(...args) {
  console.log(...args);
}

async function fetchJson(path) {
  const res = await fetch(`${SCREEN}${path}`);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

/** Minimal CDP client over the native WebSocket. */
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener('message', (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result);
      }
    });
  }

  static async attach() {
    const targets = await fetchJson('/json/list');
    const page = targets.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
    if (!page) throw new Error('no page target found');
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', reject, { once: true });
    });
    return new Cdp(ws);
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(
        `eval failed: ${result.exceptionDetails.exception?.description ||
          result.exceptionDetails.text}`
      );
    }
    return result.result.value;
  }

  async waitFor(expression, { timeout = 20000, interval = 200, label = expression } = {}) {
    const deadline = Date.now() + timeout;
    for (;;) {
      let value = false;
      try {
        value = await this.eval(`!!(${expression})`);
      } catch {
        value = false;
      }
      if (value) return true;
      if (Date.now() > deadline) throw new Error(`timeout waiting for: ${label}`);
      await new Promise((r) => setTimeout(r, interval));
    }
  }

  async click(selector) {
    const ok = await this.eval(
      `(() => { const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return false; el.click(); return true; })()`
    );
    if (!ok) throw new Error(`click target not found: ${selector}`);
  }

  async text(selector) {
    return this.eval(
      `(() => { const el = document.querySelector(${JSON.stringify(selector)});
        return el ? el.textContent.trim() : null; })()`
    );
  }

  async visible(selector) {
    return this.eval(
      `(() => { const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return false; const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0; })()`
    );
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const scenario = process.argv[2] || 'flow';
  const cdp = await Cdp.attach();
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable');

  // Surface renderer console errors: a silent exception in a click handler is
  // exactly the kind of bug this harness exists to catch.
  const consoleErrors = [];
  cdp.ws.addEventListener('message', (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
        consoleErrors.push(message.params.entry.text);
      }
      if (
        message.method === 'Runtime.exceptionThrown' &&
        message.params.exceptionDetails
      ) {
        consoleErrors.push(
          message.params.exceptionDetails.exception?.description ||
            message.params.exceptionDetails.text
        );
      }
    } catch {
      /* ignore */
    }
  });

  log(`[ui] attached, scenario=${scenario}`);

  if (scenario === 'screens') {
    const screens = await cdp.eval(
      `[...document.querySelectorAll('.screen')].map(s => s.dataset.screen + ':' + (s.hidden ? 'hidden' : 'visible'))`
    );
    log('[ui] screens:', screens.join(', '));
    log('[ui] welcome detect text:', await cdp.text('#welcome-detect'));
    await cdp.click('[data-test="get-started"]');
    await sleep(600);
    const modelsVisible = await cdp.visible('#screen-models');
    log('[ui] Get Started -> models screen visible:', modelsVisible);
    const cards = await cdp.eval(`document.querySelectorAll('.model-card').length`);
    log('[ui] model cards rendered:', cards);
    const ollama = await cdp.text('#ollama-title');
    log('[ui] ollama banner:', ollama, '|', await cdp.text('#ollama-detail'));
  }

  if (scenario === 'game') {
    await cdp.eval(`document.getElementById('btn-get-started').click()`);
    await sleep(400);
    await cdp.eval(`document.getElementById('btn-models-continue').click()`);
    await sleep(400);
    await cdp.eval(`document.getElementById('btn-install').click()`);
    await cdp.waitFor(`!document.getElementById('download-warning').hidden`, {
      label: 'install warning before setup',
    });
    await cdp.eval(`document.getElementById('btn-warn-go').click()`);
    await sleep(2500);
    const before = await cdp.eval(`document.getElementById('game-score').textContent`);
    const hasCanvas = await cdp.eval(`!!document.getElementById('forest-game')`);
    log('[ui] canvas present:', hasCanvas);
    const initialButtons = await cdp.eval(
      `[...document.querySelectorAll('#game-workspace button')].map(button => button.textContent.trim())`
    );
    log('[ui] only game control:', initialButtons.join(', '));
    await cdp.click('#btn-game-toggle');
    const pausedLabel = await cdp.text('#btn-game-toggle');
    log('[ui] pause changes control to Continue:', pausedLabel === 'Continue');
    await cdp.click('#btn-game-toggle');
    await sleep(1500);
    const after = await cdp.eval(`document.getElementById('game-score').textContent`);
    const continuedLabel = await cdp.text('#btn-game-toggle');
    log(`[ui] score ${before} -> ${after} after continue (loop running: ${before !== after})`);
    log('[ui] continue changes control to Pause:', continuedLabel === 'Pause');
    const canvas = await cdp.eval(`(() => {
      const rect = document.getElementById('forest-game').getBoundingClientRect();
      const panel = document.getElementById('game-workspace').getBoundingClientRect();
      return { canvas: { width: rect.width, height: rect.height }, panel: { width: panel.width, height: panel.height } };
    })()`);
    log('[ui] forest fills game panel:', JSON.stringify(canvas));
  }

  if (scenario === 'flow') {
    log('[ui] step 1: welcome');
    await cdp.waitFor(`document.getElementById('welcome-detect').textContent.indexOf('Ready to install') >= 0 ||
                       document.getElementById('welcome-detect').textContent.indexOf('missing') >= 0`,
      { label: 'welcome detection to finish' });
    log('   ', await cdp.text('#welcome-detect'));

    log('[ui] step 2: Get Started');
    await cdp.click('[data-test="get-started"]');
    await cdp.waitFor(`!document.getElementById('screen-models').hidden`, { label: 'models screen' });
    const cards = await cdp.eval(`[...document.querySelectorAll('.model-card')].map(c => c.dataset.model)`);
    log('    models:', cards.join(', '));
    log('    summary:', await cdp.text('#model-summary'));

    log('[ui] step 3: toggle two models off/on to prove selection is honoured');
    await cdp.click('[data-test="model-qwen3:8b"]');
    await sleep(250);
    log('    after unchecking qwen3:8b ->', await cdp.text('#model-summary'));
    await cdp.click('[data-test="model-qwen3:4b"]');
    await sleep(250);
    log('    after checking qwen3:4b    ->', await cdp.text('#model-summary'));

    log('[ui] step 4: Continue to location');
    await cdp.click('[data-test="models-continue"]');
    await cdp.waitFor(`!document.getElementById('screen-location').hidden`, { label: 'location screen' });
    log('    path     :', await cdp.eval(`document.getElementById('input-path').value`));
    log('    required :', await cdp.text('#space-required'));
    log('    available:', await cdp.text('#space-available'));
    log('    after    :', await cdp.text('#space-after'));
    log('    install disabled?', await cdp.eval(`document.getElementById('btn-install').disabled`));

    log('[ui] step 5: back to models, reselect, then install');
    await cdp.click('[data-test="loc-back"]');
    await cdp.waitFor(`!document.getElementById('screen-models').hidden`, { label: 'models again' });
    await cdp.click('[data-test="model-qwen3:4b"]');
    await cdp.click('[data-test="model-qwen3:8b"]');
    await sleep(200);
    log('    summary:', await cdp.text('#model-summary'));
    await cdp.click('[data-test="models-continue"]');
    await cdp.waitFor(`!document.getElementById('screen-location').hidden`, { label: 'location again' });

    log('[ui] step 6: Install');
    await cdp.click('[data-test="install"]');
    await cdp.waitFor(`!document.getElementById('screen-install').hidden`, { label: 'install screen' });
    await sleep(4000);
    const snapshot = await cdp.eval(`({
      overall: document.getElementById('overall-percent').textContent,
      task: document.getElementById('install-subtask').textContent,
      item: document.getElementById('current-item').textContent,
      speed: document.getElementById('stat-speed').textContent,
      done: document.getElementById('stat-done').textContent,
      total: document.getElementById('stat-total').textContent,
      eta: document.getElementById('stat-eta').textContent,
      phases: [...document.querySelectorAll('#phase-list li')].map(li => li.textContent.trim()),
      game: document.getElementById('game-score').textContent
    })`);
    log('    progress snapshot:', JSON.stringify(snapshot, null, 2).split('\n').join('\n    '));

    log('[ui] step 7: dino game runs during install');
    const g1 = await cdp.text('#game-score');
    await sleep(3000);
    const g2 = await cdp.text('#game-score');
    log(`    game score ${g1} -> ${g2} (running: ${g1 !== g2})`);

    log('[ui] step 8: window controls respond');
    await cdp.click('#btn-game-toggle');
    log('    pause button label:', await cdp.text('#btn-game-toggle'));
    await cdp.click('#btn-game-toggle');
    log('    resume button label:', await cdp.text('#btn-game-toggle'));
  }

  if (scenario === 'cancel') {
    await cdp.eval(`document.getElementById('btn-get-started').click()`);
    await sleep(500);
    await cdp.eval(`document.getElementById('btn-models-continue').click()`);
    await sleep(500);
    await cdp.eval(`document.getElementById('btn-install').click()`);
    await sleep(3000);
    log('[ui] overall before cancel:', await cdp.text('#overall-percent'));
    await cdp.click('[data-test="cancel"]');
    await sleep(4000);
    const errorVisible = await cdp.visible('#error-box');
    log('[ui] error box shown after cancel:', errorVisible);
    log('[ui] error text:', await cdp.text('#error-text'));
    const state = await cdp.eval(`window.clipify.state().then(s => JSON.stringify(s))`);
    log('[ui] persisted state:', state);
  }

  if (scenario === 'space') {
    await cdp.eval(`document.getElementById('btn-get-started').click()`);
    await sleep(500);
    await cdp.eval(`document.getElementById('btn-models-continue').click()`);
    await sleep(500);
    // Point at a path that does not exist so mkdir/free reporting is exercised.
    await cdp.eval(`(() => { const i = document.getElementById('input-path');
      i.value = 'Z:\\\\not-a-real-drive\\\\Clipify'; i.dispatchEvent(new Event('change')); })()`);
    await sleep(2500);
    log('[ui] required:', await cdp.text('#space-required'));
    log('[ui] available:', await cdp.text('#space-available'));
    log('[ui] warning hidden?', await cdp.eval(`document.getElementById('space-warning').hidden`));
    log('[ui] warning:', await cdp.text('#space-warning'));
    log('[ui] install disabled?', await cdp.eval(`document.getElementById('btn-install').disabled`));
  }

  if (consoleErrors.length) {
    log('[ui] RENDERER ERRORS:');
    for (const error of consoleErrors) log('   ', error);
  } else {
    log('[ui] no renderer console errors');
  }

  // The debugger socket keeps the event loop alive, so close it and exit with a
  // status code instead of hanging after the last log line.
  cdp.ws.close();
  process.exit(0);
}

main().catch((error) => {
  console.error('[ui] FAILED:', error.message);
  process.exit(1);
});
