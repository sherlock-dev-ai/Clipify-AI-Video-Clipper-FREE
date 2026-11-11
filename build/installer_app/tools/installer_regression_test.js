'use strict';

const assert = require('assert');
const fs = require('fs');
const http = require('http');
const path = require('path');
const appRoot = path.resolve(process.env.CLIPIFY_TEST_APP_ROOT || path.join(__dirname, '..'));
const { Installer } = require(path.join(appRoot, 'lib', 'installer'));
const { uniqueSibling, retryFileOperation, acquireInstallLock, copyDirectoryContents } = require(path.join(appRoot, 'lib', 'filesystem'));
const { removeBundledFiles } = require(path.join(appRoot, 'lib', 'uninstall'));
const { findOllama, detectAll, DEFAULT_ID, UNINSTALL_KEY, validateInstallDir, defaultInstallDir, isDevelopmentCheckout, isolatedInstallDir, APP_SLUG, RUNTIME_COMPLETE_MARKER, NARRATION_MODEL_BYTES, payloadSummary } = require(path.join(appRoot, 'lib', 'detect'));

function getOllamaTags() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:11434/api/tags', (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    }).on('error', reject);
  });
}

async function main() {
  const root = process.env.CLIPIFY_TEST_ROOT;
  if (!root) throw new Error('Set CLIPIFY_TEST_ROOT to a new workspace directory.');
  fs.mkdirSync(root, { recursive: false });
  const candidateA = uniqueSibling(root, 'stage');
  const candidateB = uniqueSibling(root, 'stage');
  assert.notStrictEqual(candidateA, candidateB, 'each staging attempt must receive a unique path');
  let transientAttempts = 0;
  const retried = await retryFileOperation(async () => {
    transientAttempts += 1;
    if (transientAttempts < 3) throw Object.assign(new Error('temporary file lock'), { code: 'EPERM' });
    return 'copied';
  }, { attempts: 4, delayMs: 0, wait: async () => {} });
  assert.strictEqual(retried, 'copied');
  assert.strictEqual(transientAttempts, 3, 'transient Windows sharing errors should be retried with a bound');
  const lockPath = path.join(root, 'setup.lock');
  const release = acquireInstallLock(lockPath, path.join(root, 'install'));
  assert.throws(() => acquireInstallLock(lockPath, path.join(root, 'other-install')), { code: 'INSTALL_LOCKED' });
  release();
  assert.strictEqual(fs.existsSync(lockPath), false, 'the owner releases only its lock file');
  const deadLockPath = path.join(root, 'dead-owner.lock');
  fs.writeFileSync(deadLockPath, JSON.stringify({ pid: 4321, token: 'stale-owner', target: path.join(root, 'old') }));
  const recoveryProcess = { pid: 8765, kill(pid) {
    if (pid === 8765) return;
    throw Object.assign(new Error('process is gone'), { code: 'ESRCH' });
  } };
  const recoveredRelease = acquireInstallLock(deadLockPath, path.join(root, 'install'), { processApi: recoveryProcess });
  recoveredRelease();
  const freshMalformedLock = path.join(root, 'malformed-fresh.lock');
  fs.writeFileSync(freshMalformedLock, '{partial');
  assert.throws(() => acquireInstallLock(freshMalformedLock, path.join(root, 'install')), { code: 'INSTALL_LOCKED' });
  const oldMalformedLock = path.join(root, 'malformed-stale.lock');
  fs.writeFileSync(oldMalformedLock, '{partial');
  const oldTime = new Date(Date.now() - 10 * 60 * 1000);
  fs.utimesSync(oldMalformedLock, oldTime, oldTime);
  const malformedRelease = acquireInstallLock(oldMalformedLock, path.join(root, 'install'), { processApi: recoveryProcess });
  malformedRelease();
  const copySource = path.join(root, 'copy-source');
  const copyTarget = path.join(root, 'copy-target');
  fs.mkdirSync(copySource);
  fs.writeFileSync(path.join(copySource, 'runtime.txt'), 'verified');
  await copyDirectoryContents(copySource, copyTarget);
  assert.strictEqual(fs.readFileSync(path.join(copyTarget, 'runtime.txt'), 'utf8'), 'verified');
  const pythonProbeRoot = path.join(root, 'python-probe');
  fs.mkdirSync(pythonProbeRoot);
  const pythonProbeExe = path.join(pythonProbeRoot, 'python.exe');
  fs.writeFileSync(pythonProbeExe, 'fixture');
  fs.writeFileSync(path.join(pythonProbeRoot, 'python311.zip'), 'fixture');
  const pythonProbe = new Installer({
    payloadRoot: copySource,
    logPath: path.join(root, 'python-probe.log'),
    statePath: path.join(root, 'python-probe-state.json'),
    lockPath: path.join(root, 'python-probe.lock'),
  });
  let pythonProbeOutput = 'CLIPIFY_PYTHON_OK:3.11.9';
  let pythonProbeCode = 0;
  pythonProbe.runProcess = async (_exe, _args, options) => {
    options.onLine(pythonProbeOutput);
    return { code: pythonProbeCode };
  };
  assert.strictEqual(await pythonProbe.pythonEngineUsable(pythonProbeExe), true,
    'the zip-based embeddable Python layout should pass verification');
  fs.rmSync(path.join(pythonProbeRoot, 'python311.zip'));
  fs.mkdirSync(path.join(pythonProbeRoot, 'Lib'));
  fs.writeFileSync(path.join(pythonProbeRoot, 'Lib', 'os.py'), 'fixture');
  assert.strictEqual(await pythonProbe.pythonEngineUsable(pythonProbeExe), true);
  fs.rmSync(path.join(pythonProbeRoot, 'Lib', 'os.py'));
  assert.strictEqual(await pythonProbe.pythonEngineUsable(pythonProbeExe), false,
    'an interpreter without a standard-library anchor must fail readiness');
  assert.match(pythonProbe.lastPythonProbeError, /standard library is missing/);
  fs.writeFileSync(path.join(pythonProbeRoot, 'Lib', 'os.py'), 'fixture');
  pythonProbeOutput = 'CLIPIFY_PYTHON_OK:3.11.8';
  assert.strictEqual(await pythonProbe.pythonEngineUsable(pythonProbeExe), false, 'a wrong Python version must fail readiness');
  pythonProbeOutput = 'ModuleNotFoundError: No module named ensurepip';
  pythonProbeCode = 1;
  assert.strictEqual(await pythonProbe.pythonEngineUsable(pythonProbeExe), false, 'a failed interpreter probe must fail readiness');
  assert.match(pythonProbe.lastPythonProbeError, /ModuleNotFoundError/,
    'the setup log should retain Python probe output for actionable diagnostics');
  const pythonInstallRoot = path.join(root, 'python install with spaces');
  const pythonStageEngine = new Installer({
    payloadRoot: copySource,
    logPath: path.join(root, 'python-stage.log'),
    statePath: path.join(root, 'python-stage-state.json'),
    lockPath: path.join(root, 'python-stage.lock'),
  });
  pythonStageEngine.options = { installDir: pythonInstallRoot };
  pythonStageEngine.downloadFile = async (_url, archive, progress) => {
    fs.writeFileSync(archive, 'mock Python archive');
    progress(100, 100);
  };
  pythonStageEngine.runProcess = async (_exe, args) => {
    const command = args[args.indexOf('-Command') + 1];
    assert(command.includes('Expand-Archive -LiteralPath'));
    const match = command.match(/-DestinationPath '((?:[^']|'')+)'/);
    assert(match, 'archive extraction path must be safely quoted');
    const unpack = match[1].replace(/''/g, "'");
    const tools = path.join(unpack, 'tools');
    fs.mkdirSync(tools, { recursive: true });
    fs.writeFileSync(path.join(tools, 'python.exe'), 'python fixture');
    fs.mkdirSync(path.join(tools, 'Lib'), { recursive: true });
    fs.writeFileSync(path.join(tools, 'Lib', 'os.py'), 'stdlib fixture');
    fs.writeFileSync(path.join(tools, 'python311._pth'), 'site fixture');
    return { code: 0 };
  };
  pythonStageEngine.pythonEngineUsable = async (exe) =>
    fs.existsSync(exe) && fs.existsSync(path.join(path.dirname(exe), 'Lib', 'os.py'));
  const realRename = fs.promises.rename.bind(fs.promises);
  let injectedRenameFailures = 0;
  fs.promises.rename = async (from, to) => {
    if (path.basename(from) === 'tools' && injectedRenameFailures < 2) {
      injectedRenameFailures += 1;
      throw Object.assign(new Error('simulated Windows sharing lock'), { code: 'EPERM' });
    }
    return realRename(from, to);
  };
  try {
    await pythonStageEngine.ensurePython();
  } finally {
    fs.promises.rename = realRename;
  }
  const installedPythonDir = path.join(pythonInstallRoot, 'python311');
  assert.strictEqual(injectedRenameFailures, 2, 'Python extraction retries transient EPERM during directory promotion');
  assert.strictEqual(fs.existsSync(path.join(installedPythonDir, 'python.exe')), true);
  assert.strictEqual(fs.existsSync(path.join(installedPythonDir, 'Lib', 'os.py')), true,
    'the official NuGet Python Lib directory must remain intact after install');
  assert.strictEqual(fs.existsSync(path.join(installedPythonDir, 'python311.zip')), false,
    'the NuGet layout must not require an embeddable python311.zip');
  assert.strictEqual(fs.existsSync(path.join(installedPythonDir, 'python311._pth')), false);
  assert.strictEqual(pythonStageEngine.phaseState.python.status, 'done');
  assert.deepStrictEqual(fs.readdirSync(pythonInstallRoot), ['python311']);
  console.log('PASS Python archive uses a unique same-volume stage, quotes spaced paths, retries EPERM, and cleans only its stage');
  const honestProgress = new Installer({ payloadRoot: copySource });
  honestProgress.phaseState = {
    files: { status: 'done', percent: 100 },
    runtime: { status: 'running', percent: 97 },
  };
  honestProgress.activePhaseId = 'runtime';
  assert.strictEqual(honestProgress.overallPercent(), 5, 'an indeterminate runtime must not inflate aggregate progress');
  const retryProbe = new Installer({ payloadRoot: copySource });
  retryProbe.start = async (options) => options;
  assert.deepStrictEqual(await retryProbe.retryPhase('runtime', { installDir: root }), { installDir: root });
  await assert.rejects(retryProbe.retryPhase('unknown-phase', {}), /unknown phase/);
  console.log('PASS unique staging, bounded EPERM retry, active and stale lock recovery, and safe directory copy');
  assert(UNINSTALL_KEY.startsWith('HKCU:\\Software\\'), 'uninstall registration must use the PowerShell registry provider path');
  const mainSource = fs.readFileSync(path.join(appRoot, 'main.js'), 'utf8');
  assert(mainSource.includes('UNINSTALL_KEY') && !/const\s+UNINSTALL_KEY\s*=/.test(mainSource),
    'main process must reuse the provider-qualified uninstall key instead of a stale duplicate');
  assert(mainSource.includes('New-ItemProperty -Path $k -Name NoModify -Value 1 -PropertyType DWord -Force'),
    'DWORD uninstall values must use New-ItemProperty with PropertyType');
  assert(!/Set-ItemProperty[^;]*-Type\s+DWord/.test(mainSource),
    'Set-ItemProperty does not accept a -Type parameter');
  assert(mainSource.includes('$ErrorActionPreference=\'Stop\';') &&
    mainSource.includes('Get-ItemPropertyValue -Path $k -Name InstallLocation'),
  'uninstall registration must fail on PowerShell errors and verify the registered target');
  const launchBlock = mainSource.match(/ipcMain\.handle\('setup:launch',[\s\S]*?(?=\nipcMain\.handle|\n\/\/ -{10,} uninstall)/);
  assert(launchBlock && launchBlock[0].includes('env: Object.assign({}, process.env, ensureInstaller().appEnv())'),
    'launching the installed app must override inherited paths with the selected install target');
  const installerBuildSource = fs.readFileSync(path.resolve(__dirname, '..', '..', 'build_installer.py'), 'utf8');
  const detectSource = fs.readFileSync(path.join(appRoot, 'lib', 'detect.js'), 'utf8');
  const stagePayloadSource = fs.readFileSync(path.resolve(__dirname, 'stage_payload.py'), 'utf8');
  assert(!detectSource.includes('L:\\\\ClippedAI'),
    'source checkout must never be a default application installation target');
  assert(detectSource.includes("for (const candidate of ['L:\\\\ClipifyAI'])"),
    'the existing production installation remains the production default when L: is available');
  const checkoutFixture = path.join(root, 'development-checkout-fixture');
  fs.mkdirSync(path.join(checkoutFixture, 'build'), { recursive: true });
  fs.mkdirSync(path.join(checkoutFixture, '.git'));
  fs.writeFileSync(path.join(checkoutFixture, 'main.py'), '# source');
  fs.writeFileSync(path.join(checkoutFixture, 'build', 'build_installer.py'), '# builder');
  assert.strictEqual(isDevelopmentCheckout(checkoutFixture), true,
    'a candidate containing the source markers must be recognized as a checkout');
  const plainInstallFixture = path.join(root, 'plain-install-fixture');
  fs.mkdirSync(plainInstallFixture);
  assert.strictEqual(isDevelopmentCheckout(plainInstallFixture), false,
    'a normal install folder must remain eligible for upgrades');
  const projectRoot = path.resolve(appRoot, '..', '..');
  if (path.resolve('L:/ClipifyAI').toLowerCase() === projectRoot.toLowerCase()
      && isDevelopmentCheckout(projectRoot)) {
    const savedInstallRoot = process.env.CLIPIFY_INSTALL_ROOT;
    try {
      process.env.CLIPIFY_INSTALL_ROOT = '';
      assert.notStrictEqual(path.resolve(defaultInstallDir()).toLowerCase(), projectRoot.toLowerCase(),
        'the development checkout must not be used as the default install destination');
    } finally {
      if (savedInstallRoot === undefined) delete process.env.CLIPIFY_INSTALL_ROOT;
      else process.env.CLIPIFY_INSTALL_ROOT = savedInstallRoot;
    }
  }
  assert(stagePayloadSource.includes('for needle in (str(PROJECT), ".venv")'),
    'payload validation must detect the active checkout path dynamically');
  const brandedRuntimePayload = path.join(root, 'runtime-script-payload');
  fs.mkdirSync(brandedRuntimePayload, { recursive: true });
  fs.writeFileSync(path.join(brandedRuntimePayload, 'ClipifyAI-Runtime.ps1'), '# Clipify AI runtime');
  assert.strictEqual(payloadSummary(brandedRuntimePayload).hasRuntimeScript, true,
    'the branded runtime script filename must be recognized in payload summaries');
  console.log('PASS default install target skips development checkouts; payload checks follow the active project root');
  assert(installerBuildSource.includes('--config.nsis.oneClick=false') &&
    installerBuildSource.includes('--config.nsis.allowToChangeInstallationDirectory=true') &&
    installerBuildSource.includes('--config.nsis.runAfterFinish=true') &&
    !installerBuildSource.includes('--config.nsis.runAfterFinish=false') &&
    installerBuildSource.includes('--config.extraMetadata.clipifyQaInstallSlug=') &&
    installerBuildSource.includes('ARGS.isolated_qa'),
  'isolated QA packages must launch the custom Electron UI and receive a build-specific isolated identity');
  assert(mainSource.includes('setup:renderer-ready') && mainSource.includes('setup:renderer-error') &&
    mainSource.includes('did-fail-load') && mainSource.includes('render-process-gone'),
  'the custom renderer must report successful boot and visible startup failures');

  const qaTarget = isolatedInstallDir('ClipifyAI-QA-regression-001', 'C:\\Users\\Dell\\AppData\\Local', '');
  assert.strictEqual(qaTarget, path.join('C:\\Users\\Dell\\AppData\\Local', 'Programs', 'ClipifyAI-QA-regression-001'));
  assert.notStrictEqual(qaTarget, 'C:\\Users\\Dell\\AppData\\Local\\Programs\\ClipifyAI');
  assert.strictEqual(APP_SLUG, 'ClipifyAI', 'source development install identity remains production default');
  assert(mainSource.includes('QA_DATA_ROOT') &&
    mainSource.indexOf('Object.assign(process.env, qaPaths)') < mainSource.indexOf("require('./lib/installer')"),
  'isolated QA paths must be active before installer and user-data modules load');
  assert(mainSource.includes('QA mode: skipped Add/Remove Programs registration'),
    'isolated QA runs must not write an uninstall registration into the developer profile');
  const rendererSource = fs.readFileSync(path.join(appRoot, 'renderer', 'app.js'), 'utf8');
  assert(rendererSource.includes("$('chk-runtime').checked = false") && rendererSource.includes('state.selected = api.qa ? new Set()'),
    'isolated QA runs must not start multi-gigabyte or model downloads by default');
  assert(rendererSource.indexOf('/python engine|python311|python\\.exe/i') < rendererSource.indexOf('/download|network|ENOTFOUND'),
    'Python engine validation failures must not be mislabeled as generic download failures');
  console.log('PASS QA package resolves a unique app-data, registry and shortcut identity');

  const setupShellRoot = path.join(root, 'Clipify AI Setup QA');
  fs.mkdirSync(setupShellRoot, { recursive: true });
  const nestedTarget = validateInstallDir(path.join(setupShellRoot, 'qa-profile', 'Local', 'Programs', 'ClipifyAI'), setupShellRoot);
  assert.strictEqual(nestedTarget.ok, false);
  assert.strictEqual(nestedTarget.reason, 'overlaps-installer');
  const siblingTarget = validateInstallDir(path.join(root, 'ClipifyAI-QA'), setupShellRoot);
  assert.strictEqual(siblingTarget.ok, true, siblingTarget.message);
  console.log('PASS application target cannot overlap the setup shell; independent sibling test targets remain valid');

  const copyPayload = path.join(root, 'copy-payload');
  const installDir = path.join(root, 'copy-install');
  fs.mkdirSync(copyPayload, { recursive: true });
  fs.mkdirSync(installDir, { recursive: true });
  fs.writeFileSync(path.join(copyPayload, 'Clipify AI.exe'), 'launcher-current');
  fs.writeFileSync(path.join(copyPayload, 'main.exe'), 'worker-new!');
  fs.writeFileSync(path.join(installDir, 'main.exe'), 'worker-old!');

  const engine = new Installer({
    payloadRoot: copyPayload,
    logPath: path.join(root, 'copy.log'),
    statePath: path.join(root, 'copy-state.json'),
  });
  engine.options = { installDir };
  const copyProgress = [];
  engine.on('progress', (event) => copyProgress.push(event));
  const launchEnv = engine.appEnv();
  assert.strictEqual(launchEnv.CLIPPEDAI_DATA_DIR, path.resolve(installDir));
  assert.strictEqual(launchEnv.CLIPPEDAI_RUNTIME, path.join(path.resolve(installDir), 'runtime'));
  assert.strictEqual(launchEnv.OLLAMA_MODELS, path.join(path.resolve(installDir), 'models'));
  console.log('PASS installed app launch environment is rooted in the selected target');
  await engine.copyPayload();
  const finalCopyProgress = copyProgress.at(-1);
  assert.strictEqual(finalCopyProgress.phases.find((phase) => phase.id === 'files').status, 'done',
    'overall progress must be refreshed when a phase finishes');
  assert.strictEqual(fs.readFileSync(path.join(installDir, 'main.exe'), 'utf8'), 'worker-new!');
  console.log('PASS same-size stale worker is replaced during payload copy');

  const footprintDir = path.join(root, 'measured-footprint');
  fs.mkdirSync(path.join(footprintDir, 'runtime'), { recursive: true });
  fs.mkdirSync(path.join(footprintDir, 'models'), { recursive: true });
  fs.mkdirSync(path.join(footprintDir, 'settings'), { recursive: true });
  fs.mkdirSync(path.join(footprintDir, 'output'), { recursive: true });
  fs.writeFileSync(path.join(footprintDir, 'Clipify AI.exe'), 'a'.repeat(100));
  fs.writeFileSync(path.join(footprintDir, 'runtime', 'python.dll'), 'b'.repeat(200));
  fs.writeFileSync(path.join(footprintDir, 'models', 'model.blob'), 'c'.repeat(300));
  fs.writeFileSync(path.join(footprintDir, 'settings', 'browser-profile.bin'), 'd'.repeat(500));
  fs.writeFileSync(path.join(footprintDir, 'output', 'user-video.mp4'), 'e'.repeat(1000));
  const footprintEngine = new Installer({
    payloadRoot: copyPayload,
    logPath: path.join(root, 'footprint.log'),
    statePath: path.join(root, 'footprint-state.json'),
    lockPath: path.join(root, 'footprint.lock'),
  });
  footprintEngine.copyPayload = async () => {};
  footprintEngine.seedUserData = () => {};
  footprintEngine.installModels = async () => {};
  footprintEngine.createShortcuts = () => {};
  footprintEngine.verifyInstallation = async () => {};
  let completedInstall = null;
  footprintEngine.on('done', (result) => { completedInstall = result; });
  await footprintEngine.start({
    installDir: footprintDir,
    installRuntime: false,
    installOllama: false,
    models: [],
  });
  assert.strictEqual(completedInstall.installedBytes, 600,
    'finish size should include app/runtime/models and exclude settings/output user data');
  console.log('PASS finish screen size excludes generated user data and includes app/runtime/model files');

  const verificationTarget = path.join(root, 'final-component-verification');
  fs.mkdirSync(verificationTarget, { recursive: true });
  for (const name of ['Clipify AI.exe', 'main.exe']) {
    fs.writeFileSync(path.join(verificationTarget, name), Buffer.alloc(1024 * 1024 + 1, 0x5a));
  }
  const verifyEngine = new Installer({
    payloadRoot: copyPayload,
    logPath: path.join(root, 'final-verification.log'),
    statePath: path.join(root, 'final-verification-state.json'),
  });
  verifyEngine.options = { installDir: verificationTarget, installRuntime: false, models: [] };
  await verifyEngine.verifyInstallation();
  assert.strictEqual(verifyEngine.phaseState.verify.status, 'done');
  fs.unlinkSync(path.join(verificationTarget, 'main.exe'));
  await assert.rejects(verifyEngine.verifyInstallation(), /main.exe is missing/);
  assert.strictEqual(verifyEngine.phaseState.verify.status, 'error');
  console.log('PASS final verification completes only when both application executables are present');

  const stubStartOperations = (startEngine) => {
    startEngine.copyPayload = async () => {};
    startEngine.seedUserData = () => {};
    startEngine.installModels = async () => {};
    startEngine.createShortcuts = () => {};
    startEngine.verifyInstallation = async () => {};
  };
  const freshInstallDir = path.join(root, 'fresh-start-target');
  const freshStart = new Installer({
    payloadRoot: copyPayload,
    logPath: path.join(root, 'fresh-start.log'),
    statePath: path.join(root, 'fresh-start-state.json'),
    lockPath: path.join(root, 'fresh-start.lock'),
  });
  stubStartOperations(freshStart);
  await freshStart.start({
    installDir: freshInstallDir,
    installRuntime: false,
    installOllama: false,
    models: [],
    desktopShortcut: false,
  });
  assert.strictEqual(freshStart.readState().status, 'complete');
  assert(!fs.readFileSync(path.join(root, 'fresh-start.log'), 'utf8').includes('resuming a previously interrupted installation'));

  const interruptedInstallDir = path.join(root, 'interrupted-start-target');
  const interruptedState = path.join(root, 'interrupted-start-state.json');
  fs.writeFileSync(interruptedState, JSON.stringify({
    app: APP_SLUG,
    status: 'in-progress',
    installDir: interruptedInstallDir,
  }));
  const resumedStart = new Installer({
    payloadRoot: copyPayload,
    logPath: path.join(root, 'interrupted-start.log'),
    statePath: interruptedState,
    lockPath: path.join(root, 'interrupted-start.lock'),
  });
  stubStartOperations(resumedStart);
  await resumedStart.start({
    installDir: interruptedInstallDir,
    installRuntime: false,
    installOllama: false,
    models: [],
    desktopShortcut: false,
  });
  assert(fs.readFileSync(path.join(root, 'interrupted-start.log'), 'utf8').includes('resuming a previously interrupted installation'));
  console.log('PASS fresh installs are not mislabeled as resume; matching interrupted state is recognized');

  const uninstallPayload = path.join(root, 'uninstall-payload');
  const uninstallTarget = path.join(root, 'uninstall-install');
  fs.mkdirSync(path.join(uninstallPayload, 'static'), { recursive: true });
  fs.mkdirSync(path.join(uninstallTarget, 'static'), { recursive: true });
  fs.mkdirSync(path.join(uninstallTarget, 'jobs'), { recursive: true });
  fs.mkdirSync(path.join(uninstallTarget, 'models'), { recursive: true });
  fs.mkdirSync(path.join(uninstallTarget, 'runtime'), { recursive: true });
  fs.writeFileSync(path.join(uninstallPayload, 'Clipify AI.exe'), 'app');
  fs.writeFileSync(path.join(uninstallPayload, 'static', 'app.js'), 'asset');
  fs.writeFileSync(path.join(uninstallTarget, 'Clipify AI.exe'), 'app');
  fs.writeFileSync(path.join(uninstallTarget, 'static', 'app.js'), 'asset');
  fs.writeFileSync(path.join(uninstallTarget, 'jobs', 'user-job.json'), '{"keep":true}');
  fs.writeFileSync(path.join(uninstallTarget, 'models', 'manifest'), 'user-model');
  fs.writeFileSync(path.join(uninstallTarget, 'runtime', '.clipify-runtime-complete'), 'ready');
  fs.writeFileSync(path.join(uninstallTarget, 'user-note.txt'), 'keep');

  const removed = removeBundledFiles(uninstallTarget, uninstallPayload);
  assert.strictEqual(fs.existsSync(path.join(uninstallTarget, 'Clipify AI.exe')), false);
  assert.strictEqual(fs.existsSync(path.join(uninstallTarget, 'static', 'app.js')), false);
  assert.strictEqual(fs.readFileSync(path.join(uninstallTarget, 'jobs', 'user-job.json'), 'utf8'), '{"keep":true}');
  assert.strictEqual(fs.readFileSync(path.join(uninstallTarget, 'models', 'manifest'), 'utf8'), 'user-model');
  assert.strictEqual(fs.existsSync(path.join(uninstallTarget, 'runtime', '.clipify-runtime-complete')), true);
  assert.strictEqual(fs.readFileSync(path.join(uninstallTarget, 'user-note.txt'), 'utf8'), 'keep');
  assert.strictEqual(removed.removed, 2);
  console.log('PASS uninstall removes payload while preserving jobs, models, runtime and user files');

  const detectionOptions = { installRuntime: false, installOllama: false };
  const detectionDir = path.join(root, 'model-selection-detection');
  const emptySelection = await detectAll({
    installDir: detectionDir,
    payloadRoot: copyPayload,
    selectedModels: [],
    options: detectionOptions,
  });
  assert.deepStrictEqual(emptySelection.ids, []);
  assert.deepStrictEqual(emptySelection.modelsToDownload, []);
  assert.strictEqual(emptySelection.modelBytes, 0);
  const defaultSelection = await detectAll({
    installDir: detectionDir,
    payloadRoot: copyPayload,
    options: detectionOptions,
  });
  assert.deepStrictEqual(defaultSelection.ids, [DEFAULT_ID]);
  console.log('PASS explicit zero-model selection is preserved; omitted selection keeps the recommended default');

  const partialRuntimeRoot = path.join(root, 'partial-runtime-install');
  const partialRuntime = path.join(partialRuntimeRoot, 'runtime');
  fs.mkdirSync(path.join(partialRuntime, 'Lib', 'site-packages', 'clipsai'), { recursive: true });
  fs.mkdirSync(path.join(partialRuntime, 'Scripts'), { recursive: true });
  fs.writeFileSync(path.join(partialRuntime, 'Scripts', 'python.exe'), 'fixture');
  fs.writeFileSync(path.join(partialRuntime, RUNTIME_COMPLETE_MARKER), 'runtime installed');
  const partialRuntimeDetection = await detectAll({
    installDir: partialRuntimeRoot,
    payloadRoot: copyPayload,
    selectedModels: [],
    options: { installRuntime: true, installOllama: false },
  });
  assert.strictEqual(partialRuntimeDetection.runtimeInTarget, true);
  assert.strictEqual(partialRuntimeDetection.runtimeBytes, NARRATION_MODEL_BYTES);

  async function stageRuntimeFixture(targetRoot, failFinalVerification = false) {
    const runtimeTarget = path.join(targetRoot, 'runtime');
    fs.mkdirSync(runtimeTarget, { recursive: true });
    fs.writeFileSync(path.join(runtimeTarget, RUNTIME_COMPLETE_MARKER), 'original runtime');
    fs.writeFileSync(path.join(runtimeTarget, 'keep-me.txt'), 'old verified copy');
    fs.mkdirSync(path.join(targetRoot, 'python311'), { recursive: true });
    fs.writeFileSync(path.join(targetRoot, 'python311', 'python.exe'), 'base python fixture');
    fs.writeFileSync(path.join(targetRoot, 'requirements-runtime.txt'), '# mocked requirements\n');
    const engine = new Installer({
      payloadRoot: copyPayload,
      logPath: path.join(root, 'runtime-stage.log'),
      statePath: path.join(root, 'runtime-stage-state.json'),
    });
    engine.options = { installDir: targetRoot };
    engine.runProcess = async (_exe, args) => {
      if (args[0] === '-m' && args[1] === 'venv') {
        const stage = args[2];
        fs.mkdirSync(path.join(stage, 'Scripts'), { recursive: true });
        fs.mkdirSync(path.join(stage, 'Lib', 'site-packages'), { recursive: true });
        fs.writeFileSync(path.join(stage, 'Scripts', 'python.exe'), 'staged python fixture');
      }
      if (args[0] === '-m' && args[1] === 'pip') {
        const site = path.join(path.dirname(path.dirname(_exe)), 'Lib', 'site-packages');
        fs.mkdirSync(path.join(site, 'clipsai'), { recursive: true });
      }
      return { code: 0 };
    };
    const checks = [];
    engine.verifyRuntime = async (_python, expectedRoot) => {
      checks.push(expectedRoot);
      if (expectedRoot !== runtimeTarget) {
        assert.strictEqual(fs.readFileSync(path.join(runtimeTarget, 'keep-me.txt'), 'utf8'), 'old verified copy',
          'the existing runtime must stay in place while the replacement is verified');
      } else if (failFinalVerification) {
        throw new Error('synthetic final-location probe failure');
      }
    };
    return { engine, runtimeTarget, checks };
  }

  const stagedRuntimeRoot = path.join(root, 'staged-runtime-install');
  const stagedFixture = await stageRuntimeFixture(stagedRuntimeRoot);
  await stagedFixture.engine.ensureRuntime();
  assert.strictEqual(stagedFixture.checks.length, 2, 'staged and promoted runtime must both pass verification');
  assert.strictEqual(stagedFixture.checks[0] === stagedFixture.runtimeTarget, false);
  assert.strictEqual(fs.readFileSync(path.join(stagedFixture.runtimeTarget, RUNTIME_COMPLETE_MARKER), 'utf8').includes('Installed'), true);
  assert.strictEqual(fs.existsSync(path.join(stagedFixture.runtimeTarget, 'keep-me.txt')), false,
    'the previous runtime is retired only after replacement verification succeeds');
  console.log('PASS AI runtime is built and verified beside the existing runtime before promotion');

  const rollbackRoot = path.join(root, 'runtime-rollback-install');
  const rollbackFixture = await stageRuntimeFixture(rollbackRoot, true);
  await assert.rejects(rollbackFixture.engine.ensureRuntime(), /synthetic final-location probe failure/);
  assert.strictEqual(fs.readFileSync(path.join(rollbackFixture.runtimeTarget, 'keep-me.txt'), 'utf8'), 'old verified copy',
    'a failed final-location check restores the previous runtime');
  console.log('PASS failed runtime promotion restores the previous runtime');

  fs.mkdirSync(path.join(partialRuntime, 'Lib', 'site-packages', 'en_core_web_sm'), { recursive: true });
  const completeRuntimeDetection = await detectAll({
    installDir: partialRuntimeRoot,
    payloadRoot: copyPayload,
    selectedModels: [],
    options: { installRuntime: true, installOllama: false },
  });
  assert.strictEqual(completeRuntimeDetection.runtimeBytes, 0);
  console.log('PASS marked runtime with language model installed estimates zero runtime bytes');

  if (process.env.CLIPIFY_TEST_OLLAMA_REUSE === '1') {
    const tags = await getOllamaTags();
    assert((tags.models || []).some((model) => model.name === 'qwen3:8b'), 'qwen3:8b must already be cached');
    const ollama = findOllama();
    const modelRoot = path.join(root, 'cached-model-install', 'models');
    const modelEngine = new Installer({
      payloadRoot: copyPayload,
      logPath: path.join(root, 'ollama-reuse.log'),
      statePath: path.join(root, 'ollama-reuse-state.json'),
    });
    modelEngine.options = { installDir: path.dirname(modelRoot) };
    // When the API is already available this method returns before spawning
    // the executable, so it safely verifies that the user's service is kept.
    await modelEngine.startOllamaServer(ollama || 'not-invoked-while-api-is-live');
    assert.strictEqual(fs.existsSync(modelRoot), false, 'existing Ollama store should not be redirected');
    assert(modelEngine.activity.some((entry) =>
      entry.text.includes('Using the running Ollama service and its existing model store')));
    console.log('PASS live Ollama service is reused without stopping or redirecting it');
    if (ollama) {
      await modelEngine.installModels(['qwen3:8b']);
      assert.strictEqual(modelEngine.models[0].status, 'installed');
      assert(modelEngine.activity.some((entry) =>
        entry.text.includes('Already installed, not downloading again: qwen3:8b')));
      console.log('PASS cached qwen3:8b is detected without starting a pull');
    } else {
      console.log('SKIP Ollama CLI model-list integration: executable path is inaccessible in this sandbox');
    }
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
