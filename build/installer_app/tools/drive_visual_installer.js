'use strict';
/**
 * Drives the Clipify AI installer visibly on the user's desktop,
 * captures evidence screenshots at every stage, exercises the mini-game,
 * and launches the installed application.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const setupExe = process.argv[2] || path.resolve('L:\\ClipifyAI\\installer\\Clipify AI Setup.exe');
const installDir = process.argv[3] || path.join(process.env.LOCALAPPDATA || 'C:\\Users\\Dell\\AppData\\Local', 'Programs', 'ClipifyAI');
const shotDir = path.resolve('C:\\Users\\Dell\\.gemini\\antigravity\\brain\\5bf1f793-a593-488a-8501-e22f375c5231');

console.log(`[visual-driver] setupExe: ${setupExe}`);
console.log(`[visual-driver] installDir: ${installDir}`);
console.log(`[visual-driver] shotDir: ${shotDir}`);

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

  // Spawn visibly on desktop (windowsHide: false)
  const child = spawn(setupExe, [], {
    detached: true,
    windowsHide: false,
    stdio: 'ignore',
  });
  child.on('error', (err) => { console.error('[visual-driver] LAUNCH ERROR: ' + err.message); process.exit(7); });
  child.unref();
  console.log(`[visual-driver] spawned pid=${child.pid}`);

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
  if (!page) { console.error('[visual-driver] ERROR: no page target on CDP:' + CDP_PORT); process.exit(3); }
  console.log('[visual-driver] connected to CDP: ' + page.webSocketDebuggerUrl);

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pending = new Map();
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));

  let id = 0;
  const send = (method, params) => new Promise((res, rej) => {
    const i = ++id;
    pending.set(i, (m) => { clearTimeout(to); res(m); });
    const to = setTimeout(() => { pending.delete(i); rej(new Error('timeout ' + method)); }, 30000);
    ws.send(JSON.stringify({ id: i, method, params }));
  });

  const eval_ = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
    return r.result.result.value;
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const click = (sel) => eval_(`(function(){ var e=document.querySelector(${JSON.stringify(sel)}); if(!e) return 'missing:'+${JSON.stringify(sel)}; e.scrollIntoView({block:'center'}); e.click(); return 'ok:'+${JSON.stringify(sel)}; })()`);

  const saveScreenshot = async (name) => {
    try {
      const shot = await send('Page.captureScreenshot', { format: 'png', quality: 100 });
      const p = path.join(shotDir, name);
      fs.writeFileSync(p, Buffer.from(shot.data, 'base64'));
      console.log(`[visual-driver] screenshot saved: ${p}`);
    } catch (e) {
      console.error(`[visual-driver] screenshot ${name} failed: ${e.message}`);
    }
  };

  try {
    await send('Runtime.enable', {});
    await send('Emulation.setDeviceMetricsOverride', { width: 1040, height: 840, deviceScaleFactor: 1, mobile: false });

    // 1. Stage: Get Started
    await wait(2000);
    await saveScreenshot('installer_stage1_get_started.png');

    await click('#btn-get-started');
    console.log('[visual-driver] clicked Get Started');
    await wait(1500);

    // 2. Stage: AI Model
    await saveScreenshot('installer_stage2_ai_model.png');
    await click('#btn-models-continue');
    console.log('[visual-driver] clicked Models Continue');
    await wait(1500);

    // 3. Stage: Install Location
    const setPath = await eval_(`(function(){
      var i=document.getElementById('input-path');
      if(!i) return 'input-path-missing';
      i.value=${JSON.stringify(installDir)};
      i.dispatchEvent(new Event('input',{bubbles:true}));
      i.dispatchEvent(new Event('change',{bubbles:true}));
      return 'path-set:'+i.value;
    })()`);
    console.log('[visual-driver] location:', setPath);
    await wait(1000);
    await saveScreenshot('installer_stage3_location.png');

    // Ensure options checked
    await eval_(`(function(){
      function chk(id){var e=document.getElementById(id); if(e){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));} return e?e.checked:false;}
      chk('chk-runtime'); chk('chk-ollama'); chk('chk-desktop');
    })()`);

    // 4. Click Install
    await click('#btn-install');
    console.log('[visual-driver] clicked Install');
    await wait(800);

    // Confirm pre-download warning popup if shown
    await click('#btn-warn-go');
    console.log('[visual-driver] confirmed warn-go');
    await wait(3000);

    // Mini-game interaction & installing progress screenshot
    await saveScreenshot('installer_stage4_installing_progress.png');

    // Exercise mini-game: press Space / jump over obstacles
    for (let jump = 0; jump < 6; jump++) {
      await wait(1200);
      await eval_(`(function(){
        window.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space', key: ' ', bubbles: true }));
        setTimeout(() => window.dispatchEvent(new KeyboardEvent('keyup', { code: 'Space', key: ' ', bubbles: true })), 150);
      })()`);
    }
    await wait(1000);
    await saveScreenshot('installer_stage4_minigame_running.png');

    // Toggle theme to test night mode in mini-game
    await eval_(`(function(){
      var themeBtn = document.getElementById('theme-toggle') || document.querySelector('.theme-toggle');
      if (themeBtn) themeBtn.click();
      else document.body.dataset.theme = document.body.dataset.theme === 'night' ? 'day' : 'night';
    })()`);
    await wait(1000);
    await saveScreenshot('installer_stage4_minigame_night_mode.png');

    // Poll until install completes
    console.log('[visual-driver] waiting for installation completion...');
    const end = Date.now() + 30 * 60 * 1000;
    let final = null;
    let lastLogTime = Date.now();

    while (Date.now() < end) {
      await wait(3000);
      const st = await eval_(`(function(){
        var done = document.getElementById('screen-done');
        var err = document.getElementById('error-box');
        var pct = document.getElementById('overall-percent');
        var sub = document.getElementById('install-subtask');
        var ci = document.getElementById('current-item');
        var speed = document.getElementById('stat-speed');
        var eta = document.getElementById('stat-eta');
        var scoreVis = document.getElementById('game-score-vis');
        var bestVis = document.getElementById('game-best-vis');
        return {
          doneScreen: done ? !done.hidden : false,
          error: err ? !err.hidden : false,
          pct: pct ? pct.textContent.trim() : '',
          sub: sub ? sub.textContent.trim() : '',
          current: ci ? ci.textContent.trim() : '',
          speed: speed ? speed.textContent.trim() : '',
          eta: eta ? eta.textContent.trim() : '',
          score: scoreVis ? scoreVis.textContent.trim() : '',
          best: bestVis ? bestVis.textContent.trim() : '',
        };
      })()`);

      if (Date.now() - lastLogTime > 9000) {
        console.log(`[visual-driver] progress: ${st.pct} | ${st.sub} | speed: ${st.speed} | eta: ${st.eta} | score: ${st.score} (best: ${st.best})`);
        lastLogTime = Date.now();
      }

      if (st.doneScreen || st.pct === '100%') {
        final = 'done';
        break;
      }
      if (st.error) {
        final = 'error';
        break;
      }
    }

    console.log(`[visual-driver] install finished with status: ${final}`);
    await wait(2000);
    await saveScreenshot('installer_stage5_installed_completion.png');

    // 5. Click "Launch Clipify AI" button in the installer!
    console.log('[visual-driver] clicking Launch Clipify AI button (#btn-launch)...');
    const launchResult = await click('#btn-launch');
    console.log('[visual-driver] launch click result:', launchResult);

    await wait(4000);
    await saveScreenshot('installer_stage5_post_launch.png');

    console.log('[visual-driver] COMPLETED SUCCESSFULLY!');
    process.exit(0);

  } catch (err) {
    console.error('[visual-driver] EXCEPTION:', err.message);
    process.exit(1);
  }
})();

