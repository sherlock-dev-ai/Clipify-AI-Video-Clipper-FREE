'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { buildDownloadWarning, selectedModelDownloadBytes } = require('../renderer/download_warning');

const appSource = fs.readFileSync(path.join(__dirname, '../renderer/app.js'), 'utf8');
const htmlSource = fs.readFileSync(path.join(__dirname, '../renderer/index.html'), 'utf8');
assert(appSource.includes("selected · ${formatBytes(bytes)} to download"));
assert(!/[Â][·]|â[€][”¦]/u.test(`${appSource}\n${htmlSource}`));
console.log('PASS installer summary uses correctly encoded separators and status punctuation');

const cachedRuntime = {
  runtimeBytes: 0,
  runtimeInTarget: true,
  ollamaBytes: 0,
  models: [{ id: 'qwen3:8b', name: 'Qwen3 8B', sizeBytes: 5_230_000_000, installed: true }],
};
const noDownloads = buildDownloadWarning(cachedRuntime, {
  models: [], installRuntime: true, installOllama: true,
});
assert.strictEqual(noDownloads.bytes, 0);
assert.match(noDownloads.body, /No AI model, runtime, or Ollama downloads/);
assert(!/gigabytes|100%|GPU|CPU/i.test(`${noDownloads.title} ${noDownloads.body} ${noDownloads.estimate}`));
assert.deepStrictEqual(noDownloads.details, []);
assert.strictEqual(selectedModelDownloadBytes(cachedRuntime, ['qwen3:8b']), 0);
console.log('PASS zero models and an already-present runtime do not claim a large download');
console.log('PASS a selected model already in Ollama contributes zero bytes to the model-selection summary');

const missingRuntime = buildDownloadWarning({
  runtimeBytes: 2_700_000_000,
  runtimeInTarget: false,
  ollamaBytes: 0,
  models: [],
}, { models: [], installRuntime: true, installOllama: false });
assert.strictEqual(missingRuntime.bytes, 2_700_000_000);
assert(missingRuntime.details.some((line) => /AI runtime.*2.70 GB.*download/i.test(line)));
assert(/2.70 GB/.test(missingRuntime.estimate));
console.log('PASS a missing selected runtime is included in the warning');

const missingNarrationModel = buildDownloadWarning({
  runtimeBytes: 13 * 1024 ** 2,
  runtimeInTarget: true,
  ollamaBytes: 0,
  models: [],
}, { models: [], installRuntime: true, installOllama: false });
assert.strictEqual(missingNarrationModel.bytes, 13 * 1024 ** 2);
assert(missingNarrationModel.details.some((line) => /AI runtime.*13\.6 MB.*download/i.test(line)));
assert(!/gigabytes|5\.23 GB/i.test(missingNarrationModel.estimate));
console.log('PASS a core runtime missing only the Kokoro language model estimates only that wheel');

const selectedModels = buildDownloadWarning({
  runtimeBytes: 2_700_000_000,
  runtimeInTarget: false,
  ollamaBytes: 0,
  models: [
    { id: 'qwen3:8b', name: 'Qwen3 8B', sizeBytes: 5_230_000_000, installed: false },
    { id: 'qwen3:4b', name: 'Qwen3 4B', sizeBytes: 2_500_000_000, installed: true },
  ],
}, { models: ['qwen3:8b', 'qwen3:4b'], installRuntime: false, installOllama: false });
assert.strictEqual(selectedModels.bytes, 5_230_000_000);
assert.strictEqual(selectedModelDownloadBytes({ models: [
  { id: 'qwen3:8b', sizeBytes: 5_230_000_000, installed: false },
  { id: 'qwen3:4b', sizeBytes: 2_500_000_000, installed: true },
] }, ['qwen3:8b', 'qwen3:4b']), 5_230_000_000);
assert(selectedModels.details.some((line) => /Qwen3 8B.*5.23 GB/.test(line)));
assert(!selectedModels.details.some((line) => /Qwen3 4B/.test(line)));
console.log('PASS selected uncached models are estimated; cached models are excluded');
