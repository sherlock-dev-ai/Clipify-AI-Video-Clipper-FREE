'use strict';
/**
 * Click-through test for the setup UI, driven through the Chrome DevTools
 * Protocol. Because we cannot look at screenshots, this asserts on DOM state
 * and geometry: real text values, real computed sizes, real enablement.
 *
 * Usage: node tools/uitest.js
 */

const http = require('http');

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

let passed = 0;
let failed = 0;
const failures = [];

function check(name, condition, detail) {
  if (condition) {
    passed += 1;
    console.log(`  PASS  ${name}`);
  } else {
    failed += 1;
    failures.push(`${name} :: ${detail === undefined ? '' : detail}`);
    console.log(`  FAIL  ${name}  ${detail === undefined ? '' : detail}`);
  }
}

(async () => {
  const list = await getJSON('http://127.0.0.1:9333/json/list');
  const page = list.find((t) => t.type === 'page');
  if (!page) { console.log('no page target'); process.exit(2); }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const consoleErrors = [];

  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push(m.params.args.map((a) => a.value || a.description).join(' '));
    }
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      consoleErrors.push(`${d.text} ${d.exception ? d.exception.description : ''}`);
    }
  });

  const send = (method, params) =>
    new Promise((res) => {
      const i = ++id;
      pending.set(i, res);
      ws.send(JSON.stringify({ id: i, method, params }));
    });

  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result && r.result.exceptionDetails) {
      throw new Error(r.result.exceptionDetails.text + ' ' +
        (r.result.exceptionDetails.exception || {}).description);
    }
    return r.result.result.value;
  };

  const click = (selector) =>
    evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return 'missing'; el.click(); return 'ok'; })()`);

  const visibleScreen = () =>
    evaluate(`(() => { const s=[...document.querySelectorAll('.screen')].find(x=>!x.hidden);
      return s ? s.dataset.screen : 'none'; })()`);

  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  await send('Runtime.enable', {});
  await send('Page.enable', {});

  // ---------------------------------------------------------- 1. welcome
  console.log('\n[1] welcome screen');
  await send('Emulation.setDeviceMetricsOverride', { width: 1040, height: 760, deviceScaleFactor: 1, mobile: false });
  await evaluate(`location.reload()`);
  await wait(2600);

  check('renders welcome on load', (await visibleScreen()) === 'welcome', await visibleScreen());
  const brand = await evaluate(`document.querySelector('.titlebar-brand span')?.textContent`);
  check('title is "Clipify AI Setup"', brand === 'Clipify AI Setup', brand);
  const logoOk = await evaluate(`(() => { const i=document.querySelector('.titlebar-logo');
    return !!i && i.naturalWidth > 0 && i.getAttribute('src').includes('logo-round'); })()`);
  check('brand logo image loads', logoOk);
  const weather = await evaluate(`document.body.dataset.weather`);
  check('a weather state is active',
    ['morning', 'sunny', 'cloudy', 'rain', 'sunset', 'night'].includes(weather), weather);
  const musicTitle = await evaluate(`document.getElementById('music-title').textContent`);
  check('music track listed', /Grand Escape|Falling In Love/i.test(musicTitle), musicTitle);
  const github = await evaluate(`document.getElementById('btn-github')?.textContent.trim()`);
  check('GitHub link present', /github\.com\/sherlock-dev-ai/.test(github || ''), github);

  // ----------------------------------------------------------- 2. models
  console.log('\n[2] model selection');
  await click('#btn-get-started');
  await wait(700);
  check('navigates to models', (await visibleScreen()) === 'models', await visibleScreen());

  const names = await evaluate(`[...document.querySelectorAll('.model-name')].map(e=>e.textContent)`);
  check('catalogue has 11 models', names.length === 11, `${names.length}: ${names.join(', ')}`);
  const icons = await evaluate(`document.querySelectorAll('.model-icon svg').length`);
  check('every model card has a visible icon', icons === 11, `${icons} icons for 11 cards`);
  const qwen = names.filter((n) => n.startsWith('Qwen3'));
  check('includes the 4 Qwen3 sizes', qwen.length === 4, qwen.join(', '));
  const personal = names.filter((n) => /Dolphin|Custom|My Coder/i.test(n));
  check('no personal/installed models in catalogue', personal.length === 0, personal.join(', '));
  const rec = await evaluate(`document.querySelectorAll('.badge-rec').length`);
  check('exactly one recommended badge', rec === 1, String(rec));

  const summary0 = await evaluate(`document.getElementById('model-summary').textContent`);
  check('summary reflects the preselected recommendation',
    /1 model selected/.test(summary0) && /GB to download/.test(summary0), summary0);

  const cardFacts = await evaluate(`(() => { const c=document.querySelector('.model-card');
    return [...c.querySelectorAll('.fact')].map(f=>f.textContent); })()`);
  check('cards show download size, RAM and VRAM', cardFacts.length === 3, cardFacts.join(' | '));

  await evaluate(`document.querySelector('[data-model="qwen3:32b"]').dispatchEvent(new MouseEvent('mouseenter'))`);
  await wait(250);
  let detail = await evaluate(`document.getElementById('detail-body').textContent`);
  check('hover shows the hovered model', /Qwen3 32B/.test(detail), detail.slice(0, 90));
  check('details panel shows size/RAM/VRAM/best-for',
    /20\.2 GB/.test(detail) && /32 GB/.test(detail) && /VRAM/.test(detail), detail.slice(0, 160));

  // multi-select
  await click('[data-model="gemma3:4b"]');
  await wait(200);
  const summary2 = await evaluate(`document.getElementById('model-summary').textContent`);
  check('summary counts 2 models after multi-select', /2 models selected/.test(summary2), summary2);
  const sumMatch = summary2.match(/([\d.]+) GB to download/);
  check('multi-select total is the real decimal-GB sum (5.23+3.34=8.57)',
    sumMatch && Math.abs(parseFloat(sumMatch[1]) - 8.57) < 0.05, summary2);

  // deselect back to 1
  await click('[data-model="gemma3:4b"]');
  await wait(150);

  // --------------------------------------------------------- 3. location
  console.log('\n[3] installation location + disk space');
  await click('#btn-models-continue');
  await wait(900);
  check('navigates to location', (await visibleScreen()) === 'location', await visibleScreen());

  const path0 = await evaluate(`document.getElementById('input-path').value`);
  check('default path is per-user Programs', /AppData\\Local\\Programs\\ClipifyAI$/.test(path0), path0);

  const req = await evaluate(`document.getElementById('space-required').textContent`);
  const avail = await evaluate(`document.getElementById('space-available').textContent`);
  const after = await evaluate(`document.getElementById('space-after').textContent`);
  check('Required is a real size, not 0 B', req !== '0 B' && /GB|MB/.test(req), req);
  check('Available is a real size, not 0 B', avail !== '0 B' && /GB|TB/.test(avail), avail);
  check('Free after install is a real size', /GB|TB/.test(after), after);

  const good = await evaluate(`!document.getElementById('space-good').hidden`);
  const warn = await evaluate(`!document.getElementById('space-warning').hidden`);
  const installEnabled = await evaluate(`!document.getElementById('btn-install').disabled`);
  check('enough space -> positive status', good, `good=${good} warn=${warn}`);
  check('enough space -> no warning', !warn);
  check('enough space -> Install enabled', installEnabled);
  const vol = await evaluate(`document.getElementById('space-meta').textContent`);
  check('shows which volume is measured', /[A-Z]:\\/.test(vol), vol);

  // change drive -> numbers must change
  const availC = avail;
  await evaluate(`(() => { const i=document.getElementById('input-path');
    i.value='D:\\\\ClipifyAI'; i.dispatchEvent(new Event('change')); })()`);
  await wait(1200);
  const availD = await evaluate(`document.getElementById('space-available').textContent`);
  check('recalculates when the path changes drive', availD !== availC, `C=${availC} D=${availD}`);

  // insufficient space: ask for more than the volume holds
  await evaluate(`(() => { const i=document.getElementById('input-path');
    i.value='D:\\\\ClipifyAI'; i.dispatchEvent(new Event('change')); })()`);
  await wait(400);
  // select every model to push required above D: free space
  // Select every model to push the requirement well past the smallest volume.
  // NOTE: only ids that actually exist in the catalogue may be clicked.
  await click('#btn-loc-back'); await wait(500);
  for (const id of ['qwen3:4b', 'qwen3:32b', 'qwen3:14b', 'gemma3:12b', 'phi4:14b', 'mistral:7b',
    'deepseek-r1:8b', 'mistral-small:24b', 'llama3.1:8b', 'gemma3:4b']) {
    await click(`[data-model="${id}"]`);
  }
  await wait(400);
  const summaryBig = await evaluate(`document.getElementById('model-summary').textContent`);
  check('can select all 11 models', /11 models selected/.test(summaryBig), summaryBig);
  const bigMatch = summaryBig.match(/([\d.]+) GB to download/);
  check('full-catalogue total equals the sum of all 11 real sizes (86.60 GB)',
    bigMatch && Math.abs(parseFloat(bigMatch[1]) - 86.6) < 0.05, summaryBig);

  await click('#btn-models-continue'); await wait(1100);
  // Arrive on the location screen, THEN pick the small volume - continuing from
  // the models step resets the path to the default.
  await evaluate(`(() => { const i=document.getElementById('input-path');
    i.value='D:\\\\ClipifyAI'; i.dispatchEvent(new Event('change')); })()`);
  await wait(1200);
  const reqD = await evaluate(`document.getElementById('space-required').textContent`);
  const availD2 = await evaluate(`document.getElementById('space-available').textContent`);
  const blockedD = await evaluate(`document.getElementById('btn-install').disabled`);
  const warnText = await evaluate(`document.getElementById('space-warning-text').textContent`);
  check('large selection on a small drive is blocked', blockedD === true,
    `req=${reqD} avail=${availD2} disabled=${blockedD}`);
  check('block explains the shortfall in GB',
    /need approximately .*(GB|MB)/i.test(warnText), warnText);
  check('the space bar turns red when blocked',
    await evaluate(`document.getElementById('space-bar').classList.contains('bad')`));

  // invalid path
  await evaluate(`(() => { const i=document.getElementById('input-path');
    i.value='not a path'; i.dispatchEvent(new Event('change')); })()`);
  await wait(900);
  check('invalid path blocks install',
    await evaluate(`document.getElementById('btn-install').disabled`),
    await evaluate(`document.getElementById('space-warning-text').textContent`));

  // ------------------------------- 3b. path persistence + speed (regressions)
  console.log('\n[3b] path must not change on its own');
  const custom = 'L:\\ClipifyAI-Custom';
  await evaluate(`(() => { const i=document.getElementById('input-path');
    i.value=${JSON.stringify(custom)}; i.dispatchEvent(new Event('change')); })()`);
  await wait(1000);
  check('typed path is kept verbatim',
    (await evaluate(`document.getElementById('input-path').value`)) === custom,
    await evaluate(`document.getElementById('input-path').value`));

  // Go back and forward again: the path must survive, not snap to the default.
  await click('#btn-loc-back'); await wait(600);
  await click('#btn-models-continue'); await wait(1000);
  check('path survives a back/forward round trip',
    (await evaluate(`document.getElementById('input-path').value`)) === custom,
    await evaluate(`document.getElementById('input-path').value`));
  check('still on the location screen after back/forward',
    (await visibleScreen()) === 'location', await visibleScreen());

  // Typing must not be slow: sample the round trip.
  const typedAt = Date.now();
  await evaluate(`(() => { const i=document.getElementById('input-path');
    i.value='L:\\\\ClipifyAI-Typed'; i.dispatchEvent(new Event('change')); })()`);
  await wait(400);
  const latency = Date.now() - typedAt;
  check('path change reflects quickly (<1500ms)', latency < 1500, `${latency}ms`);

  // ----------------------------------- 3c. selection must never auto-expand
  console.log('\n[3c] model selection must not auto-expand');
  await click('#btn-loc-back'); await wait(500);
  // Deselect whatever is currently ticked - do not assume a starting state.
  let guard = 0;
  while (guard < 20) {
    guard += 1;
    const on = await evaluate(`[...document.querySelectorAll('.model-card.selected')].map(e=>e.dataset.model)`);
    if (!on.length) break;
    await click(`[data-model="${on[0]}"]`);
    await wait(120);
  }
  await wait(300);
  const zero = await evaluate(`document.getElementById('model-summary').textContent`);
  check('user can deselect down to zero', /0 models selected/.test(zero), zero);

  await click('#btn-models-back'); await wait(500);
  await click('#btn-get-started'); await wait(800);
  const afterReturn = await evaluate(`document.getElementById('model-summary').textContent`);
  check('returning to models does NOT re-tick anything',
    /0 models selected/.test(afterReturn), afterReturn);
  const selectedNow = await evaluate(`[...document.querySelectorAll('.model-card.selected')].map(e=>e.dataset.model)`);
  check('zero cards are selected after the round trip',
    selectedNow.length === 0, JSON.stringify(selectedNow));
  check('did not silently jump to another screen',
    (await visibleScreen()) === 'models', await visibleScreen());

  // Re-select just the recommended model for the remaining checks.
  await click('[data-model="qwen3:8b"]');
  await wait(250);
  const one = await evaluate(`document.getElementById('model-summary').textContent`);
  check('exactly one model selected when the user picks one', /1 model selected/.test(one), one);

  // --------------------------------------------------------- 4. game/music
  console.log('\n[4] game + music controls');
  const trackCount = await evaluate(`window.__clipifyTrackCount === undefined ? document.getElementById('music-count').textContent : ''`);
  const nextDisabled = await evaluate(`document.getElementById('btn-music-next').disabled`);
  check('next/prev enabled only when a playlist exists', nextDisabled === false, `count="${trackCount}"`);

  const t0 = await evaluate(`document.getElementById('music-title').textContent`);
  await click('#btn-music-next');
  await wait(500);
  const t1 = await evaluate(`document.getElementById('music-title').textContent`);
  check('next advances the track', t0 !== t1, `${t0} -> ${t1}`);
  await click('#btn-music-prev');
  await wait(500);
  check('prev goes back', (await evaluate(`document.getElementById('music-title').textContent`)) === t0);

  // Real playback: the element must actually have a decodable source.
  const audioSrc = await evaluate(`document.getElementById('audio').currentSrc || document.getElementById('audio').src`);
  check('audio element has a staged source', /clipifymusic:/.test(audioSrc), audioSrc);
  const canPlay = await evaluate(`new Promise(res => {
    const a = document.getElementById('audio');
    if (a.readyState >= 1) return res('ready:' + a.readyState);
    a.addEventListener('loadedmetadata', () => res('ready:' + a.readyState), { once: true });
    a.addEventListener('error', () => res('error:' + (a.error && a.error.code)), { once: true });
    setTimeout(() => res('timeout:' + a.readyState), 4000);
  })`);
  check('audio metadata loads (track is decodable)', /ready:[1-4]/.test(canPlay), canPlay);

  await click('#btn-music-mute');
  await wait(300);
  check('mute is obvious', await evaluate(`document.getElementById('music').classList.contains('muted')`),
    await evaluate(`document.getElementById('music-title').textContent`));
  check('mute silences the element',
    (await evaluate(`document.getElementById('audio').volume`)) === 0 ||
    (await evaluate(`document.getElementById('audio').paused`)) === true);
  await click('#btn-music-mute');
  await wait(200);
  check('unmute restores', !(await evaluate(`document.getElementById('music').classList.contains('muted')`)));

  const volBefore = await evaluate(`document.getElementById('audio').volume`);
  await evaluate(`(() => { const v=document.getElementById('music-volume'); v.value='80';
    v.dispatchEvent(new Event('input')); })()`);
  await wait(200);
  check('volume slider changes real volume',
    Math.abs((await evaluate(`document.getElementById('audio').volume`)) - 0.8) < 0.01,
    `${volBefore} -> ${await evaluate('document.getElementById("audio").volume')}`);

  const gameExists = await evaluate(`typeof window.ClipifyForestGame === 'object'`);
  check('firefly game module present', gameExists === true);

  // --------------------------------------------------------- 5. layout
  console.log('\n[5] layout at common resolutions');
  for (const [w, h] of [[1280, 720], [1366, 768], [1920, 1080], [1040, 760]]) {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await wait(500);
    const overflow = await evaluate(`(() => {
      const d=document.documentElement;
      const scrollable=(el)=>{for(let n=el.parentElement;n&&n!==document.body;n=n.parentElement){
        const ov=getComputedStyle(n).overflowY;
        if((ov==='auto'||ov==='scroll')&&n.scrollHeight>n.clientHeight+1)return true;}return false;};
      const over=[...document.querySelectorAll('.screen:not([hidden]) *, .statusbar, .music, .steps')]
        .filter(e=>{const r=e.getBoundingClientRect();
          if(!(r.width>0&&r.height>0)) return false;
          if(r.right>innerWidth+1||r.left<-1) return true;
          return r.bottom>innerHeight+1 && !scrollable(e);})
        .map(e=>e.className||e.tagName);
      return { vScroll: d.scrollHeight > d.clientHeight+1, hScroll: d.scrollWidth > d.clientWidth+1, over: over.slice(0,4) };
    })()`);
    check(`${w}x${h}: no page scrollbars`, !overflow.vScroll && !overflow.hScroll, JSON.stringify(overflow));
    check(`${w}x${h}: nothing clipped outside the window`, overflow.over.length === 0, JSON.stringify(overflow.over));
  }

  console.log('\n[6] console errors');
  check('no renderer console errors', consoleErrors.length === 0, consoleErrors.slice(0, 4).join(' | '));

  console.log(`\n===== ${passed} passed, ${failed} failed =====`);
  if (failures.length) {
    console.log('failures:');
    failures.forEach((f) => console.log('  - ' + f));
  }
  ws.close();
  process.exit(failed ? 1 : 0);
})();
