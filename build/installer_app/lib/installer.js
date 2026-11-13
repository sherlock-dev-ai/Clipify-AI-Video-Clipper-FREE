'use strict';

/**
 * The actual installation engine.
 *
 * Design rules that this file exists to enforce:
 *
 *  1. The UI thread is never blocked. Every long operation (copying ~590 MB of
 *     application files, downloading CPython, pip-installing the ML runtime,
 *     pulling multi-gigabyte models) runs in a child process or a worker with
 *     periodic progress events, so the window keeps painting and the dino game
 *     keeps running.
 *  2. Nothing waits on a download to *display* state. The installer emits a
 *     terminal "error" state per step and the UI offers a retry, instead of
 *     hanging.
 *  3. State is persisted to %LOCALAPPDATA%\ClipifyAI\setup-state.json after
 *     every step, so an interrupted install resumes rather than restarting.
 *  4. Already-present work is never redone: an installed model is skipped, an
 *     existing application payload is verified rather than rewritten, and an
 *     existing ML runtime is detected and left alone.
 */

const { EventEmitter } = require('events');
const { spawn, execFile } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const https = require('https');
const http = require('http');
const os = require('os');
const path = require('path');
const { StringDecoder } = require('string_decoder');

const { APP_SLUG, APP_SHORTCUT_NAME, APP_EXE, findOllama, parseOllamaList, runtimeStatus, runtimeCompleteIn, narrationModelCompleteIn, RUNTIME_COMPLETE_MARKER, directorySize } = require('./detect');
const {
  acquireInstallLock,
  renameWithRetry,
  uniqueSibling,
} = require('./filesystem');

const APP_HOME = path.join(process.env.LOCALAPPDATA || '', APP_SLUG);

const USER_DATA_DIRS = new Set(['input', 'output', 'jobs', 'projects', 'settings', 'assets', 'narrate clips', 'big narrate clips', 'sliced clips']);
const USER_DATA_FILES = new Set(['.env', 'ffmpeg.log']);

function installedApplicationFootprint(installDir) {
  let entries;
  try {
    entries = fs.readdirSync(installDir, { withFileTypes: true });
  } catch (error) {
    if (error.code === 'ENOENT') return 0;
    throw error;
  }
  let total = 0;
  for (const entry of entries) {
    const name = entry.name.toLowerCase();
    if (entry.isDirectory() && USER_DATA_DIRS.has(name)) continue;
    if (entry.isFile() && USER_DATA_FILES.has(name)) continue;
    try {
      const full = path.join(installDir, entry.name);
      total += entry.isDirectory() ? directorySize(full) : fs.statSync(full).size;
    } catch { /* An unreadable optional user file should not block setup completion. */ }
  }
  return total;
}

/**
 * Move a file or directory across the filesystem, surviving cross-device
 * renames (EXDEV) that happen when the staging area lives on one drive --
 * e.g. %TEMP% on C: -- and the chosen install folder is on another, such as
 * the user-requested L:\ drive. rename() is atomic only within one volume;
 * off-volume we fall back to a recursive copy then a delete.
 */
function movePath(src, dest) {
  try {
    fs.renameSync(src, dest);
    return;
  } catch (e) {
    if (e && e.code !== 'EXDEV' && e.code !== 'EXDEV_LINUX' && e.code !== 'ENOTSUP') throw e;
  }
  fs.cpSync(src, dest, { recursive: true });
  fs.rmSync(src, { recursive: true, force: true });
}

// Everything the app needs at run time used to land in APP_HOME, which is
// %LOCALAPPDATA%\ClipifyAI on C: no matter where the user pointed the
// installer. The multi-gigabyte AI runtime and the model store therefore ended
// up on the system drive while the 250 MB payload sat wherever they asked, and
// the install looked incomplete. These two live inside the chosen directory
// instead, so "install to D:\Clipify" really does put the whole product there.
const RUNTIME_DIR_NAME = 'runtime';
const PYTHON_DIR_NAME = 'python311';
const MODELS_DIR_NAME = 'models';
const STATE_FILE = path.join(APP_HOME, 'setup-state.json');
const LOG_FILE = path.join(APP_HOME, 'setup.log');
const LOCK_FILE = path.join(APP_HOME, 'installer.lock');

const PYTHON_VERSION = '3.11.9';
// Portable CPython, distributed as a plain zip rather than the python.org .exe
// bootstrapper. The .exe is a WiX Burn bundle: when the same version is already
// installed anywhere on the machine it reports WixBundleInstalled=1,
// WixBundleAction=6 and exits 0 WITHOUT installing into our TargetDir, so
// ensurePython found an empty directory and failed. A zip has no installer
// state, so it behaves identically on a clean and a pre-configured machine.
const PYTHON_URL = `https://www.nuget.org/api/v2/package/python/${PYTHON_VERSION}`;
const OLLAMA_URL = 'https://ollama.com/download/OllamaSetup.exe';

/** Approximate download sizes, used only for ETA and disk checks. */
const MODEL_BYTES = {
  'qwen3:8b': 5.2 * 1024 ** 3,
  'qwen3:4b': 2.6 * 1024 ** 3,
  'qwen3:14b': 9.0 * 1024 ** 3,
  'dolphin3:8b': 5.2 * 1024 ** 3,
  'custom-dolphin:latest': 5.0 * 1024 ** 3,
  'my-coder:latest': 5.0 * 1024 ** 3,
  'dolphin3:8b': 4.92 * 1e9,
  'dolphin3:latest': 4.92 * 1e9,
  'dolphin-llama3:8b': 4.9 * 1e9,
  'dolphin-mistral:7b': 4.1 * 1e9,
};

// Weights are shares of the user's *waiting time*, not of the work done.
// The model pull is by far the longest step (multi-GB over the network), so
// it has to own a real slice of the bar. Weighting it at 22 while the runtime
// took 55 meant a nine-minute download could only move the bar a few points
// and it looked frozen even though bytes were streaming in.
const PHASES = [
  { id: 'files', label: 'Copying Clipify AI', weight: 5 },
  { id: 'python', label: 'Preparing the Python engine', weight: 5 },
  { id: 'runtime', label: 'Installing the AI runtime', weight: 30 },
  { id: 'ollama', label: 'Setting up the local AI engine', weight: 10 },
  { id: 'models', label: 'Downloading AI models', weight: 45 },
  { id: 'shortcuts', label: 'Creating shortcuts', weight: 3 },
  { id: 'verify', label: 'Verifying Clipify AI', weight: 2 },
];

async function sha256File(filePath) {
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(filePath)) digest.update(chunk);
  return digest.digest('hex');
}

const SIZE_UNITS = {
  b: 1,
  kb: 1000, kib: 1024,
  mb: 1000 ** 2, mib: 1024 ** 2,
  gb: 1000 ** 3, gib: 1024 ** 3,
  tb: 1000 ** 4, tib: 1024 ** 4,
};

/** Parse ollama's human-readable size ("4.9 GB") into a byte count. */
function toBytes(value, unit) {
  const scale = SIZE_UNITS[String(unit).toLowerCase()];
  if (!scale) return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n * scale : 0;
}

class Installer extends EventEmitter {
  constructor({ payloadRoot, logPath = LOG_FILE, statePath = STATE_FILE, lockPath = LOCK_FILE }) {
    super();
    this.payloadRoot = payloadRoot;
    this.logPath = logPath;
    this.statePath = statePath;
    this.lockPath = lockPath;
    this.cancelled = false;
    this.running = false;
    this.options = null;
    this.currentChild = null;
    this.phaseState = {};
    this.models = [];
    this.installedModels = [];
    this.bytesDone = 0;
    this.bytesTotal = 0;
    this.startedAt = 0;
    this.taskStartedAt = 0;
    this.lastTaskActivityAt = 0;
    this.activeTask = '';
    this.activeItem = '';
    this.speedBytes = 0;
    this.byteSample = null;
    this.installComplete = false;
    // Bounded tail of what the installer is doing right now. The renderer
    // streams this so the window always has current, concrete text on it.
    this.activity = [];
    this._noteAt = {};
    this.activePhaseId = null;
  }

  /**
   * Root for the Python engine, the AI runtime venv, the model store and user
   * data. This is the folder the user picked, so nothing lands on C:.
   */
  dataRoot() {
    const chosen = this.options && this.options.installDir;
    return chosen ? path.resolve(chosen) : APP_HOME;
  }

  pythonDir() {
    return path.join(this.dataRoot(), PYTHON_DIR_NAME);
  }

  runtimeDir() {
    return path.join(this.dataRoot(), RUNTIME_DIR_NAME);
  }

  modelsDir() {
    // If the user chose a custom Ollama model directory, honour it.
    // Otherwise default to <installDir>/models so the gigabyte model files
    // follow the installation drive rather than landing on C:.
    const custom = this.options && this.options.modelsDir;
    if (custom) return path.resolve(custom);
    return path.join(this.dataRoot(), MODELS_DIR_NAME);
  }

  /**
   * Environment handed to the installed app so it finds the runtime, the user
   * data and the models without having to guess. A path that does not exist is
   * harmless: clippedai_runtime falls back to its own defaults.
   */
  appEnv(extra) {
    const root = this.dataRoot();
    return Object.assign(
      {
        CLIPPEDAI_DATA_DIR: root,
        CLIPPEDAI_RUNTIME: this.runtimeDir(),
        CLIPPEDAI_NARRATE_CLIPS: path.join(root, 'narrate clips'),
        // Ollama model store: user-chosen path wins, then install-drive default.
        OLLAMA_MODELS: this.modelsDir(),
      },
      extra || {}
    );
  }

  // ---------------------------------------------------------------- logging

  log(message) {
    const line = `[${new Date().toISOString()}] ${message}`;
    try {
      fs.mkdirSync(path.dirname(this.logPath), { recursive: true });
      fs.appendFileSync(this.logPath, `${line}\n`);
    } catch {
      /* logging must never break the install */
    }
    this.emit('log', line);
  }

  /**
   * Live activity feed.
   *
   * Nearly all of the install is spent waiting on other programs - a pip run, a
   * multi-gigabyte pull, a file copy. A progress bar alone leaves long stretches
   * where nothing visibly changes, and the installer reads as hung even though
   * it is working. Every real step reports here so the window can show the tail
   * of the work as it happens.
   */
  phaseLabel(id) {
    const found = PHASES.find((phase) => phase.id === id);
    return found ? found.label : id;
  }

  note(text, kind = 'info') {
    const clean = String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
    if (!clean) return;
    this.lastTaskActivityAt = Date.now();
    const entry = { at: Date.now(), kind, text: clean.slice(0, 170) };
    this.activity.push(entry);
    // A long pip run can produce thousands of lines and the renderer only ever
    // shows the tail, so the buffer is capped rather than grown without limit.
    if (this.activity.length > 400) this.activity.splice(0, this.activity.length - 400);
    // The UI tail is bounded, while the on-disk diagnostic log keeps the full
    // activity history so a long install can be inspected after a restart.
    this.log(`activity [${kind}]: ${clean}`);
    this.emit('activity', entry);
  }

  resetByteProgress() {
    this.bytesDone = 0;
    this.bytesTotal = 0;
    this.speedBytes = 0;
    this.byteSample = null;
  }

  updateByteProgress(done, total) {
    const now = Date.now();
    const nextDone = Math.max(0, Number(done) || 0);
    const nextTotal = Math.max(0, Number(total) || 0);
    const previous = this.byteSample;
    if (previous && previous.total === nextTotal && nextDone >= previous.done) {
      const dt = (now - previous.at) / 1000;
      if (dt >= 0.15) {
        const instantSpeed = (nextDone - previous.done) / dt;
        this.speedBytes = this.speedBytes > 0
          ? Math.round(this.speedBytes * 0.65 + instantSpeed * 0.35)
          : Math.round(instantSpeed);
        this.byteSample = { done: nextDone, total: nextTotal, at: now };
      }
    } else {
      this.byteSample = { done: nextDone, total: nextTotal, at: now };
      if (!previous) this.speedBytes = 0;
    }
    this.bytesDone = nextDone;
    this.bytesTotal = nextTotal;
  }

  /**
   * Rate-limited note for sources that fire many times a second (pip progress
   * bars, blob chunks). Without this the feed would spend its whole budget
   * repeating one download line and bury the interesting steps.
   */
  throttledNote(key, text, kind = 'info', minGapMs = 400) {
    const now = Date.now();
    const last = this._noteAt[key] || 0;
    if (now - last < minGapMs) return;
    this._noteAt[key] = now;
    this.note(text, kind);
  }

  // ------------------------------------------------------------------ state

  readState() {
    try {
      return JSON.parse(fs.readFileSync(this.statePath, 'utf8'));
    } catch {
      return null;
    }
  }

  writeState(extra = {}) {
    const state = {
      app: APP_SLUG,
      status: this.running ? 'in-progress' : 'complete',
      updatedAt: new Date().toISOString(),
      installDir: this.options ? this.options.installDir : null,
      selectedModels: this.options ? this.options.models : [],
      desktopShortcut: this.options ? Boolean(this.options.desktopShortcut) : false,
      completedPhases: Object.entries(this.phaseState)
        .filter(([, value]) => value.status === 'done')
        .map(([key]) => key),
      installedModels: this.installedModels,
      ...extra,
    };
    const tmp = `${this.statePath}.tmp`;
    try {
      fs.mkdirSync(path.dirname(this.statePath), { recursive: true });
      fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
      fs.renameSync(tmp, this.statePath);
    } catch (error) {
      this.log(`could not persist state: ${error.message}`);
    }
    return state;
  }

  // --------------------------------------------------------------- progress

  beginPhase(id) {
    this.activePhaseId = id;
    this.taskStartedAt = Date.now();
    this.lastTaskActivityAt = this.taskStartedAt;
    this.bytesDone = 0;
    this.bytesTotal = 0;
    this.speedBytes = 0;
    this.byteSample = null;
    this.phaseState[id] = { status: 'running', percent: 0, message: '' };
    this.emit('phase', { id, ...this.phaseState[id] });
    this.note(`${this.phaseLabel(id)} \u2014 starting`, 'phase');
  }

  updatePhase(id, percent, message) {
    if (!this.phaseState[id]) this.phaseState[id] = { status: 'running' };
    this.phaseState[id].percent = Math.max(0, Math.min(100, Math.round(percent)));
    if (message) this.phaseState[id].message = message;
    this.emit('phase', { id, ...this.phaseState[id] });
  }

  finishPhase(id, status = 'done', message = '') {
    this.phaseState[id] = { status, percent: status === 'done' ? 100 : 0, message };
    if (this.activePhaseId === id) this.activePhaseId = null;
    this.emit('phase', { id, ...this.phaseState[id] });
    this.note(
      `${this.phaseLabel(id)} \u2014 ${message || (status === 'done' ? 'done' : status)}`,
      status === 'error' ? 'error' : status === 'done' ? 'ok' : 'info'
    );
    this.writeState();
    this.emitProgress();
  }

  /**
   * Overall percent is a weighted blend of the phases, so a slow runtime
   * install still advances the bar smoothly instead of jumping.
   */
  overallPercent() {
    let done = 0;
    for (const phase of PHASES) {
      const entry = this.phaseState[phase.id];
      if (!entry) continue;
      // A skipped phase is finished work. It used to fall through and add
      // nothing, which silently stole its weight from the total and left the
      // bar short of 100% whenever anything was already installed.
      if (entry.status === 'done' || entry.status === 'skipped') done += phase.weight;
      else if (entry.status === 'running') {
        const activeProgressIsUnknown = this.activePhaseId === phase.id
          && ['runtime', 'ollama', 'verify'].includes(phase.id);
        if (!activeProgressIsUnknown) done += phase.weight * (entry.percent / 100);
      }
    }
    const rounded = Math.round(done);
    return this.installComplete ? Math.min(100, rounded) : Math.min(99, rounded);
  }

  emitProgress(extra = {}) {
    const elapsed = this.startedAt ? Date.now() - this.startedAt : 0;
    if (this.byteSample && Date.now() - this.byteSample.at > 5000) this.speedBytes = 0;
    this.emit('progress', {
      overall: this.overallPercent(),
      task: this.activeTask,
      item: this.activeItem,
      bytesDone: this.bytesDone,
      bytesTotal: this.bytesTotal,
      speedBytes: this.speedBytes,
      elapsedMs: elapsed,
      taskElapsedMs: this.taskStartedAt ? Date.now() - this.taskStartedAt : 0,
      lastActivityAgoMs: this.lastTaskActivityAt ? Date.now() - this.lastTaskActivityAt : null,
      etaMs: this.etaMs(),
      determinate: !['runtime', 'ollama', 'verify'].includes(this.activePhaseId),
      phases: PHASES.map((phase) => ({
        id: phase.id,
        label: phase.label,
        ...(this.phaseState[phase.id] || { status: 'pending', percent: 0 }),
      })),
      models: this.models,
      installedModels: this.installedModels,
      ...extra,
    });
  }

  etaMs() {
    if (this.pipEtaMs && this.pipEtaMs > 0) return this.pipEtaMs;
    if (this.bytesDone <= 0 || this.bytesTotal <= 0 || this.speedBytes <= 0) {
      if (this.activePhaseId === 'runtime') {
        const spent = this.taskStartedAt ? Date.now() - this.taskStartedAt : 0;
        return Math.max(15000, 240000 - spent);
      }
      return null;
    }
    return Math.max(0, (this.bytesTotal - this.bytesDone) / this.speedBytes * 1000);
  }

  // ----------------------------------------------------------------- cancel

  cancel() {
    if (!this.running) return false;
    this.cancelled = true;
    this.log('cancel requested by the user');
    if (this.currentChild) {
      try {
        this.currentChild.kill();
      } catch {
        /* already gone */
      }
    }
    this.writeState({ status: 'interrupted' });
    return true;
  }

  checkCancelled() {
    if (this.cancelled) {
      const error = new Error('Installation cancelled');
      error.cancelled = true;
      throw error;
    }
  }

  // ------------------------------------------------------------ child procs

  /**
   * Runs a command, streaming stdout/stderr lines to `onLine`.
   * Never rejects on a non-zero exit unless `allowFailure` is false, and always
   * resolves, so a failed download surfaces as a phase error rather than a hang.
   */
  runProcess(command, args, {
    onLine, cwd, env, allowFailure = true, timeoutMs = 0,
    heartbeatMs = 0, watchDirectory = '', quietWarningMs = 0, onHeartbeat,
  } = {}) {
    return new Promise((resolve) => {
      const child = spawn(command, args, {
        cwd,
        env: { ...process.env, ...(env || {}) },
        windowsHide: true,
        shell: false,
      });
      this.currentChild = child;
      let settled = false;
      let timer = null;
      let heartbeat = null;
      let watcher = null;
      let timedOut = false;
      let lastOutputAt = Date.now();
      let lastFileActivityAt = Date.now();
      let lastWarningAt = 0;

      const finish = (code) => {
        if (settled) return;
        settled = true;
        this.currentChild = null;
        if (timer) clearTimeout(timer);
        if (heartbeat) clearInterval(heartbeat);
        if (watcher) watcher.close();
        resolve({ code: timedOut || code === null ? -1 : code });
      };

      if (timeoutMs > 0) {
        timer = setTimeout(() => {
          timedOut = true;
          this.log(`timeout after ${timeoutMs}ms: ${command}`);
          try {
            child.kill();
          } catch {
            /* ignore */
          }
        }, timeoutMs);
      }

      const stripAnsi = (line) => line.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, '');
      const makeLineHandler = () => {
        let pending = '';
        const decoder = new StringDecoder('utf8');
        const consume = (text, flush = false) => {
          const parts = text.split(/[\r\n]+/);
          pending += parts.shift() || '';
          if (parts.length) {
            if (pending.trim() && onLine) onLine(stripAnsi(pending));
            pending = parts.pop() || '';
            for (const line of parts) if (line.trim() && onLine) onLine(stripAnsi(line));
          }
          if (flush && pending.trim() && onLine) onLine(stripAnsi(pending));
          if (flush) pending = '';
        };
        return {
          data(buffer) { lastOutputAt = Date.now(); consume(decoder.write(buffer)); },
          flush() { consume(decoder.end(), true); },
        };
      };
      const stdout = makeLineHandler();
      const stderr = makeLineHandler();
      child.stdout.on('data', stdout.data);
      child.stderr.on('data', stderr.data);
      if (watchDirectory && heartbeatMs > 0) {
        try {
          watcher = fs.watch(watchDirectory, { recursive: true, persistent: false }, () => {
            lastFileActivityAt = Date.now();
          });
        } catch {
          try {
            watcher = fs.watch(watchDirectory, { persistent: false }, () => {
              lastFileActivityAt = Date.now();
            });
          } catch { watcher = null; }
        }
        if (watcher) watcher.on('error', () => { });
      }
      if (heartbeatMs > 0 && typeof onHeartbeat === 'function') {
        heartbeat = setInterval(() => {
          if (settled) return;
          const now = Date.now();
          const silentForMs = Math.max(0, now - Math.max(lastOutputAt, lastFileActivityAt));
          const processActive = child.exitCode === null && child.signalCode === null;
          const payload = {
            silentForMs,
            processActive,
            fileActivityAgoMs: Math.max(0, now - lastFileActivityAt),
            quiet: quietWarningMs > 0 && silentForMs >= quietWarningMs,
          };
          if (payload.quiet && now - lastWarningAt >= quietWarningMs) lastWarningAt = now;
          try { onHeartbeat(payload); }
          catch (error) { this.log(`heartbeat callback failed: ${error.message}`); }
        }, heartbeatMs);
        heartbeat.unref?.();
      }
      child.on('error', (error) => {
        this.log(`process error (${command}): ${error.message}`);
        stdout.flush();
        stderr.flush();
        finish(-1);
      });
      child.on('close', (code) => {
        stdout.flush();
        stderr.flush();
        if ((timedOut || code !== 0) && !allowFailure) {
          this.log(`process exited ${code}: ${command}`);
        }
        finish(code);
      });
    });
  }

  // --------------------------------------------------------------- download

  /**
   * Streams a download to disk, reporting byte progress.
   * Supports HTTP/HTTPS, follows redirects, performs automatic retries on network failures,
   * and verifies downloaded content size.
   */
  async downloadFile(url, destination, onProgress, maxRetries = 3) {
    const tempFile = `${destination}.tmp`;
    let attempt = 0;
    while (attempt < maxRetries) {
      attempt += 1;
      this.checkCancelled();
      try {
        await this._performDownload(url, tempFile, onProgress);
        try {
          if (fs.existsSync(destination)) fs.unlinkSync(destination);
        } catch { }
        fs.renameSync(tempFile, destination);
        return;
      } catch (err) {
        try { if (fs.existsSync(tempFile)) fs.unlinkSync(tempFile); } catch { }
        if (this.cancelled || err.cancelled) throw err;
        this.log(`download attempt ${attempt} failed: ${err.message}`);
        if (attempt >= maxRetries) {
          throw new Error(`Download failed after ${maxRetries} attempts: ${err.message}`);
        }
        this.note(`Download interrupted (${err.message}). Retrying (${attempt}/${maxRetries})…`, 'warn');
        await new Promise((r) => setTimeout(r, attempt * 1500));
      }
    }
  }

  _performDownload(url, destination, onProgress) {
    return new Promise((resolve, reject) => {
      const get = (target, redirectsLeft) => {
        if (this.cancelled) {
          reject(Object.assign(new Error('Installation cancelled'), { cancelled: true }));
          return;
        }
        let parsedUrl;
        try {
          parsedUrl = new URL(target);
        } catch (e) {
          reject(new Error(`Invalid download URL: ${target}`));
          return;
        }
        const transport = parsedUrl.protocol === 'http:' ? http : https;
        const request = transport.get(
          target,
          { headers: { 'User-Agent': 'ClipifyAI-Setup/2.0' } },
          (response) => {
            if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
              response.resume();
              if (redirectsLeft <= 0) {
                reject(new Error('too many redirects'));
                return;
              }
              get(new URL(response.headers.location, target).toString(), redirectsLeft - 1);
              return;
            }
            if (response.statusCode !== 200) {
              response.resume();
              reject(new Error(`download failed (HTTP ${response.statusCode})`));
              return;
            }
            const total = Number(response.headers['content-length'] || 0);
            let done = 0;
            fs.mkdirSync(path.dirname(destination), { recursive: true });
            const out = fs.createWriteStream(destination);
            response.on('data', (chunk) => {
              done += chunk.length;
              if (onProgress) onProgress(done, total);
            });
            response.pipe(out);
            out.on('finish', () => {
              out.close(() => {
                if (total > 0 && done < total) {
                  reject(new Error(`Download truncated: expected ${total} bytes, received ${done}`));
                } else {
                  resolve(total || done);
                }
              });
            });
            out.on('error', reject);
          }
        );
        request.on('error', reject);
        request.setTimeout(90000, () => request.destroy(new Error('download timed out')));
      };
      get(url, 5);
    });
  }

  // ------------------------------------------------------------ step: files

  /**
   * Copies the bundled application payload into the install directory.
   * Streams per-file progress so the dashboard stays responsive. Existing
   * files are compared by SHA-256, not size alone, so upgrades replace stale
   * same-sized binaries and assets.
   */
  async copyPayload() {
    const id = 'files';
    this.beginPhase(id);
    this.activeTask = 'Copying Clipify AI';
    this.activeItem = '';

    const target = this.options.installDir;
    // Creating the folder can fail outright on a locked or non-existent
    // volume (EPERM creating the drive root). Surface that as a normal,
    // reportable failure instead of an unhandled throw.
    try {
      await fs.promises.mkdir(target, { recursive: true });
    } catch (error) {
      this.finishPhase(id, 'error', `Cannot create ${target}: ${error.message}`);
      throw new Error(
        `Clipify AI could not create the installation folder ${target}. ` +
        `Choose a different location. (${error.code || error.message})`
      );
    }
    if (!fs.existsSync(target)) {
      this.finishPhase(id, 'error', `Cannot create ${target}`);
      throw new Error(`Clipify AI could not create the installation folder ${target}.`);
    }

    const files = [];
    const walk = (dir, rel = '') => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        const relative = rel ? path.join(rel, entry.name) : entry.name;
        if (entry.name === 'runtime' || entry.name === '__pycache__' || entry.name === '.git') continue;
        let isDir = entry.isDirectory();
        if (!isDir && entry.isSymbolicLink()) {
          try { isDir = fs.statSync(full).isDirectory(); } catch { isDir = false; }
        }
        if (isDir) walk(full, relative);
        else files.push({ full, relative });
      }
    };
    if (!fs.existsSync(this.payloadRoot)) {
      this.finishPhase(id, 'error', 'Application payload missing from the installer.');
      throw new Error('Application payload missing from the installer.');
    }
    walk(this.payloadRoot);

    this.bytesTotal = files.reduce((sum, file) => {
      try {
        return sum + fs.statSync(file.full).size;
      } catch {
        return sum;
      }
    }, 0);
    this.bytesDone = 0;

    for (const file of files) {
      this.checkCancelled();
      const destination = path.join(target, file.relative);
      await fs.promises.mkdir(path.dirname(destination), { recursive: true });
      let size = 0;
      try {
        size = (await fs.promises.stat(file.full)).size;
      } catch {
        /* ignore */
      }
      let needsCopy = true;
      try {
        const destinationSize = (await fs.promises.stat(destination)).size;
        needsCopy = destinationSize !== size;
        if (!needsCopy) {
          needsCopy = (await sha256File(file.full)) !== (await sha256File(destination));
        }
      } catch {
        needsCopy = true;
      }
      if (!needsCopy) {
        this.bytesDone += size;
      } else {
        await fs.promises.copyFile(file.full, destination);
        this.bytesDone += size;
      }
      this.activeItem = file.relative;
      // One line per file: this is the step that most obviously "does nothing"
      // on screen otherwise, and 50-odd lines of real filenames is the clearest
      // possible evidence that the copy is moving.
      this.note(`${needsCopy ? 'Copied' : 'Already have'} ${file.relative}`, 'file');
      const percent = this.bytesTotal ? (this.bytesDone / this.bytesTotal) * 100 : 100;
      this.updatePhase(id, percent, file.relative);
      this.emitProgress();
    }

    this.activeItem = '';
    this.finishPhase(id, 'done', `${files.length} files`);
    this.log(`payload copied to ${target}`);
  }

  // ---------------------------------------------------------- step: python

  async ensurePython() {
    const id = 'python';
    this.beginPhase(id);
    this.activeTask = 'Preparing the Python engine';

    const target = this.pythonDir();
    const exe = path.join(target, 'python.exe');
    if (await this.pythonEngineUsable(exe)) {
      this.note('Python engine already installed \u2014 skipping', 'ok');
      this.updatePhase(id, 100, 'Python engine already present');
      this.finishPhase(id, 'done', 'already installed');
      return exe;
    }
    if (fs.existsSync(exe)) {
      this.note('The existing Python engine is incomplete; preparing a verified repair copy', 'info');
    }

    fs.mkdirSync(path.dirname(target), { recursive: true });
    const archive = uniqueSibling(os.tmpdir(), `clipify-python-${PYTHON_VERSION}`) + '.zip';
    const stagingRoot = uniqueSibling(path.dirname(target), '.clipify-python-stage');
    const unpackDir = path.join(stagingRoot, 'unpacked');
    const stagedPythonDir = path.join(stagingRoot, 'python');
    this.note(`Downloading Python ${PYTHON_VERSION} (embedded distribution)`, 'download');
    try {
      await this.downloadFile(PYTHON_URL, archive, (done, total) => {
        this.updatePhase(id, (done / Math.max(total, 1)) * 70, 'Downloading Python engine');
        this.updateByteProgress(done, total);
        this.throttledNote('py-dl', `Python engine ${Math.round((done / Math.max(total, 1)) * 100)}%`, 'download', 900);
        this.emitProgress();
      });

      this.resetByteProgress();
      await fs.promises.mkdir(unpackDir, { recursive: true });
      this.note('Unpacking the Python engine into an isolated staging folder', 'info');
      this.updatePhase(id, 80, 'Unpacking Python engine');
      this.emitProgress();
      const quotePs = (value) => String(value).replace(/'/g, "''");
      const expandCommand = `$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '${quotePs(archive)}' -DestinationPath '${quotePs(unpackDir)}' -Force`;
      const unpackResult = await this.runProcess(
        'powershell.exe',
        ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', expandCommand],
        { timeoutMs: 15 * 60 * 1000 }
      );
      const packageRoot = path.join(unpackDir, 'tools');
      if (unpackResult.code !== 0 || !fs.existsSync(path.join(packageRoot, 'python.exe'))) {
        this.finishPhase(id, 'error', 'Python engine archive could not be unpacked');
        throw new Error(`Python engine archive extraction failed (exit ${unpackResult.code}).`);
      }

      // Normalize only the newly extracted package. Never rename or flatten an
      // installed python311\\tools directory while another process may have it
      // open. The final location stays untouched until this copy passes a real
      // interpreter and standard-library probe.
      await renameWithRetry(packageRoot, stagedPythonDir, { attempts: 5, delayMs: 180 });
      for (const name of await fs.promises.readdir(stagedPythonDir)) {
        if (name.toLowerCase().endsWith('._pth')) {
          await fs.promises.unlink(path.join(stagedPythonDir, name));
        }
      }
      const stagedExe = path.join(stagedPythonDir, 'python.exe');
      if (!(await this.pythonEngineUsable(stagedExe))) {
        this.finishPhase(id, 'error', 'Staged Python engine failed verification');
        throw new Error(`The downloaded Python engine failed its startup and standard-library checks: ${this.lastPythonProbeError || 'verification failed without a diagnostic'}.`);
      }

      this.updatePhase(id, 92, 'Promoting verified Python engine');
      this.emitProgress();
      let backupDir = null;
      if (fs.existsSync(target)) {
        backupDir = uniqueSibling(path.dirname(target), '.clipify-python-backup');
        await renameWithRetry(target, backupDir, { attempts: 5, delayMs: 180 });
      }
      try {
        await renameWithRetry(stagedPythonDir, target, { attempts: 5, delayMs: 180 });
        if (!(await this.pythonEngineUsable(exe))) {
          throw new Error(`The Python engine could not be verified in ${target}. Retry setup to repair it.`);
        }
      } catch (promotionError) {
        if (fs.existsSync(target)) {
          try { await fs.promises.rm(target, { recursive: true, force: true }); }
          catch (cleanupError) { this.log(`could not remove unverified Python folder ${target}: ${cleanupError.message}`); }
        }
        if (backupDir && fs.existsSync(backupDir)) {
          try { await renameWithRetry(backupDir, target, { attempts: 5, delayMs: 180 }); }
          catch (restoreError) {
            this.log(`Python rollback failed; preserved previous copy at ${backupDir}: ${restoreError.message}`);
            throw new Error(`The new Python engine failed verification and the previous copy remains at ${backupDir}. ${promotionError.message}`);
          }
        }
        throw promotionError;
      }
      if (backupDir) {
        try { await fs.promises.rm(backupDir, { recursive: true, force: true }); }
        catch (cleanupError) { this.log(`verified Python is active; old Python backup could not be removed: ${cleanupError.message}`); }
      }
      this.note('Python engine verified and ready', 'ok');
      this.finishPhase(id, 'done', 'verified');
    } catch (error) {
      if (this.phaseState[id] && this.phaseState[id].status !== 'error') {
        this.finishPhase(id, 'error', `Python engine setup failed: ${error.code || error.message}`);
      }
      throw error;
    } finally {
      for (const candidate of [archive, stagingRoot]) {
        try {
          if (candidate === archive) await fs.promises.rm(candidate, { force: true });
          else await fs.promises.rm(candidate, { recursive: true, force: true });
        } catch (error) {
          this.log(`could not clean this attempt's Python staging path ${candidate}: ${error.message}`);
        }
      }
    }
  }

  async pythonEngineUsable(pythonExe) {
    const pythonDir = path.dirname(pythonExe);
    if (!fs.existsSync(pythonExe)) {
      this.lastPythonProbeError = 'python.exe is missing';
      return false;
    }
    // The official python NuGet package used here stores its standard library
    // in Lib, while the embeddable zip distribution stores it in
    // python311.zip. Accept either layout, but require a real standard-library
    // anchor before trying to run the interpreter.
    const hasStandardLibrary = fs.existsSync(path.join(pythonDir, 'python311.zip'))
      || fs.existsSync(path.join(pythonDir, 'Lib', 'os.py'));
    if (!hasStandardLibrary) {
      this.lastPythonProbeError = 'the Python standard library is missing (expected python311.zip or Lib\\os.py)';
      return false;
    }
    const output = [];
    const result = await this.runProcess(
      pythonExe,
      ['-I', '-c', 'import sys, venv, ensurepip; print("CLIPIFY_PYTHON_OK:" + ".".join(map(str, sys.version_info[:3])))'],
      { timeoutMs: 30000, onLine: (line) => output.push(line.trim()) }
    );
    if (result.code !== 0) {
      this.lastPythonProbeError = `python.exe exited ${result.code}${output.length ? `: ${output.join(' | ').slice(0, 500)}` : ' without diagnostic output'}`;
      this.log(`Python engine validation failed: ${this.lastPythonProbeError}`);
      return false;
    }
    if (!output.some((line) => line === 'CLIPIFY_PYTHON_OK:3.11.9')) {
      this.lastPythonProbeError = output.length
        ? `unexpected Python probe output: ${output.join(' | ').slice(0, 500)}`
        : 'python.exe returned no version marker';
      this.log(`Python engine validation failed: ${this.lastPythonProbeError}`);
      return false;
    }
    this.lastPythonProbeError = '';
    return true;
  }

  // --------------------------------------------------------- step: runtime

  /**
   * Builds the Tier-B ML runtime. This is the long step (multi-gigabyte pip
   * install) and the one most likely to be interrupted, so progress is parsed
   * out of pip's own output and the phase is resumable: if site-packages already
   * contains clipsai the whole step is skipped.
   */
  async ensureRuntime() {
    const id = 'runtime';
    this.beginPhase(id);
    this.activeTask = 'Installing the AI runtime';

    const status = runtimeStatus();
    // "Already installed" has to mean "already installed in the folder the user
    // chose". runtimeStatus() reports the old %LOCALAPPDATA% location, so
    // trusting it here meant a new folder silently reused a runtime from
    // somewhere else and the AI libraries never landed where the user asked.
    const finalRuntimeDir = this.runtimeDir();
    const runtimeHere = runtimeCompleteIn(finalRuntimeDir);
    const finalVenvPython = path.join(finalRuntimeDir, 'Scripts', 'python.exe');
    if (runtimeHere && fs.existsSync(finalVenvPython)) {
      const narrationReady = narrationModelCompleteIn(finalRuntimeDir)
        && await this.narrationModelReady(finalVenvPython, finalRuntimeDir);
      if (narrationReady) {
        try {
          await this.verifyRuntime(finalVenvPython, finalRuntimeDir);
          this.note('AI runtime already installed in this folder \u2014 skipping', 'ok');
          this.updatePhase(id, 100, 'AI runtime already installed');
          this.finishPhase(id, 'done', 'already installed');
          return;
        } catch (error) {
          this.note(`Existing AI runtime failed verification; preparing a staged repair (${error.message})`, 'warn');
        }
      }
      this.note('The existing AI runtime is incomplete; building a verified repair copy alongside it', 'info');
    }
    if (status.complete) {
      this.note(
        `An AI runtime exists in ${status.runtime}; installing into your chosen folder instead`,
        'info'
      );
    }

    const basePython = path.join(this.pythonDir(), 'python.exe');
    if (!fs.existsSync(basePython)) {
      this.finishPhase(id, 'error', 'Python engine missing');
      throw new Error('Python engine missing');
    }

    const venvDir = uniqueSibling(path.dirname(finalRuntimeDir), '.clipify-runtime-stage');
    this.runtimeStageDir = venvDir;
    const venvPython = path.join(venvDir, 'Scripts', 'python.exe');
    fs.mkdirSync(path.dirname(venvDir), { recursive: true });

    if (!fs.existsSync(venvPython)) {
      this.note('Creating an isolated Python environment for the AI libraries', 'info');
      this.updatePhase(id, 2, 'Creating the runtime');
      this.emitProgress();
      const created = await this.runProcess(basePython, ['-m', 'venv', venvDir], {
        timeoutMs: 10 * 60 * 1000,
      });
      if (created.code !== 0 || !fs.existsSync(venvPython)) {
        this.finishPhase(id, 'error', 'Could not create the runtime');
        throw new Error(`venv creation failed (exit ${created.code})`);
      }
    }

    const requirements = path.join(this.options.installDir, 'requirements-runtime.txt');
    if (!fs.existsSync(requirements)) {
      this.finishPhase(id, 'error', 'requirements-runtime.txt missing');
      throw new Error('requirements-runtime.txt missing from the payload');
    }

    this.note('Updating pip, setuptools and wheel', 'info');
    this.updatePhase(id, 8, 'Updating pip');
    this.emitProgress();
    const pipUpgrade = await this.runProcess(
      venvPython,
      ['-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip', 'setuptools', 'wheel'],
      { timeoutMs: 15 * 60 * 1000 }
    );
    if (pipUpgrade.code !== 0) {
      this.finishPhase(id, 'error', 'Python packaging tools could not be prepared');
      throw new Error(`pip upgrade failed (exit ${pipUpgrade.code})`);
    }

    this.note('Installing the AI libraries from requirements-runtime.txt (largest step)', 'download');
    this.updatePhase(id, 12, 'Downloading AI libraries (largest step)');
    this.emitProgress();
    const pipResult = await this.runProcess(
      venvPython,
      ['-m', 'pip', 'install', '--disable-pip-version-check', '--progress-bar', 'on', '-r', requirements],
      {
        timeoutMs: 4 * 60 * 60 * 1000,
        heartbeatMs: 15000,
        quietWarningMs: 90000,
        watchDirectory: path.join(venvDir, 'Lib', 'site-packages'),
        onHeartbeat: ({ silentForMs, fileActivityAgoMs, processActive, quiet }) => {
          const idleSeconds = Math.floor(silentForMs / 1000);
          const writingPackages = fileActivityAgoMs <= 30000;
          this.activeItem = writingPackages
            ? `Installing AI libraries; package files are changing (${idleSeconds}s since console output)`
            : `Installing AI libraries; child process ${processActive ? 'is still running' : 'has stopped'}, no recent package output (${idleSeconds}s)`;
          if (quiet) {
            this.throttledNote(
              'runtime-quiet',
              `No pip output or staged package-file changes for ${Math.floor(idleSeconds / 60)}m ${idleSeconds % 60}s; the installer is checking the live child process and waiting safely.`,
              'warn',
              90000
            );
          }
          this.emitProgress({ processRunning: processActive, quietForMs: silentForMs });
        },
        onLine: (line) => {
          const trimmed = line.trim();
          // Matches: "45.2/250.0 MB", "45.2 MB / 250.0 MB", "12.3 kB / 500 kB", "1.2/3.4 GB", etc.
          const match = trimmed.match(/([\d.]+)\s*(MB|GB|kB|KB|B)?\s*\/\s*([\d.]+)\s*(MB|GB|kB|KB|B)/i);
          if (match) {
            const totalUnit = (match[4] || 'MB').toLowerCase();
            const unit = { b: 1, kb: 1024, mb: 1024 ** 2, gb: 1024 ** 3 }[totalUnit] || (1024 ** 2);
            const doneUnit = match[2] ? ({ b: 1, kb: 1024, mb: 1024 ** 2, gb: 1024 ** 3 }[match[2].toLowerCase()] || unit) : unit;
            const done = parseFloat(match[1]) * doneUnit;
            const total = parseFloat(match[3]) * unit;
            this.updateByteProgress(done, total);

            // Parse speed if pip outputs e.g. "38.4 MB/s"
            const spdMatch = trimmed.match(/([\d.]+)\s*(kB|KB|MB|GB)\/s/i);
            if (spdMatch) {
              const sUnit = { kb: 1024, mb: 1024 ** 2, gb: 1024 ** 3 }[spdMatch[2].toLowerCase()] || (1024 ** 2);
              this.speedBytes = Math.round(parseFloat(spdMatch[1]) * sUnit);
            }
            // Parse ETA if pip outputs e.g. "eta 0:00:15"
            const etaMatch = trimmed.match(/eta\s+([\d:]+)/i);
            if (etaMatch) {
              const parts = etaMatch[1].split(':').map(Number);
              let seconds = 0;
              if (parts.length === 3) seconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
              else if (parts.length === 2) seconds = parts[0] * 60 + parts[1];
              else seconds = parts[0] || 0;
              this.pipEtaMs = seconds * 1000;
            }

            this.activeItem = `pip ${trimmed.slice(0, 60)}`;
            this.throttledNote(
              'pip-dl',
              `downloading ${match[1]} / ${match[3]} ${match[4] || ''}`,
              'download',
              1200
            );
            this.emitProgress();
          } else if (/^Downloading\s+([^\s]+)\s*\(([\d.]+)\s*(MB|GB|kB|KB)\)/i.test(trimmed)) {
            const dlMatch = trimmed.match(/^Downloading\s+([^\s]+)\s*\(([\d.]+)\s*(MB|GB|kB|KB)\)/i);
            const unit = { kb: 1024, mb: 1024 ** 2, gb: 1024 ** 3 }[dlMatch[3].toLowerCase()] || (1024 ** 2);
            const size = parseFloat(dlMatch[2]) * unit;
            this.bytesTotal = size;
            this.bytesDone = 0;
            this.activeItem = `Downloading ${dlMatch[1]}`;
            this.note(`Downloading ${dlMatch[1]} (${dlMatch[2]} ${dlMatch[3]})`, 'pkg');
            this.emitProgress();
          } else if (/^(Collecting|Installing|Building|Using cached|Downloading)/.test(trimmed)) {
            const clean = trimmed.replace(/\s+/g, ' ');
            this.note(clean.slice(0, 150), 'pkg');
            this.activeItem = clean.slice(0, 70);
            this.emitProgress();
          }
        },
      }
    );
    if (pipResult.code !== 0) {
      this.finishPhase(id, 'error', 'AI runtime install failed - see setup.log');
      throw new Error(`pip install failed (exit ${pipResult.code})`);
    }

    // ClipsAI depends on the source-only python-magic distribution, while
    // python-magic-bin supplies the Windows libmagic DLL and a Windows-aware
    // loader under the same `magic` package. Installing both lets the source
    // wheel overwrite that loader, so restore the binary distribution last.
    if (process.platform === 'win32') {
      this.note('Restoring the Windows libmagic loader', 'info');
      const magicResult = await this.runProcess(
        venvPython,
        [
          '-m', 'pip', 'install', '--disable-pip-version-check',
          '--force-reinstall', '--no-deps', 'python-magic-bin>=0.4.14',
        ],
        { timeoutMs: 20 * 60 * 1000 }
      );
      if (magicResult.code !== 0) {
        this.finishPhase(id, 'error', 'Windows libmagic runtime setup failed');
        throw new Error(`python-magic-bin install failed (exit ${magicResult.code})`);
      }
    }

    // facenet-pytorch ships a stale numpy<2 pin, so it is installed without deps.
    this.note('Installing face detection (facenet-pytorch, no dependencies)', 'info');
    this.updatePhase(id, 97, 'Installing face detection');
    this.emitProgress();
    const faceResult = await this.runProcess(
      venvPython,
      ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', 'facenet-pytorch==2.6.0'],
      { timeoutMs: 20 * 60 * 1000 }
    );
    if (faceResult.code !== 0) {
      this.finishPhase(id, 'error', 'Face detection runtime install failed');
      throw new Error(`facenet-pytorch install failed (exit ${faceResult.code})`);
    }

    await this.verifyRuntime(venvPython, venvDir);

    // Only now is the runtime genuinely usable, so record that. runtimeCompleteIn
    // looks for this marker, which means a runtime left half-built by an
    // interrupted install is correctly seen as absent and rebuilt, instead of
    // being reported complete forever because clipsai happened to be installed
    // early in pip's alphabetical order.
    const marker = path.join(venvDir, RUNTIME_COMPLETE_MARKER);
    fs.writeFileSync(
      marker,
      `Installed ${new Date().toISOString()} into ${this.options.installDir}\n`,
      'utf8'
    );
    if (!runtimeCompleteIn(venvDir)) {
      this.finishPhase(id, 'error', 'AI runtime completion marker could not be verified');
      throw new Error('AI runtime completion marker could not be verified');
    }
    this.log(`runtime completion marker written to ${marker}`);

    let backupDir = null;
    let promoted = false;
    try {
      if (fs.existsSync(finalRuntimeDir)) {
        backupDir = uniqueSibling(path.dirname(finalRuntimeDir), '.clipify-runtime-backup');
        await renameWithRetry(finalRuntimeDir, backupDir, { attempts: 5, delayMs: 250 });
      }
      await renameWithRetry(venvDir, finalRuntimeDir, { attempts: 5, delayMs: 250 });
      promoted = true;
      await this.verifyRuntime(path.join(finalRuntimeDir, 'Scripts', 'python.exe'), finalRuntimeDir);
    } catch (promotionError) {
      if (promoted && fs.existsSync(finalRuntimeDir)) {
        const failedDir = uniqueSibling(path.dirname(finalRuntimeDir), '.clipify-runtime-failed');
        try { await renameWithRetry(finalRuntimeDir, failedDir, { attempts: 3, delayMs: 250 }); }
        catch (moveError) { this.log(`could not move failed staged runtime aside: ${moveError.message}`); }
        if (fs.existsSync(failedDir)) {
          try { await fs.promises.rm(failedDir, { recursive: true, force: true }); }
          catch (cleanupError) { this.log(`could not remove failed staged runtime ${failedDir}: ${cleanupError.message}`); }
        }
      }
      if (backupDir && fs.existsSync(backupDir)) {
        try { await renameWithRetry(backupDir, finalRuntimeDir, { attempts: 5, delayMs: 250 }); }
        catch (restoreError) {
          this.log(`runtime rollback failed; preserved previous runtime at ${backupDir}: ${restoreError.message}`);
          throw new Error(`The new AI runtime failed verification and the previous copy remains at ${backupDir}. ${promotionError.message}`);
        }
      }
      if (this.phaseState[id] && this.phaseState[id].status !== 'error') {
        this.finishPhase(id, 'error', `AI runtime promotion failed: ${promotionError.message}`);
      }
      throw promotionError;
    }
    this.runtimeStageDir = null;
    if (backupDir) {
      try { await fs.promises.rm(backupDir, { recursive: true, force: true }); }
      catch (cleanupError) { this.log(`verified runtime is active; old runtime backup could not be removed: ${cleanupError.message}`); }
    }

    this.bytesDone = 0;
    this.bytesTotal = 0;
    this.activeItem = '';
    this.note('AI runtime is ready', 'ok');
    this.finishPhase(id, 'done');
  }

  async narrationModelReady(venvPython, runtimeDir = this.runtimeDir()) {
    const probe = [
      'import os, sysconfig, spacy, en_core_web_sm',
      "site = os.path.normcase(os.path.realpath(sysconfig.get_paths()['purelib']))",
      'model = os.path.normcase(os.path.realpath(en_core_web_sm.__file__))',
      'if os.path.commonpath([site, model]) != site: raise RuntimeError("model is outside the selected runtime")',
      "spacy.load('en_core_web_sm', enable=['tok2vec', 'tagger'])",
    ].join('; ');
    const result = await this.runProcess(
      venvPython,
      ['-B', '-c', probe],
      { timeoutMs: 2 * 60 * 1000, env: { CLIPPEDAI_RUNTIME: path.resolve(runtimeDir) } }
    );
    return result.code === 0;
  }

  async installNarrationModel(venvPython) {
    const requirements = path.join(this.options.installDir, 'requirements-runtime.txt');
    if (!fs.existsSync(requirements)) {
      throw new Error('requirements-runtime.txt missing; cannot repair the Kokoro English model');
    }
    const modelRequirement = fs.readFileSync(requirements, 'utf8')
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => /^en-core-web-sm\s*@\s*https:\/\//i.test(line));
    if (!modelRequirement) {
      throw new Error('Pinned en-core-web-sm wheel missing from requirements-runtime.txt');
    }

    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'clipify-narration-model-'));
    const tempRequirements = path.join(tempDir, 'requirements.txt');
    fs.writeFileSync(tempRequirements, `${modelRequirement}\n`, 'utf8');
    try {
      this.updatePhase('runtime', 18, 'Installing the missing Kokoro language model');
      this.emitProgress();
      const result = await this.runProcess(
        venvPython,
        ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--force-reinstall', '-r', tempRequirements],
        {
          timeoutMs: 15 * 60 * 1000,
          onLine: (line) => this.note(`Kokoro model: ${line.trim().slice(0, 150)}`, 'pkg'),
        }
      );
      if (result.code !== 0) {
        throw new Error(`Kokoro English model install failed (exit ${result.code})`);
      }
    } finally {
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
  }

  /**
   * Verify imports in the venv the installed application actually uses.
   * ClipsAI's public Transcriber import is included because it loads the
   * python-magic binding required by the video pipeline. TorchCodec is checked
   * as an installed distribution only: the Windows app explicitly selects
   * WhisperX's Silero VAD path and decodes media through its bundled FFmpeg.
   */
  async verifyRuntime(venvPython, runtimeDir = this.runtimeDir()) {
    const id = 'runtime';
    const expectedRuntime = path.resolve(runtimeDir);
    const probe = [
      'import importlib, importlib.metadata, json, os, sys, sysconfig',
      'failures = []',
      'expected = os.path.normcase(os.path.realpath(sys.argv[1]))',
      'actual = os.path.normcase(os.path.realpath(sys.prefix))',
      "if actual != expected: failures.append('wrong Python prefix: ' + sys.prefix)",
      "expected_site = os.path.normcase(os.path.realpath(os.path.join(expected, 'Lib', 'site-packages'))) ",
      "actual_site = os.path.normcase(os.path.realpath(sysconfig.get_paths().get('purelib', ''))) ",
      "if actual_site != expected_site: failures.append('wrong site-packages: ' + actual_site)",
      "modules = ['torch', 'torchvision', 'torchaudio', 'numpy', 'cv2', 'whisperx', 'mediapipe', 'facenet_pytorch', 'kokoro', 'spacy', 'en_core_web_sm', 'soundfile', 'requests', 'yaml', 'tqdm', 'dotenv', 'yt_dlp']",
      'for name in modules:',
      '    try:',
      '        importlib.import_module(name)',
      '    except Exception as exc:',
      "        failures.append(name + ': ' + type(exc).__name__ + ': ' + str(exc))",
      'try:',
      '    import en_core_web_sm',
      "    model_path = os.path.normcase(os.path.realpath(en_core_web_sm.__file__))",
      "    if os.path.commonpath([expected_site, model_path]) != expected_site: failures.append('Kokoro English model is outside the selected runtime')",
      'except Exception as exc:',
      "    failures.append('Kokoro English model path: ' + type(exc).__name__ + ': ' + str(exc))",
      'try:',
      '    from clipsai import Transcriber',
      '    from clipsai.clip.clip import Clip',
      '    from facenet_pytorch import MTCNN',
      'except Exception as exc:',
      "    failures.append('application entry points: ' + type(exc).__name__ + ': ' + str(exc))",
      'try:',
      "    codec_version = importlib.metadata.version('torchcodec')",
      'except importlib.metadata.PackageNotFoundError:',
      "    failures.append('torchcodec distribution is missing')",
      'else:',
      "    print('TorchCodec distribution present: ' + codec_version + ' (Silero VAD is the configured path)')",
      'try:',
      "    import spacy",
      "    spacy.load('en_core_web_sm', enable=['tok2vec', 'tagger'])",
      'except Exception as exc:',
      "    failures.append('Kokoro English model: ' + type(exc).__name__ + ': ' + str(exc))",
      "print(json.dumps({'prefix': sys.prefix, 'site_packages': actual_site, 'failures': failures}))",
      'sys.exit(1 if failures else 0)',
    ].join('\n');
    const output = [];
    this.note(`Verifying AI imports with ${venvPython}`, 'info');
    const result = await this.runProcess(
      venvPython,
      ['-B', '-c', probe, expectedRuntime],
      {
        timeoutMs: 15 * 60 * 1000,
        env: {
          CLIPPEDAI_DATA_DIR: this.options.installDir,
          CLIPPEDAI_RUNTIME: expectedRuntime,
        },
        onLine: (line) => {
          output.push(line);
          this.note(`Runtime check: ${line.trim().slice(0, 160)}`, 'info');
        },
      }
    );
    if (result.code !== 0) {
      this.finishPhase(id, 'error', 'AI runtime import verification failed');
      const detail = output.slice(-6).join(' | ').slice(0, 900);
      throw new Error(
        `AI runtime import verification failed (exit ${result.code})${detail ? `: ${detail}` : ''}`
      );
    }
    this.note(`AI runtime imports verified from ${expectedRuntime}`, 'ok');
  }

  // --------------------------------------------------------- step: ollama

  async ensureOllama() {
    const id = 'ollama';
    this.beginPhase(id);
    this.activeTask = 'Setting up the local AI engine';

    let exe = findOllama();
    if (exe) {
      this.note('Ollama is already installed', 'ok');
      this.updatePhase(id, 60, 'Ollama detected');
      this.emitProgress();
    } else {
      const installer = path.join(os.tmpdir(), 'clipify-ollama-setup.exe');
      this.note('Downloading the Ollama installer', 'download');
      this.updatePhase(id, 5, 'Downloading Ollama');
      this.emitProgress();
      await this.downloadFile(OLLAMA_URL, installer, (done, total) => {
        this.updatePhase(id, 5 + (done / Math.max(total, 1)) * 45, 'Downloading Ollama');
        this.updateByteProgress(done, total);
        this.throttledNote('ollama-dl', `Ollama installer ${Math.round((done / Math.max(total, 1)) * 100)}%`, 'download', 900);
        this.emitProgress();
      });
      this.resetByteProgress();
      this.note('Running the Ollama installer', 'info');
      this.updatePhase(id, 55, 'Installing Ollama');
      this.emitProgress();
      const result = await this.runProcess(
        installer,
        ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
        { timeoutMs: 20 * 60 * 1000 }
      );
      try {
        fs.unlinkSync(installer);
      } catch {
        /* ignore */
      }
      // OllamaSetup.exe is an Inno Setup installer that returns exit 0
      // immediately while the actual installation continues asynchronously in a
      // background process. Calling findOllama() right after the process exits
      // races against that background work and reliably finds nothing, producing
      // the misleading "Ollama install failed (exit 0)" message.
      //
      // Fix: poll for the executable with a generous timeout instead of
      // checking once and failing. Two seconds between polls is enough to avoid
      // hammering the filesystem; 120 s is more than enough for Ollama to unpack.
      {
        const POLL_INTERVAL_MS = 2000;
        const POLL_TIMEOUT_MS = 120 * 1000;
        const pollStart = Date.now();
        this.note('Waiting for Ollama installation to complete…', 'info');
        while (!exe) {
          this.checkCancelled();
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
          exe = findOllama();
          if (exe) break;
          const elapsed = Math.round((Date.now() - pollStart) / 1000);
          if (elapsed >= POLL_TIMEOUT_MS / 1000) break;
          this.throttledNote(
            'ollama-wait',
            `Waiting for Ollama to finish installing (${elapsed}s / ${POLL_TIMEOUT_MS / 1000}s max)…`,
            'info',
            4000
          );
          this.emitProgress();
        }
      }
      if (!exe) {
        this.finishPhase(id, 'done', 'Ollama installation deferred');
        this.note(
          'Ollama installation was skipped or timed out. You can install Ollama anytime from ollama.com or directly inside Clipify AI.',
          'warn'
        );
        this.emitProgress();
        return;
      }
    }

    this.note('Starting the Ollama service', 'info');
    this.updatePhase(id, 80, 'Starting Ollama');
    this.emitProgress();
    await this.startOllamaServer(exe);
    this.note('Ollama is answering on port 11434', 'ok');
    this.finishPhase(id, 'done');
  }

  async startOllamaServer(exe) {
    const reachable = async () => {
      return new Promise((resolve) => {
        // Ollama serves plain HTTP. Probing it with the https module threw
        // 'Protocol "http:" not supported. Expected "https:"' and aborted the
        // whole installation after the runtime had finished.
        const req = http.get('http://127.0.0.1:11434/api/tags', (res) => {
          res.resume();
          resolve(res.statusCode >= 200 && res.statusCode < 300);
        });
        req.on('error', () => resolve(false));
        req.setTimeout(2000, () => {
          req.destroy();
          resolve(false);
        });
      });
    };
    if (await reachable()) {
      // Keep the user's existing Ollama process and model store. Killing it to
      // redirect OLLAMA_MODELS could hide cached models and trigger a duplicate
      // multi-gigabyte pull. A new service uses the install-local store below.
      this.note('Using the running Ollama service and its existing model store', 'info');
      return;
    }
    fs.mkdirSync(this.modelsDir(), { recursive: true });
    const child = spawn(exe, ['serve'], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      env: Object.assign({}, process.env, this.appEnv()),
    });
    child.unref();
    for (let i = 0; i < 25; i += 1) {
      this.checkCancelled();
      await new Promise((resolve) => setTimeout(resolve, 1000));
      if (await reachable()) return;
    }
    this.log('ollama did not become reachable in time; model pulls may still work');
  }

  // --------------------------------------------------------- step: models

  /**
   * Pulls only the models the user selected. Installed models are skipped
   * entirely, and the per-model rows in the UI move independently so one slow
   * model does not hide the state of the others.
   */
  async installModels(selectedIds) {
    const id = 'models';
    this.beginPhase(id);
    this.activeTask = 'Downloading AI models';

    if (!selectedIds || selectedIds.length === 0) {
      this.note('No models selected \u2014 skipping the download step', 'info');
      this.updatePhase(id, 100, 'No models selected');
      this.finishPhase(id, 'done', 'skipped');
      this.emitProgress();
      return;
    }

    const exe = findOllama();
    if (!exe) {
      this.note('Local AI engine (Ollama) not detected \u2014 model downloads deferred to in-app setup', 'info');
      this.updatePhase(id, 100, 'Model downloads deferred');
      this.finishPhase(id, 'done', 'deferred to in-app');
      this.emitProgress();
      return;
    }
    await this.startOllamaServer(exe);

    const listOut = await new Promise((resolve) => {
      execFile(exe, ['list'], { windowsHide: true, timeout: 20000 }, (error, stdout) =>
        resolve(error ? '' : stdout));
    });
    const already = parseOllamaList(listOut);

    this.models = selectedIds.map((modelId) => ({
      id: modelId,
      status: already.has(modelId) ? 'installed' : 'queued',
      percent: already.has(modelId) ? 100 : 0,
    }));
    this.installedModels = this.models.filter((m) => m.status === 'installed').map((m) => m.id);
    this.emitProgress();

    const alreadyOnes = this.models.filter((m) => m.status === 'installed');
    if (alreadyOnes.length) {
      this.note(
        `Already installed, not downloading again: ${alreadyOnes.map((m) => m.id).join(', ')}`,
        'ok'
      );
    }

    const todo = this.models.filter((m) => m.status !== 'installed');
    if (todo.length === 0) {
      this.finishPhase(id, 'done', 'all selected models already present');
      this.emitProgress();
      return;
    }

    let finished = 0;
    for (const model of this.models) {
      if (model.status === 'installed') {
        finished += 1;
        continue;
      }
      this.checkCancelled();
      model.status = 'downloading';
      this.activeItem = model.id;
      // The catalogue knows the real size of this model, so the bar has a
      // stable denominator from the first tick instead of waiting for ollama.
      this.bytesDone = 0;
      this.bytesTotal = Math.round(MODEL_BYTES[model.id] || 0);
      this.speedBytes = 0;
      this.byteSample = null;
      const planned = this.bytesTotal
        ? ` (${(this.bytesTotal / 1e9).toFixed(2)} GB)`
        : '';
      this.note(`Pulling ${model.id}${planned} from the Ollama registry`, 'download');
      this.emitProgress();

      await new Promise((resolve) => {
        const child = spawn(exe, ['pull', model.id], { windowsHide: true, shell: false });
        this.currentChild = child;
        // ollama pull prints lines like
        //   pulling 8e297da2  1.2 GB / 4.9 GB  24%
        // The percentage alone left bytesDone/bytesTotal frozen at whatever the
        // previous phase happened to leave behind, so the transfer readout and
        // the ETA had nothing honest to show. Track the byte counts too.
        const handle = (buffer) => {
          let changed = false;
          for (const line of buffer.toString().split(/\r?\n/)) {
            // Narrate the pull at blob granularity. This is the single longest
            // wait in the whole install, so it gets the most explicit feed.
            const blobName = line.match(/pulling\s+([0-9a-f]{6,})/i);
            if (blobName) {
              this.note(`blob ${blobName[1].slice(0, 12)} \u2014 transferring weights`, 'blob');
            } else if (/verifying/i.test(line)) {
              this.note('verifying layer checksums', 'blob');
            } else if (/writing manifest/i.test(line)) {
              this.note('writing the model manifest', 'blob');
            }
            const pctMatch = line.match(/(\d{1,3})%/);
            if (pctMatch) {
              model.percent = Math.min(99, parseInt(pctMatch[1], 10));
              changed = true;
            }
            const byteMatch = line.match(
              /([\d.]+)\s*(B|KB|KiB|MB|MiB|GB|GiB|TB)\s*\/\s*([\d.]+)\s*(B|KB|KiB|MB|MiB|GB|GiB|TB)/
            );
            if (byteMatch) {
              const done = toBytes(byteMatch[1], byteMatch[2]);
              const total = toBytes(byteMatch[3], byteMatch[4]);
              if (total > 0) {
                this.throttledNote(
                  'blob-bytes',
                  `${byteMatch[1]} ${byteMatch[2]} of ${byteMatch[3]} ${byteMatch[4]} received`,
                  'download',
                  1500
                );
                // Keep the catalogue size as the denominator when ollama
                // reports something smaller, so the bar never jumps back.
                const known = Math.round(MODEL_BYTES[model.id] || 0);
                this.updateByteProgress(done, Math.max(known, total));
                changed = true;
              }
            }
          }
          if (changed) {
            // Feed the per-model percentage into the phase as well. Without
            // this the phase percent only moved when a model *finished*, so a
            // single large download left the bar frozen for minutes while the
            // byte counter and the ETA both moved.
            if (model.status === 'downloading') {
              // share is each model's *fraction* of the phase (1/n), not a
              // percentage. It used to be 100/n, so `live * share` multiplied a
              // percentage by a percentage: with a single model 46% became
              // 46 * 100 = 4600 and Math.min(99, ...) pinned the phase at 99 for
              // the whole download. The bar sat frozen at 95% overall while
              // gigabytes streamed in, even though the byte counters were right.
              const share = 1 / Math.max(1, this.models.length);
              const settled = this.models.filter((m) => m.status === 'installed').length;
              // ollama prints a percentage per blob, and each blob races to
              // 100%, so that number saturates almost immediately. The
              // transferred bytes are the honest signal for the whole model.
              const bytePct = this.bytesTotal
                ? (this.bytesDone / this.bytesTotal) * 100
                : null;
              const live = bytePct === null ? model.percent : Math.max(bytePct, 0);
              this.updatePhase(id, Math.min(99, (settled + live) * share), model.id);
            }
            this.emitProgress();
          }
        };
        child.stdout.on('data', handle);
        child.stderr.on('data', handle);
        child.on('error', (error) => {
          this.log(`model pull error (${model.id}): ${error.message}`);
          model.status = 'failed';
          model.error = error.message;
          resolve();
        });
        child.on('close', (code) => {
          this.currentChild = null;
          if (code === 0) {
            model.status = 'installed';
            model.percent = 100;
            this.installedModels.push(model.id);
            this.note(`${model.id} is downloaded and ready`, 'ok');
          } else {
            model.status = 'failed';
            model.error = `ollama pull exited ${code}`;
            this.note(`${model.id} failed \u2014 ollama pull exited ${code}`, 'error');
          }
          finished += 1;
          this.updatePhase(id, (finished / this.models.length) * 100, model.id);
          this.emitProgress();
          resolve();
        });
      });
    }

    this.activeItem = '';
    this.resetByteProgress();
    const failed = this.models.filter((m) => m.status === 'failed');
    if (failed.length > 0) {
      this.note(
        `Model download deferred for ${failed.map((m) => m.id).join(', ')}. You can download local models directly inside Clipify AI anytime.`,
        'warn'
      );
      this.finishPhase(id, 'done', `${failed.length} model(s) deferred`);
      this.emitProgress();
    } else {
      this.finishPhase(id, 'done', `${this.installedModels.length} model(s) ready`);
      this.emitProgress();
    }
  }

  // ------------------------------------------------------ step: shortcuts

  createShortcuts({ desktopShortcut }) {
    const id = 'shortcuts';
    this.beginPhase(id);

    const target = this.options.installDir;
    const iconPath = this.resolveIconPath();
    // Shortcuts point straight at the compiled executable. The old code
    // preferred ClippedAI.vbs (-> ClippedAI.bat), which is a wrapper-based
    // launch and is not acceptable for the shipped product.
    const appExe = path.join(target, APP_EXE);
    const runTarget = fs.existsSync(appExe) ? appExe : path.join(target, 'app.exe');
    if (!fs.existsSync(runTarget)) {
      this.finishPhase(id, 'error', `${APP_EXE} missing from the installed application.`);
      throw new Error(`${APP_EXE} missing from the installed application.`);
    }

    const startMenu = path.join(
      process.env.APPDATA || '',
      'Microsoft', 'Windows', 'Start Menu', 'Programs', APP_SHORTCUT_NAME
    );
    fs.mkdirSync(startMenu, { recursive: true });
    this.log(`Start Menu folder prepared: ${startMenu}`);
    this.note(`Preparing the Start Menu folder in ${startMenu}`, 'info');

    const desktopDir = [
      path.join(os.homedir(), 'OneDrive', 'Desktop'),
      path.join(os.homedir(), 'Desktop'),
    ].find((d) => fs.existsSync(d)) || path.join(os.homedir(), 'Desktop');

    if (desktopShortcut) {
      this.emit('create-shortcut', {
        applicationType: 'product',
        targetPath: runTarget,
        shortcutPath: path.join(desktopDir, `${APP_SHORTCUT_NAME}.lnk`),
        iconPath,
        description: APP_SHORTCUT_NAME,
        workingDirectory: target,
      });
      this.note('Creating a desktop shortcut', 'info');
    }
    // Create shortcut in Start Menu Programs folder
    this.emit('create-shortcut', {
      applicationType: 'product',
      targetPath: runTarget,
      shortcutPath: path.join(startMenu, `${APP_SHORTCUT_NAME}.lnk`),
      iconPath,
      description: APP_SHORTCUT_NAME,
      workingDirectory: target,
    });
    // Also create top-level shortcut in Start Menu\Programs\
    const topStartMenu = path.join(process.env.APPDATA || '', 'Microsoft', 'Windows', 'Start Menu', 'Programs');
    if (fs.existsSync(topStartMenu)) {
      this.emit('create-shortcut', {
        applicationType: 'product',
        targetPath: runTarget,
        shortcutPath: path.join(topStartMenu, `${APP_SHORTCUT_NAME}.lnk`),
        iconPath,
        description: APP_SHORTCUT_NAME,
        workingDirectory: target,
      });
    }
    this.note('Creating Start Menu shortcuts', 'info');
    this.emit('create-shortcut', {
      applicationType: 'setup',
      targetPath: process.execPath,
      args: '--uninstall',
      shortcutPath: path.join(startMenu, `Uninstall ${APP_SHORTCUT_NAME}.lnk`),
      iconPath,
      description: `Uninstall ${APP_SHORTCUT_NAME}`,
    });

    this.finishPhase(id, 'done');
  }

  resolveIconPath() {
    const candidates = [
      path.join(this.options.installDir, 'icon.ico'),
    ];
    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) return candidate;
    }
    return process.execPath;
  }

  // ------------------------------------------------------------ user data

  seedUserData() {
    const envExample = path.join(this.options.installDir, '.env.example');
    const home = this.dataRoot();
    const target = path.join(home, '.env');
    fs.mkdirSync(home, { recursive: true });
    for (const sub of ['input', 'output', 'jobs', 'projects', 'settings', 'assets', 'narrate clips']) {
      fs.mkdirSync(path.join(home, sub), { recursive: true });
    }
    // Seed default narrate clips from installed application into user data library
    const payloadClips = path.join(this.options.installDir, 'narrate clips');
    const targetClips = path.join(home, 'narrate clips');
    if (fs.existsSync(payloadClips) && fs.existsSync(targetClips)) {
      try {
        for (const file of fs.readdirSync(payloadClips)) {
          const srcFile = path.join(payloadClips, file);
          const dstFile = path.join(targetClips, file);
          if (!fs.existsSync(dstFile) && fs.statSync(srcFile).isFile()) {
            fs.copyFileSync(srcFile, dstFile);
          }
        }
        this.log('seeded default narration clips');
      } catch (err) {
        this.log(`seed clips warning: ${err.message}`);
      }
    }
    // Never overwrite a file the user has already customised.
    if (!fs.existsSync(target) && fs.existsSync(envExample)) {
      fs.copyFileSync(envExample, target);
      this.log('seeded .env from .env.example');
    }

    // Write install-specific OLLAMA_MODELS into local .env if a dedicated models directory is configured
    const modelsDir = this.modelsDir();
    if (modelsDir && fs.existsSync(modelsDir)) {
      try {
        let envContent = fs.existsSync(target) ? fs.readFileSync(target, 'utf-8') : '';
        if (/^OLLAMA_MODELS=.*$/m.test(envContent)) {
          envContent = envContent.replace(/^OLLAMA_MODELS=.*$/m, `OLLAMA_MODELS=${modelsDir}`);
        } else {
          envContent += `\nOLLAMA_MODELS=${modelsDir}\n`;
        }
        fs.writeFileSync(target, envContent.trim() + '\n', 'utf-8');
        this.log(`Wrote OLLAMA_MODELS=${modelsDir} to ${target}`);
      } catch (err) {
        this.log(`warning: could not write OLLAMA_MODELS to .env: ${err.message}`);
      }
    }
  }

  // ---------------------------------------------------------------- driver

  async start(options) {
    if (this.running) throw new Error('an installation is already running');
    this.options = options;
    const releaseLock = acquireInstallLock(this.lockPath, options.installDir);
    this.running = true;
    this.cancelled = false;
    this.installComplete = false;
    this.startedAt = Date.now();
    this.phaseState = {};
    this.log(`--- installation started: ${JSON.stringify(options)} ---`);
    const resume = this.readState();
    if (resume && resume.status === 'in-progress' && resume.installDir === options.installDir) {
      this.log('resuming a previously interrupted installation');
    }
    this.writeState();

    try {
      await this.copyPayload();
      this.seedUserData();

      // The location screen, the space estimate and the log all use
      // installRuntime/installOllama. These two conditions used to read
      // runtimeEnabled/ollamaEnabled, which nothing ever sets, so the test was
      // always true: unticking "AI runtime" or "Ollama" still installed it, and
      // the multi-gigabyte download could not be skipped at all.
      if (options.installRuntime !== false) {
        await this.ensurePython();
        await this.ensureRuntime();
      } else {
        this.phaseState.python = { status: 'skipped', percent: 100, message: 'skipped' };
        this.phaseState.runtime = { status: 'skipped', percent: 100, message: 'skipped' };
        this.emit('phase', { id: 'python', ...this.phaseState.python });
        this.emit('phase', { id: 'runtime', ...this.phaseState.runtime });
        this.emitProgress();
      }

      if (options.installOllama !== false) {
        await this.ensureOllama();
      } else {
        this.phaseState.ollama = { status: 'skipped', percent: 100, message: 'skipped' };
        this.emit('phase', { id: 'ollama', ...this.phaseState.ollama });
        this.emitProgress();
      }

      await this.installModels(options.models || []);
      this.createShortcuts(options);
      await this.verifyInstallation();

      this.log('--- installation complete ---');
      this.installComplete = true;
      this.writeState({ status: 'complete' });
      this.emit('done', {
        installDir: options.installDir,
        installedModels: this.installedModels,
        installedBytes: installedApplicationFootprint(options.installDir),
      });
    } catch (error) {
      this.log(`installation stopped: ${error.message}`);
      // Name the phase that failed so the UI can offer a targeted retry.
      const failedPhase =
        Object.entries(this.phaseState).find(([, value]) => value.status === 'error') || [];
      this.writeState({ status: error.cancelled ? 'interrupted' : 'error', error: error.message });
      this.emit(error.cancelled ? 'cancelled' : 'failed', {
        error: error.message,
        phaseId: failedPhase[0] || null,
      });
    } finally {
      this.running = false;
      this.currentChild = null;
      this.activePhaseId = null;
      if (this.runtimeStageDir) {
        const abandonedStage = this.runtimeStageDir;
        this.runtimeStageDir = null;
        try { await fs.promises.rm(abandonedStage, { recursive: true, force: true }); }
        catch (error) { this.log(`could not clean this attempt's runtime staging path ${abandonedStage}: ${error.message}`); }
      }
      try { releaseLock(); } catch (error) {
        this.log(`could not release installer lock ${this.lockPath}: ${error.message}`);
      }
    }
  }

  /**
   * Safely retries setup. Completed file copies are hash-checked, existing
   * runtimes and models are detected, and the normal verifier runs again.
   */
  async retryPhase(phaseId, options) {
    const knownPhase = PHASES.some((phase) => phase.id === phaseId);
    if (!knownPhase && phaseId !== null) throw new Error(`unknown phase: ${phaseId}`);
    this.log(`retry requested${phaseId ? ` after ${phaseId}` : ''}; rechecking completed work`);
    return this.start(options);
  }

  async verifyInstallation() {
    const id = 'verify';
    this.beginPhase(id);
    this.activeTask = 'Verifying Clipify AI';
    const requiredFiles = [APP_EXE];
    for (const name of requiredFiles) {
      const file = path.join(this.options.installDir, name);
      let stat;
      try { stat = await fs.promises.stat(file); } catch {
        this.finishPhase(id, 'error', `${name} is missing`);
        throw new Error(`Required application file ${name} is missing from the installation.`);
      }
      if (!stat.isFile() || stat.size < 1024) {
        this.finishPhase(id, 'error', `${name} did not pass file verification`);
        throw new Error(`Required application file ${name} failed verification.`);
      }
    }

    // Verify worker pipeline (accept either main.py or main.exe)
    const workerPy = path.join(this.options.installDir, 'main.py');
    const workerExe = path.join(this.options.installDir, 'main.exe');
    let hasWorker = false;
    try {
      const s = await fs.promises.stat(workerPy);
      if (s.isFile() && s.size > 1024) hasWorker = true;
    } catch {}
    if (!hasWorker) {
      try {
        const s = await fs.promises.stat(workerExe);
        if (s.isFile() && s.size > 1024) hasWorker = true;
      } catch {}
    }
    if (!hasWorker) {
      this.finishPhase(id, 'error', 'main.py / main.exe failed verification');
      throw new Error('Required application worker file (main.py / main.exe) failed verification.');
    }
    this.updatePhase(id, 35, 'Application files verified');
    this.emitProgress();

    if (this.options.installRuntime !== false) {
      const pythonExe = path.join(this.pythonDir(), 'python.exe');
      if (!(await this.pythonEngineUsable(pythonExe))) {
        this.finishPhase(id, 'error', 'Python engine readiness check failed');
        throw new Error('The Python engine could not pass its final readiness check.');
      }
      if (!runtimeCompleteIn(this.runtimeDir())) {
        this.finishPhase(id, 'error', 'AI runtime completion marker is missing');
        throw new Error('The local AI runtime is incomplete. Retry the runtime setup.');
      }
      await this.verifyRuntime(path.join(this.runtimeDir(), 'Scripts', 'python.exe'));
    }

    if (this.options.models && this.options.models.length) {
      const ollamaExe = findOllama();
      if (ollamaExe) {
        try {
          const output = [];
          const result = await this.runProcess(ollamaExe, ['list'], {
            timeoutMs: 15000,
            onLine: (line) => output.push(line),
          });
          const installed = parseOllamaList(output.join('\n'));
          const missing = this.options.models.filter((model) => !installed.has(model));
          if (missing.length) {
            this.log(`info: selected model(s) not yet in default list: ${missing.join(', ')}`);
            this.note(`Selected model (${missing.join(', ')}) will be available in Clipify AI`, 'info');
          } else {
            this.log(`verified models: ${this.options.models.join(', ')}`);
          }
        } catch (err) {
          this.log(`warning during model verification: ${err.message}`);
        }
      } else {
        this.log('warning: ollama executable not found during verify phase');
      }
    }

    this.updatePhase(id, 100, 'All required components verified');
    this.finishPhase(id, 'done', 'all required components verified');
  }
}

module.exports = {
  Installer,
  APP_HOME,
  STATE_FILE,
  LOG_FILE,
  PYTHON_VERSION,
  PYTHON_URL,
  OLLAMA_URL,
  MODEL_BYTES,
  PHASES,
};
