'use strict';

/**
 * Clipify AI setup - renderer controller.
 *
 * Owns screen navigation, the model catalogue, the live disk-space readout, the
 * music player and the waiting game. Every real decision (disk space, Ollama
 * detection, what still needs downloading) comes from the main process over IPC
 * so this file never guesses and never blocks.
 */

(function () {
  const api = window.clipify;

  const state = {
    screen: 'welcome',
    detection: null,
    // USER SELECTION - never derived from what happens to be installed.
    selected: new Set(),
    // Set once, on the very first visit. Afterwards the user owns the choice.
    defaultsApplied: false,
    // The user's own path. Detection must never overwrite this.
    userPath: null,
    // The user's chosen Ollama model storage directory. null = use default.
    userModelsDir: null,
    focusModel: null,
    manualNight: false,
    game: null,
    lastDiskKey: '',
    navigationBusy: false,
    diskRequest: 0,
    installOptions: null,
    failedPhaseId: null,
    installBusy: false,
    installTerminal: false,
  };

  // A missing element must never be able to abort the rest of boot: a single
// stale id used to throw here and silently kill every handler bound after it,
// which is how the Install button once stopped working. Unknown ids resolve to
// an inert stand-in instead.
const NOOP = () => {};
const $ = (id) => {
  const el = document.getElementById(id);
  if (el) return el;
  const stub = {
    id,
    hidden: true,
    disabled: true,
    value: '',
    textContent: '',
    innerText: '',
    innerHTML: '',
    style: {},
    dataset: {},
    classList: { add: NOOP, remove: NOOP, toggle: NOOP, contains: () => false },
    addEventListener: NOOP,
    removeEventListener: NOOP,
    appendChild: NOOP,
    setAttribute: NOOP,
    focus: NOOP,
  };
  return stub;
};

  // ------------------------------------------------------------ helpers

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
    // Decimal units, deliberately. Ollama reports model sizes in decimal GB and
    // the catalogue quotes those numbers verbatim, so dividing by 1024 here
    // would make the card claim less than the registry actually downloads.
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let index = 0;
    while (value >= 1000 && index < units.length - 1) {
      value /= 1000;
      index += 1;
    }
    const digits = value >= 100 || index === 0 ? 0 : value >= 10 ? 1 : 2;
    return `${value.toFixed(digits)} ${units[index]}`;
  }

  function formatDuration(ms) {
    if (!Number.isFinite(ms) || ms < 0) return '—';
    const total = Math.round(ms / 1000);
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  function plural(count, word) {
    return `${count} ${word}${count === 1 ? '' : 's'}`;
  }

  function setStatus(text) {
    $('status-text').textContent = text;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  /**
   * A recognisable mark per model family.
   *
   * These are drawn here rather than shipped as image files: a mark that is a
   * few paths stays sharp at any DPI, adds nothing to the installer payload, and
   * avoids redistributing somebody else's artwork inside a third-party setup
   * wizard. What matters is that the card is instantly identifiable - a dolphin
   * model gets a dolphin, a Llama fine-tune gets a llama - because a grid of
   * near-identical abstract shapes tells the user nothing.
   */
  const FAMILY_STYLE = {
    // Qwen's brand is the letter Q, so it is drawn as one.
    Qwen3: { a: '#6ea497', b: '#294946', mark: 'qwen' },
    Gemma: { a: '#5b8fd6', b: '#2f4f7a', mark: 'flower' },
    Llama: { a: '#c98a4b', b: '#7a4f24', mark: 'llama' },
    // Dolphin is Eric Hartford's fine-tune line, always shown as a dolphin.
    Dolphin: { a: '#3f9fc4', b: '#1d5a76', mark: 'dolphin' },
    Mistral: { a: '#e0705f', b: '#8f3a2c', mark: 'wind' },
    DeepSeek: { a: '#5a7fd0', b: '#2b3f75', mark: 'whale' },
    Phi: { a: '#8b6fd0', b: '#46357a', mark: 'phi' },
  };

  const FALLBACK_STYLE = { a: '#6ea497', b: '#294946', mark: 'qwen' };

  function modelIcon(family) {
    const style = FAMILY_STYLE[family] || FALLBACK_STYLE;
    const B = style.b;
    const A = style.a;
    const marks = {
      // A Q with an orbiting core.
      qwen: `<circle cx="10.8" cy="10.8" r="6" fill="none" stroke="${B}" stroke-width="2.4"/>
             <path d="M14.4 14.4 18.6 18.6" stroke="${B}" stroke-width="2.6" stroke-linecap="round"/>
             <circle cx="10.8" cy="10.8" r="1.9" fill="${A}"/>`,
      // Gemma is a four-petal bloom.
      flower: `<g fill="${B}">
                 <ellipse cx="12" cy="7.2" rx="2.5" ry="4"/>
                 <ellipse cx="12" cy="16.8" rx="2.5" ry="4"/>
                 <ellipse cx="7.2" cy="12" rx="4" ry="2.5"/>
                 <ellipse cx="16.8" cy="12" rx="4" ry="2.5"/>
               </g>
               <circle cx="12" cy="12" r="2" fill="${A}"/>`,
      // Llama: upright ears over a rounded head.
      llama: `<path d="M7.7 4.4 9 8.4M16.3 4.4 15 8.4" stroke="${B}" stroke-width="2.1" stroke-linecap="round" fill="none"/>
              <path d="M12 8.2c2.6 0 4.3 2 4.3 4.4 0 2.7-2 5.4-4.3 5.4s-4.3-2.7-4.3-5.4c0-2.4 1.7-4.4 4.3-4.4Z" fill="${B}"/>
              <circle cx="10.3" cy="12.3" r=".95" fill="${A}"/>
              <circle cx="13.7" cy="12.3" r=".95" fill="${A}"/>
              <path d="M10.5 16.3h3" stroke="${A}" stroke-width="1.4" stroke-linecap="round"/>`,
      // Dolphin: a leaping body, dorsal fin, forked tail and an eye.
      dolphin: `<path d="M4.2 18.4c4.2-1 6.2-3.1 8.2-6.1 1.8-2.7 4.1-4.6 7-4.6"
                       fill="none" stroke="${B}" stroke-width="2.5" stroke-linecap="round"/>
                <path d="m12.2 12.6 1.5-4 2.7 3.1Z" fill="${B}"/>
                <path d="M4.2 18.4 2.1 15.6M4.2 18.4l2.4 1.5" stroke="${B}" stroke-width="1.9" stroke-linecap="round" fill="none"/>
                <circle cx="17.4" cy="8.3" r=".85" fill="${A}"/>`,
      // Mistral: wind.
      wind: `<path d="M3 9.4c3-2 6-2 9 0s6 2 9 0" fill="none" stroke="${B}" stroke-width="2" stroke-linecap="round"/>
             <path d="M3 14c3-2 6-2 9 0s6 2 9 0" fill="none" stroke="${B}" stroke-width="2" stroke-linecap="round"/>
             <path d="M3 18.6c2.4-1.6 4.9-1.8 7.3-.5" fill="none" stroke="${A}" stroke-width="2" stroke-linecap="round"/>`,
      // DeepSeek: a whale.
      whale: `<ellipse cx="10.8" cy="13.4" rx="7" ry="4.5" fill="${B}"/>
              <path d="M17.4 13.2c1.7-.2 3-1.1 3.8-2.3.3 1.6-.6 3-2 3.7Z" fill="${B}"/>
              <path d="M5.4 10.6c1.5-1.4 3.5-2 5.4-1.8" fill="none" stroke="${A}" stroke-width="1.5" stroke-linecap="round"/>
              <circle cx="6.6" cy="12.4" r=".85" fill="${A}"/>`,
      // Phi is the Greek letter, which is literally the model's name.
      phi: `<circle cx="12" cy="12" r="6.1" fill="none" stroke="${B}" stroke-width="2.2"/>
            <path d="M12 3.6v16.8" stroke="${B}" stroke-width="2.2" stroke-linecap="round"/>`,
    };
    return `<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
      <rect width="24" height="24" rx="7" fill="${style.a}" opacity="0.18"/>
      ${marks[style.mark] || marks.qwen}
    </svg>`;
  }

  // ------------------------------------------------------------- steps

  // The step rail must always agree with the page on screen:
  // location (INSTALL CLIPIFY AI) = Installation, models = AI Models,
  // install = Downloading, done = Finish.
  const STEP_FOR_SCREEN = { welcome: 1, models: 2, location: 3, install: 4, done: 5 };

  function updateSteps() {
    const current = STEP_FOR_SCREEN[state.screen] || 1;
    document.querySelectorAll('.step').forEach((el) => {
      const step = Number(el.dataset.step);
      el.classList.toggle('active', step === current);
      el.classList.toggle('done', step < current);
    });
  }

  // ------------------------------------------------------------ screens

  function show(name) {
    if (state.screen === 'install' && name !== 'install') state.game?.setVisible(false);
    state.screen = name;
    document.querySelectorAll('.screen').forEach((screen) => {
      screen.hidden = screen.dataset.screen !== name;
    });
    updateSteps();
    if (name === 'models') $('model-grid').focus?.();
    // Show the welcome popup the first time the user lands on the first screen.
    document.body.dataset.screen = name;
  }

  // ------------------------------------------------------------- music

  const music = {
    tracks: [],
    index: 0,
    muted: false,
    playing: false,
    // Chromium blocks audio until the user has interacted with the page, so the
    // first play is armed and fires on the first click anywhere.
    armed: false,
    volume: 0.35,
    get audio() {
      return $('audio');
    },

    init(payload) {
      this.tracks = Array.isArray(payload && payload.tracks) ? payload.tracks : [];
      try {
        this.muted = localStorage.getItem('clipify.music.muted') === '1';
        // Number(null) is 0, not NaN, so an unset value used to satisfy the
        // range check and pin the volume at zero - the player then looked
        // loaded and played but was permanently silent.
        const rawVolume = localStorage.getItem('clipify.music.volume');
        const saved = rawVolume === null ? NaN : Number(rawVolume);
        if (Number.isFinite(saved) && saved > 0 && saved <= 1) this.volume = saved;
      } catch {
        /* defaults are fine */
      }
      $('music-volume-value') && ($('music-volume-value').textContent = `${Math.round(this.volume * 100)}%`);
      this.audio.volume = this.muted ? 0 : this.volume;
      this.audio.addEventListener('timeupdate', () => this.paintTime());
      // Duration only becomes known once metadata arrives. Without this the
      // clock sat at "00:00 / 00:00" until the user happened to press play,
      // because timeupdate does not fire while the track is paused.
      this.audio.addEventListener('loadedmetadata', () => this.paintTime());
      this.audio.addEventListener('durationchange', () => this.paintTime());
      this.audio.addEventListener('canplay', () => this.paintTime());
      this.audio.addEventListener('error', () => this.paintUnavailable());
      // The disc must follow the element's real transport state, not a cached
      // intent, so a blocked autoplay can never look like it is playing.
      this.audio.addEventListener('play', () => { this.playing = true; this.armed = true; this.paint(); });
      this.audio.addEventListener('pause', () => { this.playing = false; this.paint(); });
      this.audio.addEventListener('ended', () => { this.playing = false; this.paint(); });
      this.audio.addEventListener('ended', () => {
        this.playing = false;
        // End of a playlist rolls back to the first track.
        if (this.tracks.length > 1) this.load(0, true);
        this.paint();
      });
      this.paint();
      if (this.tracks.length) this.load(0, false);
      // Try to start on its own. Electron may still refuse without a gesture;
      // the rejection is handled so nothing is left in a fake "playing" state.
      if (this.tracks.length) {
        this.audio.play().then(
          () => { this.playing = true; this.armed = true; this.paint(); },
          () => { this.playing = false; this.armed = true; this.paint(); }
        );
      }
    },

    load(index, autoplay) {
      if (!this.tracks.length) return;
      this.index = (index + this.tracks.length) % this.tracks.length;
      const track = this.tracks[this.index];
      // clipifymusic:// is same-origin from the page, so the strict CSP allows it.
      this.audio.src = `clipifymusic://track/${encodeURIComponent(track.file)}`;
      this.audio.load();
      this.audio.volume = this.muted ? 0 : this.volume;
      if (autoplay) this.play();
      this.paint();
      this.paintTime();
    },

    // A track that cannot be decoded must say so rather than sitting on a
    // permanent "00:00 / 00:00".
    paintUnavailable() {
      $('music-title').textContent = 'Music unavailable';
      $('music-time').textContent = '—';
    },

    play() {
      if (!this.tracks.length) return;
      if (this.muted) { this.playing = false; this.paint(); return; }
      this.playing = true;
      this.armed = true;
      const attempt = this.audio.play();
      if (attempt && attempt.catch) {
        attempt.catch(() => {
          // Refused until a user gesture: keep the button in "paused" and
          // re-arm so the next interaction starts it for real.
          this.playing = false;
          this.armed = true;
          this.paint();
        });
      }
      this.paint();
    },

    pause() {
      this.playing = false;
      this.audio.pause();
      this.paint();
    },

    togglePlay() {
      if (!this.tracks.length) return;
      if (this.playing) this.pause();
      else this.play();
    },

    setMuted(value) {
      this.muted = value;
      try {
        localStorage.setItem('clipify.music.muted', value ? '1' : '0');
      } catch {
        /* ignore */
      }
      // Always restore the real level on unmute - otherwise the player stays
      // silent forever, because mute is implemented as volume 0.
      this.audio.volume = this.muted ? 0 : this.volume;
      if (value) {
        this.audio.pause();
        this.playing = false;
      } else if (this.armed) {
        this.play();
      }
      this.paint();
    },

    toggleMute() {
      this.setMuted(!this.muted);
    },

    next() {
      if (this.tracks.length < 2) { this.load(0, true); return; }
      this.load(this.index + 1, true);
    },

    prev() {
      if (this.tracks.length < 2) { this.load(0, true); return; }
      this.load(this.index - 1, true);
    },

    setVolume(value) {
      this.volume = Math.max(0, Math.min(1, value));
      this.audio.volume = this.muted ? 0 : this.volume;
      try {
        localStorage.setItem('clipify.music.volume', String(this.volume));
      } catch {
        /* ignore */
      }
    },

    seekTo(ratio) {
      const duration = this.audio.duration;
      if (!Number.isFinite(duration) || duration <= 0) return;
      this.audio.currentTime = Math.max(0, Math.min(duration, duration * ratio));
      this.paintTime();
    },

    paintTime() {
      const clock = (seconds) => {
        if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
        const total = Math.floor(seconds);
        return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
      };
      $('music-time').textContent =
        `${clock(this.audio.currentTime)} / ${clock(this.audio.duration)}`;
      const duration = this.audio.duration;
      const seek = $('music-seek');
      if (seek) {
        seek.disabled = !Number.isFinite(duration) || duration <= 0;
        if (!this.seeking) {
          seek.value = String(
            Number.isFinite(duration) && duration > 0
              ? Math.round((this.audio.currentTime / duration) * 1000)
              : 0
          );
        }
      }
    },

    paint() {
      const track = this.tracks.length ? this.tracks[this.index] : null;
      $('music-title').textContent = this.muted && track ? 'Muted' : track ? track.title : 'No music';
      $('music-artist').textContent = track && track.artist ? track.artist : '';
      $('btn-music-play').textContent = this.playing ? '\u{23F8}' : '\u{25B6}';
      $('btn-music-play').title = this.playing ? 'Pause' : 'Play';
      $('btn-music-mute').textContent = this.muted ? '\u{1F507}' : '\u{1F50A}';
      // Skip/previous are meaningless with nothing loaded, so they say so.
      $('btn-music-next').disabled = !this.tracks.length;
      $('btn-music-prev').disabled = !this.tracks.length;
      $('music').classList.toggle('muted', this.muted);
      $('music').classList.toggle('empty', !this.tracks.length);
      // The disc follows the element's real transport state, not intent: it
      // spins only while the audio is genuinely playing, and stops the
      // instant playback pauses.
      $('music').classList.toggle('playing', !this.audio.paused && this.audio.readyState > 0);
      this.paintTime();
    },

    /** Called when setup finishes - the staged tracks are deleted at this point. */
    stopAndRelease() {
      this.audio.pause();
      this.audio.removeAttribute('src');
      this.playing = false;
    },
  };

  // ------------------------------------------------------------ welcome

  async function loadDetection(installDir, selectedModels, options) {
    setStatus('Detecting system…');
    const detection = await api.detect({ installDir, selectedModels, options });
    state.detection = detection;
    return detection;
  }

  function renderWelcome(detection) {
    $('welcome-version').textContent = `v${api.version}`;
    $('welcome-os').textContent = detection.windows.replace(/\s*\(.*\)$/, '');
    const ram = detection.totalMemoryBytes
      ? ` · ${Math.round(detection.totalMemoryBytes / 1024 ** 3)} GB RAM`
      : '';
    $('welcome-detect').textContent = detection.payload.exists
      ? `Ready to install · ${detection.payload.files} app files · ${detection.cpuCount} cores${ram}`
      : 'Application payload is missing from this installer build.';
    $('status-engine').textContent = `Bundled app files: ${formatBytes(detection.payload.bytes)}`;
    if (detection.previous && detection.previous.interrupted) {
      $('welcome-foot').textContent =
        'A previous installation was interrupted — continuing picks up where it stopped.';
    }
  }

  // ------------------------------------------------------------- models

  function renderModels(detection) {
    const grid = $('model-grid');
    grid.innerHTML = '';
    grid.tabIndex = 0;

    detection.models.forEach((model, index) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'model-card';
      card.dataset.model = model.id;
      card.dataset.test = `model-${model.id}`;
      card.style.animationDelay = `${Math.min(index * 32, 420)}ms`;
      if (state.selected.has(model.id)) card.classList.add('selected');
      if (state.focusModel === model.id) card.classList.add('focused');

      const badges = [];
      if (model.recommended) badges.push('<span class="badge badge-rec">Recommended</span>');
      if (model.installed) badges.push('<span class="badge badge-have">Already here</span>');
      (model.tags || []).slice(0, 1).forEach((tag) => {
        if (tag !== 'Recommended') badges.push(`<span class="badge badge-tag">${escapeHtml(tag)}</span>`);
      });

      card.innerHTML = `
        <div class="model-head">
          <span class="model-icon">${modelIcon(model.family)}</span>
          <span class="model-name">${escapeHtml(model.name)}</span>
        </div>
        ${badges.length ? `<div class="model-badges">${badges.join('')}</div>` : ''}
        <span class="model-check" aria-hidden="true">&#10003;</span>
        <p class="model-desc">${escapeHtml(model.description)}</p>
        <div class="model-facts">
          <span class="fact fact-size">${formatBytes(model.sizeBytes)}</span>
          <span class="fact">${escapeHtml(model.ramMin)}+ RAM</span>
        </div>`;

      card.addEventListener('click', (event) => {
        // The badge area focuses; anywhere else toggles.
        if (event.altKey) {
          state.focusModel = model.id;
          renderDetail(model);
          return;
        }
        toggleModel(model.id);
      });
      card.addEventListener('mouseenter', () => renderDetail(model));
      card.addEventListener('focus', () => renderDetail(model));
      grid.appendChild(card);
    });

    const recommended = detection.models.find((m) => m.recommended);
    if (recommended) {
      $('model-reco').textContent = `${recommended.name} is recommended for most users.`;
    }
    renderSummary();
  }

  function toggleModel(id) {
    if (state.selected.has(id)) state.selected.delete(id);
    else state.selected.add(id);
    // NOTE: no CSS.escape here. Inside a quoted attribute value the colon in
    // "qwen3:8b" is already unambiguous, and CSS.escape would inject a
    // backslash that stops the selector matching at all.
    const card = document.querySelector(`[data-model="${id}"]`);
    if (card) card.classList.toggle('selected', state.selected.has(id));
    renderSummary();
  }

  function renderSummary() {
    const bytes = window.ClipifyDownloadWarning.selectedModelDownloadBytes(
      state.detection,
      [...state.selected]
    );
    const count = state.selected.size;
    $('model-summary').textContent = count
      ? `${plural(count, 'model')} selected · ${formatBytes(bytes)} to download`
      : '0 models selected · No AI models will be downloaded.';
  }

  function renderDetail(model) {
    const body = $('detail-body');
    if (!model) {
      body.innerHTML = '<p class="muted">Hover or select a model to see its details.</p>';
      return;
    }
    const bestFor = (model.bestFor || []).map((item) => `<li class="fact">${escapeHtml(item)}</li>`).join('');
    body.innerHTML = `
      <p class="detail-tag">${escapeHtml(model.family || '')}</p>
      <h4 class="detail-title">${escapeHtml(model.name)}</h4>
      <p class="detail-desc">${escapeHtml(model.description)}</p>
      <dl>
        <dt>Download</dt><dd>~${formatBytes(model.sizeBytes)}</dd>
        <dt>RAM min</dt><dd>${escapeHtml(model.ramMin)}</dd>
        <dt>RAM rec</dt><dd>${escapeHtml(model.ramRecommended)}</dd>
        <dt>VRAM</dt><dd>${escapeHtml(model.vram)}</dd>
        <dt>Speed</dt><dd>${escapeHtml(model.speed)}</dd>
        <dt>GPU</dt><dd>${model.gpuUseful ? 'Accelerated' : 'CPU only'}</dd>
        ${model.installed ? '<dt>Status</dt><dd>Already installed</dd>' : ''}
      </dl>
      <ul class="tag-list">${bestFor}</ul>`;
  }

  // ------------------------------------------------------------ location

  async function renderLocation(detection) {
    // Reuse whatever the user already chose. On a later visit we must NOT reset
    // the box back to the default - that reads as the installer changing the
    // install location on its own.
    if (state.userPath === null) {
      state.userPath = detection.installDir;
      $('input-path').value = state.userPath;
    } else {
      $('input-path').value = state.userPath;
    }
    $('chk-runtime').checked = detection.runtimeBytes > 0;
    $('chk-ollama').checked = detection.ollamaBytes > 0;
    $('chk-desktop').checked = true;

    // Model storage UI — show detected current directory.
    const ollama = detection.ollama || {};
    const detectedModelsDir = ollama.modelsDir || '';
    if (detectedModelsDir) {
      $('models-dir-current').textContent = detectedModelsDir;
      const detectedEl = $('models-dir-detected');
      detectedEl.hidden = false;
      // Show model count badge if models already exist there.
      const modelCount = (ollama.models || []).length;
      if (modelCount > 0) {
        detectedEl.querySelector('span:last-child').textContent =
          `${modelCount} existing model${modelCount !== 1 ? 's' : ''} detected at ` +
          detectedModelsDir;
      } else {
        detectedEl.querySelector('span:last-child').textContent =
          `Current model storage: ${detectedModelsDir}`;
      }
    } else {
      $('models-dir-detected').hidden = true;
    }
    // On first visit, leave the field blank (placeholder shows the message).
    if (state.userModelsDir !== null) {
      $('input-models-dir').value = state.userModelsDir;
    }

    await refreshDisk();
  }

  /** What the user has actually chosen, so the required-space maths agrees. */
  function userOptions() {
    return {
      installRuntime: $('chk-runtime').checked,
      installOllama: $('chk-ollama').checked,
    };
  }

  async function refreshDisk() {
    const dir = $('input-path').value.trim();
    const request = ++state.diskRequest;
    const options = userOptions();
    const selected = [...state.selected];
    setStatus('Checking space…');

    let detection;
    try {
      detection = await loadDetection(dir, selected, options);
    } catch (error) {
      if (request !== state.diskRequest || dir !== $('input-path').value.trim()) return;
      setStatus('Could not read the disk');
      $('space-warning').hidden = false;
      $('space-warning-text').textContent = `Could not check the drive: ${error.message}`;
      $('btn-install').disabled = true;
      return;
    }
    if (request !== state.diskRequest || dir !== $('input-path').value.trim()) return;
    state.detection = detection;
    renderDisk(detection);
  }

  function renderDisk(detection) {
    const required = detection.requiredBytes;
    const free = detection.disk.freeBytes || 0;
    const volume = detection.diskVolume || '';

    $('space-required').textContent = `~${formatBytes(required)}`;
    $('space-available').textContent = detection.disk.ok ? formatBytes(free) : 'Unknown';
    $('space-after').textContent = detection.disk.ok ? `~${formatBytes(detection.freeAfterBytes)}` : '—';

    $('space-meta').textContent = detection.disk.ok
      ? `${volume} · ${formatBytes(free)} free of ${formatBytes(detection.disk.totalBytes)}`
      : detection.disk.error || '';

    const ratio = required > 0 ? Math.min(1, free / required) : 1;
    const fill = $('space-bar');
    fill.style.width = `${Math.max(4, ratio * 100)}%`;

    const warn = $('space-warning');
    const good = $('space-good');
    let blocked = false;

    if (!detection.pathValid) {
      warn.hidden = false;
      warn.className = 'notice notice-bad';
      $('space-warning-text').textContent = detection.pathError;
      good.hidden = true;
      blocked = true;
    } else if (!detection.disk.ok) {
      // Unknown is NOT the same as full. Never block on a measurement we could
      // not take - say so and let the user decide.
      warn.hidden = false;
      warn.className = 'notice notice-warn';
      $('space-warning-text').textContent =
        `${detection.disk.error} You can still continue, but installation may fail.`;
      good.hidden = true;
      blocked = false;
    } else if (!detection.enoughSpace) {
      warn.hidden = false;
      warn.className = 'notice notice-warn';
      $('space-warning-text').textContent =
        `You need approximately ${formatBytes(detection.shortfallBytes)} more on ${volume}.`;
      good.hidden = true;
      fill.classList.add('bad');
      blocked = true;
    } else {
      warn.hidden = true;
      fill.classList.remove('bad');
      good.hidden = false;
    }

    const models = detection.modelsToDownload.length;
    $('loc-summary').textContent = [
      models ? `${plural(models, 'model')} to download` : 'No models to download',
      detection.runtimeBytes ? 'AI runtime' : null,
      detection.ollamaBytes ? 'Ollama' : null,
    ].filter(Boolean).join(' · ');

    $('btn-install').disabled = blocked || !detection.payload.exists;
    setStatus(blocked ? 'Not enough space' : 'Ready to install');
  }

  // ------------------------------------------------------------- install

  /** Mirrors the engine's phase list so we can show real per-step state. */
  // Must mirror PHASES in lib/installer.js - the engine emits these ids.
  const PHASE_LABELS = [
    { id: 'files', label: 'Copying Clipify AI', est: '~15s', estSeconds: 15 },
    { id: 'python', label: 'Preparing the Python engine', est: '~25s', estSeconds: 25 },
    { id: 'runtime', label: 'Installing the AI runtime', est: '~3-5m', estSeconds: 240 },
    { id: 'ollama', label: 'Setting up the local AI engine', est: '~30s', estSeconds: 30 },
    { id: 'models', label: 'Downloading AI models', est: '~2-4m', estSeconds: 180 },
    { id: 'shortcuts', label: 'Creating shortcuts', est: '~5s', estSeconds: 5 },
    { id: 'verify', label: 'Checking installed components', est: '~15s', estSeconds: 15 },
  ];

  let installElapsedTimer = null;
  let installStartTime = null;
  let currentOperationName = 'Installing Clipify AI';
  let activePhaseId = null;
  let activePhaseStartedAt = null;

  function startElapsedClock() {
    if (!installStartTime) installStartTime = Date.now();
    if (installElapsedTimer) clearInterval(installElapsedTimer);
    installElapsedTimer = setInterval(() => {
      if (!installStartTime || state.installTerminal) return;
      const elapsedMs = Math.max(0, Date.now() - installStartTime);
      const subtaskEl = $('install-subtask');
      if (subtaskEl && !$('install-workspace').hidden) {
        subtaskEl.textContent = `${currentOperationName} · ${formatDuration(elapsedMs)} elapsed`;
      }
    }, 1000);
  }

  function stopElapsedClock() {
    if (installElapsedTimer) {
      clearInterval(installElapsedTimer);
      installElapsedTimer = null;
    }
  }

  function resetPhases() {
    state.phases = PHASE_LABELS.map((p) => ({ ...p, status: 'pending', percent: 0 }));
    const list = $('phase-list');
    Array.from(list.children).forEach((item) => {
      if (item._completionTimer) window.clearTimeout(item._completionTimer);
      item._completionTimer = 0;
      item.dataset.status = 'pending';
      item.classList.remove('just-completed');
    });
  }

  function renderPhaseList() {
    // Defensive: the install button used to call this before anything had ever
    // initialised state.phases, which threw and silently killed the whole click
    // handler before the progress screen was ever shown.
    if (!state.phases) resetPhases();
    const list = $('phase-list');
    for (const phase of state.phases) {
      let li = Array.from(list.children).find((item) => item.dataset.phaseId === phase.id);
      if (!li) {
        li = document.createElement('li');
        li.dataset.phaseId = phase.id;
        list.appendChild(li);
      }
      const previous = li.dataset.status || 'pending';
      li.className = phase.status === 'running' ? 'active'
        : phase.status === 'done' ? 'done'
        : phase.status === 'skipped' ? 'skipped'
        : phase.status === 'error' ? 'error' : 'pending';
      if (phase.status === 'done' && previous !== 'done') {
        if (li._completionTimer) window.clearTimeout(li._completionTimer);
        li.classList.add('just-completed');
        li._completionTimer = window.setTimeout(() => {
          li.classList.remove('just-completed');
          li._completionTimer = 0;
        }, 420);
      } else if (phase.status !== 'done') {
        if (li._completionTimer) window.clearTimeout(li._completionTimer);
        li._completionTimer = 0;
        li.classList.remove('just-completed');
      }
      li.dataset.status = phase.status;
      const etaLabel = phase.status === 'done' ? '✓'
        : phase.status === 'skipped' ? '–'
        : phase.status === 'running' ? (phase.est || 'In progress')
        : (phase.est || '');
      li.innerHTML = `<span class="phase-name">${escapeHtml(phase.label)}</span><span class="phase-eta">${escapeHtml(etaLabel)}</span>`;
    }
    Array.from(list.children).forEach((item) => {
      if (!state.phases.some((phase) => phase.id === item.dataset.phaseId)) item.remove();
    });
  }

  function renderModelStatus(models) {
    const list = $('model-status');
    list.innerHTML = '';
    if (!models || !models.length) {
      const li = document.createElement('li');
      li.className = 'pending';
      li.innerHTML = '<span>No models selected</span>';
      list.appendChild(li);
      return;
    }
    for (const model of models) {
      const li = document.createElement('li');
      li.className = model.status === 'done' ? 'done' : model.status === 'error' ? 'error' : model.status;
      const note = model.status === 'done' ? 'ready'
        : model.status === 'error' ? 'failed'
        : model.status === 'pending' ? 'queued'
        : model.progress != null ? `${model.progress}%` : '…';
      li.innerHTML = `<span>${escapeHtml(model.name)}</span><em>${escapeHtml(note)}</em>`;
      list.appendChild(li);
    }
  }

  // ------------------------------------------------------ live activity feed

  const ACTIVITY_ROW_HEIGHT = 26;
  const ACTIVITY_OVERSCAN = 5;
  const activityEntries = [];
  let activityCount = 0;
  let activityIdleTimer = 0;
  let activityScrollQueued = false;

  function resetActivity() {
    const feed = $('activity-feed');
    activityEntries.length = 0;
    if (feed) {
      feed.innerHTML = '';
      feed.scrollTop = 0;
    }
    activityCount = 0;
    $('activity-count').textContent = '0 steps';
    $('activity-latest').hidden = true;
  }

  function activityAtBottom(feed) {
    return feed.scrollHeight - feed.clientHeight - feed.scrollTop <= 20;
  }

  function renderActivityFeed() {
    const feed = $('activity-feed');
    if (!feed || !feed.closest('details').open) return;
    const count = activityEntries.length;
    const scrollTop = feed.scrollTop;
    const first = Math.max(0, Math.floor(scrollTop / ACTIVITY_ROW_HEIGHT) - ACTIVITY_OVERSCAN);
    const visible = Math.ceil((feed.clientHeight || 104) / ACTIVITY_ROW_HEIGHT) + ACTIVITY_OVERSCAN * 2;
    const last = Math.min(count, first + visible);
    const fragment = document.createDocumentFragment();

    const spacer = (height) => {
      const row = document.createElement('li');
      row.className = 'activity-spacer';
      row.setAttribute('aria-hidden', 'true');
      row.style.height = `${Math.max(0, height)}px`;
      return row;
    };
    if (first) fragment.appendChild(spacer(first * ACTIVITY_ROW_HEIGHT));

    for (let index = first; index < last; index += 1) {
      const entry = activityEntries[index];
      const li = document.createElement('li');
      li.dataset.kind = entry.kind;
      li.setAttribute('aria-posinset', String(index + 1));
      li.setAttribute('aria-setsize', String(count));
      const when = new Date(entry.at);
      const time = document.createElement('time');
      time.dateTime = when.toISOString();
      time.textContent = [when.getHours(), when.getMinutes(), when.getSeconds()]
        .map((n) => String(n).padStart(2, '0'))
        .join(':');
      const text = document.createElement('span');
      text.className = 'a-text';
      text.textContent = entry.text;
      text.title = entry.text;
      li.append(time, text);
      fragment.appendChild(li);
    }

    if (last < count) fragment.appendChild(spacer((count - last) * ACTIVITY_ROW_HEIGHT));
    feed.replaceChildren(fragment);
    const atBottom = activityAtBottom(feed);
    $('activity-latest').hidden = atBottom || !count;
  }

  function queueActivityRender() {
    if (activityScrollQueued) return;
    activityScrollQueued = true;
    window.requestAnimationFrame(() => {
      activityScrollQueued = false;
      renderActivityFeed();
    });
  }

  /** The pulse stops after silence; it never claims progress that is not happening. */
  function markActivityFresh() {
    const pulse = $('activity-pulse');
    if (pulse) pulse.classList.remove('idle');
    window.clearTimeout(activityIdleTimer);
    activityIdleTimer = window.setTimeout(() => {
      const later = $('activity-pulse');
      if (later) later.classList.add('idle');
    }, 6000);
  }

  function pushActivity(entry) {
    if (!entry || !entry.text) return;
    const feed = $('activity-feed');
    if (!feed) return;
    const wasAtBottom = !feed.closest('details').open || activityAtBottom(feed);
    activityEntries.push({
      at: entry.at || Date.now(),
      kind: entry.kind || 'info',
      text: String(entry.text),
    });
    activityCount += 1;
    $('activity-count').textContent = plural(activityCount, 'step');
    renderActivityFeed();
    if (wasAtBottom && feed.closest('details').open) {
      feed.scrollTop = feed.scrollHeight;
      renderActivityFeed();
    }
    markActivityFresh();
  }

  function onActivity(entry) {
    pushActivity(entry);
  }

  function onProgress(data) {
    if (data.title) $('install-title').textContent = data.title;
    const operation = data.item || data.task || 'Waiting for the next installation update…';
    currentOperationName = operation;
    const sessionElapsed = Number(data.elapsedMs);
    if (Number.isFinite(sessionElapsed) && sessionElapsed > 0) {
      const impliedStart = Date.now() - sessionElapsed;
      if (!installStartTime || Math.abs(installStartTime - impliedStart) > 2000) {
        installStartTime = impliedStart;
      }
    }
    const quietCandidates = [data.quietForMs, data.lastActivityAgoMs]
      .filter((value) => value !== null && value !== undefined && value !== '')
      .map(Number).filter(Number.isFinite);
    const quiet = quietCandidates.length ? Math.max(...quietCandidates) : -1;
    let statusText = operation;
    if (Number.isFinite(quiet) && quiet >= 90000) {
      statusText = `${operation}. No process output or staged package-file activity for ${formatDuration(quiet)}; the child process is ${data.processRunning === false ? 'stopped' : 'still running'}, and setup is waiting safely.`;
    } else if (Number.isFinite(sessionElapsed) && sessionElapsed > 0) {
      statusText = `${operation} · ${formatDuration(sessionElapsed)} elapsed`;
    }
    $('install-subtask').textContent = statusText;
    $('current-item').textContent = operation;

    const hasActiveTransfer = Boolean(data.bytesTotal && data.bytesTotal > 0);
    const hasSpeed = Boolean(data.speedBytes && data.speedBytes > 0);
    const curPhase = activePhaseId || (state.phases && (state.phases.find((p) => p.status === 'running') || {}).id);

    // 1. Transfer speed
    if (hasActiveTransfer && hasSpeed) {
      $('stat-speed').textContent = `${formatBytes(data.speedBytes)}/s`;
    } else if (hasSpeed) {
      $('stat-speed').textContent = `${formatBytes(data.speedBytes)}/s`;
    } else if (hasActiveTransfer) {
      $('stat-speed').textContent = 'Connecting…';
    } else if (curPhase === 'runtime') {
      $('stat-speed').textContent = 'Installing…';
    } else if (curPhase === 'files' || curPhase === 'python' || curPhase === 'models') {
      $('stat-speed').textContent = 'Processing…';
    } else {
      $('stat-speed').textContent = 'Active';
    }

    // 2. Received
    if (hasActiveTransfer) {
      $('stat-done').textContent = formatBytes(data.bytesDone);
    } else if (data.bytesDone && data.bytesDone > 0) {
      $('stat-done').textContent = formatBytes(data.bytesDone);
    } else if (curPhase === 'runtime') {
      $('stat-done').textContent = 'In progress';
    } else {
      $('stat-done').textContent = 'In progress';
    }

    // 3. Transfer size
    if (hasActiveTransfer) {
      $('stat-total').textContent = formatBytes(data.bytesTotal);
    } else if (curPhase === 'runtime') {
      $('stat-total').textContent = '~2.4 GB';
    } else if (curPhase === 'python') {
      $('stat-total').textContent = '~18 MB';
    } else if (curPhase === 'files') {
      $('stat-total').textContent = '~297 MB';
    } else if (curPhase === 'models') {
      $('stat-total').textContent = '~2.2 GB';
    } else {
      $('stat-total').textContent = '—';
    }

    // 4. Transfer ETA
    const pctForEta = Number(data.percent);
    let etaShown = 'In progress';
    if (Number.isFinite(pctForEta) && pctForEta >= 100) {
      etaShown = 'Done';
    } else if (Number.isFinite(data.etaMs) && data.etaMs > 0) {
      etaShown = formatDuration(data.etaMs);
    } else {
      const phaseInfo = PHASE_LABELS.find((p) => p.id === curPhase);
      if (phaseInfo && phaseInfo.estSeconds) {
        const pElapsed = activePhaseStartedAt ? (Date.now() - activePhaseStartedAt) / 1000 : 0;
        const remainingSec = Math.max(5, Math.round(phaseInfo.estSeconds - pElapsed));
        etaShown = `~${formatDuration(remainingSec * 1000)}`;
      } else {
        etaShown = hasSpeed ? 'Calculating…' : 'In progress';
      }
    }
    $('stat-eta').textContent = etaShown;

    // The engine reports the weighted overall figure as `overall`. It used to be
    // read as `data.percent`, which no progress event ever carried, so pct was
    // always NaN and the readout fell through to showing a word.
    const pct = Number.isFinite(Number(data.overall))
      ? Number(data.overall)
      : Number(data.percent);
    const bar = $('overall-bar');
    const indet = $('overall-indeterminate');
    if (data.determinate === false) {
      // Runtime setup has no honest whole-phase percentage. Keep the last
      // completed-work position, but replace its number with an explicit
      // in-progress label so a long pip operation cannot look frozen at 5%.
      $('overall-percent').textContent = 'Working';
      $('overall-percent').dataset.indeterminate = 'true';
      indet.hidden = false;
      moveBuilder(null);
    } else if (Number.isFinite(pct)) {
      lastKnownPercent = pct;
      $('overall-percent').textContent = `${Math.round(pct)}%`;
      $('overall-percent').dataset.indeterminate = 'false';
      bar.style.width = `${Math.max(0, Math.min(99, pct))}%`;
      indet.hidden = true;
      moveBuilder(Math.max(0, Math.min(99, pct)));
    } else {
      // Genuinely unknown: show motion and the last real figure. Never prose -
      // a percentage readout that says "Working" looks broken.
      $('overall-percent').textContent =
        lastKnownPercent === null ? '—' : `${Math.round(lastKnownPercent)}%`;
      $('overall-percent').dataset.indeterminate = 'true';
      indet.hidden = false;
      moveBuilder(null);
    }
    const aria = $('overall-progress');
    if (aria && data.determinate !== false && Number.isFinite(pct)) {
      if (Number.isFinite(pct)) aria.setAttribute('aria-valuenow', String(Math.max(0, Math.min(99, Math.round(pct)))));
    } else if (aria) aria.removeAttribute('aria-valuenow');
    const builder = $('builder');
    if (builder && !builder.classList.contains('done')) {
      const isAdvancing = (data.speedBytes && data.speedBytes > 0) || (quiet < 5000 && data.processRunning !== false);
      builder.dataset.motion = isAdvancing ? 'run' : 'idle';
      builder.style.opacity = '1';
    }
    setStatus(data.item || 'Installing…');
  }

  // The builder only ever reflects the real percentage - it is never faked.
  let builderAt = -1;
  // Last real overall percentage, so the readout never has to show prose.
  let lastKnownPercent = null;
  function moveBuilder(percent) {
    const el = $('builder');
    const track = $('overall-progress');
    if (!el || !track) return;
    const actualPercent = percent;
    if (percent === null) percent = builderAt >= 0 ? builderAt : 0;
    el.style.opacity = '1';
    const width = track.clientWidth || track.getBoundingClientRect().width;
    if (width <= 0) return;
    const mascotWidth = el.getBoundingClientRect().width || 42;
    const center = Math.max(0, width - mascotWidth) * Math.max(0, Math.min(100, percent)) / 100;
    const safeCenter = Math.max(0, Math.min(width - mascotWidth, center));
    el.style.left = `${safeCenter}px`;
    el.classList.toggle('done', percent >= 99.5);
    if (actualPercent !== null) builderAt = percent;
  }

  function applyTheme(night, persist = false) {
    const isNight = Boolean(night);
    document.body.dataset.theme = isNight ? 'night' : 'forest';
    state.manualNight = isNight;
    const button = $('btn-theme-toggle');
    if (button) {
      const label = isNight ? 'Switch to day' : 'Switch to night';
      button.title = label;
      button.setAttribute('aria-label', label);
      button.setAttribute('aria-pressed', String(isNight));
    }
    if (window.clipifyForestWorld) window.clipifyForestWorld.setTheme(isNight);
    if (persist) {
      try { localStorage.setItem('clipify.installer.theme', isNight ? 'night' : 'forest'); }
      catch { /* Theme remains usable when storage is unavailable. */ }
    }
  }

  function onPhase(data) {
    // The engine reports one phase at a time: { id, status, percent, message }.
    if (!state.phases) resetPhases();
    if (data.status === 'running') {
      activePhaseId = data.id;
      activePhaseStartedAt = Date.now();
    }
    const target = state.phases.find((p) => p.id === data.id);
    if (target) {
      target.status = data.status === 'running' ? 'running' : data.status;
      target.percent = data.percent || 0;
    } else {
      state.phases.push({ id: data.id, label: data.id, status: data.status, percent: data.percent || 0 });
    }
    renderPhaseList();
    if (data.message) $('current-item').textContent = data.message;
    if (data.models) renderModelStatus(data.models);
  }

  function onFailed(data) {
    stopElapsedClock();
    if (state.installTerminal) return;
    state.installTerminal = true;
    state.installBusy = false;
    state.failedPhaseId = data.phaseId || null;
    state.game?.setVisible(false);
    $('install-workspace').hidden = true;
    $('activity-details').hidden = true;
    $('overall-progress').hidden = true;
    document.querySelector('.stat-row').hidden = true;
    $('failure-panel').hidden = false;
    $('failure-message').textContent = friendlyFailure(data.error);
    const builder = $('builder');
    if (builder) builder.dataset.motion = 'error';
    setStatus('Failed');
  }

  function onDone(data) {
    stopElapsedClock();
    if (state.installTerminal) return;
    state.installTerminal = true;
    state.installBusy = false;
    $('error-box').hidden = true;
    $('overall-percent').textContent = '100%';
    $('overall-percent').dataset.indeterminate = 'false';
    $('overall-bar').style.width = '100%';
    $('overall-progress').setAttribute('aria-valuenow', '100');
    $('overall-indeterminate').hidden = true;
    $('install-subtask').textContent = 'Finished.';
    lastKnownPercent = 100;
    builderAt = 100;
    moveBuilder(100);
    const builder = $('builder');
    if (builder) builder.dataset.motion = 'celebrate';
    $('done-location').textContent = `Installed to ${data.installDir}`;
    $('done-models').innerHTML = (data.models || data.installedModels || [])
      .map((m) => `<span class="pill">${escapeHtml(m)}</span>`)
      .join('');
    const doneDetails = [];
    const installedBytes = Number(data.installedBytes);
    if (Number.isFinite(installedBytes) && installedBytes >= 0) {
      doneDetails.push('<span class="pill">Application and runtime files: ' + escapeHtml(formatBytes(installedBytes)) + '</span>');
    }
    if (data.userDataKept) doneDetails.push('<span class="pill">Your projects and models are kept</span>');
    $('done-meta').innerHTML = doneDetails.join('');
    // Music is a setup-time luxury: the staged tracks are deleted now.
    music.stopAndRelease();
    $('music').hidden = true;
    state.game?.setVisible(false);
    state.game?.stop();
    show('done');
    setStatus('Setup complete');
  }

  function onCancelled(data = {}) {
    if (state.installTerminal) return;
    state.installTerminal = true;
    state.installBusy = false;
    state.failedPhaseId = data.phaseId || null;
    state.game?.setVisible(false);
    $('install-workspace').hidden = true;
    $('overall-progress').hidden = true;
    document.querySelector('.stat-row').hidden = true;
    $('failure-title').textContent = 'Installation paused safely';
    $('failure-message').textContent = 'Setup was cancelled before it finished. You can retry to check completed work and continue.';
    const builder = $('builder');
    if (builder) builder.dataset.motion = 'idle';
    $('failure-panel').hidden = false;
    setStatus('Cancelled');
  }

  function friendlyFailure(message) {
    const detail = String(message || 'Clipify AI could not finish installing.');
    if (/EPERM|EACCES|EBUSY|sharing violation|access is denied|operation not permitted/i.test(detail)) {
      return 'Windows could not update a setup file because it is in use. Close any Clipify AI or Python windows, then retry. The previous runtime has been preserved.';
    }
    if (/python engine|python311|python\.exe/i.test(detail)) {
      return 'Setup could not prepare its Python engine. Retry setup or open the setup log to see the validation detail.';
    }
    if (/ENOSPC|not enough space|disk space/i.test(detail)) {
      return 'There is not enough free space to complete setup. Choose a drive with more room, then retry.';
    }
    if (/download|network|ENOTFOUND|ECONN|timed out|timeout/i.test(detail)) {
      return 'A required download did not finish. Check your connection, then retry setup.';
    }
    if (/AI runtime|pip|python engine|python311|import verification/i.test(detail)) {
      return 'The local AI runtime did not pass its readiness checks. The previous runtime was kept; retry setup or open the setup log for details.';
    }
    if (/ollama|selected local AI model/i.test(detail)) {
      return 'The local AI engine or a selected model could not be verified. Retry setup or open the setup log for details.';
    }
    return detail.replace(/\s+/g, ' ').slice(0, 360);
  }

  // --------------------------------------------- pre-download warning popup

  let pendingInstall = null;

  function openDownloadWarning(options) {
    pendingInstall = options;
    const popup = $('download-warning');
    const warning = window.ClipifyDownloadWarning.buildDownloadWarning(state.detection, options);
    $('warn-title').textContent = warning.title;
    $('warn-body').textContent = warning.body;
    $('warn-estimate').textContent = warning.estimate;
    const points = $('warn-points');
    points.replaceChildren();
    for (const detail of warning.details) {
      const item = document.createElement('li');
      const icon = document.createElement('span');
      icon.className = 'popup-ico';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = '\u2193';
      const text = document.createElement('span');
      text.textContent = detail;
      item.append(icon, text);
      points.appendChild(item);
    }
    points.style.display = warning.details.length ? '' : 'none';
    if (!popup) {
      // No popup in the DOM should never be a reason not to install.
      startInstall(options);
      return;
    }
    popup.hidden = false;
    window.setTimeout(() => $('btn-warn-go').focus(), 60);
  }

  function closeDownloadWarning() {
    const popup = $('download-warning');
    if (popup) popup.hidden = true;
    pendingInstall = null;
  }

  async function startInstall(options) {
    if (state.installBusy) return;
    state.installBusy = true;
    state.installTerminal = false;
    state.installOptions = { ...options, models: [...(options.models || [])] };
    state.failedPhaseId = null;
    closeDownloadWarning();
    $('install-workspace').hidden = false;
    $('activity-details').hidden = false;
    $('overall-progress').hidden = false;
    document.querySelector('.stat-row').hidden = false;
    $('failure-panel').hidden = true;
    $('error-box').hidden = true;
    $('btn-retry').hidden = true;
    $('overall-percent').textContent = '0%';
    $('overall-bar').style.width = '0%';
    $('overall-progress').setAttribute('aria-valuenow', '0');
    $('overall-indeterminate').hidden = true;
    lastKnownPercent = 0;
    builderAt = 0;
    $('current-item').textContent = '—';
    $('stat-done').textContent = '0 B';
    $('stat-total').textContent = '0 B';
    $('stat-speed').textContent = '—';
    $('stat-eta').textContent = '—';
    renderModelStatus((options.models || []).map((id) => {
      const model = state.detection.models.find((m) => m.id === id);
      return { name: model ? model.name : id, status: 'pending', progress: 0 };
    }));
    resetPhases();
    renderPhaseList();
    resetActivity();
    markActivityFresh();

    // Move to the progress screen BEFORE starting work, so a fast failure is
    // still reported on the installing screen rather than on the form.
    show('install');
    installStartTime = Date.now();
    startElapsedClock();
    initGame();
    setStatus('Installing…');

    try {
      await api.start(options);
    } catch (error) {
      onFailed({ error: error.message, phaseId: null });
    }
  }

  // --------------------------------------------------------------- game

  function initGame() {
    if (state.game || !window.ClipifyForestGame) return;
    state.game = new window.ClipifyForestGame.Game(
      $('forest-game'), $('game-score'), $('game-best'), $('game-state'), paintGameControls
    );
    state.game.setVisible(true);
    state.game.start();

    if (state.game && typeof state.game.syncHud === 'function') {
      state.game.syncHud();
    }

    // Mirror the sr-only score/best text into the visible HUD elements.
    // The Game constructor writes to #game-score and #game-best (sr-only spans).
    // A MutationObserver picks up each change and copies it to the HUD.
    const scoreVis = document.getElementById('game-score-vis');
    const bestVis  = document.getElementById('game-best-vis');
    const scoreEl = document.getElementById('game-score');
    const bestEl  = document.getElementById('game-best');
    if (bestEl && bestVis) bestVis.textContent = bestEl.textContent || '0';
    if (scoreEl && scoreVis) scoreVis.textContent = scoreEl.textContent || '0';
    if (scoreVis || bestVis) {
      const mo = new MutationObserver((mutations) => {
        for (const m of mutations) {
          if (m.target === scoreEl && scoreVis) scoreVis.textContent = scoreEl.textContent;
          if (m.target === bestEl  && bestVis)  bestVis.textContent  = bestEl.textContent;
        }
      });
      if (scoreEl) mo.observe(scoreEl, { childList: true, characterData: true, subtree: true });
      if (bestEl)  mo.observe(bestEl,  { childList: true, characterData: true, subtree: true });
    }
    $('btn-game-toggle').addEventListener('click', () => {
      continueGame();
    });
    // Do not burn CPU while the installer is in the background.
    window.addEventListener('blur', () => {
      if (state.game) state.game.pause();
    });
  }

  function paintGameControls(gameState) {
    const toggle = $('btn-game-toggle');
    if (!toggle) return;
    if (gameState === 'gameover') {
      toggle.textContent = 'Play Again';
      toggle.setAttribute('aria-label', 'Play game again');
    } else {
      const canPause = gameState === 'playing';
      toggle.textContent = canPause ? 'Pause' : 'Continue';
      toggle.setAttribute('aria-label', canPause ? 'Pause game' : 'Continue game');
    }
  }

  function continueGame() {
    if (!state.game) return;
    if (state.game.state === 'playing') state.game.pause();
    else if (state.game.state === 'paused') state.game.resume();
    else if (state.game.state === 'gameover') state.game.restart();
    else state.game.start();
  }

  // --------------------------------------------------------------- wire

  function attachRipples() {
    document.addEventListener('pointerdown', (event) => {
      const button = event.target.closest('.btn, .model-card');
      if (!button) return;
      const rect = button.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      const ripple = document.createElement('span');
      ripple.className = 'ripple';
      ripple.style.width = ripple.style.height = `${size}px`;
      ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
      ripple.style.top = `${event.clientY - rect.top - size / 2}px`;
      button.appendChild(ripple);
      window.setTimeout(() => ripple.remove(), 620);
    });
  }

  function wire() {
    $('btn-theme-toggle').addEventListener('click', () => {
      applyTheme(document.body.dataset.theme !== 'night', true);
    });
    window.addEventListener('resize', () => {
      if (lastKnownPercent !== null) moveBuilder(lastKnownPercent);
    }, { passive: true });
    const activityFeed = $('activity-feed');
    activityFeed.addEventListener('scroll', queueActivityRender, { passive: true });
    $('activity-details').addEventListener('toggle', () => {
      if ($('activity-details').open) {
        renderActivityFeed();
        activityFeed.scrollTop = activityFeed.scrollHeight;
        renderActivityFeed();
      }
    });
    $('activity-latest').addEventListener('click', () => {
      activityFeed.scrollTop = activityFeed.scrollHeight;
      renderActivityFeed();
      activityFeed.focus({ preventScroll: true });
    });
    document.addEventListener('visibilitychange', () => {
      document.body.dataset.inactive = document.hidden ? 'true' : 'false';
      if (document.hidden && state.game) state.game.pause();
    });
    $('btn-minimize').addEventListener('click', () => api.window('minimize'));
    $('btn-close').addEventListener('click', () => api.window('close'));

    $('btn-get-started').addEventListener('click', async () => {
      if (state.navigationBusy) return;
      state.navigationBusy = true;
      $('btn-get-started').disabled = true;
      try {
      const detection = await loadDetection(undefined, [...state.selected]);
      // On the FIRST visit only, tick the recommended model so the common case
      // is one click. After that the user's choices stand, including an empty
      // selection - coming back must never re-tick anything.
      if (!state.defaultsApplied) {
        state.defaultsApplied = true;
        state.selected = api.qa ? new Set() : new Set([detection.recommendedModelId]);
      }
      renderModels(detection);
      renderDetail(detection.models.find((m) => m.id === state.focusModel));
      show('models');
      } catch (error) {
        $('welcome-detect').textContent = `Could not read model options: ${error.message}`;
      } finally {
        state.navigationBusy = false;
        $('btn-get-started').disabled = false;
      }
    });

    $('btn-models-back').addEventListener('click', () => show('welcome'));
    $('btn-models-continue').addEventListener('click', async () => {
      if (state.navigationBusy) return;
      state.navigationBusy = true;
      $('btn-models-continue').disabled = true;
      $('btn-models-back').disabled = true;
      $('model-grid').inert = true;
      $('model-grid').setAttribute('aria-busy', 'true');
      try {
        const detection = await loadDetection(undefined, [...state.selected]);
        await renderLocation(detection);
        show('location');
      } catch (error) {
        setStatus(`Could not prepare install location: ${error.message}`);
      } finally {
        state.navigationBusy = false;
        $('btn-models-continue').disabled = false;
        $('btn-models-back').disabled = false;
        $('model-grid').inert = false;
        $('model-grid').removeAttribute('aria-busy');
      }
    });

    $('btn-loc-back').addEventListener('click', () => show('models'));

    $('btn-browse').addEventListener('click', async () => {
      const chosen = await api.browse();
      // Cancelling must be a complete no-op: no path change, no navigation.
      if (chosen) {
        state.userPath = chosen;
        $('input-path').value = chosen;
        await refreshDisk();
      }
    });

    $('btn-browse-models').addEventListener('click', async () => {
      const chosen = await api.browse();
      if (chosen) {
        state.userModelsDir = chosen;
        $('input-models-dir').value = chosen;
        // Validate the chosen directory.
        const warning = $('models-dir-warning');
        const warningText = $('models-dir-warning-text');
        try {
          // Warn if the path is on a different drive to the install dir.
          const installDrive = ($('input-path').value.trim().match(/^([A-Za-z]:)/) || [])[1] || '';
          const modelsDrive = (chosen.match(/^([A-Za-z]:)/) || [])[1] || '';
          if (installDrive && modelsDrive && installDrive.toUpperCase() !== modelsDrive.toUpperCase()) {
            warningText.textContent = `Model storage is on a different drive (${modelsDrive}) than the installation (${installDrive}). This is fine — Ollama will find them via the OLLAMA_MODELS environment variable.`;
            warning.className = 'notice notice-warn';
            warning.hidden = false;
          } else {
            warning.hidden = true;
          }
        } catch {
          warning.hidden = true;
        }
      }
    });

    let diskTimer = 0;
    $('input-path').addEventListener('input', () => {
      // Debounced: validating per keystroke would fire a dozen IPC round trips
      // while a path is being typed.
      state.diskRequest += 1;
      $('btn-install').disabled = true;
      setStatus('Validating location…');
      window.clearTimeout(diskTimer);
      diskTimer = window.setTimeout(() => {
        state.userPath = $('input-path').value.trim();
        refreshDisk();
      }, 260);
    });
    $('input-path').addEventListener('change', () => {
      window.clearTimeout(diskTimer);
      state.userPath = $('input-path').value.trim();
      refreshDisk();
    });
    $('chk-runtime').addEventListener('change', refreshDisk);
    $('chk-ollama').addEventListener('change', refreshDisk);
    $('chk-desktop').addEventListener('change', () => {});
    // Keep models-dir state in sync when the user edits the field directly.
    $('input-models-dir').addEventListener('change', () => {
      state.userModelsDir = $('input-models-dir').value.trim() || null;
    });

    $('btn-install').addEventListener('click', () => {
      if (state.navigationBusy || !$('download-warning').hidden) return;
      state.navigationBusy = true;
      $('btn-install').disabled = true;
      const installDir = $('input-path').value.trim();
      const selected = [...state.selected];
      const detectionOptions = userOptions();
      const signature = JSON.stringify({ installDir, selected, detectionOptions });
      const request = ++state.diskRequest;
      setStatus('Checking the selected location…');
      (async () => {
        try {
          const detection = await loadDetection(installDir, selected, detectionOptions);
          const currentSignature = JSON.stringify({
            installDir: $('input-path').value.trim(),
            selected: [...state.selected],
            detectionOptions: userOptions(),
          });
          if (request !== state.diskRequest || signature !== currentSignature) return;
          state.detection = detection;
          renderDisk(detection);
          if ($('btn-install').disabled) return;
          openDownloadWarning({
            installDir,
            models: selected,
            installRuntime: detectionOptions.installRuntime,
            installOllama: detectionOptions.installOllama,
            createDesktopShortcut: $('chk-desktop').checked,
            createStartMenuShortcut: !api.qa,
            modelsDir: state.userModelsDir || undefined,
          });
        } catch (error) {
          if (request !== state.diskRequest) return;
          state.detection = null;
          $('btn-install').disabled = true;
          $('space-warning').hidden = false;
          $('space-warning-text').textContent = `Could not check the selected location: ${error.message}`;
          setStatus('Could not validate this location');
        } finally {
          state.navigationBusy = false;
          if (request === state.diskRequest && state.detection) renderDisk(state.detection);
        }
      })();
    });

    $('btn-cancel').addEventListener('click', () => api.cancel());
    $('btn-retry').addEventListener('click', () => retryInstall());
    $('btn-failure-retry').addEventListener('click', () => retryInstall());
    $('btn-view-log').addEventListener('click', async () => {
      const result = await api.openLog();
      if (result && result.ok === false) $('failure-message').textContent = result.error || 'The setup log could not be opened.';
    });
    $('btn-failure-close').addEventListener('click', () => api.quit());
    $('btn-close-installer').addEventListener('click', () => api.quit());

    $('btn-launch').addEventListener('click', async () => {
      $('launch-error').hidden = true;
      const result = await api.launch();
      if (!result || result.ok === false) {
        $('launch-error').textContent = result?.error || 'Clipify AI could not be launched. Open the installation folder or setup log for help.';
        $('launch-error').hidden = false;
      }
    });
    $('btn-open-folder').addEventListener('click', () => api.openFolder());

    $('btn-music-play').addEventListener('click', () => music.togglePlay());
    $('btn-music-mute').addEventListener('click', () => music.toggleMute());
    $('btn-music-next').addEventListener('click', () => music.next());
    $('btn-music-prev').addEventListener('click', () => music.prev());
    // Seek is driven by the range input itself; scrubbing is held so the
    // timeupdate handler does not fight the user's drag.
    const seek = $('music-seek');
    if (seek) {
      seek.addEventListener('pointerdown', () => { music.seeking = true; });
      seek.addEventListener('input', () => music.seekTo(Number(seek.value) / 1000));
      const release = () => { music.seeking = false; };
      seek.addEventListener('pointerup', release);
      seek.addEventListener('change', () => { music.seekTo(Number(seek.value) / 1000); release(); });
      seek.addEventListener('pointercancel', release);
    }
    // The compact player has no separate volume slider; muting controls level.
    $('btn-github').addEventListener('click', () => api.openExternal('https://github.com/sherlock-dev-ai'));

    // --- pre-download warning popup ---------------------------------------
    $('btn-warn-go').addEventListener('click', () => {
      if (pendingInstall) startInstall(pendingInstall);
    });
    $('btn-warn-back').addEventListener('click', closeDownloadWarning);
    $('warn-scrim').addEventListener('click', closeDownloadWarning);
    document.addEventListener('keydown', (event) => {
      if ($('download-warning').hidden) return;
      // Escape backs out without starting anything.
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDownloadWarning();
      }
    });

    api.on('activity', onActivity);
    api.on('progress', onProgress);
    api.on('phase', onPhase);
    api.on('done', onDone);
    api.on('failed', onFailed);
    api.on('cancelled', onCancelled);
  }

  async function retryInstall() {
    if (state.installBusy || !state.installOptions) return;
    const options = state.installOptions;
    state.installBusy = true;
    state.installTerminal = false;
    $('failure-panel').hidden = true;
    $('install-workspace').hidden = false;
    $('activity-details').hidden = false;
    $('overall-progress').hidden = false;
    document.querySelector('.stat-row').hidden = false;
    setStatus('Checking completed work…');
    state.game?.setVisible(true);
    if (state.game && state.game.state !== 'playing') continueGame();
    try {
      await api.retry(state.failedPhaseId, options);
    } catch (error) {
      onFailed({ error: error.message, phaseId: state.failedPhaseId });
    }
  }

  // --------------------------------------------------------------- boot

  function verifyCustomUi() {
    const requiredIds = [
      'screen-welcome', 'screen-models', 'screen-location', 'screen-install', 'screen-done',
      'btn-get-started', 'model-grid', 'btn-models-continue', 'btn-install', 'install-workspace',
      'game-workspace', 'forest-game',
      'forest-art', 'forest-world', 'overall-progress', 'builder', 'install-subtask',
      'btn-theme-toggle', 'btn-game-toggle', 'game-state',
    ];
    const missing = requiredIds.filter((id) => !document.getElementById(id));
    if (!document.querySelector('.forest-backdrop')) missing.push('forest-backdrop');
    if (missing.length) throw new Error(`Required custom installer UI elements are missing: ${missing.join(', ')}`);
    if (!api || typeof api.rendererReady !== 'function' || typeof api.rendererError !== 'function') {
      throw new Error('The secure installer preload bridge did not initialize.');
    }
    if (!window.ClipifyForestGame || typeof window.ClipifyForestGame.Game !== 'function') {
      throw new Error('The optional forest game module did not initialize.');
    }
    if (!window.clipifyForestWorld || typeof window.clipifyForestWorld.setTheme !== 'function') {
      throw new Error('The persistent forest world module did not initialize.');
    }
    if (!window.ClipifyDownloadWarning || typeof window.ClipifyDownloadWarning.buildDownloadWarning !== 'function') {
      throw new Error('The model-selection download-warning module did not initialize.');
    }
  }

  async function boot() {
    verifyCustomUi();
    let savedTheme = 'forest';
    try { savedTheme = localStorage.getItem('clipify.installer.theme') || 'forest'; }
    catch { /* Use the default daytime forest when storage is unavailable. */ }
    applyTheme(savedTheme === 'night');
    attachRipples();
    wire();
    show('welcome');
    if (api.qa) {
      $('chk-runtime').checked = false;
      $('chk-ollama').checked = false;
    }
    try {
      const musicTracks = await api.musicTracks().catch(() => ({ tracks: [] }));
      music.init(musicTracks);
    } catch {
      music.init({ tracks: [] });
    }
    try {
      const detection = await loadDetection();
      renderWelcome(detection);
    } catch (error) {
      $('welcome-detect').textContent = `Detection failed: ${error.message}`;
    }
  }

  function reportRendererFailure(error) {
    const message = error && (error.stack || error.message) ? (error.stack || error.message) : String(error);
    if (api && typeof api.rendererError === 'function') {
      api.rendererError(message).catch(() => {});
    }
  }

  window.addEventListener('error', (event) => {
    reportRendererFailure(event.error || event.message || 'Uncaught renderer error');
  });
  window.addEventListener('unhandledrejection', (event) => {
    reportRendererFailure(event.reason || 'Unhandled renderer promise rejection');
  });

  document.addEventListener('DOMContentLoaded', async () => {
    try {
      await boot();
      const ready = await api.rendererReady();
      if (!ready) throw new Error('The main process rejected the renderer startup signal.');
    } catch (error) {
      reportRendererFailure(error);
    }
  });
})();
