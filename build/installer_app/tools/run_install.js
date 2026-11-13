'use strict';
/*
 * Corrected CDP driver for the Clipify AI installer (Electron wizard).
 *
 * Fixes vs. the stale drive_installer.js:
 *  - clicks the #btn-warn-go confirmation that the download-warning popup requires
 *    (otherwise startInstall() never runs)
 *  - detects "done" via #screen-done losing its `hidden` attribute instead of
 *    #btn-launch (which is always present in the static DOM)
 *  - selects the qwen3:8b model card WITHOUT toggling it off when it is already
 *    auto-selected as the recommended model
 *  - ensures runtime/ollama checkboxes are ticked before installing
 *
 * Usage: node tools\run_install.js "<path-to-setup.exe>" "<install-dir>"
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const setupExe = process.argv[2];
const installDir = process.argv[3];
if (!setupExe || !installDir) {
  console.error('usage: node run_install.js <setup.exe> <install-dir>');
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
function log(msg) { console.log(`[install] ${msg}`); }

(async () => {
  fs.mkdirSync(installDir, { recursive: true });

  // The packaged Electron wizard loads its own resources/<app|app.asar> from
  // its install dir, so no app-path argument is needed. (Passing one makes
  // Electron run the app in Node mode, and if the app dir contains a
  // node_modules/electron shim, require('electron') is shadowed.) CDP on
  // 127.0.0.1:9333 is enabled by main.js via app.commandLine.appendSwitch, which
  // is required because Electron v44 rejects --remote-debugging-port on the CLI.
  const spawnEnv = { ...process.env };
  delete spawnEnv.ELECTRON_RUN_AS_NODE;
  const child = spawn(setupExe, [], {
    detached: true, windowsHide: false, stdio: 'ignore', env: spawnEnv
  });
  child.on('error', (err) => { console.error('[install] LAUNCH ERROR: ' + err.message); process.exit(7); });
  child.unref();
  log(`launcher spawned pid=${child.pid} -> ${setupExe}`);

  let page = null;
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    try {
      const list = await getJSON(`${BASE}/json/list`);
      page = list.find((t) => t.type === 'page');
      if (page) break;
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 800));
  }
  if (!page) { console.error('[install] ERROR: no page target on CDP:' + CDP_PORT); process.exit(3); }
  log('renderer ready: ' + (page.name || page.url).slice(0, 70));

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pending = new Map();
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  ws.addEventListener('error', (e) => log('ws error: ' + e.message));
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));

  let id = 0;
  const send = (method, params) => new Promise((res, rej) => {
    const i = ++id;
    pending.set(i, (m) => { clearTimeout(to); res(m); });
    const to = setTimeout(() => { pending.delete(i); rej(new Error('timeout ' + method)); }, 120000);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const eval_ = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result.exceptionDetails) {
      const exc = JSON.stringify(r.result.exceptionDetails);
      throw new Error('eval exception: ' + exc);
    }
    return r.result.result.value;
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const click = (sel) => eval_(`(function(){ var e=document.querySelector(${JSON.stringify(sel)}); if(!e){return 'missing:'+${JSON.stringify(sel)}; } e.scrollIntoView({block:'center'}); e.click(); return 'ok:'+${JSON.stringify(sel)}; })()`);

  try {
    await send('Runtime.enable', {});
    await send('Page.enable', {});
    await send('Page.bringToFront', {});
    await send('Emulation.setDeviceMetricsOverride', { width: 1040, height: 840, deviceScaleFactor: 1, mobile: false });

    await click('#btn-get-started');
    log('clicked Get Started');
    await wait(1500);

    // Select recommended model (qwen2.5:3b) if not already selected.
    const sel = await eval_(`(function(){
      var c=document.querySelector('[data-model="qwen2.5:3b"]') || document.querySelector('.model-card.recommended') || document.querySelector('[data-model="qwen3:8b"]');
      if(!c){return 'no-card';}
      var on=c.classList.contains('selected');
      if(!on){c.scrollIntoView({block:'center'});c.click();}
      return on?'already-selected':'selected';
    })()`);
    log('model state: ' + sel);

    await click('#btn-models-continue');
    log('clicked Models Continue');
    await wait(1500);

    // Set install path.
    const setPath = await eval_(`(function(){
      var i=document.getElementById('input-path');
      if(!i){return 'input-path-missing';}
      i.value=${JSON.stringify(installDir)};
      i.dispatchEvent(new Event('input',{bubbles:true}));
      i.dispatchEvent(new Event('change',{bubbles:true}));
      return 'path-set:'+i.value;
    })()`);
    log('location: ' + setPath);

    // Ensure runtime + ollama checkboxes are checked.
    await wait(1500);
    const opts = await eval_(`(function(){
      function chk(id){var e=document.getElementById(id); if(e){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));} return e?e.checked:false;}
      return { runtime: chk('chk-runtime'), ollama: chk('chk-ollama'), desktop: chk('chk-desktop') };
    })()`);
    log('options: ' + JSON.stringify(opts));

    // Wait until btn-install becomes enabled after disk check completes.
    let isBtnEnabled = false;
    for (let attempt = 0; attempt < 40; attempt++) {
      isBtnEnabled = await eval_(`!document.getElementById('btn-install').disabled`);
      if (isBtnEnabled) break;
      await wait(500);
    }
    log('btn-install enabled: ' + isBtnEnabled);

    await click('#btn-install');
    log('clicked Install');
    await wait(1000);

    // If download-warning popup is displayed, click confirm.
    const warn = await eval_(`(function(){
      var w = document.getElementById('download-warning');
      if (w && !w.hidden) {
        var btn = document.getElementById('btn-warn-go');
        if (btn) { btn.click(); return 'warn-go-clicked'; }
      }
      return 'no-warning';
    })()`);
    log('warning popup check: ' + warn);

    // Poll the install phase. Done = #screen-done no longer hidden.
    const end = Date.now() + 60 * 60 * 1000;
    let final = null;
    while (Date.now() < end) {
      await wait(4000);
      const st = await eval_(`(function(){
        var done=document.getElementById('screen-done');
        var err=document.getElementById('error-box');
        var pct=document.getElementById('overall-percent');
        var sub=document.getElementById('install-subtask');
        var ci=document.getElementById('current-item');
        var errText=document.getElementById('error-text');
        return {
          doneScreen: done ? !done.hidden : false,
          error: err ? !err.hidden : false,
          pct: pct?pct.textContent.trim():'',
          sub: sub?sub.textContent.trim():'',
          current: ci?ci.textContent.trim():'',
          errText: errText?errText.textContent.trim():''
        };
      })()`);
      log('progress pct=' + st.pct + ' sub=' + st.sub + ' item=' + st.current);
      if (st.doneScreen || st.pct === '100%') { final = 'done'; break; }
      if (st.error) { final = 'error:' + st.errText; break; }
    }
    log('install phase ended: ' + (final || 'timeout'));

    // Capture finished screenshot.
    try {
      const shot = await send('Page.captureScreenshot', { format: 'png', quality: 100 });
      fs.writeFileSync(path.join(installDir, 'finish-shot.png'), Buffer.from(shot.data, 'base64'));
    } catch (e) { log('screenshot failed: ' + e.message); }

    if (final && final.startsWith('done')) {
      fs.writeFileSync(path.join(installDir, '.install-driver-ok'), 'installed via CDP driver');
      log('SUCCESS: installed at ' + installDir);
      process.exit(0);
    }
    process.exit(final && final.startsWith('error') ? 4 : 5);
  } catch (e) {
    console.error('[install] EXCEPTION: ' + e.message);
    process.exit(6);
  }
})();
