import { spawn } from 'child_process';
import http from 'http';
import fs from 'fs';
import path from 'path';

const outDir = 'C:\\Users\\Dell\\.gemini\\antigravity\\brain\\5bf1f793-a593-488a-8501-e22f375c5231';
const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const debugPort = 9266;
const tempUserData = path.join(process.env.TEMP, 'edge_verify_' + Date.now());

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
  await new Promise(r => setTimeout(r, 2500));
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

  // 1. Trending Section
  console.log('[1/2] Verifying Trending streams & gameplay cards...');
  await send('Runtime.evaluate', {
    expression: `
      if (typeof window.navigateTo === 'function') window.navigateTo('trending');
      if (typeof window.loadTrending === 'function') window.loadTrending();
    `
  });
  await new Promise(r => setTimeout(r, 2500));

  let res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'trending_verified_v503.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved trending_verified_v503.png');

  // 2. Editor Section & wassap text overlay
  console.log('[2/2] Verifying Editor caption background box removal...');
  await send('Runtime.evaluate', {
    expression: `(() => {
      if (typeof window.navigateTo === 'function') window.navigateTo('editor');
      const txtInput = document.getElementById('editorTextValue');
      if (txtInput) {
        txtInput.value = 'wassap';
        txtInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
      const txt = document.getElementById('editorText');
      const bgBox = document.getElementById('editorTextBg');
      return {
        textVal: txtInput ? txtInput.value : '',
        bgChecked: bgBox ? bgBox.checked : false,
        elementBg: txt ? window.getComputedStyle(txt).backgroundColor : '',
        textContent: txt ? txt.textContent : ''
      };
    })()`,
    returnByValue: true
  });
  await new Promise(r => setTimeout(r, 1500));

  res = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, 'editor_clean_caption_v503.png'), Buffer.from(res.result.data, 'base64'));
  console.log('Saved editor_clean_caption_v503.png');

  ws.close();
  edgeProc.kill();
  try { fs.rmSync(tempUserData, { recursive: true, force: true }); } catch (e) {}
  console.log('✓ Visual verification complete!');
}

run().catch(e => {
  console.error('Error during verification:', e);
  edgeProc.kill();
});

