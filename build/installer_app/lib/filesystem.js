'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const RETRYABLE_FS_CODES = new Set(['EPERM', 'EBUSY', 'EACCES']);
const STALE_LOCK_WITHOUT_OWNER_MS = 5 * 60 * 1000;

function uniqueSibling(parent, prefix) {
  return path.join(parent, `${prefix}-${process.pid}-${crypto.randomUUID()}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function retryFileOperation(operation, {
  attempts = 5,
  delayMs = 180,
  wait = sleep,
  shouldRetry = (error) => RETRYABLE_FS_CODES.has(error && error.code),
} = {}) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (attempt >= attempts || !shouldRetry(error)) throw error;
      await wait(delayMs * attempt);
    }
  }
  throw lastError;
}

function processIsAlive(pid, processApi = process) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    processApi.kill(pid, 0);
    return true;
  } catch (error) {
    return error && error.code === 'EPERM';
  }
}

/**
 * Acquires an exclusive per-user installer lock. The lock is only removed by
 * the owner token that created it. A lock from a dead process is safe to
 * recover; a lock with a live or unknown owner is left untouched.
 */
function acquireInstallLock(lockPath, target, {
  fsApi = fs,
  processApi = process,
  now = Date.now,
  staleWithoutOwnerMs = STALE_LOCK_WITHOUT_OWNER_MS,
  token = crypto.randomUUID(),
} = {}) {
  fsApi.mkdirSync(path.dirname(lockPath), { recursive: true });
  const metadata = {
    pid: processApi.pid,
    token,
    target: path.resolve(target),
    createdAt: new Date(now()).toISOString(),
  };

  for (let attempt = 0; attempt < 2; attempt += 1) {
    let handle;
    try {
      handle = fsApi.openSync(lockPath, 'wx', 0o600);
      fsApi.writeFileSync(handle, JSON.stringify(metadata), 'utf8');
      fsApi.fsyncSync(handle);
      fsApi.closeSync(handle);
      handle = null;
      return () => {
        try {
          const current = JSON.parse(fsApi.readFileSync(lockPath, 'utf8'));
          if (current.token === token) fsApi.unlinkSync(lockPath);
        } catch (error) {
          if (!error || error.code !== 'ENOENT') throw error;
        }
      };
    } catch (error) {
      if (handle !== undefined && handle !== null) {
        try { fsApi.closeSync(handle); } catch { /* retain the original error */ }
      }
      if (!error || error.code !== 'EEXIST') throw error;

      let current = null;
      let stat = null;
      try { current = JSON.parse(fsApi.readFileSync(lockPath, 'utf8')); }
      catch { /* a corrupt lock is handled by its age below */ }
      try { stat = fsApi.statSync(lockPath); }
      catch { /* lock disappeared while it was inspected */ }

      const ownerPid = current && Number(current.pid);
      if (Number.isInteger(ownerPid) && ownerPid > 0 && processIsAlive(ownerPid, processApi)) {
        const busy = new Error(`Another Clipify AI setup is already working in ${current.target || target}.`);
        busy.code = 'INSTALL_LOCKED';
        throw busy;
      }

      const oldEnoughToRecover = stat && now() - stat.mtimeMs >= staleWithoutOwnerMs;
      if ((!current || !Number.isInteger(ownerPid) || ownerPid <= 0) && !oldEnoughToRecover) {
        const busy = new Error('Clipify AI setup is checking an installation lock. Try again in a moment.');
        busy.code = 'INSTALL_LOCKED';
        throw busy;
      }

      // Re-read before removal so a replacement lock created by a concurrent
      // recovery attempt is not mistaken for the stale record we inspected.
      try {
        const latest = JSON.parse(fsApi.readFileSync(lockPath, 'utf8'));
        if (!current || latest.token !== current.token || processIsAlive(Number(latest.pid), processApi)) {
          const busy = new Error('Another Clipify AI setup is recovering this installation lock. Try again shortly.');
          busy.code = 'INSTALL_LOCKED';
          throw busy;
        }
      } catch (readError) {
        if (readError && readError.code === 'INSTALL_LOCKED') throw readError;
        if (current && readError && readError.code !== 'ENOENT') throw readError;
      }

      // A valid dead-process lock or an old incomplete file is stale. Unlink
      // just this exact lock file; never search for or remove adjacent paths.
      try { fsApi.unlinkSync(lockPath); } catch (unlinkError) {
        if (unlinkError.code !== 'ENOENT') throw unlinkError;
      }
    }
  }

  const busy = new Error('Another Clipify AI setup is already running.');
  busy.code = 'INSTALL_LOCKED';
  throw busy;
}

async function copyDirectoryContents(source, destination, {
  skipFile = () => false,
  onFile = null,
  attempts = 5,
  delayMs = 180,
  wait = sleep,
} = {}) {
  const entries = await fs.promises.readdir(source, { withFileTypes: true });
  await fs.promises.mkdir(destination, { recursive: true });
  for (const entry of entries) {
    const from = path.join(source, entry.name);
    const to = path.join(destination, entry.name);
    if (entry.isSymbolicLink()) {
      throw new Error(`Refusing to stage a symbolic link from the runtime package: ${from}`);
    }
    if (entry.isDirectory()) {
      await copyDirectoryContents(from, to, { skipFile, onFile, attempts, delayMs, wait });
      continue;
    }
    if (!entry.isFile() || skipFile(from, entry.name)) continue;
    await fs.promises.mkdir(path.dirname(to), { recursive: true });
    await retryFileOperation(() => fs.promises.copyFile(from, to), { attempts, delayMs, wait });
    if (onFile) onFile(from, to);
  }
}

async function renameWithRetry(source, destination, options = {}) {
  return retryFileOperation(() => fs.promises.rename(source, destination), options);
}

module.exports = {
  RETRYABLE_FS_CODES,
  STALE_LOCK_WITHOUT_OWNER_MS,
  uniqueSibling,
  retryFileOperation,
  processIsAlive,
  acquireInstallLock,
  copyDirectoryContents,
  renameWithRetry,
};
