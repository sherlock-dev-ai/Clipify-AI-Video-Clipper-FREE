import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';
import path from 'path';

const outDir = 'C:\\Users\\Dell\\.gemini\\antigravity\\brain\\5bf1f793-a593-488a-8501-e22f375c5231';
const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const debugPort = 9255;
const tempUserData = path.join(process.env.TEMP, 'edge_v503_' + Date.now());

const edgeProc = spawn(edgePath, [
  `--remote-debugging-port=${debugPort}`,
  `--user-data-dir=${tempUserData}`,
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-sync',
  '--guest',
  '--headless=new',
  '--window-size=1440,1100',
  'http://127.0.0.1:5000/'
]);

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

async function run() {
  await new Promise(r => setTimeout(r, 2200));
  const list = await getJson(`http://127.0.0.1:${debugPort}/json`);
  const page = list.find(t => t.type === 'page');
  const wsUrl = page.webSocketDebuggerUrl;

  const ws = new WebSocket(wsUrl);

  let msgId = 1;
  const pending = new Map();
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.id && pending.has(data.id)) {
      pending.get(data.id)(data);
      pending.delete(data.id);
    }
  };

  function send(method, params = {}) {
    return new Promise(resolve => {
      const id = msgId++;
      pending.set(id, resolve);
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  await new Promise(r => {
    if (ws.readyState === 1) r();
    else ws.onopen = r;
  });

  await send('Page.enable');
  await send('Runtime.enable');

  console.log('[1/4] Testing Editor Section & Clipped Shorts Filmstrip Tray...');
  await send('Runtime.evaluate', {
    expression: `
      if (typeof window.navigateTo === 'function') window.navigateTo('editor');
      if (typeof window.renderEditorShortsTray === 'function') window.renderEditorShortsTray();
    `
  });
  await new Promise(r => setTimeout(r, 2000));

  let res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'editor_v503.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved editor_v503.png');

  // Test selecting a clip and applying a preset
  console.log('[2/4] Testing Card Selection, Preset Styling & Arrangement in Editor...');
  const evalResult = await send('Runtime.evaluate', {
    expression: `(() => {
      const cards = document.querySelectorAll('.editor-short-card');
      if (cards.length > 0) {
        cards[0].click();
      }
      const cyberLime = document.querySelector('.editor-cap-pill[data-preset="lime_green"]');
      if (cyberLime) cyberLime.click();
      const centerBtn = document.querySelector('.btn-arrange-pos[data-y="50"]');
      if (centerBtn) centerBtn.click();

      const tray = document.getElementById('editorShortsTrayContainer');
      if (tray) tray.scrollIntoView({ behavior: 'instant', block: 'end' });
      window.scrollTo(0, 650);
      return {
        cardsCount: cards.length,
        firstClip: cards[0]?.dataset.filename || 'none',
        editorTitle: document.getElementById('reviewTitle')?.textContent || ''
      };
    })()`,
    returnByValue: true
  });
  console.log('Card selection result:', evalResult.result?.value);
  await new Promise(r => setTimeout(r, 1200));

  res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'editor_clip_selected_v503.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved editor_clip_selected_v503.png');

  // Test Trending Section
  console.log('[3/4] Testing Trending Section...');
  await send('Runtime.evaluate', {
    expression: `
      if (typeof window.navigateTo === 'function') window.navigateTo('trending');
    `
  });
  await new Promise(r => setTimeout(r, 2000));
  res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'trending_v503.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved trending_v503.png');

  // Test Instant Section
  console.log('[4/4] Testing Instant Clipping Section...');
  await send('Runtime.evaluate', {
    expression: `
      if (typeof window.navigateTo === 'function') window.navigateTo('instant');
    `
  });
  await new Promise(r => setTimeout(r, 1200));
  res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'instant_v503.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved instant_v503.png');

  ws.close();
  edgeProc.kill();
  try { fs.rmSync(tempUserData, { recursive: true, force: true }); } catch (e) {}
  console.log('✓ All v5.0.3 verification screenshots captured successfully!');
}

run().catch(e => {
  console.error('Error during verification:', e);
  edgeProc.kill();
  process.exit(1);
});
