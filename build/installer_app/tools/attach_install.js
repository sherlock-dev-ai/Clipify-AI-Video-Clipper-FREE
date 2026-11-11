'use strict';

// Attach to the already running setup wizard and complete the installation
// without removing or resetting the existing L:\ClipifyAI data folder.
const fs = require('fs');
const http = require('http');
const path = require('path');

const port = 9333;
const installDir = path.resolve(process.argv[2] || 'L:/ClipifyAI');
const statePath = path.join(process.env.LOCALAPPDATA, 'ClipifyAI', 'setup-state.json');
const logPath = path.join(__dirname, '..', '..', 'attach-install.log');
const log = (message) => {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  fs.appendFileSync(logPath, line);
  process.stdout.write(line);
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const getJSON = (url) => new Promise((resolve, reject) => {
  http.get(url, (response) => {
    let body = '';
    response.on('data', (chunk) => { body += chunk; });
    response.on('end', () => {
      try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
    });
  }).on('error', reject);
});

async function main() {
  const pages = await getJSON(`http://127.0.0.1:${port}/json/list`);
  const page = pages.find((item) => item.type === 'page');
  if (!page) throw new Error('No page target on the already-running installer');
  log(`attached to ${page.url}`);

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pending = new Map();
  let nextId = 0;
  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const resolve = pending.get(message.id);
      pending.delete(message.id);
      resolve(message);
    }
  });
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });

  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`CDP timeout: ${method}`));
    }, 30000);
    pending.set(id, (message) => { clearTimeout(timer); resolve(message); });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const response = await send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.result?.exceptionDetails) {
      throw new Error(response.result.exceptionDetails.text || 'Renderer evaluation failed');
    }
    return response.result?.result?.value;
  };
  const click = async (selector) => {
    const raw = await evaluate(`(() => {
      const e = document.querySelector(${JSON.stringify(selector)});
      if (!e) return JSON.stringify({ ok: false, reason: 'missing element' });
      e.scrollIntoView({ block: 'center' });
      const r = e.getBoundingClientRect();
      const x = Math.round(r.left + r.width / 2);
      const y = Math.round(r.top + r.height / 2);
      const hit = document.elementFromPoint(x, y);
      return JSON.stringify({ ok: !!r.width && !!r.height && (hit === e || e.contains(hit)), x, y,
        hit: hit ? (hit.id || hit.tagName) : 'none' });
    })()`);
    const hit = JSON.parse(raw);
    if (!hit.ok) throw new Error(`Cannot click ${selector}: ${JSON.stringify(hit)}`);
    await send('Input.dispatchMouseEvent', {
      type: 'mousePressed', x: hit.x, y: hit.y, button: 'left', clickCount: 1,
    });
    await send('Input.dispatchMouseEvent', {
      type: 'mouseReleased', x: hit.x, y: hit.y, button: 'left', clickCount: 1,
    });
    await sleep(700);
    log(`clicked ${selector}`);
  };
  const inspect = () => evaluate(`JSON.stringify({
    screen: [...document.querySelectorAll('.screen')].find(s => !s.hidden)?.id || '',
    selected: [...document.querySelectorAll('.model-card.selected')].map(c => c.dataset.model || c.dataset.id || c.textContent.trim()),
    path: document.getElementById('input-path')?.value || '',
    runtime: document.getElementById('chk-runtime')?.checked ?? null,
    ollama: document.getElementById('chk-ollama')?.checked ?? null,
    error: document.getElementById('error-text')?.textContent?.trim() || '',
    percent: document.getElementById('overall-percent')?.textContent?.trim() || '',
    subtask: document.getElementById('install-subtask')?.textContent?.trim() || '',
    item: document.getElementById('current-item')?.textContent?.trim() || ''
  })`);
  const waitForScreen = async (ids, timeoutMs = 30000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const current = JSON.parse(await inspect());
      if (ids.includes(current.screen)) return current;
      await sleep(500);
    }
    throw new Error(`Timed out waiting for screen ${ids.join('|')}: ${await inspect()}`);
  };

  await send('Runtime.enable');
  await send('Page.enable');
  const before = JSON.parse(await inspect());
  log(`initial state ${JSON.stringify(before)}`);

  if (before.screen === 'screen-welcome' || before.screen === 'welcome') {
    const welcomePopup = await evaluate(`(() => {
      const popup = document.getElementById('welcome-popup');
      return !!popup && !popup.hidden;
    })()`);
    if (welcomePopup) await click('#btn-popup-ok');
    await click('#btn-get-started');
  }
  await waitForScreen(['screen-models', 'models']);

  const models = JSON.parse(await evaluate(`JSON.stringify([...document.querySelectorAll('.model-card')].map(c => ({
    id: c.dataset.model || c.dataset.id || '', selected: c.classList.contains('selected'), text: c.textContent.trim().slice(0,90)
  })))`));
  const qwen = models.find((model) => model.id === 'qwen3:8b');
  if (!qwen) throw new Error(`qwen3:8b model card missing: ${JSON.stringify(models)}`);
  if (!qwen.selected) {
    await click('[data-model="qwen3:8b"]');
  }
  for (const model of models) {
    if (model.selected && model.id && model.id !== 'qwen3:8b') {
      await click(`[data-model="${model.id.replaceAll('"', '\\"')}"]`);
    }
  }
  const selected = JSON.parse(await evaluate(`JSON.stringify([...document.querySelectorAll('.model-card.selected')].map(c => c.dataset.model || c.dataset.id))`));
  if (selected.length !== 1 || selected[0] !== 'qwen3:8b') throw new Error(`Unexpected selected models: ${JSON.stringify(selected)}`);
  log('selected only qwen3:8b');
  await click('#btn-models-continue');
  await waitForScreen(['screen-location', 'location']);

  const pathResult = await evaluate(`(() => {
    const input = document.getElementById('input-path');
    if (!input) return 'missing';
    input.value = ${JSON.stringify(installDir)};
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return input.value;
  })()`);
  await sleep(1300);
  const options = JSON.parse(await evaluate(`(() => {
    const runtime = document.getElementById('chk-runtime');
    const ollama = document.getElementById('chk-ollama');
    const desktop = document.getElementById('chk-desktop');
    if (runtime) { runtime.checked = true; runtime.dispatchEvent(new Event('change', { bubbles: true })); }
    if (ollama) { ollama.checked = false; ollama.dispatchEvent(new Event('change', { bubbles: true })); }
    if (desktop) { desktop.checked = true; desktop.dispatchEvent(new Event('change', { bubbles: true })); }
    return JSON.stringify({ path: document.getElementById('input-path')?.value, runtime: runtime?.checked,
      ollama: ollama?.checked, desktop: desktop?.checked,
      installDisabled: document.getElementById('btn-install')?.disabled });
  })()`));
  log(`location=${pathResult}; options=${JSON.stringify(options)}`);
  if (path.resolve(options.path) !== installDir) throw new Error(`Install path was not set to ${installDir}`);
  if (!options.runtime || options.ollama || options.installDisabled) throw new Error(`Unexpected install options: ${JSON.stringify(options)}`);

  await click('#btn-install');
  await sleep(900);
  const warning = await evaluate(`JSON.stringify({ shown: !!document.getElementById('download-warning') && !document.getElementById('download-warning').hidden,
    go: !!document.getElementById('btn-warn-go') })`);
  log(`download warning ${warning}`);
  const warningState = JSON.parse(warning);
  if (warningState.go) await click('#btn-warn-go');

  log('installation started; polling installer status and runtime progress');
  const end = Date.now() + 4 * 60 * 60 * 1000;
  let last = '';
  while (Date.now() < end) {
    await sleep(12000);
    let state = {};
    try { state = JSON.parse(fs.readFileSync(statePath, 'utf8')); } catch {}
    const ui = JSON.parse(await inspect());
    const brief = JSON.stringify({ status: state.status, phases: state.completedPhases, ui: ui.percent, sub: ui.subtask, item: ui.item, error: ui.error });
    if (brief !== last) { log(brief); last = brief; }
    if (state.status === 'complete' || ui.screen === 'screen-done' || ui.screen === 'done') break;
    if (state.status === 'error' || ui.error) {
      throw new Error(`Installer reported failure: ${state.error || ui.error || brief}`);
    }
  }

  const finalState = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  const finalUi = JSON.parse(await inspect());
  if (finalState.status !== 'complete' && !['screen-done', 'done'].includes(finalUi.screen)) {
    throw new Error(`Install timeout; final state=${JSON.stringify(finalState)} UI=${JSON.stringify(finalUi)}`);
  }
  const screenshot = await send('Page.captureScreenshot', { format: 'png' });
  const screenshotPath = path.join(path.dirname(logPath), 'attach-install-finished.png');
  fs.writeFileSync(screenshotPath, Buffer.from(screenshot.result.data, 'base64'));
  log(`INSTALL_COMPLETE state=${JSON.stringify(finalState)} marker=${fs.existsSync(path.join(installDir, 'runtime', '.clipify-runtime-complete'))} screenshot=${screenshotPath}`);
  ws.close();
}

main().catch((error) => {
  console.error(`[attach-install] ERROR ${error.stack || error}`);
  process.exit(1);
});
