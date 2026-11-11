'use strict';
/**
 * Screenshot + console-error capture for the running setup window.
 * Usage: node tools/shot.js <outfile.png> [width] [height]
 */
const fs = require('fs');
const http = require('http');

const out = process.argv[2] || 'shot.png';
const W = Number(process.argv[3] || 1040);
const H = Number(process.argv[4] || 760);

const getJSON = (url) =>
  new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            reject(e);
          }
        });
      })
      .on('error', reject);
  });

(async () => {
  const list = await getJSON('http://127.0.0.1:9333/json/list');
  const target = list.find((t) => t.type === 'page');
  if (!target) {
    console.log('no page target');
    process.exit(2);
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m);
      pending.delete(m.id);
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      console.log('CONSOLE ERROR:', JSON.stringify(m.params.args.map((a) => a.value || a.description)));
    }
    if (m.method === 'Runtime.exceptionThrown') {
      console.log('EXCEPTION:', m.params.exceptionDetails.text, m.params.exceptionDetails.exception && m.params.exceptionDetails.exception.description);
    }
  });
  const send = (method, params) =>
    new Promise((res) => {
      const i = ++id;
      pending.set(i, res);
      ws.send(JSON.stringify({ id: i, method, params }));
    });

  await send('Runtime.enable', {});
  await send('Page.enable', {});
  await send('Emulation.setDeviceMetricsOverride', {
    width: W, height: H, deviceScaleFactor: 1, mobile: false,
  });
  await new Promise((r) => setTimeout(r, 2200));
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  if (!shot.result || !shot.result.data) {
    console.log('screenshot failed:', JSON.stringify(shot).slice(0, 300));
    process.exit(3);
  }
  fs.writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
  console.log('wrote', out, fs.statSync(out).size, 'bytes');

  const probe = await send('Runtime.evaluate', {
    expression: `JSON.stringify({
      weather: document.body.dataset.weather,
      screen: [...document.querySelectorAll('.screen')].find(s=>!s.hidden)?.dataset.screen,
      steps: [...document.querySelectorAll('.step')].map(e=>e.className),
      models: document.querySelectorAll('.model-card').length,
      music: document.getElementById('music-title')?.textContent,
      detect: document.getElementById('welcome-detect')?.textContent
    })`,
    returnByValue: true,
  });
  console.log('STATE', probe.result && probe.result.result && probe.result.result.value);
  ws.close();
  process.exit(0);
})();
