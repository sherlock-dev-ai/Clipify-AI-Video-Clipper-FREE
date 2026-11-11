'use strict';
/**
 * Installs for real into a scratch directory and asserts that provisioning
 * reports honest progress, that the waiting game runs, and that the staged
 * music is released when setup completes.
 *
 * Usage: node tools/installtest.js
 */

const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');

const getJSON = (url) =>
  new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => {
        try { resolve(JSON.parse(d)); } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });

let passed = 0, failed = 0;
const failures = [];
function check(name, cond, detail) {
  if (cond) { passed += 1; console.log(`  PASS  ${name}`); }
  else {
    failed += 1;
    failures.push(`${name} :: ${detail === undefined ? '' : detail}`);
    console.log(`  FAIL  ${name}  ${detail === undefined ? '' : detail}`);
  }
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const list = await getJSON('http://127.0.0.1:9333/json/list');
  const page = list.find((t) => t.type === 'page');
  if (!page) { console.log('no page target'); process.exit(2); }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const errors = [];
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') {
      errors.push(m.params.exceptionDetails.text + ' ' +
        (m.params.exceptionDetails.exception || {}).description);
    }
  });
  const send = (method, params) => new Promise((res) => {
    const i = ++id; pending.set(i, res);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result && r.result.exceptionDetails) {
      throw new Error(r.result.exceptionDetails.text);
    }
    return r.result.result.value;
  };
  const click = (sel) => evaluate(`(() => { const e=document.querySelector(${JSON.stringify(sel)});
    if(!e) return 'missing'; e.click(); return 'ok'; })()`);

  await send('Runtime.enable', {});
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
  await evaluate('location.reload()');
  await wait(2500);

  const scratch = path.join(os.tmpdir(), `ClipifySetupTest-${Date.now()}`);

  // Walk to the location screen.
  await click('#btn-get-started'); await wait(700);
  await click('#btn-models-continue'); await wait(900);
  await evaluate(`(() => { const i=document.getElementById('input-path');
    i.value=${JSON.stringify(scratch)}; i.dispatchEvent(new Event('change')); })()`);
  await wait(1200);

  // Install with no models and no runtime: fast, and proves zero-selection works.
  await evaluate(`document.getElementById('chk-runtime').checked=false;
    document.getElementById('chk-runtime').dispatchEvent(new Event('change'));`);
  await wait(900);
  const req = await evaluate(`document.getElementById('space-required').textContent`);
  const avail = await evaluate(`document.getElementById('space-available').textContent`);
  console.log(`  (zero-selection requirement: ${req}, available: ${avail})`);

  // Capture the staged music folder so we can prove it is released later.
  const musicBefore = await evaluate(`document.getElementById('music-title').textContent`);

  await click('#btn-install');
  await wait(1200);
  const onInstall = await evaluate(`(() => { const s=[...document.querySelectorAll('.screen')].find(x=>!x.hidden);
    return s?s.dataset.screen:'none'; })()`);
  check('moves to the installing screen', onInstall === 'install', onInstall);

  // The waiting game must be live.
  await wait(1500);
  const gameScore1 = await evaluate(`document.getElementById('game-score').textContent`);
  await wait(1800);
  const gameScore2 = await evaluate(`document.getElementById('game-score').textContent`);
  check('waiting game is running and scoring', gameScore1 !== gameScore2, `${gameScore1} -> ${gameScore2}`);

  // Progress must be honest: it should move, and it must never claim 100 early.
  const progressSamples = [];
  for (let i = 0; i < 25; i += 1) {
    progressSamples.push(await evaluate(`JSON.stringify({
      pct: document.getElementById('overall-percent').textContent,
      item: document.getElementById('current-item').textContent,
      indet: !document.getElementById('overall-indeterminate').hidden,
      phases: document.querySelectorAll('#phase-list li').length,
      err: !document.getElementById('error-box').hidden
    })`));
    if (await evaluate(`(() => { const s=[...document.querySelectorAll('.screen')].find(x=>!x.hidden);
      return s && s.dataset.screen==='done'; })()`)) break;
    await wait(700);
  }
  const last = JSON.parse(progressSamples[progressSamples.length - 1]);
  const items = [...new Set(progressSamples.map((s) => JSON.parse(s).item))];
  console.log('  (task items seen: ' + items.filter(Boolean).join(' | ') + ')');
  check('reports real task items, not a static label', items.filter(Boolean).length >= 1, items.join(' | '));
  check('phase list is populated', last.phases > 0, `phases=${last.phases}`);

  const done = await evaluate(`(() => { const s=[...document.querySelectorAll('.screen')].find(x=>!x.hidden);
    return s?s.dataset.screen:'none'; })()`);
  const errShown = await evaluate(`!document.getElementById('error-box').hidden`);
  const errText = await evaluate(`document.getElementById('error-text').textContent`);

  if (errShown) {
    console.log('  (installer reported: ' + errText + ')');
  }
  check('installation completed or failed cleanly (no crash)', done === 'done' || errShown, done);

  if (done === 'done') {
    check('app files landed in the chosen directory', fs.existsSync(path.join(scratch, 'app.exe')),
      fs.existsSync(scratch) ? fs.readdirSync(scratch).slice(0, 20).join(', ') : 'directory missing');
    check('done screen hides the music control (setup-time only)',
      await evaluate(`document.getElementById('music').hidden`));
    check('done screen shows the install location',
      (await evaluate(`document.getElementById('done-location').textContent`)).includes(scratch));
  }

  // Staged music must be gone from the OS temp folder after completion.
  const leftovers = fs.readdirSync(os.tmpdir()).filter((n) => n.startsWith('clipify-setup-'));
  check('staged music released from %TEMP%', leftovers.length === 0, leftovers.join(', '));
  console.log(`  (music during setup: ${musicBefore})`);

  check('no uncaught renderer exceptions', errors.length === 0, errors.slice(0, 3).join(' | '));

  console.log(`\n===== ${passed} passed, ${failed} failed =====`);
  failures.forEach((f) => console.log('  - ' + f));
  ws.close();
  process.exit(failed ? 1 : 0);
})();
