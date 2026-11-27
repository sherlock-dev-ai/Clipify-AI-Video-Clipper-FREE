import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';
import path from 'path';

const outDir = 'C:\\Users\\Dell\\.gemini\\antigravity\\brain\\5bf1f793-a593-488a-8501-e22f375c5231';
const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const debugPort = 9244;
const tempUserData = path.join(process.env.TEMP, 'edge_v502_' + Date.now());

const edgeProc = spawn(edgePath, [
  `--remote-debugging-port=${debugPort}`,
  `--user-data-dir=${tempUserData}`,
  '--no-first-run',
  '--no-default-browser-check',
  '--headless=new',
  '--window-size=1440,960',
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
  await new Promise(r => setTimeout(r, 2000));
  const list = await getJson(`http://127.0.0.1:${debugPort}/json`);
  const page = list.find(t => t.type === 'page');
  const wsUrl = page.webSocketDebuggerUrl;

  const ws = new WebSocket(wsUrl);

  let msgId = 1;
  const pending = new Map();
  ws.on('message', raw => {
    const data = JSON.parse(raw);
    if (data.id && pending.has(data.id)) {
      pending.get(data.id)(data);
      pending.delete(data.id);
    }
  });

  function send(method, params = {}) {
    return new Promise(resolve => {
      const id = msgId++;
      pending.set(id, resolve);
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  await new Promise(r => ws.on('open', r));
  await send('Page.enable');
  await send('Runtime.enable');

  // 1. Verify Campaigns Modal
  console.log('Testing Campaigns Modal...');
  await send('Runtime.evaluate', {
    expression: `
      window.location.hash = '#campaigns';
      if (typeof window.showCampaignsModal === 'function') window.showCampaignsModal();
    `
  });
  await new Promise(r => setTimeout(r, 1200));
  let res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'campaigns_modal_v502.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved campaigns_modal_v502.png');

  // Close modal
  await send('Runtime.evaluate', {
    expression: `
      const overlay = document.getElementById('campaignsModalOverlay');
      if (overlay) { overlay.classList.remove('active'); overlay.style.display = 'none'; }
    `
  });
  await new Promise(r => setTimeout(r, 400));

  // 2. Verify Trending Section
  console.log('Testing Trending Section...');
  await send('Runtime.evaluate', {
    expression: `
      if (typeof window.navigateTo === 'function') window.navigateTo('trending');
    `
  });
  await new Promise(r => setTimeout(r, 2500));
  res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'trending_v502.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved trending_v502.png');

  // 3. Verify Beta Features (Captions, Languages, Playground)
  console.log('Testing Beta Features...');
  await send('Runtime.evaluate', {
    expression: `
      if (typeof window.navigateTo === 'function') window.navigateTo('beta');
      const el = document.getElementById('betaCaptionsSettingsContainer');
      if (el) el.scrollIntoView({ behavior: 'instant', block: 'center' });
    `
  });
  await new Promise(r => setTimeout(r, 1500));
  res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'beta_captions_v502.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved beta_captions_v502.png');

  ws.close();
  edgeProc.kill();
  try { fs.rmSync(tempUserData, { recursive: true, force: true }); } catch (e) {}
  console.log('All verification screenshots captured!');
}

run().catch(e => {
  console.error(e);
  edgeProc.kill();
  process.exit(1);
});
