'use strict';
const d = require('../lib/detect.js');

const cases = [
  ['missing drive', 'C:\\nonexistent-drive-xyz\\ClipifyAI'],
  ['Z drive', 'Z:\\x'],
  ['default', 'C:\\Users\\Dell\\AppData\\Local\\Programs\\ClipifyAI'],
  ['D drive', 'D:\\ClipifyAI'],
  ['UNC', '\\\\server\\share\\ClipifyAI'],
  ['relative', 'relative\\path'],
  ['empty', ''],
  ['undefined', undefined],
  ['illegal chars', 'C:\\Clipify<AI>'],
  ['file in the way', 'C:\\Windows\\System32\\notepad.exe'],
];

(async () => {
  for (const [label, value] of cases) {
    const v = d.validateInstallDir(value);
    const s = await d.diskSpaceAsync(value);
    console.log(
      label.padEnd(16),
      'valid=' + String(v.ok).padEnd(5),
      'vol=' + String(s.volume).padEnd(6),
      'free=' + (s.freeBytes / 1e9).toFixed(1).padStart(6) + 'GB',
      (v.message || s.error || '').slice(0, 58)
    );
  }
})();
