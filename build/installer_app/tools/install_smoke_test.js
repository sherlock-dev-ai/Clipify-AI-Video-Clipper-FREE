'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { Installer, PYTHON_URL } = require(path.join(process.env.CLIPIFY_TEST_APP_ROOT, 'lib', 'installer'));

async function main() {
  const installDir = path.resolve(process.env.CLIPIFY_TEST_INSTALL_DIR || '');
  const payloadRoot = path.resolve(process.env.CLIPIFY_TEST_PAYLOAD || '');
  const expectedLauncher = String(process.env.CLIPIFY_EXPECTED_LAUNCHER_SHA256 || '').toUpperCase();
  const expectedWorker = String(process.env.CLIPIFY_EXPECTED_WORKER_SHA256 || '').toUpperCase();
  if (!installDir || !payloadRoot || !expectedLauncher || !expectedWorker) {
    throw new Error('Set CLIPIFY_TEST_INSTALL_DIR, CLIPIFY_TEST_PAYLOAD and both expected SHA-256 values.');
  }

  const resultRoot = path.resolve(process.env.CLIPIFY_TEST_RESULT_DIR || path.dirname(installDir));
  const engine = new Installer({
    payloadRoot,
    logPath: path.join(resultRoot, 'installer-engine.log'),
    statePath: path.join(resultRoot, 'installer-engine-state.json'),
  });
  const pythonArchive = process.env.CLIPIFY_TEST_PYTHON_ARCHIVE
    ? path.resolve(process.env.CLIPIFY_TEST_PYTHON_ARCHIVE)
    : null;
  let pythonArchiveSha256 = null;
  if (pythonArchive) {
    assert(fs.existsSync(pythonArchive), `cached Python archive does not exist: ${pythonArchive}`);
    const bytes = fs.readFileSync(pythonArchive);
    pythonArchiveSha256 = crypto.createHash('sha256').update(bytes).digest('hex').toUpperCase();
    engine.downloadFile = async (url, destination, onProgress) => {
      if (url !== PYTHON_URL) throw new Error(`Unexpected cached archive URL: ${url}`);
      await fs.promises.copyFile(pythonArchive, destination);
      const size = fs.statSync(destination).size;
      onProgress(size, size);
    };
  }
  engine.options = {
    installDir,
    installRuntime: true,
    installOllama: false,
    models: [],
    desktopShortcut: false,
  };
  const shortcutRequests = [];
  engine.on('create-shortcut', (request) => shortcutRequests.push(request));
  let failed = null;
  engine.on('failed', (event) => { failed = event; });

  await engine.start(engine.options);
  assert.strictEqual(failed, null, JSON.stringify(failed));
  for (const id of ['files', 'python', 'runtime', 'models', 'shortcuts']) {
    assert.strictEqual(engine.phaseState[id].status, 'done', `${id} phase: ${JSON.stringify(engine.phaseState[id])}`);
  }
  assert.strictEqual(engine.phaseState.ollama.status, 'skipped');

  const launcher = path.join(installDir, 'Clipify AI.exe');
  const worker = path.join(installDir, 'main.exe');
  const launcherHash = require('crypto').createHash('sha256').update(fs.readFileSync(launcher)).digest('hex').toUpperCase();
  const workerHash = require('crypto').createHash('sha256').update(fs.readFileSync(worker)).digest('hex').toUpperCase();
  assert.strictEqual(launcherHash, expectedLauncher);
  assert.strictEqual(workerHash, expectedWorker);
  assert(fs.existsSync(path.join(installDir, 'python311', 'python.exe')));
  assert(fs.existsSync(path.join(installDir, 'runtime', '.clipify-runtime-complete')));
  assert(fs.existsSync(path.join(installDir, 'input')));
  assert(fs.existsSync(path.join(installDir, 'jobs')));
  assert.strictEqual(fs.existsSync(path.join(installDir, 'models')), false);

  const state = JSON.parse(fs.readFileSync(path.join(resultRoot, 'installer-engine-state.json'), 'utf8'));
  assert.strictEqual(state.status, 'complete');
  const result = {
    result: 'PASS',
    installDir,
    payloadRoot,
    launcherSha256: launcherHash,
    workerSha256: workerHash,
    phases: engine.phaseState,
    pythonPath: path.join(installDir, 'python311', 'python.exe'),
    runtimePath: path.join(installDir, 'runtime'),
    pythonArchive,
    pythonArchiveSha256,
    modelsRequested: [],
    shortcutsRequested: shortcutRequests.map((entry) => entry.shortcutPath),
    stateFile: path.join(resultRoot, 'installer-engine-state.json'),
    logFile: path.join(resultRoot, 'installer-engine.log'),
  };
  fs.writeFileSync(path.join(resultRoot, 'install-smoke-result.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
