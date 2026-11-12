'use strict';

/**
 * Environment detection for the Clipify AI installer.
 *
 * Everything the UI needs to make a decision up front - disk space, whether
 * Ollama is present, which models already exist, whether a previous install was
 * interrupted - is gathered here so the renderer never has to guess and never
 * has to block on a child process.
 */

const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { promisify } = require('util');

const execFileAsync = promisify(execFile);

// `electron` resolves to a path string when this module is loaded outside a
// running app (unit tests, tooling), so treat the app object as optional.
const electronApp = (() => {
  try {
    return require('electron').app || null;
  } catch {
    return null;
  }
})();

const APP_NAME = 'Clipify AI';
const PACKAGE_METADATA = require('../package.json');
const QA_INSTALL_SLUG = typeof PACKAGE_METADATA.clipifyQaInstallSlug === 'string' &&
  /^[A-Za-z0-9.-]+$/.test(PACKAGE_METADATA.clipifyQaInstallSlug)
  ? PACKAGE_METADATA.clipifyQaInstallSlug
  : '';
const APP_SLUG = QA_INSTALL_SLUG || 'ClipifyAI';
const APP_SHORTCUT_NAME = QA_INSTALL_SLUG
  ? `Clipify AI QA ${QA_INSTALL_SLUG.replace(/^ClipifyAI-QA-/, '')}`
  : 'Clipify AI';
/**
 * The user-facing executable name.
 *
 * The payload ships the compiled binary under its real product name. The user
 * must never be pointed at a .bat, .vbs or python script, and must never see
 * the old "ClippedAI" name.
 */
const APP_EXE = 'Clipify AI.exe';
const PUBLISHER = 'sherlock-dev-ai';
const UNINSTALL_KEY =
  `HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${APP_SLUG}`;

/**
 * The catalog is a clean, curated recommendation list - it deliberately does
 * NOT reflect the models this particular user already has installed. Installed
 * models are still detected internally so we can skip re-pulling them, but they
 * never become cards in the UI.
 *
 * Sizes come from resources/catalog.json, which is generated from real Ollama
 * registry manifests by tools/verify_models.py.
 *
 * In development the catalog sits next to the app sources. Once packaged, the
 * app code lives inside app.asar, where a `../` can no longer escape the asar
 * root, so the catalog is copied to <resources>/catalog.json and resolved from
 * process.resourcesPath instead.
 */
function loadCatalog() {
  if (electronApp && electronApp.isPackaged) {
    const packaged = path.join(process.resourcesPath, 'catalog.json');
    if (fs.existsSync(packaged)) return JSON.parse(fs.readFileSync(packaged, 'utf8'));
  }
  return require('../resources/catalog.json');
}

const CATALOG = loadCatalog();
const RUNTIME_MODELS = CATALOG.models.map((model) => ({
  id: model.id,
  name: model.name,
  description: model.description,
  sizeBytes: model.sizeBytes,
  ramMin: model.ramMin,
  ramRecommended: model.ramRecommended,
  vram: model.vram,
  speed: model.speed,
  gpuUseful: model.gpuUseful,
  recommended: Boolean(model.recommended),
  bestFor: model.bestFor,
  tags: model.tags,
}));

/** Real measured sizes for the runtime, used for the required-space estimate. */
const RUNTIME_BYTES = 2.7 * 1024 ** 3;
const NARRATION_MODEL_BYTES = 13 * 1024 ** 2;
const OLLAMA_BYTES = 1.0 * 1024 ** 3;
const DEFAULT_ID = 'qwen2.5:3b';

/**
 * The preferred install root.
 *
 * Clipify AI is a multi-gigabyte app, so it ships to a fixed data volume rather
 * than the system drive. Override with CLIPIFY_INSTALL_ROOT when deploying
 * somewhere else. Returns null when the volume is not usable, which is the
 * signal for callers to fall back to the per-user location.
 */
function preferredInstallRoot() {
  const override = String(process.env.CLIPIFY_INSTALL_ROOT || '').trim();
  if (override) {
    try {
      if (fs.existsSync(override) && !isDevelopmentCheckout(override)) return path.resolve(override);
    } catch (_) { /* ignore and keep probing */ }
  }
  // L:\\ClipifyAI is the separate production installation. Never treat the
  // source checkout as an application install destination. A developer may
  // have the checkout on this volume, so verify the candidate before using it.
  for (const candidate of ['L:\\ClipifyAI']) {
    try {
      if (fs.existsSync(path.parse(candidate).root) && !isDevelopmentCheckout(candidate)) return candidate;
    } catch (_) { /* ignore and keep probing */ }
  }
  return null;
}

/**
 * Avoid installing over a source checkout that happens to share the product's
 * preferred volume path. Normal installed payloads do not contain these source
 * markers, so existing product installs remain eligible for upgrades.
 */
function isDevelopmentCheckout(targetRoot) {
  const root = path.resolve(String(targetRoot || ''));
  return fs.existsSync(path.join(root, '.git'))
    && fs.existsSync(path.join(root, 'main.py'))
    && fs.existsSync(path.join(root, 'build', 'build_installer.py'));
}

/** The default installation location: L: when available, per-user otherwise. */
function defaultInstallDir() {
  if (QA_INSTALL_SLUG) {
    return isolatedInstallDir(QA_INSTALL_SLUG, process.env.LOCALAPPDATA, process.env.APPDATA);
  }
  const root = preferredInstallRoot();
  if (root) return root;
  return path.join(process.env.LOCALAPPDATA || '', 'Programs', APP_SLUG);
}

/** Builds an isolated per-user install target for a uniquely named QA package. */
function isolatedInstallDir(slug, localAppData, userData) {
  const safeSlug = String(slug || '').trim();
  if (!safeSlug || !/^[A-Za-z0-9.-]+$/.test(safeSlug)) return null;
  const base = String(localAppData || userData || '').trim();
  if (!base) return null;
  return path.join(base, 'Programs', safeSlug);
}

/** Runs a command and resolves to stdout, or null when it is unavailable. */
async function tryRun(command, args, timeout = 8000) {
  try {
    const { stdout } = await execFileAsync(command, args, {
      timeout,
      windowsHide: true,
      maxBuffer: 8 * 1024 * 1024,
    });
    return stdout;
  } catch {
    return null;
  }
}

function findOllama() {
  const candidates = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Ollama', 'ollama.exe'),
    path.join(process.env.ProgramFiles || '', 'Ollama', 'ollama.exe'),
    path.join(process.env['ProgramFiles(x86)'] || '', 'Ollama', 'ollama.exe'),
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || null;
}

/**
 * Parses `ollama list` output into a set of installed model names.
 */
function parseOllamaList(stdout) {
  const installed = new Set();
  if (!stdout) return installed;
  for (const line of stdout.split(/\r?\n/)) {
    const parts = line.trim().split(/\s+/);
    if (parts.length >= 2 && parts[0].toUpperCase() === 'NAME') continue;
    if (parts.length >= 2 && /^[0-9a-f]{8,}$/i.test(parts[1])) installed.add(parts[0]);
  }
  return installed;
}

/**
 * Ollama is asked about at most once every few seconds.
 *
 * Shelling out to `ollama --version` and `ollama list` on every keystroke was
 * pointless work: the answer cannot change while the user is typing a path, and
 * on a cold or busy machine each call can block for a second or more.
 */
let ollamaCache = null;
let ollamaCachedAt = 0;
const OLLAMA_TTL_MS = 8000;

async function detectOllama({ force = false } = {}) {
  if (!force && ollamaCache && Date.now() - ollamaCachedAt < OLLAMA_TTL_MS) {
    return ollamaCache;
  }
  const result = await readOllama();
  ollamaCache = result;
  ollamaCachedAt = Date.now();
  return result;
}

/**
 * Resolve the directory Ollama currently stores its models in.
 *
 * Priority (matches Ollama's own lookup order):
 *   1. OLLAMA_MODELS env var (user-set override)
 *   2. %USERPROFILE%\.ollama\models  (Windows default)
 *   3. /usr/share/ollama/.ollama/models (Linux fallback, included for safety)
 */
function resolveOllamaModelsDir() {
  if (process.env.OLLAMA_MODELS) return process.env.OLLAMA_MODELS;
  const home = process.env.USERPROFILE || os.homedir();
  return path.join(home, '.ollama', 'models');
}

async function readOllama() {
  const exe = findOllama();
  const modelsDir = resolveOllamaModelsDir();
  const modelsDirExists = fs.existsSync(modelsDir);
  if (!exe) {
    return { installed: false, path: null, version: null, models: [], modelsDir, modelsDirExists };
  }
  const [versionOut, listOut] = await Promise.all([
    tryRun(exe, ['--version'], 4000),
    tryRun(exe, ['list'], 6000),
  ]);
  let version = null;
  if (versionOut) {
    const match = versionOut.match(/(\d+\.\d+\.\d+)/);
    version = match ? match[1] : versionOut.trim().split(/\r?\n/)[0];
  }
  return {
    installed: true,
    path: exe,
    version,
    models: [...parseOllamaList(listOut)],
    modelsDir,
    modelsDirExists,
  };
}

/**
 * Validates a proposed install path without creating anything.
 *
 * `installDir` may be undefined, blank, or nonsense - the UI calls this on
 * every keystroke, so it must never throw.
 */
function validateInstallDir(installDir, installerRoot = path.dirname(process.execPath)) {
  const value = (installDir || '').trim();
  if (!value) {
    return { ok: false, reason: 'empty', message: 'Choose an installation folder.' };
  }
  if (!path.isAbsolute(value)) {
    return {
      ok: false,
      reason: 'relative',
      message: 'Use a full path, for example C:\\Program Files\\ClipifyAI.',
    };
  }
  // The setup shell is installed separately from Clipify AI. If the selected
  // app target overlaps the setup shell's own directory, a later NSIS update
  // can recursively remove the application while replacing that shell. Keep
  // the two installations disjoint in either direction.
  if (installerRoot) {
    const setupRoot = path.resolve(installerRoot);
    const target = path.resolve(value);
    const isWithin = (parent, child) => {
      const relative = path.relative(parent, child);
      return relative === '' || (!path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`));
    };
    if (isWithin(setupRoot, target) || isWithin(target, setupRoot)) {
      return {
        ok: false,
        reason: 'overlaps-installer',
        message: 'Choose a folder separate from the Clipify AI Setup program folder.',
      };
    }
  }
  // A drive letter that is not present must not silently fall back to C:\,
  // because that would report the wrong volume's free space.
  const root = path.parse(value).root;
  if (/^[A-Za-z]:\\$/.test(root) && !fs.existsSync(root)) {
    return {
      ok: false,
      reason: 'missing-drive',
      message: `Drive ${root} is not available on this computer.`,
    };
  }
  // Reject characters that are illegal in a Windows path.
  if (/[<>:"|?*\u0000-\u001f]/.test(value.replace(/^[A-Za-z]:/, ''))) {
    return { ok: false, reason: 'illegal', message: 'That path contains invalid characters.' };
  }
  let parent = path.dirname(value);
  try {
    // The folder itself may not exist yet, but its parent must, otherwise we
    // cannot tell which volume it would land on.
    fs.accessSync(parent, fs.constants.W_OK);
  } catch {
    // Walk up until we find something that exists - a brand new folder under an
    // existing parent is perfectly normal.
    let probe = parent;
    while (probe && !fs.existsSync(probe)) {
      const next = path.dirname(probe);
      if (next === probe) break;
      probe = next;
    }
    if (!probe) {
      return {
        ok: false,
        reason: 'missing-root',
        message: 'That drive does not exist on this computer.',
      };
    }
    try {
      fs.accessSync(probe, fs.constants.W_OK);
    } catch {
      return {
        ok: false,
        reason: 'readonly',
        message: `You do not have permission to write to ${probe}.`,
      };
    }
  }
  if (fs.existsSync(value)) {
    let stat;
    try {
      stat = fs.statSync(value);
    } catch {
      stat = null;
    }
    if (stat && !stat.isDirectory()) {
      return {
        ok: false,
        reason: 'file',
        message: 'A file already exists at that location.',
      };
    }
  }
  return { ok: true, reason: null, message: '' };
}

/**
 * Real free space for the volume that will hold `installDir`.
 *
 * Key points:
 *  - The volume is found by parsing the root (C:\, D:\, \\server\share) and
 *    querying THAT, not the install folder. The folder usually does not exist.
 *  - `bavail` is user-available space, which is what an installer should show.
 *  - Any failure is reported explicitly in `error` rather than silently
 *    becoming 0, because 0 reads as "full disk" and wrongly blocks the install.
 */
function diskSpace(installDir) {
  const target = (installDir || '').trim() || defaultInstallDir();

  let root;
  try {
    root = path.parse(path.resolve(target)).root;
  } catch (error) {
    return {
      ok: false,
      freeBytes: 0,
      totalBytes: 0,
      volume: null,
      target,
      error: `Could not resolve that path: ${error.message}`,
    };
  }

  try {
    const stat = fs.statfsSync(root);
    const bsize = Number(stat.bsize);
    const freeBytes = Number(stat.bavail) * bsize;
    const totalBytes = Number(stat.blocks) * bsize;
    return {
      ok: true,
      volume: root,
      target,
      freeBytes,
      totalBytes,
      usedBytes: Math.max(0, totalBytes - freeBytes),
      error: null,
    };
  } catch (error) {
    // Fall back to PowerShell only when the native call is unavailable. This is
    // the difference between "we could not tell you" and a hard zero.
    return {
      ok: false,
      volume: root,
      target,
      freeBytes: 0,
      totalBytes: 0,
      error: `Could not read free space for ${root}: ${error.message}`,
    };
  }
}

/** Async variant that falls back to PowerShell when statfs is unavailable. */
async function diskSpaceAsync(installDir) {
  const direct = diskSpace(installDir);
  if (direct.ok) return direct;

  const root = direct.volume;
  if (!root) return direct;
  const script =
    `$v=New-Object System.IO.DriveInfo('${root.replace(/'/g, "''")}');` +
    'Write-Output ("$($v.AvailableFreeSpace)|$($v.TotalSize)")';
  const out = await tryRun('powershell.exe', ['-NoProfile', '-Command', script], 10000);
  if (!out) return direct;
  const match = out.match(/(\d+)\s*\|\s*(\d+)/);
  if (!match) return direct;
  const freeBytes = Number(match[1]);
  const totalBytes = Number(match[2]);
  if (!freeBytes || !totalBytes) return direct;
  return {
    ok: true,
    volume: root,
    target: direct.target,
    freeBytes,
    totalBytes,
    usedBytes: Math.max(0, totalBytes - freeBytes),
    error: null,
  };
}

function directorySize(dir) {
  let total = 0;
  const walk = (current) => {
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) walk(full);
      else {
        try {
          total += fs.statSync(full).size;
        } catch {
          /* ignore */
        }
      }
    }
  };
  walk(dir);
  return total;
}

/**
 * Walks the payload tree once so the UI can show a real total size.
 *
 * This is deliberately memoised. The payload is a few hundred megabytes and
 * never changes while setup is running, so re-walking it on every keystroke in
 * the path box was the single most expensive thing the installer could do -
 * and in a packaged build, where the files are read from inside the
 * installation, that is where the multi-second stalls came from.
 */
let payloadCache = null;
let payloadCachedFor = null;

function payloadSummary(payloadRoot) {
  if (!payloadRoot) {
    return { exists: false, files: 0, bytes: 0, hasAppExe: false, hasRuntimeScript: false };
  }
  if (payloadCache && payloadCachedFor === payloadRoot) return payloadCache;

  const result = readPayloadSummary(payloadRoot);
  payloadCache = result;
  payloadCachedFor = payloadRoot;
  return result;
}

function readPayloadSummary(payloadRoot) {
  if (!fs.existsSync(payloadRoot)) {
    return { exists: false, files: 0, bytes: 0, hasAppExe: false, hasRuntimeScript: false };
  }
  const files = [];
  const walk = (current) => {
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.name === 'runtime' || entry.name === '__pycache__' || entry.name === '.git') continue;
      const full = path.join(current, entry.name);
      let isDir = entry.isDirectory();
      if (!isDir && entry.isSymbolicLink()) {
        try { isDir = fs.statSync(full).isDirectory(); } catch { isDir = false; }
      }
      if (isDir) walk(full);
      else files.push(full);
    }
  };
  walk(payloadRoot);
  return {
    exists: true,
    files: files.length,
    bytes: files.reduce((sum, file) => {
      try {
        return sum + fs.statSync(file).size;
      } catch {
        return sum;
      }
    }, 0),
    hasAppExe: files.some((f) => path.basename(f).toLowerCase() === APP_EXE.toLowerCase()),
    hasRuntimeScript: files.some((f) => {
      const name = f.toLowerCase();
      return name.endsWith('clipifyai-runtime.ps1') || name.endsWith('clippedai-runtime.ps1');
    }),
  };
}

/** Test hook: forget the memoised payload walk. */
function resetCaches() {
  payloadCache = null;
  payloadCachedFor = null;
  ollamaCache = null;
  ollamaCachedAt = 0;
}

function runtimeStatus() {
  const home = path.join(process.env.LOCALAPPDATA || '', APP_SLUG);
  const runtime = path.join(home, 'runtime');
  const sitePackages = path.join(runtime, 'Lib', 'site-packages');
  const complete = fs.existsSync(path.join(sitePackages, 'clipsai'));
  let bytes = 0;
  if (fs.existsSync(runtime)) bytes = directorySize(runtime);
  return { home, runtime, sitePackages, complete, bytes };
}

//: Written into the runtime directory only after pip has finished successfully.
const RUNTIME_COMPLETE_MARKER = '.clipify-runtime-complete';

/**
 * Is a complete Tier-B runtime present *in this directory*?
 *
 * runtimeStatus() only ever looks at %LOCALAPPDATA%\<slug>\runtime, so a
 * runtime sitting in an older install always answered "complete". The location
 * screen turned that into zero bytes to download, which unticked the runtime
 * box on its own, and picking a new folder left the AI libraries behind where
 * they had always been. The answer has to depend on the folder the user chose.
 *
 * The marker file is written only after pip finishes, so a runtime left behind
 * by an interrupted install is correctly treated as absent. ClipsAI alone is
 * not a safe signal: pip installs packages alphabetically, so clipsai lands
 * early and hundreds of packages (jinja2, soundfile, torch itself) can still be
 * missing afterwards.
 */
function runtimeCompleteIn(runtimeDir) {
  if (!runtimeDir) return false;
  return fs.existsSync(path.join(runtimeDir, 'Lib', 'site-packages', 'clipsai')) &&
    fs.existsSync(path.join(runtimeDir, RUNTIME_COMPLETE_MARKER));
}

function narrationModelCompleteIn(runtimeDir) {
  if (!runtimeDir) return false;
  return fs.existsSync(path.join(runtimeDir, 'Lib', 'site-packages', 'en_core_web_sm'));
}

function previousInstall() {
  const home = path.join(process.env.LOCALAPPDATA || '', APP_SLUG);
  const statePath = path.join(home, 'setup-state.json');
  if (!fs.existsSync(statePath)) return { state: null, appDir: null, interrupted: false };
  try {
    const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
    return {
      state,
      appDir: state.installDir || null,
      interrupted: state.status === 'in-progress' || state.status === 'interrupted',
    };
  } catch {
    return { state: null, appDir: null, interrupted: false };
  }
}

function installedAtDefaultDir() {
  const dir = defaultInstallDir();
  return fs.existsSync(path.join(dir, APP_EXE)) ? dir : null;
}

function formatWindowsRelease() {
  return `${os.type()} ${os.release()} (${process.arch})`;
}

/**
 * Full detection pass. `installDir` is the currently proposed target so the
 * disk numbers match what the user sees on the location screen.
 */
async function detectAll({ installDir, payloadRoot, modelIds, selectedModels, options, installerRoot } = {}) {
  const targetDir = (installDir || '').trim() || defaultInstallDir();
  // The user can untick the runtime and/or Ollama on the location screen. The
  // required-space figure has to honour that, otherwise it keeps quoting space
  // for something we are not going to install.
  const wantRuntime = !options || options.installRuntime !== false;
  const wantOllama = !options || options.installOllama !== false;

  const ollama = await detectOllama();
  const runtime = runtimeStatus();
  const payload = payloadSummary(payloadRoot);
  const space = await diskSpaceAsync(targetDir);
  const validation = validateInstallDir(targetDir, installerRoot);
  const previous = previousInstall();
  const existing = installedAtDefaultDir();

  // Catalog cards always come from catalog.json. `installed` is an internal
  // hint so provisioning can skip a model that is already present, and the
  // summary can say "already on this computer" - it never adds new cards.
  const models = RUNTIME_MODELS.map((model) => ({
    ...model,
    installed: ollama.models.includes(model.id),
  }));

  // If an installed Qwen model is already available locally in Ollama, prioritize it
  // to avoid multi-gigabyte network downloads that can stall the installer.
  const defaultRecommended = (ollama && Array.isArray(ollama.models) && (
    ollama.models.find((m) => m === 'qwen2.5:3b' || m === 'qwen2.5:latest' || m.startsWith('qwen2.5:')) ||
    ollama.models.find((m) => m.startsWith('qwen'))
  )) || DEFAULT_ID;

  // An explicitly empty array means the user chose no models. Only fall back
  // to the recommended model when neither selection argument was provided.
  const wanted = Array.isArray(selectedModels)
    ? selectedModels
    : Array.isArray(modelIds)
      ? modelIds
      : [defaultRecommended];

  // Required space: the application payload, plus every model actually still to
  // be pulled (real registry sizes, not a flat guess), plus the ML runtime when
  // it is missing, plus Ollama when it is missing.
  const byId = new Map(models.map((m) => [m.id, m]));
  let modelBytes = 0;
  const modelsToDownload = [];
  for (const id of wanted) {
    const model = byId.get(id);
    if (!model) continue;
    if (model.installed) continue;
    modelBytes += model.sizeBytes || 0;
    modelsToDownload.push(model.id);
  }
  // "Already installed" has to mean "already installed in the folder the user
  // picked". Keying it off runtime.complete looked only at the old AppData
  // location, so choosing a new folder reported nothing to download and the
  // runtime checkbox unticked itself.
  const chosenRuntime = path.join(targetDir, 'runtime');
  const runtimeInTarget = runtimeCompleteIn(chosenRuntime);
  const runtimeBytes = !wantRuntime
    ? 0
    : runtimeInTarget
      ? (narrationModelCompleteIn(chosenRuntime) ? 0 : NARRATION_MODEL_BYTES)
      : RUNTIME_BYTES;
  const ollamaBytes = ollama.installed || !wantOllama ? 0 : OLLAMA_BYTES;
  const requiredBytes = Math.ceil(
    payload.bytes + modelBytes + runtimeBytes + ollamaBytes
  );

  const freeAfterBytes = Math.max(0, (space.freeBytes || 0) - requiredBytes);
  const enoughSpace =
    validation.ok && space.ok && (space.freeBytes || 0) >= requiredBytes;
  const shortfallBytes = Math.max(0, requiredBytes - (space.freeBytes || 0));

  return {
    appName: APP_NAME,
    publisher: PUBLISHER,
    windows: formatWindowsRelease(),
    arch: process.arch,
    cpuCount: os.cpus().length,
    totalMemoryBytes: os.totalmem(),
    freeMemoryBytes: os.freemem(),
    defaultInstallDir: defaultInstallDir(),
    installDir: targetDir,
    pathValid: validation.ok,
    pathError: validation.message,
    disk: space,
    diskVolume: space.volume,
    requiredBytes,
    freeAfterBytes,
    enoughSpace,
    shortfallBytes,
    modelsToDownload,
    modelBytes,
    runtimeBytes,
    runtimeInTarget,
    chosenRuntime,
    ollamaBytes,
    ollama,
    runtime,
    payload,
    models,
    recommendedModelId: defaultRecommended,
    previous,
    existingInstall: existing,
    uninstallKey: UNINSTALL_KEY,
    ids: wanted,
  };
}

module.exports = {
  APP_NAME,
  APP_SLUG,
  APP_SHORTCUT_NAME,
  APP_EXE,
  PUBLISHER,
  UNINSTALL_KEY,
  RUNTIME_MODELS,
  DEFAULT_ID,
  RUNTIME_BYTES,
  OLLAMA_BYTES,
  RUNTIME_COMPLETE_MARKER,
  defaultInstallDir,
  preferredInstallRoot,
  isDevelopmentCheckout,
  isolatedInstallDir,
  detectAll,
  detectOllama,
  diskSpace,
  diskSpaceAsync,
  validateInstallDir,
  directorySize,
  payloadSummary,
  runtimeStatus,
  runtimeCompleteIn,
  narrationModelCompleteIn,
  NARRATION_MODEL_BYTES,
  parseOllamaList,
  findOllama,
};
