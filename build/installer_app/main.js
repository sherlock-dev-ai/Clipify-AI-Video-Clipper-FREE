'use strict';

/**
 * Clipify AI setup - Electron main process.
 *
 * Owns the window, exposes a narrow IPC surface to the renderer, and hosts the
 * installation engine. All real work happens in lib/installer.js so this file
 * stays a thin, predictable shell: no blocking calls on the main thread, and
 * every engine event is forwarded to the renderer as it happens.
 */

const { app, BrowserWindow, dialog, ipcMain, shell, protocol, net, screen } = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PACKAGE_METADATA = require('./package.json');
const QA_INSTALL_SLUG = typeof PACKAGE_METADATA.clipifyQaInstallSlug === 'string'
  ? PACKAGE_METADATA.clipifyQaInstallSlug
  : '';
const PRODUCTION_APP_ID = PACKAGE_METADATA.build?.appId || 'dev.sherlock.clipifyai.setup';
const PRODUCT_APP_ID = 'dev.sherlock.clipifyai';
const WINDOWS_APP_ID = QA_INSTALL_SLUG
  ? `dev.sherlock.clipifyai.setup.qa.${QA_INSTALL_SLUG.toLowerCase().replace(/[^a-z0-9]+/g, '.')}`
  : PRODUCTION_APP_ID;

// Windows groups taskbar windows and shortcuts by AUMID. The executable and
// window already use the current ICO; without an explicit identity, stale
// shortcuts or Windows' fallback identity can keep an old taskbar grouping.
if (process.platform === 'win32') app.setAppUserModelId(WINDOWS_APP_ID);

// A packaged QA build keeps its Electron state, installer state, temp files,
// shortcuts, and default target beside the QA package. This lets smoke tests
// run from a workspace folder without touching the developer's normal profile.
const QA_DATA_ROOT = QA_INSTALL_SLUG
  ? path.join(process.resourcesPath || __dirname, '.clipify-qa-data')
  : '';
if (QA_INSTALL_SLUG) {
  const qaPaths = {
    LOCALAPPDATA: path.join(QA_DATA_ROOT, 'LocalAppData'),
    APPDATA: path.join(QA_DATA_ROOT, 'Roaming'),
    USERPROFILE: path.join(QA_DATA_ROOT, 'Profile'),
    TEMP: path.join(QA_DATA_ROOT, 'Temp'),
    TMP: path.join(QA_DATA_ROOT, 'Temp'),
  };
  for (const value of Object.values(qaPaths)) fs.mkdirSync(value, { recursive: true });
  Object.assign(process.env, qaPaths);
  for (const name of ['Desktop', 'Documents', 'Downloads', 'Music', 'Pictures', 'Videos']) {
    fs.mkdirSync(path.join(qaPaths.USERPROFILE, name), { recursive: true });
  }
  app.setPath('userData', path.join(QA_DATA_ROOT, 'userData'));
  app.setPath('appData', qaPaths.APPDATA);
  app.setPath('desktop', path.join(qaPaths.USERPROFILE, 'Desktop'));
  app.setPath('documents', path.join(qaPaths.USERPROFILE, 'Documents'));
  app.setPath('downloads', path.join(qaPaths.USERPROFILE, 'Downloads'));
  app.setPath('music', path.join(qaPaths.USERPROFILE, 'Music'));
  app.setPath('pictures', path.join(qaPaths.USERPROFILE, 'Pictures'));
  app.setPath('videos', path.join(qaPaths.USERPROFILE, 'Videos'));
}

const { detectAll, findOllama, defaultInstallDir, isolatedInstallDir, APP_SLUG, APP_SHORTCUT_NAME, APP_EXE, PUBLISHER, UNINSTALL_KEY, validateInstallDir } = require('./lib/detect');
const { Installer, APP_HOME, STATE_FILE, LOG_FILE } = require('./lib/installer');
const { removeBundledFiles } = require('./lib/uninstall');
const { stageTracks, releaseTracks, sweepStale } = require('./lib/music');
const { findMissingStartupFiles } = require('./lib/startup');

// Electron 44 no longer forwards Chromium switches from the command line
// (--remote-debugging-port / --no-sandbox now exit with "bad option"), so the
// wizard's CDP endpoint must be registered programmatically, before the app is
// ready. This keeps the build/driver tooling (which connects to 127.0.0.1:9333)
// working against the portable / packaged wizard. The installer is an ephemeral
// setup UI (not a persistent app), so a localhost-only DevTools port is safe.
app.commandLine.appendSwitch('remote-debugging-port', '9333');

/** Live reference to the staging folder, read by the protocol handler. */
const MUSIC_STAGE_DIR = () => require('./lib/music').stageDir || path.join(os.tmpdir(), '__none__');

/**
 * Where the bundled Clipify AI application lives.
 *
 * Packaged:  <resources>/payload, written by electron-builder from the verified
 *            payload staged by tools/stage_payload.py.
 * Dev run:   the same staged payload, because process.resourcesPath points at
 *            Electron's own resources folder when running unpackaged.
 *
 * The staged payload is deliberately NOT build/dist: that directory carries
 * test media, FFmpeg logs with developer paths, and legacy .bat/.vbs wrappers.
 */
function resolvePayloadRoot() {
  const candidates = [];
  if (process.resourcesPath) candidates.push(path.join(process.resourcesPath, 'payload'));
  candidates.push(path.join(__dirname, 'resources', 'payload'));
  candidates.push(path.join(__dirname, '..', '..', 'dist'));
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return candidates[candidates.length - 1];
}

const PAYLOAD_ROOT = resolvePayloadRoot();

let mainWindow = null;
let installer = null;
let rendererStartupTimer = null;
let startupFailureReported = false;

const isUninstallMode = process.argv.includes('--uninstall');

/**
 * Staged music is served over clipifymusic:// rather than file:///.
 *
 * The renderer runs under a strict CSP, and a file:/// URL pointing at %TEMP%
 * does not match 'self', so the <audio> element was silently refused and the
 * music never played. A registered scheme is same-origin from the page's point
 * of view and is therefore allowed, and it also removes any path-escaping worry
 * about spaces in the temp folder name.
 */
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'clipifymusic',
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
  },
]);

function registerMusicProtocol() {
  protocol.handle('clipifymusic', (request) => {
    const name = decodeURIComponent(new URL(request.url).pathname.replace(/^\/+/, ''));
    const base = MUSIC_STAGE_DIR();
    const file = path.join(base, path.basename(name));
    // Only ever serve from the folder we staged into.
    if (!file.startsWith(base) || !fs.existsSync(file)) {
      return new Response('not found', { status: 404 });
    }
    return net.fetch(`file://${file.replace(/\\/g, '/')}`);
  });
}

function createWindow() {
  const missing = findMissingStartupFiles(fs, app.getAppPath(), process.resourcesPath);
  if (missing.length) {
    failStartup('The custom installer UI package is incomplete.',
      `Missing required packaged files:\n\n${missing.map((name) => `• ${name}`).join('\n')}`);
    return;
  }

  const workArea = screen.getPrimaryDisplay().workAreaSize;
  const width = Math.min(1040, Math.max(820, workArea.width - 24));
  const height = Math.min(780, Math.max(640, workArea.height - 24));
  const iconPath = path.join(process.resourcesPath, 'icon.ico');
  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth: Math.min(820, width),
    minHeight: Math.min(640, height),
    resizable: true,
    maximizable: true,
    frame: false,
    show: false,
    backgroundColor: '#07070c',
    icon: iconPath,
    title: 'Clipify AI Setup',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  if (process.platform === 'win32') {
    try {
      mainWindow.setAppDetails({ appId: WINDOWS_APP_ID, appIconPath: iconPath });
    } catch (error) {
      writeStartupLog(`could not set Windows taskbar identity: ${error.message}`);
    }
  }

  mainWindow.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
    if (isMainFrame) failStartup('The custom installer UI could not load.',
      `Chromium error ${code}: ${description}\n\nURL: ${url}`);
  });
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    failStartup('The custom installer UI stopped unexpectedly.',
      `Renderer exit: ${details.reason}; exit code: ${details.exitCode}`);
  });
  mainWindow.webContents.on('console-message', (_event, details) => {
    if (details && details.level >= 3) {
      writeStartupLog(`renderer console error: ${details.message} (${details.sourceId}:${details.lineNumber})`);
    }
  });
  rendererStartupTimer = setTimeout(() => {
    failStartup('The custom installer UI did not finish starting.',
      'The renderer did not report a successful UI boot within 60 seconds. Check setup-startup.log for details.');
  }, 60000);
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html')).catch((error) => {
    failStartup('The custom installer UI could not load.', error.stack || error.message);
  });
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function writeStartupLog(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  try {
    const logPath = path.join(app.getPath('userData'), 'setup-startup.log');
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, line, 'utf8');
  } catch (_) {
    console.error(line.trim());
  }
}

function failStartup(title, detail) {
  if (startupFailureReported) return;
  startupFailureReported = true;
  if (rendererStartupTimer) clearTimeout(rendererStartupTimer);
  writeStartupLog(`${title}\n${detail}`);
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.destroy();
  dialog.showErrorBox(title, `${detail}\n\nDiagnostic log: ${path.join(app.getPath('userData'), 'setup-startup.log')}`);
  app.quit();
}

/** Pushes an engine event to the renderer, but only while a window exists. */
function forward(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

function ensureInstaller() {
  if (installer) return installer;
  installer = new Installer({ payloadRoot: PAYLOAD_ROOT });
  installer.on('progress', (data) => forward('setup:progress', data));
  installer.on('phase', (data) => forward('setup:phase', data));
  installer.on('log', (line) => forward('setup:log', line));
  // The live activity feed. Streamed one entry at a time so the install screen
  // can keep a running tail of what is actually happening right now.
  installer.on('activity', (entry) => forward('setup:activity', entry));
  installer.on('done', async (data) => {
    // Music belongs to the setup process only.
    releaseTracks();
    // Register only after every install phase succeeds. Registering at click
    // time left Add/Remove Programs pointing at a partial target after a
    // cancelled or failed install.
    if (QA_INSTALL_SLUG) {
      reportUninstallRegistration(`QA mode: skipped Add/Remove Programs registration for ${data.installDir}`);
    } else {
      await registerUninstallEntry(data.installDir);
    }
    forward('setup:done', data);
  });
  installer.on('failed', (data) => forward('setup:failed', data));
  installer.on('cancelled', () => forward('setup:cancelled', {}));
  installer.on('create-shortcut', (request) => {
    try {
      const shortcutAppId = request.applicationType === 'product' ? PRODUCT_APP_ID : WINDOWS_APP_ID;
      const written = shell.writeShortcutLink(request.shortcutPath, 'create', {
        target: request.targetPath,
        args: request.args || '',
        cwd: request.workingDirectory || '',
        description: request.description || '',
        ...(request.iconPath ? { icon: request.iconPath, iconIndex: 0 } : {}),
        appUserModelId: shortcutAppId,
      });
      if (!written) throw new Error('Windows did not create the shortcut.');
      const shortcut = shell.readShortcutLink(request.shortcutPath);
      if (shortcut.appUserModelId !== shortcutAppId) {
        throw new Error(`Shortcut AppUserModelID mismatch: ${shortcut.appUserModelId || '(empty)'}`);
      }
    } catch (error) {
      forward('setup:log', `shortcut creation failed: ${error.message}`);
    }
  });
  return installer;
}

function reportUninstallRegistration(message) {
  try { fs.appendFileSync(LOG_FILE, `[${new Date().toISOString()}] ${message}\n`, 'utf8'); } catch {}
  forward('setup:log', message);
}

/** Writes the Add/Remove Programs entry so Windows can uninstall us. */
function registerUninstallEntry(installDir) {
  if (process.platform !== 'win32') return;
  try {
    const { execFile } = require('child_process');
    const psQuote = (value) => String(value).replace(/'/g, "''");
    const ps =
      `$ErrorActionPreference='Stop';` +
      `$k='${UNINSTALL_KEY}';` +
      `New-Item -Path $k -Force | Out-Null;` +
      `Set-ItemProperty $k -Name DisplayName -Value 'Clipify AI';` +
      `Set-ItemProperty $k -Name DisplayVersion -Value '${app.getVersion()}';` +
      `Set-ItemProperty $k -Name Publisher -Value '${PUBLISHER}';` +
      `Set-ItemProperty $k -Name DisplayIcon -Value '${psQuote(path.join(installDir, 'icon.ico'))}';` +
      `Set-ItemProperty $k -Name InstallLocation -Value '${psQuote(installDir)}';` +
      `New-ItemProperty -Path $k -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null;` +
      `New-ItemProperty -Path $k -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null;` +
      `Set-ItemProperty $k -Name UninstallString -Value '"${psQuote(process.execPath)}" --uninstall';` +
      `$registeredPath=Get-ItemPropertyValue -Path $k -Name InstallLocation;` +
      `if ($registeredPath -ne '${psQuote(installDir)}') { throw 'InstallLocation registry verification failed'; }`;
    return new Promise((resolve) => {
      execFile('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], {
        windowsHide: true,
      }, (error, _stdout, stderr) => {
        if (error) {
          reportUninstallRegistration(`could not register uninstall entry: ${error.message}; ${stderr || ''}`);
          resolve(false);
        } else {
          reportUninstallRegistration(`registered uninstall entry for ${installDir}`);
          resolve(true);
        }
      });
    });
  } catch (error) {
    reportUninstallRegistration(`could not register uninstall entry: ${error.message}`);
    return Promise.resolve(false);
  }
}

// ------------------------------------------------------------------- IPC

ipcMain.handle('setup:detect', async (_event, options = {}) => {
  return detectAll({
    installDir: options.installDir || options_defaultDir(),
    payloadRoot: PAYLOAD_ROOT,
    selectedModels: options.selectedModels,
    options: options.options,
    installerRoot: path.dirname(process.execPath),
  });
});

// Music is a setup-time feature. Tracks are staged into a temp folder at launch
// and removed as soon as setup finishes, so nothing is left behind.
ipcMain.handle('setup:music', async () => stageTracks());

ipcMain.handle('setup:browse', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Choose where Clipify AI should be installed',
    defaultPath: options_defaultDir(),
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled) return null;
  // Electron >= 14 returns `filePaths`; `result` was removed. Reading the old
  // field threw a TypeError in the renderer.
  const paths = result.filePaths || [];
  return paths.length ? paths[0] : null;
});

// Mirrors lib/detect.defaultInstallDir so the folder picker opens on the same
// L: location the screen shows, instead of a stale C:\ path.
function options_defaultDir() {
  const isolatedTarget = isolatedInstallDir(
    QA_INSTALL_SLUG,
    process.env.LOCALAPPDATA,
    app.getPath('userData')
  );
  if (isolatedTarget) return isolatedTarget;
  try {
    return defaultInstallDir();
  } catch (_) {
    return path.join(process.env.LOCALAPPDATA || '', 'Programs', APP_SLUG);
  }
}

ipcMain.handle('setup:renderer-ready', (event) => {
  if (!mainWindow || event.sender !== mainWindow.webContents || startupFailureReported) return false;
  if (rendererStartupTimer) clearTimeout(rendererStartupTimer);
  rendererStartupTimer = null;
  mainWindow.show();
  writeStartupLog('custom installer renderer reported successful boot');
  return true;
});

ipcMain.handle('setup:renderer-error', (event, message) => {
  if (!mainWindow || event.sender !== mainWindow.webContents) return false;
  failStartup('The custom installer UI failed during startup.', String(message || 'Unknown renderer error'));
  return true;
});

ipcMain.handle('setup:start', async (_event, options) => {
  const pathCheck = validateInstallDir(options.installDir, path.dirname(process.execPath));
  if (!pathCheck.ok) {
    forward('setup:failed', { error: pathCheck.message, phaseId: null });
    return { started: false, error: pathCheck.message };
  }
  const engine = ensureInstaller();
  // Deliberately not awaited: the renderer receives progress over IPC and must
  // stay interactive for the whole installation.
  engine.start(options).catch((error) => {
    forward('setup:failed', { error: error.message });
  });
  return { started: true };
});

ipcMain.handle('setup:cancel', async () => {
  return ensureInstaller().cancel();
});

ipcMain.handle('setup:retry', async (_event, { phaseId, options }) => {
  const engine = ensureInstaller();
  engine.retryPhase(phaseId, options).catch((error) => {
    forward('setup:failed', { error: error.message, phaseId });
  });
  return { started: true };
});

ipcMain.handle('setup:launch', async () => {
  const dir = ensureInstaller().options
    ? ensureInstaller().options.installDir
    : options_defaultDir();
  // Launch the compiled executable directly. The old path preferred
  // ClippedAI.vbs, which shelled out to a .bat - that is exactly the
  // wrapper-based launch the product requirements forbid.
  const exe = path.join(dir, APP_EXE);
  if (!fs.existsSync(exe)) {
    return { ok: false, error: `Clipify AI was not found at ${dir}` };
  }
  const { spawn } = require('child_process');
  const child = spawn(exe, [], {
    cwd: dir,
    detached: true,
    stdio: 'ignore',
    // Keep the worker's runtime, model store and writable data rooted in the
    // folder the user selected. Inheriting a developer or older install's
    // environment can silently point the freshly installed app elsewhere.
    env: Object.assign({}, process.env, ensureInstaller().appEnv()),
    // The app is a GUI-subsystem binary that opens its own browser window, so
    // there is nothing to show here.
    windowsHide: true,
    shell: false,
  });
  try {
    await new Promise((resolve, reject) => {
      child.once('spawn', resolve);
      child.once('error', reject);
    });
  } catch (error) {
    forward('setup:log', `launch failed: ${error.message}`);
    return { ok: false, error: `Clipify AI could not be launched: ${error.message}` };
  }
  child.unref();
  setTimeout(() => {
    try {
      shell.openExternal('http://127.0.0.1:5000/');
    } catch (e) {
      forward('setup:log', `openExternal failed: ${e.message}`);
    }
  }, 2500);
  return { ok: true, launched: exe };
});

ipcMain.handle('setup:openFolder', async (_event, target) => {
  const dir = target || (ensureInstaller().options || {}).installDir;
  if (!dir || !fs.existsSync(dir)) return { ok: false };
  const error = await shell.openPath(dir);
  return { ok: !error, error: error || null };
});

ipcMain.handle('setup:openLog', async () => {
  const logPath = fs.existsSync(LOG_FILE) ? LOG_FILE : path.join(app.getPath('userData'), 'setup-startup.log');
  if (!fs.existsSync(logPath)) {
    return { ok: false, error: 'The setup log has not been created yet.' };
  }
  const error = await shell.openPath(logPath);
  return { ok: !error, error: error || null };
});

ipcMain.handle('setup:openExternal', async (_event, url) => {
  // Only ever open a real https URL in the user's browser.
  if (typeof url !== 'string' || !/^https:\/\/github\.com\/sherlock-dev-ai/.test(url)) {
    return { ok: false };
  }
  await shell.openExternal(url);
  return { ok: true };
});

ipcMain.handle('setup:window', async (_event, action) => {
  if (!mainWindow) return;
  if (action === 'minimize') mainWindow.minimize();
  else if (action === 'close') mainWindow.close();
});

ipcMain.handle('setup:state', async () => {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return null;
  }
});

ipcMain.handle('setup:quit', async () => {
  if (ensureInstaller().running) ensureInstaller().cancel();
  app.quit();
});

// --------------------------------------------------------------- uninstall

async function runUninstall() {
  const state = (() => {
    try {
      return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    } catch {
      return null;
    }
  })();
  const installDir = (state && state.installDir) || options_defaultDir();

  const result = await dialog.showMessageBox({
    type: 'question',
    buttons: ['Uninstall', 'Cancel'],
    defaultId: 1,
    cancelId: 1,
    title: 'Uninstall Clipify AI',
    message: 'Remove Clipify AI?',
    detail:
      'The application files will be removed. Your projects, rendered videos, settings, ' +
      `AI runtime and downloaded models in ${installDir} will be preserved unless you ` +
      'choose to remove all Clipify AI data too.',
    checkboxLabel: 'Also remove my Clipify AI data',
    checkboxChecked: false,
  });
  if (result.response !== 0) {
    app.quit();
    return;
  }

  try {
    if (result.checkboxChecked) {
      fs.rmSync(APP_HOME, { recursive: true, force: true });
      fs.rmSync(installDir, { recursive: true, force: true });
    } else {
      const cleanup = removeBundledFiles(installDir, PAYLOAD_ROOT);
      forward('setup:log', `removed ${cleanup.removed} application files; preserved non-payload data`);
    }
    const startMenu = path.join(
      process.env.APPDATA || '',
      'Microsoft', 'Windows', 'Start Menu', 'Programs', APP_SHORTCUT_NAME
    );
    for (const name of [`${APP_SHORTCUT_NAME}.lnk`, `Uninstall ${APP_SHORTCUT_NAME}.lnk`]) {
      fs.rmSync(path.join(startMenu, name), { force: true });
    }
    try {
      fs.rmdirSync(startMenu);
    } catch (error) {
      if (error.code !== 'ENOENT' && error.code !== 'ENOTEMPTY') throw error;
    }
    const desktop = path.join(app.getPath('desktop'), `${APP_SHORTCUT_NAME}.lnk`);
    fs.rmSync(desktop, { force: true });
    await new Promise((resolve, reject) => {
      require('child_process').execFile(
        'powershell.exe',
        [
          '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
          `Remove-Item -LiteralPath '${UNINSTALL_KEY}' -Recurse -Force -ErrorAction SilentlyContinue`,
        ],
        { windowsHide: true },
        (error) => error ? reject(error) : resolve()
      );
    });
    dialog.showMessageBox({
      type: 'info',
      buttons: ['OK'],
      title: 'Clipify AI',
      message: 'Clipify AI has been uninstalled.',
    });
  } catch (error) {
    dialog.showErrorBox('Uninstall failed', error.message);
  }
  app.quit();
}

// ------------------------------------------------------------------- boot

app.whenReady().then(() => {
  // Clear anything a previous, hard-killed run left in %TEMP% before staging new.
  sweepStale();
  registerMusicProtocol();
  if (isUninstallMode) {
    runUninstall();
    return;
  }
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  app.quit();
});

// Never leave a half-installed state behind if the user force-closes the window,
// and never leave the staged music behind either.
app.on('before-quit', () => {
  if (installer && installer.running) installer.cancel();
  releaseTracks();
});
