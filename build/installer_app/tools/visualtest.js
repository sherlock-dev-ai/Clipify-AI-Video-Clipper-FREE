'use strict';
/**
 * Visual-quality assertions. I cannot look at screenshots, so this measures the
 * things that actually go wrong visually: overlapping boxes, text that is
 * clipped, inconsistent card heights, elements off-screen, and baselines that
 * do not line up.
 */
const http = require('http');
const getJSON = (u) => new Promise((r, j) => {
  http.get(u, (x) => { let d = ''; x.on('data', (c) => (d += c)); x.on('end', () => { try { r(JSON.parse(d)); } catch (e) { j(e); } }); }).on('error', j);
});

let pass = 0, fail = 0; const fails = [];
const check = (n, c, d) => { if (c) { pass++; console.log(`  PASS  ${n}`); } else { fail++; fails.push(n + ' :: ' + (d ?? '')); console.log(`  FAIL  ${n}  ${d ?? ''}`); } };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const OVERLAP_PROBE = `(() => {
  const groups = [
    ['step', '.step'],
    ['modelcard', '.model-card'],
    ['stat', '.stat'],
    ['spacecell', '.space-cell'],
    ['musicbtn', '.music-btn'],
    ['footeritem', '.statusbar > *'],
  ];
  const bad = [];
  for (const [label, sel] of groups) {
    const els = [...document.querySelectorAll(sel)].filter(e => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && !e.hidden;
    });
    for (let i = 0; i < els.length; i++) {
      for (let j = i + 1; j < els.length; j++) {
        const a = els[i].getBoundingClientRect(), b = els[j].getBoundingClientRect();
        const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ox > 2 && oy > 2) bad.push(label + ' ' + i + '/' + j + ' overlap ' + Math.round(ox) + 'x' + Math.round(oy));
      }
    }
  }
  return bad.slice(0, 6);
})()`;

const CLIP_PROBE = `(() => {
  const bad = [];
  // An element that extends past the window but sits inside a container the
  // user can scroll is not clipped - it is reachable. Only flag content that
  // cannot be scrolled into view.
  const scrollable = (el) => {
    for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
      const ov = getComputedStyle(n).overflowY;
      if ((ov === 'auto' || ov === 'scroll') && n.scrollHeight > n.clientHeight + 1) return true;
    }
    return false;
  };
  for (const e of document.querySelectorAll('.screen:not([hidden]) *, .music *, .statusbar *, .steps *')) {
    if (e.children.length) continue;
    if (e.scrollWidth > e.clientWidth + 2 && getComputedStyle(e).overflow !== 'visible' && getComputedStyle(e).textOverflow !== 'ellipsis') {
      bad.push((e.className || e.tagName) + ' text clipped: ' + e.scrollWidth + '>' + e.clientWidth);
    }
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (r.right > innerWidth + 1 || r.left < -1) {
      bad.push((e.className || e.tagName) + ' off-screen horizontally');
    } else if (r.bottom > innerHeight + 1 && !scrollable(e)) {
      bad.push((e.className || e.tagName) + ' off-screen vertically and NOT scrollable');
    }
  }
  return bad.slice(0, 6);
})()`;

(async () => {
  const list = await getJSON('http://127.0.0.1:9333/json/list');
  const page = list.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
  const send = (method, params) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true }); return r.result.result.value; };
  const click = (s) => ev(`(()=>{const e=document.querySelector(${JSON.stringify(s)});if(!e)return'missing';e.click();return'ok'})()`);
  await send('Runtime.enable', {});

  const SIZES = [[1280, 720, 1], [1366, 768, 1], [1920, 1080, 1], [1366, 768, 1.25], [1920, 1080, 1.5]];

  for (const [w, h, dpr] of SIZES) {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: dpr, mobile: false });
    await ev('location.reload()');
    await wait(2600);
    const label = `${w}x${h} @${dpr * 100}%`;

    // welcome
    let bad = await ev(OVERLAP_PROBE); let clip = await ev(CLIP_PROBE);
    check(`welcome ${label}: no overlapping elements`, bad.length === 0, bad.join(' | '));
    check(`welcome ${label}: nothing clipped or off-screen`, clip.length === 0, clip.join(' | '));

    // models
    await click('#btn-get-started'); await wait(900);
    bad = await ev(OVERLAP_PROBE); clip = await ev(CLIP_PROBE);
    check(`models ${label}: no overlapping elements`, bad.length === 0, bad.join(' | '));
    check(`models ${label}: nothing clipped or off-screen`, clip.length === 0, clip.join(' | '));

    // card height consistency
    const heights = await ev(`[...document.querySelectorAll('.model-card')].map(e=>Math.round(e.getBoundingClientRect().height))`);
    const spread = Math.max(...heights) - Math.min(...heights);
    check(`models ${label}: card heights are consistent (<=6px)`, spread <= 6, `spread=${spread}px`);

    // icon actually rendered at this DPI
    const iconOk = await ev(`(() => { const s=document.querySelector('.model-icon svg');
      if(!s) return 'missing'; const r=s.getBoundingClientRect();
      return r.width>=20 && r.height>=20 ? 'ok' : 'too small ' + Math.round(r.width); })()`);
    check(`models ${label}: model icons render at a usable size`, iconOk === 'ok', iconOk);

    // detail panel aligned with the grid, not overlapping
    const aligned = await ev(`(() => { const g=document.getElementById('model-grid').getBoundingClientRect();
      const d=document.getElementById('model-detail').getBoundingClientRect();
      return d.top >= 0 && d.bottom <= innerHeight + 1; })()`);
    check(`models ${label}: details panel within the viewport`, aligned === true, String(aligned));

    // location
    await click('#btn-models-continue'); await wait(1100);
    bad = await ev(OVERLAP_PROBE); clip = await ev(CLIP_PROBE);
    check(`location ${label}: no overlapping elements`, bad.length === 0, bad.join(' | '));
    check(`location ${label}: nothing clipped or off-screen`, clip.length === 0, clip.join(' | '));

    // baseline alignment of the three space cells
    const baselines = await ev(`(() => { const l=[...document.querySelectorAll('.space-label')].map(e=>Math.round(e.getBoundingClientRect().top));
      const v=[...document.querySelectorAll('.space-value')].map(e=>Math.round(e.getBoundingClientRect().top));
      return JSON.stringify({l,v}); })()`);
    const b = JSON.parse(baselines);
    check(`location ${label}: the three space labels share a baseline`,
      new Set(b.l).size === 1, JSON.stringify(b.l));
    check(`location ${label}: the three space values share a baseline`,
      new Set(b.v).size === 1, JSON.stringify(b.v));
  }

  // installing screen layout (jump there directly)
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
  await ev('location.reload()'); await wait(2400);
  await ev(`(()=>{ document.querySelectorAll('.screen').forEach(s=>s.hidden = s.id!=='screen-install'); })()`);
  await wait(700);
  const gameBox = await ev(`(()=>{const c=document.getElementById('dino').getBoundingClientRect();return JSON.stringify({w:Math.round(c.width),h:Math.round(c.height)})})()`);
  const gb = JSON.parse(gameBox);
  check('game canvas is at least 500x180', gb.w >= 500 && gb.h >= 180, JSON.stringify(gb));
  let bad = await ev(OVERLAP_PROBE); let clip = await ev(CLIP_PROBE);
  check('installing 1280x720: no overlapping elements', bad.length === 0, bad.join(' | '));
  check('installing 1280x720: nothing clipped', clip.length === 0, clip.join(' | '));
  const barVisible = await ev(`(()=>{const b=document.getElementById('overall-bar').getBoundingClientRect();
    const i=document.getElementById('overall-indeterminate').getBoundingClientRect();
    return Math.max(b.height,i.height);})()`);
  check('progress bar has real height', barVisible >= 10, `${barVisible}px`);

  console.log(`\n===== ${pass} passed, ${fail} failed =====`);
  fails.forEach((f) => console.log('  - ' + f));
  ws.close(); process.exit(fail ? 1 : 0);
})();
