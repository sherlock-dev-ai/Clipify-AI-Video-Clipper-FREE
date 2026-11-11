'use strict';
/**
 * Why are the model cards invisible, and why were 9 models selected?
 * Prints hard evidence rather than guesses.
 */
const http = require('http');
const getJSON = (u) => new Promise((r, j) => {
  http.get(u, (x) => { let d = ''; x.on('data', (c) => (d += c)); x.on('end', () => { try { r(JSON.parse(d)); } catch (e) { j(e); } }); }).on('error', j);
});
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const list = await getJSON('http://127.0.0.1:9333/json/list');
  const page = list.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pending = new Map(); const errs = [];
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') errs.push('EXC: ' + m.params.exceptionDetails.text + ' ' + ((m.params.exceptionDetails.exception || {}).description || '').split('\n')[0]);
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errs.push('ERR: ' + m.params.args.map((a) => a.value || a.description).join(' '));
  });
  const send = (m, p) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
  const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) return 'THREW: ' + r.result.exceptionDetails.text; return r.result.result.value; };
  const click = (s) => ev(`(()=>{const e=document.querySelector(${JSON.stringify(s)});if(!e)return'missing';e.click();return'ok'})()`);
  await send('Runtime.enable', {});

  const SIZES = [[1040, 760], [1280, 720], [1366, 768], [1920, 1080], [900, 680]];

  for (const [w, h] of SIZES) {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await ev('location.reload()');
    await wait(2500);
    await click('#btn-get-started');
    await wait(1000);

    const report = await ev(`(() => {
      const grid = document.getElementById('model-grid');
      const cards = [...grid.querySelectorAll('.model-card')];
      const gr = grid.getBoundingClientRect();
      const cr0 = cards[0] ? cards[0].getBoundingClientRect() : null;
      const main = document.querySelector('.models-main').getBoundingClientRect();
      const side = document.getElementById('model-detail').getBoundingClientRect();
      const cs = getComputedStyle(grid);
      return JSON.stringify({
        gridFound: !!grid,
        cards: cards.length,
        selectedCards: cards.filter(c => c.classList.contains('selected')).length,
        summary: document.getElementById('model-summary').textContent,
        gridH: Math.round(gr.height), gridW: Math.round(gr.width), gridTop: Math.round(gr.top), gridBottom: Math.round(gr.bottom),
        gridOverflowY: cs.overflowY, gridFlex: cs.flex, gridMaxH: cs.maxHeight,
        scrollH: grid.scrollHeight, clientH: grid.clientHeight,
        firstCard: cr0 ? { w: Math.round(cr0.width), h: Math.round(cr0.height), top: Math.round(cr0.top) } : null,
        mainH: Math.round(main.height),
        sideH: Math.round(side.height),
        innerH: window.innerHeight,
        firstCardVisible: cr0 ? (cr0.height > 0 && cr0.top >= 0 && cr0.top < window.innerHeight) : false
      });
    })()`);
    console.log(`\n[${w}x${h}]`, report);
  }

  console.log('\nJS ERRORS:', errs.length ? errs.slice(0, 8) : 'none');
  ws.close(); process.exit(0);
})();
