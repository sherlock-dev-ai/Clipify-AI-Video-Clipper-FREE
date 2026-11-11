const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');

const PORT = 9471;
const EXE = process.argv[2] || 'node_modules/electron/dist/electron.exe';
const ARGS = process.argv[2] ? [`--remote-debugging-port=${PORT}`] : ['.', `--remote-debugging-port=${PORT}`];
const p = spawn(EXE, ARGS, { stdio: ['ignore', 'pipe', 'pipe'] });
p.stderr.on('data', (d) => process.stdout.write('MAIN ' + String(d).slice(0, 300)));

const get = (u) => new Promise((res, rej) => http.get(u, (r) => { let b = ''; r.on('data', (c) => (b += c)); r.on('end', () => res(b)); }).on('error', rej));

(async () => {
  let list = null;
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    try { list = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)); if (list.length) break; } catch (e) {}
  }
  const t = list.find((x) => x.type === 'page');
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  let id = 0; const pend = {};
  const send = (m, pr) => new Promise((r) => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method: m, params: pr || {} })); });
  await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
  ws.addEventListener('message', (d) => {
    const m = JSON.parse(d.data);
    if (m.method === 'Runtime.consoleAPICalled') {
      process.stdout.write('CONSOLE[' + m.params.type + '] ' + m.params.args.map((a) => a.value ?? a.description ?? '').join(' ') + '\n');
    }
    if (m.method === 'Runtime.exceptionThrown') {
      const e = m.params.exceptionDetails;
      process.stdout.write('EXCEPTION ' + (e.exception && e.exception.description || e.text) + '\n');
    }
    if (m.id && pend[m.id]) { pend[m.id](m); delete pend[m.id]; }
  });
  await send('Runtime.enable');
  const ev = async (e) => {
    const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) return 'THREW: ' + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
    return r.result && r.result.result ? r.result.result.value : undefined;
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const step = (s) => ev(`(()=>{const e=document.getElementById('screen-${s}');return e?(e.hidden?'hidden':'VISIBLE'):'MISSING'})()`);
  const steps = () => ev("Array.from(document.querySelectorAll('.step')).map(e=>e.textContent.trim().replace(/\\s+/g,' ')+(e.classList.contains('active')?' [ACTIVE]':(e.classList.contains('done')?' [done]':''))).join(' | ')");

  await wait(8000);
  console.log('DIAG INSTALL BUTTON CLICKED');
  await ev("window.__diag=[];const _s=console.error;console.error=(...a)=>{window.__diag.push(String(a[0]));_s(...a)};1");
  await ev("window.addEventListener('error',e=>window.__diag.push('WINERR '+e.message));1");
  await ev("window.addEventListener('unhandledrejection',e=>window.__diag.push('REJECT '+e.reason));1");

  await ev("document.getElementById('btn-get-started').click()");
  await wait(7000);
  console.log('after get-started -> models:', await step('models'), '| selected:', await ev("Array.from(document.querySelectorAll('#model-grid .model-card.selected')).length"));

  await ev("document.getElementById('btn-models-continue').click()");
  await wait(6000);
  console.log('after models-continue -> location:', await step('location'));
  console.log('STEP INDICATOR:', await steps());

  console.log('--- clicking INSTALL ---');
  const r = await ev("(()=>{try{document.getElementById('btn-install').click();return 'clicked'}catch(e){return 'CLICK THREW: '+e.message}})()");
  console.log('click result:', r);
  await wait(4000);
  console.log('after INSTALL -> install screen:', await step('install'));
  console.log('STEP INDICATOR:', await steps());
  console.log('diag errors:', JSON.stringify(await ev("window.__diag")));
  console.log('current-item:', await ev("(document.getElementById('current-item')||{}).textContent"));
  console.log('error-box hidden:', await ev("(document.getElementById('error-box')||{}).hidden"));
  console.log('error-box text:', await ev("(document.getElementById('error-box')||{}).innerText"));

  p.kill();
  process.exit(0);
})().catch((e) => { console.log('HARNESS ERR', e.message); p.kill(); process.exit(1); });
