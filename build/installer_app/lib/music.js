'use strict';

/**
 * Setup-time music.
 *
 * The installer is meant to play background music while it works, and the
 * tracks must NOT survive the installation. To achieve that the audio is staged
 * into a temporary folder at startup and deleted when setup finishes (or when
 * the process exits), so nothing is left in the app install directory.
 *
 * Files are read from resources/music next to the app when present. The folder
 * is allowed to be empty - the player then simply reports "no tracks" rather
 * than failing.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const AUDIO_EXT = new Set(['.mp3', '.ogg', '.wav', '.m4a', '.flac']);

let stagedDir = null;

/** Where the bundled tracks live, if the build included any. */
/** The bundled tracks are soundtrack pieces, so name the piece they come from. */
const ARTIST_FOR = {
  'grand escape': 'Weathering With You',
};

function sourceDir() {
  const candidates = [];
  if (process.resourcesPath) candidates.push(path.join(process.resourcesPath, 'music'));
  candidates.push(path.join(__dirname, '..', 'resources', 'music'));
  return candidates.find((dir) => fs.existsSync(dir)) || null;
}

/**
 * Removes folders left behind by a previous run that was force-killed and so
 * never reached before-quit. Without this, every crash would strand another
 * ~10 MB of staged audio in %TEMP%.
 */
function sweepStale(maxAgeMs = 6 * 60 * 60 * 1000) {
  let removed = 0;
  let entries = [];
  try {
    entries = fs.readdirSync(os.tmpdir(), { withFileTypes: true });
  } catch {
    return 0;
  }
  const now = Date.now();
  for (const entry of entries) {
    if (!entry.isDirectory() || !entry.name.startsWith('clipify-setup-')) continue;
    const full = path.join(os.tmpdir(), entry.name);
    try {
      if (now - fs.statSync(full).mtimeMs < maxAgeMs) continue;
      fs.rmSync(full, { recursive: true, force: true });
      removed += 1;
    } catch {
      /* leave anything we cannot remove */
    }
  }
  return removed;
}

/**
 * Copies tracks into a temp folder. Returns descriptors the renderer can use.
 * Never throws: a failure here must not stop an installation.
 */
function stageTracks() {
  const source = sourceDir();
  if (!source) return { tracks: [], dir: null };

  let entries = [];
  try {
    entries = fs
      .readdirSync(source)
      .filter((name) => AUDIO_EXT.has(path.extname(name).toLowerCase()))
      .sort();
  } catch {
    return { tracks: [], dir: null };
  }
  if (!entries.length) return { tracks: [], dir: null };

  try {
    stagedDir = fs.mkdtempSync(path.join(os.tmpdir(), 'clipify-setup-'));
  } catch {
    return { tracks: [], dir: null };
  }

  const tracks = [];
  for (const name of entries) {
    const from = path.join(source, name);
    try {
      fs.copyFileSync(from, path.join(stagedDir, name));
      const title = name.replace(/^\d+\s*/, '').replace(/\.[^.]+$/, '').replace(/_/g, ' ');
      tracks.push({
        title,
        artist: ARTIST_FOR[title.toLowerCase()] || '',
        file: name,
      });
    } catch {
      /* skip a track we could not stage */
    }
  }
  return { tracks, dir: stagedDir };
}

/** Removes the staged tracks. Called when setup finishes or the app quits. */
function releaseTracks() {
  if (!stagedDir) return;
  try {
    fs.rmSync(stagedDir, { recursive: true, force: true });
  } catch {
    /* the OS temp sweeper will get it eventually */
  }
  stagedDir = null;
}

module.exports = { stageTracks, releaseTracks, sweepStale, get stageDir() { return stagedDir; } };
