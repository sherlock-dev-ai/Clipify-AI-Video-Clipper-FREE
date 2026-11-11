'use strict';
/** Diagnostic: what does the window actually show, and did anything go wrong? */
const http = require('http');
const getJSON = (u) => new Promise((res, rej) => {
  http.get(u, (r) => { let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } }); }).on('error', rej);
});
(async () => {
  const list = await getJSON('http://127.0.0.1:9333/json/list');
  const targets = list.map((t) => ({ type: t.type, title: t.title, url: t.url.split('\\').pop() }));
  console.log('TARGETS:', JSON.stringify(targets, null, 1));
  const page = list.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pending = new Map(); const errs = [];
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') errs.push(m.params.exceptionDetails.text + ' ' + ((m.params.exceptionDetails.exception || {}).description || '').split('\n')[0]);
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errs.push('console: ' + m.params.args.map((a) => a.value || a.description).join(' '));
  });
  const send = (method, params) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true }); return r.result.result.value; };
  await send('Runtime.enable', {});

  console.log('\nSCREENS:', await ev(`JSON.stringify([...document.querySelectorAll('.screen')].map(s=>({id:s.dataset.screen, hidden:s.hidden})))`));
  console.log('LOCATION HASH:', await ev('location.href'));
  console.log('READY STATE:', await ev('document.readyState'));
  console.log('UI MARKERS:', await ev(`JSON.stringify({
    mountains: !!document.querySelector('.mountains svg'),
    musicTime: !!document.getElementById('music-time'),
    github: !!document.getElementById('btn-github'),
    icons: document.querySelectorAll('.model-icon svg').length,
    fireflies: document.querySelectorAll('.firefly').length,
    clouds: document.querySelectorAll('.cloud').length,
    trees: document.querySelectorAll('.tree').length,
    grass: document.querySelectorAll('.blade').length,
    weather: document.body.dataset.weather
  })`));
  console.log('GAME:', await ev(`JSON.stringify({ firefly: typeof window.ClipifyForestGame, canvas: !!document.getElementById('forest-game') })`));
  console.log('ERRORS:', errs.length ? errs.slice(0, 6) : 'none');
  ws.close(); process.exit(0);
})();
