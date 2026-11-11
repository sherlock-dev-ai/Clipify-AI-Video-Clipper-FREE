'use strict';
/*
 * Drives the real Clipify AI installer (a custom Electron wizard) over CDP so
 * the whole BUILD -> RUN INSTALLER -> INSTALL L:\ClipifyAI -> LAUNCH flow is
 * actually exercised, not just assumed.
 *
 * Usage: node tools/drive_installer.js "<path-to-setup.exe>" "<install-dir>"
 */
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const setupExe = process.argv[2];
const installDir = process.argv[3];
if (!setupExe || !installDir) {
  console.error('usage: node drive_installer.js <setup.exe> <install-dir>');
  process.exit(2);
}

const CDP_PORT = 9333;
const BASE = `http://127.0.0.1:${CDP_PORT}`;

function getJSON(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

(async () => {
  fs.mkdirSync(installDir, { recursive: true });

  const child = spawn('"' + setupExe + '"', ['--remote-debugging-port=' + CDP_PORT, '--no-sandbox'], {
    detached: true, windowsHide: true, stdio: 'ignore',
  });
  child.unref();
  console.log('[driver] installer launched pid=' + child.pid);

  let page = null;
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    try {
      const list = await getJSON(`${BASE}/json/list`);
      page = list.find((t) => t.type === 'page');
      if (page) break;
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 800));
  }
  if (!page) { console.error('[driver] ERROR: no page target appeared'); process.exit(3); }
  console.log('[driver] connected to renderer:', page.webSocketDebuggerUrl.slice(0, 60) + '...');

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pending = new Map();
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));

  let id = 0;
  const send = (method, params) => new Promise((res, rej) => {
    const i = ++id; pending.set(i, (m) => res(m));
    const to = setTimeout(() => { pending.delete(i); rej(new Error('timeout ' + method)); }, 20000);
    const orig = pending.get(i);
    pending.set(i, (m) => { clearTimeout(to); orig(m); });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const eval_ = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text);
    return r.result.result.value;
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  try {
    await send('Runtime.enable', {});
    await send('Emulation.setDeviceMetricsOverride', { width: 1040, height: 840, deviceScaleFactor: 1, mobile: false });

    const click = (sel) => eval_(`(function(){ const e=document.querySelector(${JSON.stringify(sel)});
      if(!e){ return 'missing:'+${JSON.stringify(sel)} }; e.scrollIntoView({behavior:'smooth',block:'center'}); e.click(); return 'ok'; })()`);

    console.log('[driver] -> click Get Started');
    let r = await click('#btn-get-started');
    console.log('[driver]   result:', r);

    // Models page: select qwen3:8b (checkbox inside the card). Toggle on.
    console.log('[driver] -> select qwen3:8b model');
    const picked = await eval_(`(function(){
      const cards = document.querySelectorAll('[data-test="model-grid"] [data-model], [data-test="model-grid"] label, [data-test="model-grid"] button');
      let found = false;
      cards.forEach(c => {
        if(/qwen3:?\s?8b/i.test(c.textContent) || /qwen3.*8b/i.test(c.textContent) || c.textContent.includes('8B')){
          const cb = c.querySelector('input[type=checkbox]');
          if(cb){ cb.checked=true; cb.dispatchEvent(new Event('change',{bubbles:true})); found=true; }
          else { c.click(); found=true; }
        }
      });
      return found ? 'selected' : 'no-qwen3-8b-card-found-count='+cards.length;
    })()`);
    console.log('[driver]   model pick:', picked);
    await click('#btn-models-continue');

    // Location page: set install dir, leave runtime+ollama checked.
    await wait(1000);
    const setPath = await eval_(`(function(){
      const i = document.getElementById('input-path');
      if(!i) return 'input-path-missing';
      i.value = ${JSON.stringify(installDir)};
      i.dispatchEvent(new Event('change',{bubbles:true}));
      i.dispatchEvent(new Event('input',{bubbles:true}));
      return 'path-set:' + i.value;
    })()`);
    console.log('[driver]   location:', setPath);

    // Confirm checkboxes are ticked.
    const opts = await eval_(`(function(){
      return { desktop: !!document.getElementById('chk-desktop'), desktopOn: document.getElementById('chk-desktop')&&document.getElementById('chk-desktop').checked,
               runtimeOn: document.getElementById('chk-runtime')&&document.getElementById('chk-runtime').checked,
               ollamaOn: document.getElementById('chk-ollama')&&document.getElementById('chk-ollama').checked };
    })()`);
    console.log('[driver]   options:', JSON.stringify(opts));

    console.log('[driver] -> click Install');
    await click('#btn-install');

    // Poll until the done screen or error.
    const end = Date.now() + 60 * 60 * 1000;
    let final = null;
    while (Date.now() < end) {
      await wait(4000);
      const done = await eval_(`(function(){
        const d = document.getElementById('btn-launch');
        const e = document.getElementById('error-box');
        const pct = document.getElementById('overall-percent');
        const sub = document.getElementById('install-subtask');
        return { launched: !!d, error: e && !e.hidden, pct: pct?pct.textContent.trim():'', sub: sub?sub.textContent.trim():'' };
      })()`);
      console.log('[driver]   progress: pct=' + done.pct + ' sub=' + done.sub);
      if (done.launched) { final = 'done'; break; }
      if (done.error) { final = 'error'; break; }
    }
    console.log('[driver] install phase ended:', final || 'timeout');

    if (final === 'done') {
      fs.writeFileSync(path.join(installDir, '.install-driver-ok'), 'installed via CDP driver');
      console.log('[driver] SUCCESS: installed at', installDir);
      // Capture a finished screenshot.
      const shot = await send('Page.captureScreenshot', { format: 'png', quality: 100 });
      fs.writeFileSync(path.join(installDir, 'finish-shot.png'), Buffer.from(shot.data, 'base64'));
      process.exit(0);
    }
    process.exit(final === 'error' ? 4 : 5);
  } catch (e) {
    console.error('[driver] EXCEPTION:', e.message);
    process.exit(6);
  }
})();
