const state = window.state = { jobId: null, mode: 'viral', source: null, logoFile: null, logoPath: null, logoServerPath: null, es: null, model: null, modelsAvailable: false, font: 'Montserrat Extra Bold', outputs: [], currentOutputIndex: 0, drag: null, reviewFile: null, editorLogoFile: null, editorLogoPath: null, youtubePoll: null, sourcePreviewUrl: null };
const $ = s => document.querySelector(s); const $$ = s => [...document.querySelectorAll(s)];

async function safeJson(response, fallbackMsg = 'Server response error') {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch (err) {
    let msg = fallbackMsg;
    try {
      const doc = new DOMParser().parseFromString(text, 'text/html');
      msg = doc.querySelector('title, h1, p')?.textContent?.trim() || fallbackMsg;
    } catch (_) { }
    throw new Error(msg);
  }
}
const editorDownloads = () => ['#reviewDownload', '#reviewDownloadMain'].map($).filter(Boolean);
const editorApplyButtons = () => ['#applyEditorBranding', '#applyEditorBrandingMain'].map($).filter(Boolean);
const reviewPlayer = window.ClipifyReviewPlayer?.attach($('#reviewVideo'), $('#reviewVideoStatus'), $('#reviewVideoSpinner'), $('#reviewVideoStatusText'));
const input = $('#videoInput'), drop = $('#dropzone'), create = $('#createBtn'), chip = $('#fileChip'), nameEl = $('#fileName'), sizeEl = $('#fileSize'), progressPanel = $('#progressPanel'), results = $('#results'), grid = $('#resultGrid'), log = $('#log'), modelSelect = $('#modelSelect'), refreshModelsBtn = $('#refreshModelsBtn'), scanModelsBtn = $('#scanModelsBtn'), fontSelect = $('#fontSelect'), minDuration = $('#minDuration'), maxDuration = $('#maxDuration'), youtubeUrl = $('#youtubeUrl'), youtubeImport = $('#youtubeImport'), youtubeStatus = $('#youtubeStatus');
const positions = ['top-left', 'top-center', 'top-right', 'center-left', 'center', 'center-right', 'bottom-left', 'bottom-center', 'bottom-right', 'custom'];

function startTypewriter() {
  const lead = $('#typewriterLead');
  const focus = $('#typewriterFocus');
  if (!lead || !focus) return;
  const leadText = 'From long-form video to a ';
  const phrases = [
    'Short worth watching.',
    'viral TikTok hook.',
    'high-retention 9:16 cut.',
    'trending YouTube Short.'
  ];
  let phraseIdx = 0;
  let focusText = phrases[phraseIdx];
  let index = 0;
  let phase = 'typingLead';

  // Clear initially so typing starts from scratch cleanly without ghost text
  lead.textContent = '';
  focus.textContent = '';

  const tick = () => {
    if (phase === 'typingLead') {
      lead.textContent = leadText.slice(0, ++index);
      if (index >= leadText.length) {
        index = 0;
        phase = 'typingFocus';
        return setTimeout(tick, 180);
      }
      return setTimeout(tick, 48);
    }
    if (phase === 'typingFocus') {
      focus.textContent = focusText.slice(0, ++index);
      if (index >= focusText.length) {
        phase = 'pause';
        return setTimeout(tick, 2400);
      }
      return setTimeout(tick, 58);
    }
    if (phase === 'pause') {
      phase = 'erasingFocus';
      index = focusText.length;
      return tick();
    }
    if (phase === 'erasingFocus') {
      focus.textContent = focusText.slice(0, --index);
      if (index <= 0) {
        phraseIdx = (phraseIdx + 1) % phrases.length;
        focusText = phrases[phraseIdx];
        index = 0;
        phase = 'typingFocus';
        return setTimeout(tick, 350);
      }
      return setTimeout(tick, 32);
    }
  };
  setTimeout(tick, 350);
}

startTypewriter();

modelSelect?.addEventListener('change', () => { state.model = modelSelect.value });

refreshModelsBtn?.addEventListener('click', async () => {
  try {
    if (refreshModelsBtn) {
      refreshModelsBtn.disabled = true;
      refreshModelsBtn.textContent = '…';
    }
    // Deep PC scan & auto-recover unmounted or offline Ollama models
    try {
      await fetch('/api/models/scan', { method: 'POST', cache: 'no-store' });
    } catch (_) {}
    await loadOptions();
    if (window.refreshModelHub) {
      await window.refreshModelHub();
    }
  } finally {
    if (refreshModelsBtn) {
      refreshModelsBtn.disabled = false;
      refreshModelsBtn.textContent = '↻';
    }
  }
});

scanModelsBtn?.addEventListener('click', async () => {
  if (scanModelsBtn) {
    scanModelsBtn.disabled = true;
    scanModelsBtn.textContent = '🔍 Searching PC…';
  }
  try {
    const res = await fetch('/api/models/scan', { method: 'POST' });
    const data = await safeJson(res, 'PC scan failed.');
    if (data.ok && data.models && data.models.length) {
      await loadOptions();
      if (scanModelsBtn) scanModelsBtn.style.display = 'none';
    } else {
      alert(data.error || 'No Ollama models found during PC scan. Please make sure models were downloaded.');
    }
  } catch (err) {
    alert('PC scan failed: ' + err.message);
  } finally {
    if (scanModelsBtn) {
      scanModelsBtn.disabled = false;
      scanModelsBtn.textContent = '🔍 Search PC';
    }
  }
});

async function refreshModelOptions() {
  if (refreshModelsBtn) {
    refreshModelsBtn.disabled = true;
    refreshModelsBtn.textContent = '…';
  }

  try {
    await loadOptions();
  } finally {
    if (refreshModelsBtn) {
      refreshModelsBtn.disabled = false;
      refreshModelsBtn.textContent = '↻';
    }
  }
}

function formatBytes(n) {
  if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < 3) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}

function setFile(file) {
  state.jobId = null;
  state.source = file;
  nameEl.textContent = file.name;
  sizeEl.textContent = formatBytes(file.size);
  chip.hidden = false;
  create.disabled = false;
  if (youtubeStatus) youtubeStatus.textContent = '';
  const url = URL.createObjectURL(file);
  const preview = $('#sourcePreview');
  // Assigning src is not enough: the element was hidden while the file was
  // being read, and Chromium leaves a blob-backed <video> parked in
  // NETWORK_LOADING (readyState 0) so the preview box stays empty. load()
  // restarts the fetch and lets the poster render.
  if (state.sourcePreviewUrl) URL.revokeObjectURL(state.sourcePreviewUrl);
  state.sourcePreviewUrl = url;
  preview.src = url;
  preview.load();
  preview.hidden = false;
  $('.preview-placeholder').style.display = 'none';
  $('#previewMeta').textContent = `${file.name} · ${formatBytes(file.size)}`
}

input?.addEventListener('change', e => e.target.files[0] && setFile(e.target.files[0]));

['dragenter', 'dragover'].forEach(x => drop?.addEventListener(x, e => {
  e.preventDefault();
  drop.classList.add('drag')
}));

['dragleave', 'drop'].forEach(x => drop?.addEventListener(x, e => {
  e.preventDefault();
  drop.classList.remove('drag')
}));

drop?.addEventListener('drop', e => {
  const f = e.dataTransfer.files[0];
  if (f && (f.type.startsWith('video/') || /\.(mp4|mov|mkv|webm|avi|m4v|ts|flv)$/i.test(f.name))) {
    setFile(f);
  }
});

async function importYouTube() {
  sanitizeYouTubeInput(youtubeUrl);
  const url = youtubeUrl.value.trim();

  if (!url || (url.includes('@') && !url.includes('youtube.com') && !url.includes('youtu.be'))) {
    youtubeUrl.value = '';
    youtubeStatus.textContent = 'Paste a valid YouTube video link first.';
    return;
  }

  youtubeImport.disabled = true;
  youtubeImport.textContent = 'Connecting…';
  youtubeStatus.textContent = 'Connecting to YouTube…';

  const track = $('#youtubeProgress');
  const bar = $('#youtubeProgressBar');

  if (track) track.hidden = false;
  if (bar) bar.style.width = '0%';

  try {
    const r = await fetch('/api/import-youtube', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });

    const d = await safeJson(r, 'Could not start YouTube import.');

    if (!r.ok) throw Error(d.error || 'Could not start YouTube import.');

    state.jobId = d.job_id || state.jobId;
    state.source = null;
    chip.hidden = true;
    create.disabled = true;

    youtubeImport.textContent = 'Downloading…';

    await waitForYouTubeDownload(d.job_id);

  } catch (error) {

    if (state.youtubePoll) clearInterval(state.youtubePoll);
    state.youtubePoll = null;

    youtubeStatus.textContent = error.message;
    youtubeImport.disabled = false;
    youtubeImport.textContent = 'Import video';

    if (track) track.hidden = true;
  }
}

async function waitForYouTubeDownload(jobId) {

  const track = $('#youtubeProgress');
  const bar = $('#youtubeProgressBar');

  let finished = false;

  const tick = async () => {

    try {

      const r = await fetch(`/api/status/${jobId}`, { cache: 'no-store' });
      const d = await safeJson(r, 'Could not read YouTube download status.');

      if (!r.ok) throw Error(d.error || 'Could not read YouTube download status.');

      const pct = Math.max(
        0,
        Math.min(100, Number(d.progress) || 0)
      );

      if (bar) bar.style.width = pct + '%';

      youtubeStatus.textContent =
        `${pct}% · ${d.detail || d.stage || 'Downloading video…'}`;

      if (d.status === 'uploaded') {

        finished = true;

        if (state.youtubePoll) clearInterval(state.youtubePoll);
        state.youtubePoll = null;

        state.jobId = jobId;
        state.source = {
          name: d.filename,
          size: 0,
          origin: 'youtube',
          jobId: jobId
        };

        nameEl.textContent = d.filename;
        sizeEl.textContent = 'Downloaded locally';
        chip.hidden = false;

        // Immediately show the downloaded YouTube video in the main preview frame
        const mediaUrl = `/project-media/${encodeURIComponent(jobId)}/input/${encodeURIComponent(d.filename)}`;
        const preview = $('#sourcePreview');
        if (preview) {
          preview.src = mediaUrl;
          preview.load();
          preview.hidden = false;
        }
        const placeholder = $('.preview-placeholder');
        if (placeholder) placeholder.style.display = 'none';
        const meta = $('#previewMeta');
        if (meta) meta.textContent = `${d.filename} · Downloaded from YouTube`;

        youtubeStatus.textContent =
          '100% · Download complete. Video ready.';

        youtubeImport.disabled = false;
        youtubeImport.textContent = 'Import video';

        // Keep Beta Testing Lab in sync with downloaded YouTube video
        if (typeof betaState !== 'undefined') {
          betaState.jobId = jobId;
          betaState.sourceFile = null;
          betaState.downloading = false;
          const bDrop = $('#betaDropZone');
          const bInfo = $('#betaSourceInfo');
          const bName = $('#betaSourceName');
          const bMeta = $('#betaSourceMeta');
          const bRun = $('#betaRunPipelineBtn');
          if (bDrop) bDrop.style.display = 'none';
          if (bInfo) bInfo.style.display = 'flex';
          if (bName) bName.textContent = d.filename;
          if (bMeta) bMeta.textContent = `Project ${jobId} · Ready to Clip`;
          if (bRun) { bRun.disabled = false; bRun.textContent = '⚡ Run Beta AI Pipeline'; }
          const bVideo = $('#betaResultVideo');
          const bPlaceholder = $('#betaPlaceholder');
          if (bVideo) {
            bVideo.src = mediaUrl;
            bVideo.load();
            bVideo.style.display = 'block';
            if (bPlaceholder) bPlaceholder.style.display = 'none';
            bVideo.onloadedmetadata = () => {
              const dur = Math.round(bVideo.duration || 0);
              const scrubber = $('#betaScrubberTimeline');
              if (scrubber) scrubber.style.display = 'block';
              const bEnd = $('#betaTextEnd');
              if (bEnd) bEnd.value = dur.toFixed(1);
            };
          }
        }

        if (!state.modelsAvailable) {
          try { await loadOptions(); } catch { }
        }

        create.disabled = false;

        if (track) track.hidden = true;

      } else if (d.status === 'error') {

        finished = true;

        if (state.youtubePoll) clearInterval(state.youtubePoll);
        state.youtubePoll = null;

        throw Error(
          d.error ||
          d.detail ||
          'YouTube download failed.'
        );
      }

    } catch (error) {

      if (state.youtubePoll) clearInterval(state.youtubePoll);
      state.youtubePoll = null;

      youtubeImport.disabled = false;
      youtubeImport.textContent = 'Import video';
      youtubeStatus.textContent = error.message;

      if (track) track.hidden = true;

      state.jobId = null;
      state.source = null;
      create.disabled = true;
    }

    if (finished) return;
  };

  await tick();

  if (finished) return;

  state.youtubePoll = setInterval(tick, 500);
}

youtubeImport?.addEventListener(
  'click',
  importYouTube
);

youtubeUrl?.addEventListener(
  'keydown',
  event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      importYouTube();
    }
  }
);

youtubeUrl?.addEventListener(
  'paste',
  event => {
    setTimeout(() => {
      const val = (youtubeUrl.value || '').trim();
      if (val.includes('youtube.com/') || val.includes('youtu.be/')) {
        importYouTube();
      }
    }, 50);
  }
);

// Prevent browser password/email autofill from injecting credentials into YouTube link inputs
function sanitizeYouTubeInput(inputEl) {
  if (!inputEl) return;
  const v = (inputEl.value || '').trim();
  if (v && v.includes('@') && !v.includes('youtube.com') && !v.includes('youtu.be')) {
    inputEl.value = '';
  }
}

['DOMContentLoaded', 'load'].forEach(ev => {
  window.addEventListener(ev, () => {
    [10, 80, 200, 500, 1000, 2000].forEach(delay => {
      setTimeout(() => {
        sanitizeYouTubeInput(youtubeUrl);
        const betaYt = $('#betaYtUrl');
        if (betaYt) sanitizeYouTubeInput(betaYt);
      }, delay);
    });
  });
});

[youtubeUrl, $('#betaYtUrl')].forEach(el => {
  if (!el) return;
  ['input', 'change', 'focus', 'animationstart'].forEach(ev => {
    el.addEventListener(ev, () => sanitizeYouTubeInput(el));
  });
});

$$('.mode-card').forEach(btn =>
  btn.addEventListener('click', () => {
    $$('.mode-card').forEach(x =>
      x.classList.remove('selected')
    );

    btn.classList.add('selected');
    state.mode = btn.dataset.mode;
  })
);

function syncDuration() {

  let min = +minDuration.value;
  let max = +maxDuration.value;

  if (min > max) {
    max = min;
    maxDuration.value = max;
  }

  $('#durationNote').textContent =
    `Recommended: ${min}–${max} seconds. Qwen can refine boundaries inside candidates.`;
}

minDuration?.addEventListener('change', syncDuration);
maxDuration?.addEventListener('change', syncDuration);
if (minDuration && maxDuration) syncDuration();

function syncRange(id, out, callback) {

  const el = $('#' + id);
  const o = $('#' + out);
  if (!el || !o) return;

  const f = () => {
    o.textContent = el.value + '%';
    if (callback) callback();
    else updatePreview();
  };

  el.addEventListener('input', f);
  f();
}

syncRange('logoSize', 'logoSizeOut');
syncRange('logoOpacity', 'logoOpacityOut');
syncRange('editorLogoSize', 'editorLogoSizeOut', editorPreviewUpdate);
syncRange('editorLogoOpacity', 'editorLogoOpacityOut', editorPreviewUpdate);
syncRange('textBgOpacity', 'textBgOpacityOut');

function updateUpscaleQualityBadge() {
  const sel = $('#upscaleQuality');
  const badge = $('#upscaleQualityBadge');
  if (!sel || !badge) return;
  const val = sel.value;
  if (val === 'ultra') {
    badge.textContent = 'Ultra HD (Crisp)';
    badge.style.background = '#a855f7';
    badge.style.color = '#ffffff';
  } else if (val === 'high') {
    badge.textContent = 'High (Recommended)';
    badge.style.background = '#4ade80';
    badge.style.color = '#041527';
  } else if (val === 'balanced') {
    badge.textContent = 'Balanced (1080p)';
    badge.style.background = '#38bdf8';
    badge.style.color = '#041527';
  } else if (val === 'fast') {
    badge.textContent = 'Fast (Compact)';
    badge.style.background = '#fbbf24';
    badge.style.color = '#041527';
  }
  const editorSel = $('#editorUpscaleQuality');
  if (editorSel && editorSel.value !== val) {
    editorSel.value = val;
  }
}
$('#upscaleQuality')?.addEventListener('change', updateUpscaleQualityBadge);
$('#editorUpscaleQuality')?.addEventListener('change', () => {
  const editorSel = $('#editorUpscaleQuality');
  const sel = $('#upscaleQuality');
  if (editorSel && sel) {
    sel.value = editorSel.value;
    updateUpscaleQualityBadge();
  }
});
if ($('#upscaleQuality')) updateUpscaleQualityBadge();

[
  'logoEnabled',
  'textEnabled',
  'textBgEnabled',
  'logoBgRemove',
  'logoBgColor',
  'logoBgSimilarity',
  'logoPosition',
  'logoMargin',
  'textPosition',
  'textSize',
  'textMargin',
  'textColor',
  'textBgColor',
  'overlayText'
].forEach(id =>
  $('#' + id)?.addEventListener(
    'input',
    () => {
      if (
        id === 'logoPosition' &&
        $('#logoPosition').value !== 'custom'
      ) { }

      if (
        id === 'textPosition' &&
        $('#textPosition').value !== 'custom'
      ) { }

      updatePreview();
    }
  )
);

function hexAlpha(hex, p) {
  return hex +
    Math.round(p * 2.55)
      .toString(16)
      .padStart(2, '0')
}

function applyPresetPosition(el, pos, m) {

  el.style.left = '';
  el.style.right = '';
  el.style.top = '';
  el.style.bottom = '';
  el.style.transform = '';

  if (pos.includes('left'))
    el.style.left = m + 'px';

  if (pos.includes('right'))
    el.style.right = m + 'px';

  if (
    pos.includes('center') &&
    !pos.startsWith('center-')
  ) {
    el.style.left = '50%';
    el.style.transform = 'translateX(-50%)';
  }

  if (pos.startsWith('top'))
    el.style.top = m + 'px';

  if (pos.startsWith('bottom'))
    el.style.bottom = m + 'px';

  if (pos === 'center') {
    el.style.top = '50%';
    el.style.transform = 'translate(-50%,-50%)';
  }

  if (
    pos === 'center-left' ||
    pos === 'center-right'
  ) {
    el.style.top = '50%';
    el.style.transform = 'translateY(-50%)';
  }
}

function setCustomFromCenter(el, x, y) {

  const frame = $('#previewFrame');
  const r = frame.getBoundingClientRect();
  const er = el.getBoundingClientRect();

  const px = Math.max(
    0,
    Math.min(
      100,
      ((x - r.left - er.width / 2) /
        (r.width - er.width)) * 100
    )
  );

  const py = Math.max(
    0,
    Math.min(
      100,
      ((y - r.top - er.height / 2) /
        (r.height - er.height)) * 100
    )
  );

  return [px, py];
}

function applyCustom(el, x, y) {

  el.style.left = x + '%';
  el.style.top = y + '%';
  el.style.right = 'auto';
  el.style.bottom = 'auto';
  el.style.transform = `translate(-${x}%, -${y}%)`;

  el.dataset.x = x;
  el.dataset.y = y;
}

function updatePreview() {

  const logo = $('#previewLogo');
  const txt = $('#previewText');
  if (!logo || !txt) return;

  const isLogoEnabled = $('#logoEnabled')?.checked;
  logo.style.display = isLogoEnabled ? 'flex' : 'none';

  const logoOpacity = (+($('#logoOpacity')?.value ?? 80));
  logo.style.opacity = logoOpacity / 100;
  if ($('#logoOpacityOut')) {
    $('#logoOpacityOut').textContent = logoOpacity + '%';
  }

  const logoSize = (+($('#logoSize')?.value ?? 8));
  const logoWidthPx = Math.max(16, Math.round(220 * logoSize / 20));
  logo.style.width = logoWidthPx + 'px';
  logo.style.height = 'auto';

  const posVal = $('#logoPosition')?.value || 'top-right';
  const marginVal = +($('#logoMargin')?.value ?? 40);

  if (posVal === 'custom') {
    applyCustom(
      logo,
      +logo.dataset.x || 92,
      +logo.dataset.y || 8
    );
  } else {
    applyPresetPosition(
      logo,
      posVal,
      marginVal
    );
  }

  const logoImg = $('#previewLogoImg');
  const placeholder = $('#previewLogoPlaceholder');

  if (state.logoPath) {
    if (logoImg) {
      const targetSrc = (state.logoPath.startsWith('data:') || state.logoPath.startsWith('blob:'))
        ? state.logoPath
        : state.logoPath + (state.logoPath.includes('?') ? '&' : '?') + 'v=' + Date.now();
      if (logoImg.getAttribute('src') !== targetSrc) {
        logoImg.src = targetSrc;
      }
      logoImg.style.display = 'block';
      logoImg.onerror = () => {
        logoImg.style.display = 'none';
        if (placeholder) placeholder.style.display = isLogoEnabled ? 'inline-flex' : 'none';
      };
      logoImg.onload = () => {
        logoImg.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
      };
    }
    if (placeholder) placeholder.style.display = 'none';
  } else {
    if (logoImg) {
      logoImg.removeAttribute('src');
      logoImg.style.display = 'none';
    }
    if (placeholder) placeholder.style.display = isLogoEnabled ? 'inline-flex' : 'none';
  }

  const isTxtOn = $('#textEnabled')?.checked && $('#overlayText')?.value.trim();
  txt.style.display = isTxtOn ? 'block' : 'none';

  const previewContent = txt.querySelector('.editor-text-content');
  const previewVal = $('#overlayText')?.value || 'Your text';
  if (previewContent) {
    previewContent.textContent = previewVal;
  } else {
    txt.textContent = previewVal;
  }

  const pFrame = txt.closest('.preview-frame, .editor-preview-frame');
  const pFrameWidth = (pFrame && pFrame.clientWidth > 0) ? pFrame.clientWidth : 320;
  const pSizePct = Math.max(2, Math.min(25, +(+$('#textSize')?.value || 6)));
  // Proportional font size matching video ratio (1080p width): fs = round(1080 * size / 100)
  const pPreviewFs = Math.max(10, Math.round(pFrameWidth * (pSizePct / 100)));
  txt.style.fontSize = pPreviewFs + 'px';

  const pBadge = txt.querySelector('.ctrl-size-badge');
  if (pBadge) pBadge.textContent = pSizePct + '%';

  txt.style.color =
    $('#textColor')?.value || '#FFFFFF';

  txt.style.background =
    $('#textBgEnabled')?.checked
      ? hexAlpha(
        $('#textBgColor')?.value || '#000000',
        +($('#textBgOpacity')?.value || 65)
      )
      : 'transparent';

  if ($('#textPosition')?.value === 'custom') {

    applyCustom(
      txt,
      +txt.dataset.x || 50,
      +txt.dataset.y || 75
    );

  } else {

    applyPresetPosition(
      txt,
      $('#textPosition')?.value || 'bottom-center',
      +($('#textMargin')?.value || 110)
    );
  }

  const wm = $('#previewWatermark');
  if (wm) {
    const wmEnabled = $('#watermarkTextEnabled')?.checked || false;
    const wmText = ($('#watermarkTextInput')?.value || '').trim();
    if (wmEnabled && wmText) {
      wm.style.display = 'block';
      wm.textContent = wmText;
      const opacity = (+($('#watermarkTextOpacity')?.value || 35)) / 100;
      const angle = +($('#watermarkTextAngle')?.value || -20);
      const sizePct = +($('#watermarkTextSize')?.value || 6);
      const color = $('#watermarkTextColor')?.value || '#FFFFFF';
      const pos = $('#watermarkTextPosition')?.value || 'center';
      wm.style.opacity = opacity;
      wm.style.color = color;
      wm.style.fontSize = Math.max(12, Math.round(280 * (sizePct / 100))) + 'px';
      wm.style.transform = `rotate(${angle}deg)`;

      if (pos === 'custom') {
        const xPct = +($('#watermarkTextX')?.value || 50);
        const yPct = +($('#watermarkTextY')?.value || 50);
        applyCustom(wm, xPct, yPct);
      } else {
        applyPresetPosition(wm, pos, 40);
      }
    } else {
      wm.style.display = 'none';
    }
  }
}

function beginDrag(el, e) {

  if (
    e.button !== undefined &&
    e.button !== 0
  ) return;

  if (
    !el ||
    getComputedStyle(el).display === 'none'
  ) return;

  if (
    e.target.closest?.('.ctrl-btn-size') ||
    e.target.closest?.('.overlay-resize-handle')
  ) return;

  e.preventDefault();

  const frame =
    el.closest(
      '.preview-frame,.editor-preview-frame'
    );

  if (!frame) return;

  const r = frame.getBoundingClientRect();
  const er = el.getBoundingClientRect();

  state.drag = {
    el,
    frame,
    startX: e.clientX,
    startY: e.clientY,
    startLeft: er.left - r.left,
    startTop: er.top - r.top,
    frameW: r.width,
    frameH: r.height
  };

  el.classList.add('dragging');

  try {
    el.setPointerCapture?.(e.pointerId)
  } catch { }
}

function dragMove(e) {

  if (!state.drag) return;

  const d = state.drag;
  const er = d.el.getBoundingClientRect();

  const maxLeft = Math.max(0, d.frameW - er.width);
  const maxTop = Math.max(0, d.frameH - er.height);

  const x = Math.max(0, Math.min(maxLeft, d.startLeft + (e.clientX - d.startX)));
  const y = Math.max(0, Math.min(maxTop, d.startTop + (e.clientY - d.startY)));

  const px = maxLeft > 0 ? Math.round((x / maxLeft) * 100) : 50;
  const py = maxTop > 0 ? Math.round((y / maxTop) * 100) : 75;

  applyCustom(d.el, px, py);

  if (d.el.id.includes('Logo')) {

    if ($('#logoPosition'))
      $('#logoPosition').value = 'custom';

    if ($('#editorLogoPosition'))
      $('#editorLogoPosition').value = 'custom';

    if ($('#editorLogoEnabled'))
      $('#editorLogoEnabled').checked = true;

  } else {

    if ($('#textPosition'))
      $('#textPosition').value = 'custom';

    if ($('#editorTextEnabled'))
      $('#editorTextEnabled').checked = true;
  }
}

function endDrag() {

  if (!state.drag) return;

  state.drag.el.classList.remove('dragging');
  state.drag = null;
}

[
  'previewLogo',
  'previewText',
  'editorLogo',
  'editorText'
].forEach(id => {

  $('#' + id)?.addEventListener(
    'pointerdown',
    e => beginDrag($('#' + id), e)
  );

});

document.addEventListener(
  'pointermove',
  dragMove
);

document.addEventListener(
  'pointerup',
  endDrag
);

document.addEventListener(
  'pointercancel',
  endDrag
);

function editorPreviewUpdate() {

  const logo = $('#editorLogo');
  const txt = $('#editorText');

  if (!logo || !txt) return;

  const isLogoEnabled = $('#editorLogoEnabled')?.checked;
  logo.style.display = isLogoEnabled ? 'flex' : 'none';

  const logoOpacity = (+($('#editorLogoOpacity')?.value ?? 80));
  logo.style.opacity = logoOpacity / 100;
  if ($('#editorLogoOpacityOut')) {
    $('#editorLogoOpacityOut').textContent = logoOpacity + '%';
  }

  const logoSize = (+($('#editorLogoSize')?.value ?? 8));
  const logoWidthPx = Math.max(16, Math.round(220 * logoSize / 20));
  logo.style.width = logoWidthPx + 'px';
  logo.style.height = 'auto';
  if ($('#editorLogoSizeOut')) {
    $('#editorLogoSizeOut').textContent = logoSize + '%';
  }

  const posVal = $('#editorLogoPosition')?.value || 'custom';
  const marginVal = +($('#editorLogoMargin')?.value ?? 40);

  if (posVal === 'custom') {
    applyCustom(
      logo,
      +logo.dataset.x || 92,
      +logo.dataset.y || 8
    );
  } else {
    applyPresetPosition(
      logo,
      posVal,
      marginVal
    );
  }

  const img = $('#editorLogoImg');
  const placeholder = $('#editorLogoPlaceholder');

  if (state.editorLogoPath) {
    if (img) {
      const targetSrc = (state.editorLogoPath.startsWith('data:') || state.editorLogoPath.startsWith('blob:'))
        ? state.editorLogoPath
        : state.editorLogoPath + (state.editorLogoPath.includes('?') ? '&' : '?') + 'v=' + Date.now();
      if (img.getAttribute('src') !== targetSrc) {
        img.src = targetSrc;
      }
      img.style.display = 'block';
      img.onerror = () => {
        img.style.display = 'none';
        if (placeholder) placeholder.style.display = isLogoEnabled ? 'inline-flex' : 'none';
      };
      img.onload = () => {
        img.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
      };
    }
    if (placeholder) placeholder.style.display = 'none';
  } else {
    if (img) {
      img.removeAttribute('src');
      img.style.display = 'none';
    }
    if (placeholder) placeholder.style.display = isLogoEnabled ? 'inline-flex' : 'none';
  }

  const isEditorTxtOn =
    $('#editorTextEnabled')?.checked &&
      $('#editorTextValue')?.value.trim()
      ? 'block'
      : 'none';
  txt.style.display = isEditorTxtOn;

  const editorContent = txt.querySelector('.editor-text-content');
  const editorVal = $('#editorTextValue')?.value || 'Your text';
  if (editorContent) {
    editorContent.textContent = editorVal;
  } else {
    txt.textContent = editorVal;
  }

  const eFrame = txt.closest('.editor-preview-frame, .preview-frame');
  const eFrameWidth = (eFrame && eFrame.clientWidth > 0) ? eFrame.clientWidth : 320;
  const eSizePct = Math.max(2, Math.min(25, +($('#editorTextSize')?.value || 6)));
  // Proportional font size matching video ratio (1080p width): fs = round(1080 * size / 100)
  const ePreviewFs = Math.max(10, Math.round(eFrameWidth * (eSizePct / 100)));
  txt.style.fontSize = ePreviewFs + 'px';

  const eBadge = txt.querySelector('.ctrl-size-badge');
  if (eBadge) eBadge.textContent = eSizePct + '%';

  txt.style.color =
    $('#editorTextColor')?.value || '#FFFFFF';

  txt.style.background =
    $('#editorTextBg')?.checked
      ? hexAlpha(
        $('#editorTextBgColor')?.value || '#000000',
        +($('#editorTextBgOpacity')?.value || 65)
      )
      : 'transparent';

  const bgOut = $('#editorTextBgOpacityOut');
  if (bgOut)
    bgOut.textContent = (+($('#editorTextBgOpacity')?.value || 65)) + '%';

  if (txt.dataset.x) {

    applyCustom(
      txt,
      +txt.dataset.x,
      +txt.dataset.y
    );
  }
}

[
  'editorLogoEnabled',
  'editorLogoPosition',
  'editorLogoMargin',
  'editorTextEnabled',
  'editorTextValue',
  'editorLogoSize',
  'editorLogoOpacity',
  'editorTextSize',
  'editorTextColor',
  'editorTextBg',
  'editorTextBgColor',
  'editorTextBgOpacity'
].forEach(id => {
  $('#' + id)?.addEventListener('input', editorPreviewUpdate);
  $('#' + id)?.addEventListener('change', editorPreviewUpdate);
});

function setupOverlayTextInteractions() {
  function attachResizeHandle(handleId, sizeInputId, isBeta, onUpdate) {
    const handle = $('#' + handleId);
    const sizeInput = $('#' + sizeInputId);
    if (!handle || !sizeInput) return;

    let isResizing = false;
    let startX = 0;
    let startY = 0;
    let startVal = 0;

    const onDown = (e) => {
      e.preventDefault();
      e.stopPropagation();
      isResizing = true;
      startX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
      startY = e.clientY || (e.touches && e.touches[0].clientY) || 0;
      startVal = +sizeInput.value || (isBeta ? 42 : 6);
      document.body.style.cursor = 'nwse-resize';
      try { handle.setPointerCapture?.(e.pointerId); } catch {}
    };

    const onMove = (e) => {
      if (!isResizing) return;
      const clientX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
      const clientY = e.clientY || (e.touches && e.touches[0].clientY) || 0;
      const delta = (clientX - startX) + (clientY - startY);
      if (isBeta) {
        const change = Math.round(delta / 4);
        const newVal = Math.max(16, Math.min(96, startVal + change));
        if (newVal !== +sizeInput.value) {
          sizeInput.value = newVal;
          sizeInput.dispatchEvent(new Event('input', { bubbles: true }));
          sizeInput.dispatchEvent(new Event('change', { bubbles: true }));
          if (onUpdate) onUpdate();
        }
      } else {
        const change = Math.round(delta / 12);
        const newVal = Math.max(2, Math.min(25, startVal + change));
        if (newVal !== +sizeInput.value) {
          sizeInput.value = newVal;
          sizeInput.dispatchEvent(new Event('input', { bubbles: true }));
          sizeInput.dispatchEvent(new Event('change', { bubbles: true }));
          if (onUpdate) onUpdate();
        }
      }
    };

    const onUp = () => {
      if (isResizing) {
        isResizing = false;
        document.body.style.cursor = '';
      }
    };

    handle.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  }

  function attachButtons(decId, incId, sizeInputId, isBeta, onUpdate) {
    const decBtn = $('#' + decId);
    const incBtn = $('#' + incId);
    const sizeInput = $('#' + sizeInputId);
    if (!sizeInput) return;

    const step = isBeta ? 2 : 1;
    const min = isBeta ? 16 : 2;
    const max = isBeta ? 96 : 25;

    if (decBtn) {
      decBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const cur = +sizeInput.value || (isBeta ? 42 : 6);
        const newVal = Math.max(min, Math.min(max, cur - step));
        sizeInput.value = newVal;
        sizeInput.dispatchEvent(new Event('input', { bubbles: true }));
        sizeInput.dispatchEvent(new Event('change', { bubbles: true }));
        if (onUpdate) onUpdate();
      });
      decBtn.addEventListener('pointerdown', (e) => e.stopPropagation());
    }

    if (incBtn) {
      incBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const cur = +sizeInput.value || (isBeta ? 42 : 6);
        const newVal = Math.max(min, Math.min(max, cur + step));
        sizeInput.value = newVal;
        sizeInput.dispatchEvent(new Event('input', { bubbles: true }));
        sizeInput.dispatchEvent(new Event('change', { bubbles: true }));
        if (onUpdate) onUpdate();
      });
      incBtn.addEventListener('pointerdown', (e) => e.stopPropagation());
    }
  }

  function attachWheel(overlayId, sizeInputId, isBeta, onUpdate) {
    const el = $('#' + overlayId);
    const sizeInput = $('#' + sizeInputId);
    if (!el || !sizeInput) return;

    el.addEventListener('wheel', (e) => {
      e.preventDefault();
      const step = isBeta ? 2 : 1;
      const min = isBeta ? 16 : 2;
      const max = isBeta ? 96 : 25;
      const cur = +sizeInput.value || (isBeta ? 42 : 6);
      const dir = e.deltaY < 0 ? 1 : -1;
      const newVal = Math.max(min, Math.min(max, cur + (dir * step)));
      if (newVal !== cur) {
        sizeInput.value = newVal;
        sizeInput.dispatchEvent(new Event('input', { bubbles: true }));
        sizeInput.dispatchEvent(new Event('change', { bubbles: true }));
        if (onUpdate) onUpdate();
      }
    }, { passive: false });
  }

  // Preview overlay (Create panel)
  attachButtons('previewTextSizeDec', 'previewTextSizeInc', 'textSize', false, updatePreview);
  attachResizeHandle('previewTextResizeHandle', 'textSize', false, updatePreview);
  attachWheel('previewText', 'textSize', false, updatePreview);

  // Editor overlay
  attachButtons('editorTextSizeDec', 'editorTextSizeInc', 'editorTextSize', false, editorPreviewUpdate);
  attachResizeHandle('editorTextResizeHandle', 'editorTextSize', false, editorPreviewUpdate);
  attachWheel('editorText', 'editorTextSize', false, editorPreviewUpdate);

  // Beta Lab overlay
  attachButtons('betaTextSizeDec', 'betaTextSizeInc', 'betaTextSize', true, () => {
    if (typeof syncTextOverlayStyles === 'function') syncTextOverlayStyles();
  });
  attachResizeHandle('betaTextResizeHandle', 'betaTextSize', true, () => {
    if (typeof syncTextOverlayStyles === 'function') syncTextOverlayStyles();
  });
  attachWheel('betaTextDragOverlay', 'betaTextSize', true, () => {
    if (typeof syncTextOverlayStyles === 'function') syncTextOverlayStyles();
  });

  // ResizeObserver for aspect-ratio responsive scaling
  try {
    const ro = new ResizeObserver(() => {
      if (typeof updatePreview === 'function') updatePreview();
      if (typeof editorPreviewUpdate === 'function') editorPreviewUpdate();
      if (typeof syncTextOverlayStyles === 'function') syncTextOverlayStyles();
    });
    ['previewFrame', 'editorPreviewFrame', 'betaPreviewFrame'].forEach(id => {
      const el = $('#' + id);
      if (el) ro.observe(el);
    });
  } catch {}
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupOverlayTextInteractions);
} else {
  setupOverlayTextInteractions();
}

$('#editorLogoInput')?.addEventListener(
  'change',
  e => {
    const file = e.target.files[0];
    if (!file) return;

    state.editorLogoFile = file;

    const reader = new FileReader();
    reader.onload = ev => {
      state.editorLogoPath = ev.target.result;
      $('#editorLogoEnabled').checked = true;
      editorPreviewUpdate();
    };
    reader.readAsDataURL(file);
  }
);

$('#editorClearLogo')?.addEventListener(
  'click',
  () => {
    state.editorLogoFile = null;
    state.editorLogoPath = null;

    if ($('#editorLogoInput'))
      $('#editorLogoInput').value = '';

    $('#editorLogoEnabled').checked = false;

    const img = $('#editorLogoImg');
    if (img) {
      img.removeAttribute('src');
      img.style.display = 'none';
    }

    editorPreviewUpdate();
  }
);

$('#logoInput')?.addEventListener(
  'change',
  e => {
    const file = e.target.files[0];
    if (!file) return;

    state.logoFile = file;

    const reader = new FileReader();
    reader.onload = ev => {
      const dataUrl = ev.target.result;
      state.logoPath = dataUrl;
      $('#logoPath').value = file.name;
      $('#logoEnabled').checked = true;

      const thumb = $('#logoPreviewThumb') || $('.logo-preview');
      if (thumb) {
        thumb.innerHTML = `<img src="${dataUrl}" style="width:100%;height:100%;object-fit:contain;border-radius:14px;">`;
      }

      updatePreview();
    };
    reader.readAsDataURL(file);
  }
);

$('#clearLogo')?.addEventListener(
  'click',
  () => {
    state.logoFile = null;
    state.logoPath = null;
    state.logoServerPath = null;

    if ($('#logoInput'))
      $('#logoInput').value = '';

    if ($('#logoPath'))
      $('#logoPath').value = '';

    $('#logoEnabled').checked = false;

    const thumb = $('#logoPreviewThumb') || $('.logo-preview');
    if (thumb) thumb.textContent = 'C';

    const img = $('#previewLogoImg');
    if (img) {
      img.removeAttribute('src');
      img.style.display = 'none';
    }

    updatePreview();
  }
);

function addLog(message) {

  if (!log) return;

  const line =
    document.createElement('div');

  line.textContent = message;

  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function escapeHtml(value) {

  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function loadOptions() {

  if (refreshModelsBtn) {
    refreshModelsBtn.disabled = false;
    refreshModelsBtn.textContent = '↻';
  }

  try {

    const r = await fetch(
      '/api/health',
      { cache: 'no-store' }
    );

    const d = await r.json();

    let models = d.models || [];

    if (!models.length) {
      try {
        const scanRes = await fetch('/api/models/scan', { method: 'POST', cache: 'no-store' });
        if (scanRes.ok) {
          const scanData = await scanRes.json();
          if (scanData.ok && scanData.models && scanData.models.length) {
            models = scanData.models;
            d.default_model = scanData.default || models[0];
          }
        }
      } catch (_) {}
    }

    modelSelect.innerHTML = '';

    if (models.length) {

      models.forEach(model => {
        const option =
          document.createElement('option');

        option.value = model;
        option.textContent = model;

        modelSelect.appendChild(option);
      });

      state.modelsAvailable = true;
      modelSelect.disabled = false;

      state.model =
        d.default_model ||
        d.model ||
        models[0];

      modelSelect.value = state.model;

      if (window.refreshModelHub) {
        window.refreshModelHub();
      }

      create.disabled = !state.source;

      $('#healthDot')?.classList.add('online');

      // Models are up: stop any pending retry loop.
      modelRetries = MODEL_RETRY_LIMIT;
      if (modelRetryTimer) {
        clearTimeout(modelRetryTimer);
        modelRetryTimer = null;
      }

      if ($('#healthText'))
        $('#healthText').textContent =
          `${models.length} local model${models.length === 1 ? '' : 's'} ready`;

      if ($('#statusPill'))
        $('#statusPill').innerHTML =
          '<span></span> Local AI ready';

      if (scanModelsBtn) scanModelsBtn.style.display = 'none';

    } else {

      state.modelsAvailable = false;
      state.model = '';
      modelSelect.disabled = false;
      create.disabled = !state.source;

      if (scanModelsBtn) scanModelsBtn.style.display = 'inline-flex';

      modelSelect.innerHTML =
        '<option value="">⚡ Built-in Heuristic AI (No Ollama needed)</option>';

      if ($('#healthText'))
        $('#healthText').textContent =
          'Built-in Heuristic AI (Ollama offline)';

      if ($('#statusPill'))
        $('#statusPill').innerHTML =
          '<span></span> Heuristic Mode';

      _scheduleModelRetry();

    }

  } catch (error) {

    console.error(
      '[Health] failed:',
      error
    );

    state.modelsAvailable = false;
    state.model = '';
    modelSelect.disabled = false;
    create.disabled = !state.source;

    if (scanModelsBtn) scanModelsBtn.style.display = 'inline-flex';

    modelSelect.innerHTML =
      '<option value="">⚡ Built-in Heuristic AI (No Ollama needed)</option>';

    if ($('#healthText'))
      $('#healthText').textContent =
        'Built-in Heuristic AI';

    if ($('#statusPill'))
      $('#statusPill').innerHTML =
        '<span></span> Heuristic Mode';

    _scheduleModelRetry();
  }
}

// Ollama usually needs a few seconds to answer on a cold start, and a single
// check at page load would otherwise leave Generate permanently disabled until
// the user happened to find the refresh button.
const MODEL_RETRY_LIMIT = 8;
let modelRetries = 0;
let modelRetryTimer = null;

function _scheduleModelRetry() {
  if (modelRetries >= MODEL_RETRY_LIMIT) return;
  if (modelRetryTimer) clearTimeout(modelRetryTimer);
  const delay = Math.min(1000 * (modelRetries + 1), 8000);
  modelRetryTimer = setTimeout(async () => {
    modelRetryTimer = null;
    modelRetries += 1;
    await loadOptions();
  }, delay);
}

function selectedBranding() {

  return {
    logo_enabled:
      $('#logoEnabled')?.checked || false,

    logo_path:
      state.logoServerPath ||
      state.logoPath ||
      $('#logoPath')?.value ||
      '',

    logo_position:
      $('#logoPosition')?.value ||
      'top-right',

    logo_size:
      +($('#logoSize')?.value || 8),

    logo_opacity:
      +($('#logoOpacity')?.value || 80),

    logo_margin:
      +($('#logoMargin')?.value || 40),

    logo_x:
      +($('#previewLogo')?.dataset?.x || 92) || 92,

    logo_y:
      +($('#previewLogo')?.dataset?.y || 8) || 8,

    logo_bg_remove:
      $('#logoBgRemove')?.checked || false,

    logo_bg_color:
      $('#logoBgColor')?.value || '#9B5CFF',

    logo_bg_similarity:
      +($('#logoBgSimilarity')?.value || 0.22) || 0.22,

    text_enabled:
      $('#textEnabled')?.checked || false,

    text:
      $('#overlayText')?.value || '',

    text_position:
      $('#textPosition')?.value ||
      'bottom-center',

    text_size:
      +($('#textSize')?.value || 6) || 6,

    text_color:
      $('#textColor')?.value ||
      '#FFFFFF',

    text_bg_enabled:
      $('#textBgEnabled')?.checked ?? true,

    text_bg_color:
      $('#textBgColor')?.value ||
      '#000000',

    text_bg_opacity:
      +($('#textBgOpacity')?.value || 65) || 65,

    text_margin:
      +($('#textMargin')?.value || 110) || 110,

    text_x:
      +($('#previewText')?.dataset?.x || 50) || 50,

    text_y:
      +($('#previewText')?.dataset?.y || 75) || 75,

    watermark_text_enabled:
      $('#watermarkTextEnabled')?.checked || false,

    watermark_text:
      $('#watermarkTextInput')?.value || '',

    watermark_text_position:
      $('#watermarkTextPosition')?.value || 'center',

    watermark_text_size:
      +($('#watermarkTextSize')?.value || 6) || 6,

    watermark_text_opacity:
      +($('#watermarkTextOpacity')?.value || 35) || 35,

    watermark_text_angle:
      +($('#watermarkTextAngle')?.value || -20) || -20,

    watermark_text_color:
      $('#watermarkTextColor')?.value || '#FFFFFF',

    watermark_text_x:
      +($('#watermarkTextX')?.value || 50) || 50,

    watermark_text_y:
      +($('#watermarkTextY')?.value || 50) || 50,

    premium_captions:
      $('#premiumCaptionsToggle')?.checked ?? false,

    situational_cues:
      $('#situationalCuesToggle')?.checked ?? false,

    caption_preset:
      $('#captionPresetSelect')?.value || 'center_seam',

    caption_accent:
      $('#captionAccentSelect')?.value || 'gold_yellow'
  };
}

async function start() {
  const origBtnHtml = create.innerHTML;

  // Adopt from betaState if user uploaded or imported video there
  if (!state.source && !state.jobId && typeof betaState !== 'undefined' && betaState.jobId) {
    state.jobId = betaState.jobId;
    state.source = { name: 'Video Project', size: 0, origin: 'youtube', jobId: betaState.jobId };
  } else if (!state.source && typeof betaState !== 'undefined' && betaState.sourceFile) {
    state.source = betaState.sourceFile;
  }

  create.disabled = true;
  create.innerHTML = '<span class="spinner-inline"></span> <span>Preparing Video…</span>';

  // If YouTube link is pasted in either tab, auto-import if not loaded yet
  if (!state.source && !state.jobId) {
    const rawUrl = (youtubeUrl?.value || $('#betaYtUrl')?.value || '').trim();
    if (rawUrl.includes('youtube.com/') || rawUrl.includes('youtu.be/')) {
      addLog('[YouTube] Importing video link before generating…');
      create.innerHTML = '<span class="spinner-inline"></span> <span>Importing YouTube Video…</span>';
      if (youtubeUrl) youtubeUrl.value = rawUrl;
      await importYouTube();
      if (!state.source && !state.jobId) {
        create.disabled = false;
        create.innerHTML = origBtnHtml;
        return;
      }
    }
  }

  if (!state.source && !state.jobId) {
    create.disabled = false;
    create.innerHTML = origBtnHtml;
    alert('Please upload a video or paste a YouTube link to generate Shorts.');
    if (drop) {
      drop.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    return;
  }

  if (!state.modelsAvailable) {
    try { await loadOptions(); } catch { }
    if (!state.modelsAvailable) {
      addLog('[AI] Ollama offline: Using built-in candidate & audio density heuristics.');
      state.model = '';
    }
  }

  try {
    if (!state.jobId) {
      if (state.source && state.source.origin === 'youtube' && state.source.jobId) {
        state.jobId = state.source.jobId;
      } else if (state.source && (state.source.origin === 'android_native' || state.source.uri || window.AndroidBridge)) {
        state.jobId = state.source.jobId || ('mobile_job_' + Date.now());
        state.source.jobId = state.jobId;
        addLog('[Mobile] Processing local video: ' + (state.source?.name || 'native'));
      } else if (state.source instanceof File) {
        if (window.AndroidBridge && !window.CLIPPY_DESKTOP_CONNECTED) {
          state.jobId = 'mobile_job_' + Date.now();
          state.source.jobId = state.jobId;
          addLog('[Mobile] Video ready: ' + (state.source?.name || ''));
        } else {
        // Immediate visual feedback for long video uploads
        progressPanel.hidden = false;
        results.hidden = true;
        progressPanel.dataset.state = 'running';
        progressPanel.dataset.progress = '0';
        $('#progressTitle').textContent = 'Uploading Source Video…';
        $('#progressStatus').textContent = 'UPLOADING';
        $('#progressBar').style.width = '0%';
        $('#progressPercent').textContent = '0%';
        $('#stageIcon').textContent = '↑';
        $('#stageText').textContent = 'Transferring video file to Clipify AI workspace…';
        $('#subStage').textContent = `${state.source.name} (${formatBytes(state.source.size)})`;
        addLog(`[Upload] Uploading ${state.source.name} (${formatBytes(state.source.size)})…`);

        const uploadForm = new FormData();
        uploadForm.append('video', state.source);

        const uploadData = await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open('POST', '/api/upload');
          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable && e.total > 0) {
              const pct = Math.min(99, Math.round((e.loaded / e.total) * 100));
              $('#progressBar').style.width = pct + '%';
              $('#progressPercent').textContent = pct + '%';
              $('#subStage').textContent = `${formatBytes(e.loaded)} / ${formatBytes(e.total)} (${pct}%)`;
              create.innerHTML = `<span class="spinner-inline"></span> <span>Uploading (${pct}%)…</span>`;
            }
          };
          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              try {
                const res = JSON.parse(xhr.responseText);
                resolve(res);
              } catch (err) { reject(err); }
            } else {
              try {
                const res = JSON.parse(xhr.responseText);
                reject(new Error(res.error || `Upload failed (${xhr.status})`));
              } catch {
                reject(new Error(`Upload failed with status ${xhr.status}`));
              }
            }
          };
          xhr.onerror = () => reject(new Error('Network error uploading video.'));
          xhr.send(uploadForm);
        });

        state.jobId = uploadData.job_id;
        addLog(`[Upload] Video ready as project ${state.jobId}`);
        }
      } else {
        throw Error('Could not find video project. Please re-select or re-import the video.');
      }
    }

    if (state.logoFile) {
      const logoForm = new FormData();
      logoForm.append('logo', state.logoFile);
      const logoResponse = await fetch(`/api/upload-logo/${state.jobId}`, { method: 'POST', body: logoForm });
      const logoData = await safeJson(logoResponse, 'Could not upload the logo.');
      if (!logoResponse.ok) throw Error(logoData.error || 'Could not upload the logo.');
      state.logoServerPath = logoData.path;
    }

  } catch (error) {
    addLog(`[Error] ${error.message}`);
    alert(error.message);
    create.disabled = false;
    create.innerHTML = origBtnHtml;
    return;
  }

  const form = new FormData();
  form.append('job_id', state.jobId);

  form.append(
    'mode',
    state.mode
  );

  form.append(
    'clips',
    $('#clips').value
  );

  form.append(
    'model',
    modelSelect.value
  );

  form.append(
    'font',
    fontSelect.value
  );

  form.append(
    'min_duration',
    minDuration.value
  );

  form.append(
    'max_duration',
    maxDuration.value
  );

  form.append(
    'trim_start',
    $('#betaTextStart')?.value || '0'
  );

  form.append(
    'trim_end',
    $('#betaTextEnd')?.value || '0'
  );

  form.append(
    'split_screen',
    $('#splitScreenToggle')?.checked ? '1' : '0'
  );

  form.append(
    'gaming_split',
    $('#gamingSplitToggle')?.checked ? '1' : '0'
  );

  form.append(
    'fast_whisper',
    $('#fastWhisperToggle')?.checked ? '1' : '0'
  );

  form.append(
    'premium_captions',
    $('#premiumCaptionsToggle')?.checked ? '1' : '0'
  );

  form.append(
    'situational_cues',
    $('#situationalCuesToggle')?.checked ? '1' : '0'
  );

  form.append(
    'caption_preset',
    $('#captionPresetSelect')?.value || 'center_seam'
  );

  form.append(
    'caption_accent',
    $('#captionAccentSelect')?.value || 'gold_yellow'
  );

  form.append(
    'upscale_quality',
    $('#upscaleQuality')?.value || 'high'
  );

  form.append(
    'branding',
    JSON.stringify(selectedBranding())
  );

  if (window.captionPlaygroundState) {
    if (window.captionPlaygroundState.yPercent) {
      form.append('caption_y_pct', String(window.captionPlaygroundState.yPercent));
      form.append('caption_preset', 'custom');
      const marginV = Math.round(1920 * (100 - window.captionPlaygroundState.yPercent) / 100);
      form.append('caption_margin_v', String(marginV));
    }
    if (window.captionPlaygroundState.fontSize) {
      form.append('caption_font_size', String(window.captionPlaygroundState.fontSize));
    }
    if (window.captionPlaygroundState.styleId) {
      form.append('caption_accent', window.captionPlaygroundState.styleId);
    }
  }

  const selectedFont = $('#fontSelect')?.value || 'Montserrat Extra Bold';
  if (selectedFont === 'none') {
    form.append('disable_captions', '1');
    form.append('captions_enabled', '0');
  }

  create.disabled = true;
  progressPanel.hidden = false;
  results.hidden = true;

  progressPanel.dataset.state = 'running';
  progressPanel.dataset.progress = '0';
  progressPanel.setAttribute('role', 'region');
  progressPanel.setAttribute('aria-live', 'polite');
  $('#progressTitle').textContent = 'Processing locally';
  $('#progressStatus').textContent = 'LIVE';
  $('#progressBar').style.width = '0%';
  $('#progressBar').setAttribute('aria-valuenow', '0');
  $('#progressPercent').textContent = '0%';
  $('#stageIcon').textContent = '\u25cc';
  $('#stageText').textContent = 'Preparing\u2026';
  $('#subStage').textContent = 'Clipify AI is working locally';
  renderPipelineSteps(0, false);

  addLog('[Start] Starting Clipify AI…');

  try {

    const r = await fetch(
      '/api/start',
      {
        method: 'POST',
        body: form
      }
    );

    const d = await safeJson(r, 'Could not start the job.');

    if (!r.ok)
      throw Error(
        d.error ||
        'Could not start the job.'
      );

    state.jobId = d.job_id;

    addLog(
      `[Start] Job ${state.jobId}`
    );

    await watchJob(state.jobId);

  } catch (error) {

    addLog(
      `[Error] ${error.message}`
    );

    alert(error.message);

    create.disabled = false;
  }
}

function renderPipelineSteps(progress, failed = false) {
  const helper = window.ClipifyPipelineStatus;
  if (!helper) return;
  const marks = { complete: '\u2713', active: '\u2026', failed: '!', pending: '\u00b7' };
  helper.stepStates(progress, failed).forEach(step => {
    const node = document.querySelector('[data-step="' + step.name + '"]');
    if (!node) return;
    node.dataset.state = step.state;
    const indicator = node.querySelector('.step-indicator');
    if (indicator) indicator.textContent = marks[step.state] || '';
  });
}

function setPipelineFailure(message) {
  if (progressPanel.dataset.state === 'error' || progressPanel.dataset.state === 'complete') return;
  const pct = Math.max(0, Math.min(100, Number(progressPanel.dataset.progress) || 0));
  const detail = window.ClipifyPipelineStatus
    ? window.ClipifyPipelineStatus.cleanFailure(message)
    : String(message || 'The pipeline stopped before a Short was created.').trim();
  progressPanel.dataset.state = 'error';
  progressPanel.setAttribute('role', 'alert');
  progressPanel.setAttribute('aria-live', 'assertive');
  $('#progressTitle').textContent = 'Processing failed';
  $('#progressPercent').textContent = pct ? ('Stopped at ' + pct + '%') : 'Stopped';
  $('#progressBar').setAttribute('aria-valuenow', String(pct));
  $('#stageIcon').textContent = '!';
  $('#stageText').textContent = 'No Short was created';
  $('#subStage').textContent = detail;
  $('#progressStatus').textContent = 'FAILED';
  renderPipelineSteps(pct, true);
}

function setPipelineComplete() {
  updateProgress({
    progress: 100,
    stage: 'Shorts ready',
    detail: 'Your finished Shorts are ready to review.'
  });
  progressPanel.dataset.state = 'complete';
  progressPanel.setAttribute('role', 'status');
  progressPanel.setAttribute('aria-live', 'polite');
  $('#progressTitle').textContent = 'Processing complete';
  $('#progressStatus').textContent = 'DONE';
  $('#stageIcon').textContent = '\u2713';
}

function updateProgress(d) {
  if (progressPanel.dataset.state === 'error' || progressPanel.dataset.state === 'complete') return;
  const pct = Math.max(0, Math.min(100, Number(d.progress) || 0));
  progressPanel.dataset.state = 'running';
  progressPanel.dataset.progress = String(pct);
  const bar = $('#progressBar');
  if (bar) {
    bar.style.width = pct + '%';
    bar.setAttribute('aria-valuenow', String(pct));
  }
  if ($('#progressPercent')) $('#progressPercent').textContent = String(pct) + '%';
  if ($('#progressTitle')) $('#progressTitle').textContent = 'Processing locally';
  if ($('#progressStatus')) $('#progressStatus').textContent = 'LIVE';
  if ($('#stageText')) $('#stageText').textContent = d.stage || 'Working...';
  if ($('#subStage')) $('#subStage').textContent = d.detail || '';
  if ($('#stageIcon')) $('#stageIcon').textContent = pct >= 100 ? '\u2713' : '\u2726';
  renderPipelineSteps(pct, false);
}

async function watchJob(jobId) {
  if (state.es) {
    try { state.es.close() } catch { }
  }
  let terminal = false;
  let stream = null;
  try {
    stream = new EventSource('/api/events/' + jobId);
    state.es = stream;
  } catch (err) {
    console.warn('[SSE] EventSource init failed, using polling fallback:', err);
  }

  // Dual-track resilient status polling fallback:
  // If EventSource drops, hangs, or runs in a restricted mobile WebView without SSE,
  // this polling loop queries /api/status/:id every 800ms to drive progress smoothly to 100%.
  const pollInterval = setInterval(async () => {
    if (terminal) {
      clearInterval(pollInterval);
      return;
    }
    try {
      const res = await fetch(`/api/status/${jobId}`, { cache: 'no-store' });
      if (!res.ok) return;
      const d = await res.json();
      if (terminal) return;

      if (d && typeof d.progress === 'number') {
        updateProgress(d);
      }
      if (d && Array.isArray(d.events)) {
        d.events.forEach(evt => {
          if (evt && evt.kind === 'log' && evt.message) addLog(evt.message);
        });
      }

      if (d && (d.status === 'done' || d.status === 'complete' || d.progress >= 100)) {
        terminal = true;
        clearInterval(pollInterval);
        if (state.es) {
          try { state.es.close(); } catch (_) {}
          state.es = null;
        }
        setPipelineComplete();
        loadJobResult(jobId);
      } else if (d && (d.status === 'error' || d.status === 'failed')) {
        terminal = true;
        clearInterval(pollInterval);
        if (state.es) {
          try { state.es.close(); } catch (_) {}
          state.es = null;
        }
        const detail = d.detail || d.message || d.error || 'The pipeline stopped before a Short was created.';
        addLog('[Error] ' + detail);
        setPipelineFailure(detail);
        create.disabled = false;
      }
    } catch (_) {}
  }, 800);

  if (stream) {
    stream.onmessage = event => {
      try {
        const d = JSON.parse(event.data);
        const failed = d.kind === 'error' || (d.kind === 'status' && d.status === 'error');
        const succeeded = (d.kind === 'complete' && d.pipeline === true) || d.kind === 'done' || (d.kind === 'status' && d.status === 'done');

        if (d.kind === 'log') {
          addLog(d.message);
          return;
        }
        if (failed) {
          const detail = d.detail || d.message || d.error || 'The pipeline stopped before a Short was created.';
          addLog('[Error] ' + detail);
          setPipelineFailure(detail);
          terminal = true;
          clearInterval(pollInterval);
          stream.close();
          if (state.es === stream) state.es = null;
          create.disabled = false;
          return;
        }
        if (succeeded) {
          setPipelineComplete();
          terminal = true;
          clearInterval(pollInterval);
          stream.close();
          if (state.es === stream) state.es = null;
          loadJobResult(jobId);
          return;
        }
        if (d.kind === 'progress' || d.kind === 'status') updateProgress(d);
      } catch (error) {
        console.error('[SSE]', error);
      }
    };

    stream.onerror = () => {
      // SSE connection closed/errored: Close SSE handle, but DO NOT abort the job!
      // The pollInterval loop continues to poll /api/status/:id seamlessly.
      if (stream) {
        try { stream.close(); } catch (_) {}
        if (state.es === stream) state.es = null;
        stream = null;
      }
    };
  }
}

async function loadJobResult(jobId) {

  try {

    const r = await fetch(
      `/api/status/${jobId}`,
      { cache: 'no-store' }
    );

    const d = await r.json();

    if (!r.ok)
      throw Error(
        d.error ||
        'Could not load job result.'
      );

    const outputs =
      d.outputs ||
      d.output_files ||
      [];

    await loadResults(outputs, jobId);

    if (outputs.length) {

      await selectReview(jobId, outputs[0]);

      // Present all generated clips in the results view
      $('#results')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
      });

      addLog(
        `[Done] ${outputs.length} Short(s) ready.`
      );

      // Automatically show Share & Publish options once clipping completes
      setTimeout(() => {
        if (window.openPublishModal) {
          window.openPublishModal(jobId, outputs[0]);
        }
      }, 700);

    } else {

      addLog(
        '[Done] Job completed but no output files were returned.'
      );

      create.disabled = false;
    }

  } catch (error) {

    addLog(
      `[Error] ${error.message}`
    );

    create.disabled = false;
  }
}

async function fetchMetadata(job, file) {

  try {

    const r = await fetch(
      `/api/metadata/${job}/${encodeURIComponent(file)}`,
      { cache: 'no-store' }
    );

    if (!r.ok) return null;

    return await r.json();

  } catch {

    return null;
  }
}

function metadataMarkup(m) {

  if (!m) return '';

  const title =
    escapeHtml(m.title || '');

  const description =
    escapeHtml(m.description || '');

  const hashes =
    escapeHtml(
      (m.hashtags || []).join(' ')
    );

  const tags =
    escapeHtml(
      (m.tags || []).join(', ')
    );

  return `
    <div class="metadata-title">${title}</div>
    <div class="metadata-description">${description}</div>
    <div class="metadata-label">Hashtags</div>
    <div class="metadata-hashes">${hashes}</div>
    <div class="metadata-label">Tags</div>
    <small>${tags}</small>
    <div class="metadata-copy-actions">
      <button class="ghost" type="button" data-copy-field="title">Copy Title</button>
      <button class="ghost" type="button" data-copy-field="description">Copy Description</button>
      <button class="ghost" type="button" data-copy-field="hashtags">Copy Hashtags</button>
      <button class="ghost" type="button" data-copy-field="tags">Copy Tags</button>
    </div>
  `;
}

async function copyMetadataValue(value, button) {

  if (!value) return;

  try {

    if (navigator.clipboard?.writeText) {

      await navigator.clipboard.writeText(value);

    } else {

      const area =
        document.createElement('textarea');

      area.value = value;
      area.style.position = 'fixed';
      area.style.opacity = '0';

      document.body.appendChild(area);

      area.select();

      document.execCommand('copy');

      area.remove();
    }

    const label = button.textContent;

    button.textContent = 'Copied';

    setTimeout(
      () => button.textContent = label,
      1200
    );

  } catch (error) {

    console.error(
      '[Metadata] copy failed:',
      error
    );
  }
}

function bindMetadataCopyButtons(container, m) {

  const values = {
    title: String(m.title || ''),
    description: String(m.description || ''),
    hashtags: (m.hashtags || []).join(' '),
    tags: (m.tags || []).join(', ')
  };

  container
    .querySelectorAll('[data-copy-field]')
    .forEach(button =>
      button.addEventListener(
        'click',
        () => {
          copyMetadataValue(
            values[button.dataset.copyField],
            button
          );
        }
      )
    );
}

function renderOutputCarousel() {
  const featured = $('#featuredResult');
  if (!featured) return;
  if (!state.outputs.length) {
    featured.hidden = true;
    return;
  }

  const total = state.outputs.length;
  const currentFile = state.outputs[state.currentOutputIndex] || state.outputs[0];
  const src = `/media/${state.jobId}/${encodeURIComponent(currentFile)}`;
  const title = currentFile.replace(/\.mp4$/i, '');

  featured.hidden = false;
  featured.classList.remove('featured-pop');
  void featured.offsetWidth;
  featured.classList.add('featured-pop');

  featured.innerHTML = `
    <div class="featured-carousel-shell">
      <button class="carousel-nav prev" type="button" aria-label="Previous clip" ${state.currentOutputIndex === 0 ? 'disabled' : ''}>‹</button>
      <div class="featured-video-shell">
        <video id="featuredVideo" controls playsinline preload="metadata" muted autoplay loop src="${src}?v=${Date.now()}"></video>
        <div class="featured-badge">${state.currentOutputIndex + 1} / ${total} · FINISHED SHORT</div>
      </div>
      <button class="carousel-nav next" type="button" aria-label="Next clip" ${state.currentOutputIndex === total - 1 ? 'disabled' : ''}>›</button>
    </div>
    <div class="featured-copy">
      <div class="featured-meta-row">
        <span class="kicker">JUST GENERATED</span>
        <span class="carousel-index">${state.currentOutputIndex + 1} / ${total}</span>
      </div>
      <h3 id="featuredTitle">${escapeHtml(title)}</h3>
      <p id="featuredMeta">1080 × 1920 · finished captions · optional branding</p>
      <div class="featured-dots" aria-label="Select clip">
        ${state.outputs.map((_, index) => `<button class="dot ${index === state.currentOutputIndex ? 'active' : ''}" type="button" aria-label="Go to clip ${index + 1}" data-index="${index}"></button>`).join('')}
      </div>
      <div class="featured-actions">
        <button class="primary" id="featuredReview" type="button"><span>✏️ Edit in Studio</span><b>→</b></button>
        <button class="secondary" id="featuredPublish" type="button" style="background:rgba(215,187,148,0.18);border:1px solid rgba(215,187,148,0.4);color:var(--text);border-radius:10px;padding:9px 18px;font-weight:600;cursor:pointer;"><span>🚀 Share / Publish</span></button>
        <a class="ghost" id="featuredDownload" href="${src}" download="${currentFile}">Download ↓</a>
        <button class="ghost" id="featuredNew" type="button">＋ New</button>
      </div>
    </div>
  `;

  const featuredVideo = $('#featuredVideo');
  const featuredReview = $('#featuredReview');
  const featuredDownload = $('#featuredDownload');

  if (featuredVideo) {
    featuredVideo.muted = true;
    featuredVideo.autoplay = true;
    featuredVideo.loop = true;
    featuredVideo.load();
    featuredVideo.play().catch(() => { });
  }

  featuredReview?.addEventListener('click', () => selectReview(state.jobId, currentFile));
  featured.querySelector('#featuredPublish')?.addEventListener('click', () => {
    if (window.openPublishModal) {
      window.openPublishModal(state.jobId, currentFile);
    }
  });
  featured.querySelector('#featuredNew')?.addEventListener('click', () => {
    $('#newBtn')?.click();
  });
  featuredDownload?.addEventListener('click', (event) => {
    event.preventDefault();
    window.location.href = `${src}?download=1`;
  });

  featured.querySelector('.carousel-nav.prev')?.addEventListener('click', () => {
    if (state.currentOutputIndex > 0) {
      state.currentOutputIndex -= 1;
      renderOutputCarousel();
    }
  });

  featured.querySelector('.carousel-nav.next')?.addEventListener('click', () => {
    if (state.currentOutputIndex < state.outputs.length - 1) {
      state.currentOutputIndex += 1;
      renderOutputCarousel();
    }
  });

  featured.querySelectorAll('.featured-dots .dot').forEach((dot) => {
    dot.addEventListener('click', () => {
      state.currentOutputIndex = Number(dot.dataset.index || 0);
      renderOutputCarousel();
    });
  });

  featured.querySelector('.featured-video-shell')?.addEventListener('dblclick', () => selectReview(state.jobId, currentFile));

  const reviewFile = currentFile;
  const renderedJob = state.jobId;
  fetchMetadata(renderedJob, reviewFile).then((m) => {
    if (state.jobId !== renderedJob || state.outputs[state.currentOutputIndex] !== reviewFile) return;
    const titleEl = $('#featuredTitle');
    if (titleEl && m?.title) titleEl.textContent = m.title;
    const metaEl = $('#featuredMeta');
    const selection = m?.selection || {};
    let timePrefix = '';
    if (m?.duration) {
      const dur = Math.round(m.duration);
      const dm = Math.floor(dur / 60);
      const ds = String(dur % 60).padStart(2, '0');
      timePrefix = `⏱️ ${dm}:${ds} (${dur}s) · `;
    }
    if (metaEl && selection.method === 'qwen' && selection.decision === 'reject') {
      metaEl.textContent = `${timePrefix}1080 × 1920 · Qwen (${selection.model || 'local model'}) rejected this clip · recovery used`;
    } else if (metaEl && selection.method === 'qwen' && selection.decision === 'keep') {
      metaEl.textContent = `${timePrefix}1080 × 1920 · Qwen (${selection.model || 'local model'}) selected this clip`;
    } else if (metaEl && selection.method === 'deterministic_fallback') {
      metaEl.textContent = `${timePrefix}1080 × 1920 · deterministic fallback · Qwen score unavailable`;
    } else if (metaEl) {
      metaEl.textContent = `${timePrefix}1080 × 1920 · finished captions · local render`;
    }
  });
}

async function loadResults(outputs, jobId = state.jobId) {

  state.jobId = jobId || state.jobId;
  state.outputs = outputs || [];
  state.currentOutputIndex = 0;

  grid.innerHTML = '';

  renderOutputCarousel();

  for (let i = 0; i < state.outputs.length; i++) {
    const file = state.outputs[i];
    const src = `/media/${state.jobId}/${encodeURIComponent(file)}`;
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'result-thumb';
    card.dataset.index = String(i);
    card.innerHTML = `
      <video muted playsinline preload="metadata" src="${src}"></video>
      <span>${i + 1}</span>
    `;
    card.addEventListener('click', () => {
      state.currentOutputIndex = i;
      renderOutputCarousel();
    });
    grid.appendChild(card);
  }

  results.hidden = !state.outputs.length;

  if (state.outputs.length) {
    results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setTimeout(() => $('#featuredVideo')?.focus({ preventScroll: true }), 450);
  }

  updateEditorClipSwitcher();
  create.disabled = false;
}

function updateEditorClipSwitcher() {
  const switcher = $('#editorClipSwitcher');
  if (!switcher) return;
  if (!state.outputs || state.outputs.length <= 1) {
    switcher.hidden = true;
    switcher.innerHTML = '';
    return;
  }
  switcher.hidden = false;
  switcher.innerHTML = state.outputs.map((out, idx) => {
    const active = (out === state.reviewFile || (!state.reviewFile && idx === 0));
    return `<button type="button" class="editor-short-pill ${active ? 'active' : ''}" data-file="${out}" style="background:${active ? 'rgba(215,187,148,0.28)' : 'rgba(255,255,255,0.06)'};border:1px solid ${active ? 'var(--warm,#d6b388)' : 'rgba(190,176,159,0.3)'};color:var(--text);padding:6px 12px;border-radius:8px;font-size:0.8rem;font-weight:600;cursor:pointer;">Short #${idx + 1}</button>`;
  }).join('');
  switcher.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      const f = btn.dataset.file;
      if (f) selectReview(state.jobId, f);
    });
  });
}

function updateEditorFramingPreview() {
  const panX = +$('#editorPanX')?.value || 0;
  const panY = +$('#editorPanY')?.value || 0;
  const zoom = (+$('#editorZoom')?.value || 100) / 100;
  if ($('#editorPanXOut')) $('#editorPanXOut').textContent = (panX >= 0 ? `+${panX}%` : `${panX}%`);
  if ($('#editorPanYOut')) $('#editorPanYOut').textContent = (panY >= 0 ? `+${panY}%` : `${panY}%`);
  if ($('#editorZoomOut')) $('#editorZoomOut').textContent = `${zoom.toFixed(1)}x`;

  const video = $('#reviewVideo');
  if (video) {
    if (panX === 0 && panY === 0 && zoom === 1) {
      video.style.transform = 'none';
    } else {
      video.style.transform = `scale(${zoom}) translate(${panX * 0.3}%, ${panY * 0.3}%)`;
      video.style.transformOrigin = 'center center';
    }
  }
}

async function selectReview(job, file) {

  state.jobId = job;
  state.reviewFile = file;

  const src =
    `/media/${job}/${encodeURIComponent(file)}`;

  $('#reviewTitle').textContent = file;

  $('#reviewMeta').textContent =
    '1080 × 1920 · local render · post-render branding available';

  // Reset framing preview controls to automatic defaults
  if ($('#editorPanX')) $('#editorPanX').value = 0;
  if ($('#editorPanY')) $('#editorPanY').value = 0;
  if ($('#editorZoom')) $('#editorZoom').value = 100;
  if ($('#editorSplitRatio')) $('#editorSplitRatio').value = 50;
  updateEditorFramingPreview();
  updateEditorClipSwitcher();

  // The editor renders its primary actions twice (panel + footer). Both copies
  // must be wired, otherwise the visible one stays a dead href="#".
  editorDownloads().forEach(a => { a.href = src; a.hidden = false; });

  editorApplyButtons().forEach(b => b.disabled = false);

  const editorImg = $('#editorLogoImg');
  if (editorImg) {
    editorImg.removeAttribute('src');
    editorImg.style.display = 'none';
  }
  const editorPlaceholder = $('#editorLogoPlaceholder');
  if (editorPlaceholder) editorPlaceholder.style.display = 'none';

  state.editorLogoFile = null;
  state.editorLogoPath = null;

  if ($('#editorLogoEnabled')) $('#editorLogoEnabled').checked = false;
  if ($('#editorLogoPosition')) $('#editorLogoPosition').value = 'top-right';
  if ($('#editorLogoMargin')) $('#editorLogoMargin').value = 40;
  if ($('#editorLogoSize')) $('#editorLogoSize').value = 8;
  if ($('#editorLogoSizeOut')) $('#editorLogoSizeOut').textContent = '8%';
  if ($('#editorLogoOpacity')) $('#editorLogoOpacity').value = 80;
  if ($('#editorLogoOpacityOut')) $('#editorLogoOpacityOut').textContent = '80%';
  if ($('#editorLogo')) {
    $('#editorLogo').dataset.x = '92';
    $('#editorLogo').dataset.y = '8';
  }

  // Check if job already has a saved logo on server
  try {
    const testImg = new Image();
    testImg.onload = () => {
      state.editorLogoPath = `/api/logo/${job}`;
      if ($('#editorLogoEnabled')) $('#editorLogoEnabled').checked = true;
      editorPreviewUpdate();
    };
    testImg.src = `/api/logo/${job}?t=${Date.now()}`;
  } catch {}

  if ($('#editorTextEnabled')) $('#editorTextEnabled').checked = false;
  $('#editorTextValue').value = '';

  $('#editorLogo').dataset.x = '92';
  $('#editorLogo').dataset.y = '8';

  $('#editorText').dataset.x = '50';
  $('#editorText').dataset.y = '75';

  const m =
    await fetchMetadata(
      job,
      file
    );

  const meta =
    $('#editorMetadata');

  if (m) {

    meta.hidden = false;

    const selectionNote = $('#editorSelectionNote');
    const selection = m.selection || {};
    if (selectionNote) {
      selectionNote.hidden = true;
      selectionNote.textContent = '';
      selectionNote.dataset.decision = '';
      if (selection.method === 'qwen' && selection.decision === 'reject') {
        selectionNote.textContent = `Qwen (${selection.model || 'local model'}) marked this clip reject. It was retained by the older recovery policy after boundary and duration validation.`;
        selectionNote.dataset.decision = 'reject';
        selectionNote.hidden = false;
      } else if (selection.method === 'qwen' && selection.decision === 'keep') {
        selectionNote.textContent = `Selected by Qwen (${selection.model || 'local model'}); decision: keep.`;
        selectionNote.dataset.decision = 'keep';
        selectionNote.hidden = false;
      } else if (selection.method === 'deterministic_fallback') {
        selectionNote.textContent = 'Selected by deterministic fallback because no usable Qwen score was available.';
        selectionNote.dataset.decision = 'fallback';
        selectionNote.hidden = false;
      }
    }

    $('#reviewTitle').textContent =
      m.title || file;

    $('#editorMetaDescription').textContent =
      m.description ||
      m.title ||
      '';

    $('#editorMetaHashtags').textContent =
      (m.hashtags || []).join(' ');

    $('#editorMetaTags').textContent =
      'Tags: ' +
      (m.tags || []).join(', ');

  } else {

    meta.hidden = true;
  }

  navigateTo('editor');
  // Let the editor section become visible before asking Chromium to fetch media.
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  $('#reviewEmpty').hidden = true;
  if (reviewPlayer) {
    reviewPlayer.load(src);
  } else {
    const video = $('#reviewVideo');
    video.hidden = false;
    video.src = src;
    video.load();
  }
  editorPreviewUpdate();
}

async function applyEditorBranding() {

  if (
    !state.jobId ||
    !state.reviewFile
  ) return;

  const b = {

    logo_enabled:
      $('#editorLogoEnabled')?.checked || false,

    logo_path:
      state.editorLogoPath || '',

    logo_position:
      $('#editorLogoPosition')?.value || 'custom',

    logo_size:
      +($('#editorLogoSize')?.value || 8),

    logo_opacity:
      +($('#editorLogoOpacity')?.value || 80),

    logo_margin:
      +($('#editorLogoMargin')?.value || 40),

    logo_x:
      +$('#editorLogo').dataset.x || 92,

    logo_y:
      +$('#editorLogo').dataset.y || 8,

    logo_bg_remove:
      $('#editorLogoBgRemove').checked,

    logo_bg_color:
      $('#editorLogoBgColor').value,

    logo_bg_similarity:
      .22,

    logo_bg_blend:
      .05,

    text_enabled:
      $('#editorTextEnabled').checked,

    text:
      $('#editorTextValue').value,

    text_position:
      'custom',

    text_size:
      +$('#editorTextSize').value,

    text_color:
      $('#editorTextColor').value,

    text_bg_enabled:
      $('#editorTextBg').checked,

    text_bg_color:
      $('#editorTextBgColor').value,

    text_bg_opacity:
      +$('#editorTextBgOpacity').value,

    text_margin:
      110,

    text_x:
      +$('#editorText').dataset.x || 50,

    text_y:
      +$('#editorText').dataset.y || 75,

    framing: {
      pan_x: +$('#editorPanX')?.value || 0,
      pan_y: +$('#editorPanY')?.value || 0,
      zoom: (+$('#editorZoom')?.value || 100) / 100,
      split_ratio: +$('#editorSplitRatio')?.value || 50
    },
    upscale_quality: $('#editorUpscaleQuality')?.value || $('#upscaleQuality')?.value || 'high'
  };

  try {

    editorApplyButtons().forEach(b => {
      b.disabled = true;
      const span = b.querySelector('span');
      if (span) span.textContent = 'Rendering…';
    });

    if (state.editorLogoFile) {

      const fd = new FormData();

      fd.append(
        'logo',
        state.editorLogoFile
      );

      const ur =
        await fetch(
          '/api/upload-logo/' + state.jobId,
          {
            method: 'POST',
            body: fd
          }
        );

      const ud =
        await ur.json();

      if (!ur.ok)
        throw Error(
          ud.error ||
          'Logo upload failed'
        );

      b.logo_path = ud.path;
      if (!state.editorLogoPath || !state.editorLogoPath.startsWith('data:')) {
        state.editorLogoPath = ud.url || `/api/logo/${state.jobId}`;
      }
    }

    const r =
      await fetch(
        '/api/apply-branding/' + state.jobId,
        {
          method: 'POST',
          headers: {
            'Content-Type':
              'application/json'
          },
          body: JSON.stringify({
            filename: state.reviewFile,
            branding: b,
            font: fontSelect.value
          })
        }
      );

    const d =
      await r.json();

    if (!r.ok)
      throw Error(
        d.error ||
        'Branding render failed'
      );

    state.reviewFile = d.filename;

    const src =
      d.url +
      '?v=' +
      Date.now();

    if (reviewPlayer) reviewPlayer.load(src);
    else { $('#reviewVideo').src = src; $('#reviewVideo').load(); }

    editorDownloads().forEach(a => a.href = d.url);

    $('#reviewTitle').textContent =
      d.filename;

    addLog(
      '[Editor] ' +
      d.filename +
      ' created'
    );

    const m =
      await fetchMetadata(
        state.jobId,
        state.reviewFile
      );

    if (m) {

      $('#editorMetadata').hidden = false;

      $('#editorMetaDescription').textContent =
        m.description ||
        m.title ||
        '';

      $('#editorMetaHashtags').textContent =
        (m.hashtags || []).join(' ');

      $('#editorMetaTags').textContent =
        'Tags: ' +
        (m.tags || []).join(', ');
    }

    loadProjects();

  } catch (e) {

    alert(e.message);

  } finally {

    editorApplyButtons().forEach(b => {
      b.disabled = false;
      const span = b.querySelector('span');
      if (span) span.textContent = 'Apply to Finished Short';
    });
  }
}

editorApplyButtons().forEach(btn => btn.addEventListener('click', applyEditorBranding));

['#editorPanX', '#editorPanY', '#editorZoom', '#editorSplitRatio'].forEach(sel => {
  $(sel)?.addEventListener('input', updateEditorFramingPreview);
});

$('#resetFramingBtn')?.addEventListener('click', () => {
  if ($('#editorPanX')) $('#editorPanX').value = 0;
  if ($('#editorPanY')) $('#editorPanY').value = 0;
  if ($('#editorZoom')) $('#editorZoom').value = 100;
  if ($('#editorSplitRatio')) $('#editorSplitRatio').value = 50;
  updateEditorFramingPreview();
});

async function loadProjects() {

  const r =
    await fetch('/api/projects');

  const d =
    await r.json();

  const list =
    $('#projectList');

  list.innerHTML = '';

  const sel =
    $('#assetProject');

  if (sel)
    sel.innerHTML =
      '<option value="">Choose a project</option>';

  const visibleProjects = (d.projects || []).filter(x => x.outputs?.length || ['running', 'uploaded'].includes(x.status));

  visibleProjects.forEach(x => {

    if (sel) {

      sel.add(
        new Option(
          `${x.source || x.id} · ${x.outputs.length} Short(s)`,
          x.id
        )
      );
    }

    const el =
      document.createElement('article');

    el.className =
      'project-card panel';
    const firstOutput = x.outputs?.[0];
    const firstMetadata = x.output_metadata?.[firstOutput] || {};
    const projectTitle = firstMetadata.title || x.name || x.source || x.id;
    const projectDescription = firstMetadata.description || 'No description generated yet.';
    const outputTitles = (x.outputs || []).map((output, index) => {
      const metadata = x.output_metadata?.[output] || {};
      return `<button class="project-output" type="button" data-output="${escapeHtml(output)}">${escapeHtml(metadata.title || `Short ${index + 1}`)}</button>`;
    }).join('');
    const thumbnail = firstOutput ? `<video class="project-thumb" muted playsinline preload="metadata" src="/media/${encodeURIComponent(x.id)}/${encodeURIComponent(firstOutput)}"></video>` : '<div class="project-thumb project-thumb-empty">✦</div>';

    el.innerHTML = `
      ${thumbnail}

      <div class="project-main">

        <b>
          ${escapeHtml(
      projectTitle
    )}
        </b>

        <small>
          ${x.outputs.length} Short(s) · ${x.status}
        </small>

        <span>
          ${escapeHtml(projectDescription)}
        </span>

        <div class="project-outputs">${outputTitles}</div>

      </div>

      <div class="project-actions">
        <button class="ghost project-open">Open</button>
        <button class="ghost project-share" title="Share & Publish this project's Short" style="color:var(--warm,#d6b388);font-weight:600;">🚀 Share</button>
        <button class="ghost project-rename" title="Rename project">Rename</button>
        <button class="ghost project-delete" title="Move project to Recently deleted">Delete</button>
      </div>
    `;

    el
      .querySelector('.project-open')
      .onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const output = (x.outputs && x.outputs.length) ? x.outputs[0] : null;
        if (output)
          await selectReview(
            x.id,
            output
          );
        else
          navigateTo('create');
      };

    el.querySelector('.project-share')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const output = x.outputs?.[0] || 'short_01.mp4';
      if (window.openPublishModal) {
        window.openPublishModal(x.id, output);
      }
    });

    el.querySelectorAll('.project-output').forEach(button => {
      button.onclick = () => selectReview(x.id, button.dataset.output);
    });

    el.querySelector('.project-rename').onclick = async () => {
      const next = prompt('Project name', x.name || x.source || x.id);
      if (next === null) return;
      const response = await fetch(`/api/projects/${x.id}/rename`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: next }) });
      const data = await response.json();
      if (!response.ok) { alert(data.error || 'Could not rename project.'); return; }
      loadProjects();
    };

    el.querySelector('.project-delete').onclick = async () => {
      if (!confirm('Move this project to Recently deleted?')) return;
      const response = await fetch(`/api/projects/${x.id}`, { method: 'DELETE' });
      const data = await response.json();
      if (!response.ok) { alert(data.error || 'Could not delete project.'); return; }
      await loadProjects();
      loadTrash();
    };

    list.appendChild(el);

    const thumb = el.querySelector('.project-thumb');
    if (thumb?.tagName === 'VIDEO') {
      thumb.addEventListener('loadedmetadata', () => {
        thumb.currentTime = Math.min(1, thumb.duration || 1);
      });
    }
  });

  if (!visibleProjects.length) {

    list.innerHTML =
      '<div class="empty-state">No projects yet. Generate your first Short.</div>';
  }
}

async function loadTrash() {
  const list = $('#trashList');
  if (!list) return;
  const response = await fetch('/api/projects/trash', { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) { list.innerHTML = '<div class="empty-state">Could not load deleted projects.</div>'; return; }
  list.innerHTML = (data.projects || []).map(x => `
    <div class="trash-row">
      <div><b>${escapeHtml(x.name || x.id)}</b><small>${escapeHtml(x.id)}</small></div>
      <button class="ghost" data-restore="${escapeHtml(x.id)}">Restore</button>
    </div>`).join('') || '<div class="empty-state">No deleted projects.</div>';
  list.querySelectorAll('[data-restore]').forEach(button => button.onclick = async () => {
    const response = await fetch(`/api/projects/${encodeURIComponent(button.dataset.restore)}/restore`, { method: 'POST' });
    const result = await response.json();
    if (!response.ok) { alert(result.error || 'Could not restore project.'); return; }
    await loadProjects();
    loadTrash();
  });
}

async function loadAssets() {

  const id =
    $('#assetProject').value;

  if (!id) {

    $('#assetList').innerHTML =
      '<div class="empty-state">Choose a project to load assets.</div>';

    return;
  }

  const r =
    await fetch(
      '/api/assets/' + id
    );

  const d =
    await r.json();

  $('#assetList').innerHTML =
    (d.assets || [])
      .map(a => `

        <div class="asset-row">

          <span>
            ${a.kind === 'source' ? '🎬' : '✦'}
          </span>

          <div>

            <b>
              ${escapeHtml(a.name)}
            </b>

            <small>
              ${escapeHtml(a.kind)} ·
              ${formatBytes(a.size)}
            </small>

          </div>

          <a
            class="ghost"
            href="${a.url}"
            target="_blank"
          >
            Open
          </a>

        </div>

      `)
      .join('') ||
    '<div class="empty-state">No assets.</div>';
}

$('#refreshProjects')
  .onclick = loadProjects;

$('#refreshTrash')
  ?.addEventListener('click', loadTrash);

$('#refreshAssets')
  .onclick = loadAssets;

$('#assetProject')
  .onchange = loadAssets;

$('#newBtn')
  .onclick = () => {

    state.jobId = null;
    state.source = null;
    state.logoFile = null;
    state.logoPath = null;

    input.value = '';

    if (youtubeUrl)
      youtubeUrl.value = '';

    if (youtubeStatus)
      youtubeStatus.textContent = '';

    $('#logoInput').value = '';

    chip.hidden = true;
    results.hidden = true;
    progressPanel.hidden = true;
    create.disabled = true;

    location.hash = 'create';
  };

if (create) {
  create.onclick = start;
  create.addEventListener('click', start);
}

function navigateTo(id) {
  const target = id || 'create';
  if (target === 'live') {
    if (!window.location.pathname.includes('/live')) {
      window.location.href = '/live';
    }
    return;
  }
  if (target === 'narrate') {
    if (!window.location.pathname.includes('/narrate')) {
      window.location.href = '/narrate';
    }
    return;
  }
  if (['support', 'promoters', 'campaigns', 'models', 'update', 'guide'].includes(target)) {
    // Ensure base section is visible so the main workspace is never pitch black behind modals
    const currentVisible = document.querySelector('.page-section.visible') || document.getElementById('create');
    if (currentVisible) {
      currentVisible.classList.add('visible');
      currentVisible.style.display = 'block';
    }
    if (target === 'models' && window.openModelHub) window.openModelHub();
    if (target === 'update' && window.openClipifyUpdate) window.openClipifyUpdate();
    if (target === 'guide' && window.startClipifyTour) window.startClipifyTour();
    if (target === 'support' && window.showSupportModal) window.showSupportModal();
    if (target === 'promoters' && window.showPromotersModal) window.showPromotersModal();
    if (target === 'campaigns' && window.showCampaignsModal) window.showCampaignsModal();
    return;
  }
  if (location.hash.slice(1) !== target) {
    location.hash = target;
  }
  const knownSection = document.getElementById(target);
  const activeSectionId = (knownSection && knownSection.classList.contains('page-section')) ? target : 'create';
  $$('.page-section').forEach(s => {
    const isTarget = s.id === activeSectionId;
    s.classList.toggle('visible', isTarget);
    s.style.display = isTarget ? 'block' : 'none';
  });
  $$('[data-nav]').forEach(a =>
    a.classList.toggle('active', a.dataset.nav === activeSectionId)
  );
  if (target === 'projects') loadProjects();
  if (target === 'assets') loadProjects().then(loadAssets);
  if (target === 'trending') {
    if (typeof window.loadTrending === 'function') window.loadTrending();
  }
  window.scrollTo({ top: 0, behavior: 'instant' });
}

window.clipTrendingVideo = function(videoUrl) {
  if (!videoUrl) return;
  navigateTo('create');
  const ytInput = $('#youtubeUrl');
  if (ytInput) {
    ytInput.value = videoUrl;
    setTimeout(() => {
      if (typeof importYouTube === 'function') importYouTube();
    }, 200);
  }
};

window.clipTrendingLive = function(streamUrl) {
  if (!streamUrl) return;
  window.location.href = `/live?stream_url=${encodeURIComponent(streamUrl)}`;
};

$('#navGuideLink')?.addEventListener('click', (e) => {
  e.preventDefault();
  const activeNav = document.querySelector('[data-nav].active')?.dataset?.nav;
  const h = (window.location.hash || '').replace('#', '').split('?')[0].toLowerCase();
  const ctx = activeNav || h || null;
  if (window.startClipifyTour) window.startClipifyTour(ctx);
});

$('#previewReview')?.addEventListener('click', (e) => {
  e.preventDefault();
  if (state.jobId && state.reviewFile) {
    selectReview(state.jobId, state.reviewFile);
  } else if (state.outputs && state.outputs.length) {
    selectReview(state.jobId, state.outputs[0]);
  } else {
    navigateTo('editor');
  }
});

async function handleOpenInput(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  const btn = e?.currentTarget || $('#openInput');
  const originalText = btn ? btn.textContent : 'Open input';
  if (btn) btn.textContent = 'Opening…';

  try {
    const res = await fetch('/api/open-input-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobId: state.jobId || null })
    });
    const data = await res.json();
    if (data && data.opened) {
      if (btn) {
        btn.textContent = 'Opened ✓';
        setTimeout(() => { if (btn) btn.textContent = originalText; }, 2000);
      }
      return;
    }
  } catch (err) {
    console.warn('Native input folder open failed:', err);
  }

  if (btn) {
    btn.textContent = originalText;
  }
}

async function handleOpenOutput(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  const btn = e?.currentTarget || $('#openOutput') || $('#openOutput2');
  const originalText = btn ? btn.textContent : 'Open output';
  if (btn) btn.textContent = 'Opening…';

  try {
    const res = await fetch('/api/open-output-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobId: state.jobId || null })
    });
    const data = await res.json();
    if (data && data.opened) {
      if (btn) {
        btn.textContent = 'Opened ✓';
        setTimeout(() => { if (btn) btn.textContent = originalText; }, 2000);
      }
      return;
    }
  } catch (err) {
    console.warn('Native folder open failed:', err);
  }

  if (btn) {
    btn.textContent = originalText;
  }

  // Graceful browser fallback: if in a remote/sandbox browser or explorer failed
  if (state.jobId && state.outputs?.[0]) {
    selectReview(state.jobId, state.outputs[0]);
  } else {
    navigateTo('projects');
  }
}

$('#openInput')?.addEventListener('click', handleOpenInput);
$('#openOutput')?.addEventListener('click', handleOpenOutput);
$('#openOutput2')?.addEventListener('click', handleOpenOutput);

window.addEventListener(
  'hashchange',
  () => {
    const searchParams = new URLSearchParams(location.search);
    const raw = location.hash.slice(1) || searchParams.get('section') || 'create';
    const id = raw.split('?')[0];
    navigateTo(id);

    const urlParams = new URLSearchParams(raw.includes('?') ? raw.slice(raw.indexOf('?')) : location.search);
    const videoParam = urlParams.get('video');
    const titleParam = urlParams.get('title') || 'Custom Short';
    if (id === 'editor' && videoParam) {
      if ($('#reviewEmpty')) $('#reviewEmpty').hidden = true;
      if (reviewPlayer) {
        reviewPlayer.load(videoParam);
      } else {
        const video = $('#reviewVideo');
        if (video) {
          video.hidden = false;
          video.src = videoParam;
          video.load();
        }
      }
      if ($('#reviewTitle')) $('#reviewTitle').textContent = titleParam;
      if ($('#reviewMeta')) $('#reviewMeta').textContent = '1080 × 1920 · live stream short · editor';
      editorDownloads().forEach(a => { a.href = videoParam; a.hidden = false; });
      editorApplyButtons().forEach(b => b.disabled = false);
      editorPreviewUpdate();
    }
  }
);

const initialHash = (location.hash.slice(1) || '').split('?')[0];
if (initialHash === 'live') {
  window.location.href = '/live';
} else if (initialHash === 'narrate') {
  window.location.href = '/narrate';
} else if (initialHash && document.getElementById(initialHash)) {
  try { navigateTo(initialHash); } catch (e) { console.warn(e); }
} else if (initialHash === 'models') {
  if (window.openModelHub) window.openModelHub();
} else if (initialHash === 'support') {
  try { navigateTo('create'); } catch (e) { }
  if (window.showSupportModal) setTimeout(() => window.showSupportModal(), 100);
} else if (initialHash === 'promoters') {
  try { navigateTo('create'); } catch (e) { }
  if (window.showPromotersModal) setTimeout(() => window.showPromotersModal(), 100);
} else {
  try { window.dispatchEvent(new Event('hashchange')); } catch (e) { console.warn(e); }
  try { navigateTo('create'); } catch (e) { console.warn(e); }
}
try { loadOptions(); } catch (e) { console.warn(e); }
try { loadProjects(); } catch (e) { console.warn(e); }
try { loadTrash(); } catch (e) { console.warn(e); }
try { updatePreview(); } catch (e) { console.warn(e); }
try { editorPreviewUpdate(); } catch (e) { console.warn(e); }

const revealSections = $$('.page-section');
if ('IntersectionObserver' in window) {
  const revealObserver = new IntersectionObserver((entries, observer) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('reveal-visible');
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
  revealSections.forEach(section => revealObserver.observe(section));
} else {
  revealSections.forEach(section => section.classList.add('reveal-visible'));
}

// --- Social Publishing & MCP Integration ---
function initSocialPublishing() {
  const modal = $('#publishModal');
  const closeBtn = $('#closePublishModal');
  const cancelBtn = $('#cancelPublish');
  const form = $('#publishForm');
  const featuredPublish = $('#featuredPublish');
  const reviewPublish = $('#reviewPublish');
  const statusMsg = $('#publishStatusMsg');
  const pubTabs = $$('.pub-tab');

  // Ensure modal is strictly hidden on initial page load
  if (modal) {
    modal.style.display = 'none';
    modal.hidden = true;
  }

  function openPublish(jobId, filename, optionalTitle) {
    if (!modal) return;
    const jId = jobId || state.jobId;
    const rawName = filename || state.outputs?.[state.currentOutputIndex] || state.reviewFile || 'short_01.mp4';
    if (!jId || !rawName) {
      alert('Please generate or select a Short first.');
      return;
    }
    const fName = String(rawName).split('?')[0].split('#')[0].split('/').pop() || 'short_01.mp4';
    $('#publishJobId').value = jId;
    $('#publishFilename').value = fName;
    $('#publishTitle').value = optionalTitle || fName.replace(/\.[^/.]+$/, '').replace(/_/g, ' ');
    $('#publishDescription').value = '#Shorts #ClipifyAI #Viral';
    if (statusMsg) { statusMsg.style.display = 'none'; statusMsg.textContent = ''; }

    fetchMetadata(jId, fName).then(meta => {
      if (meta && meta.title) $('#publishTitle').value = meta.title;
      if (meta && meta.description) {
        const hashtags = Array.isArray(meta.hashtags) ? meta.hashtags.join(' ') : (Array.isArray(meta.tags) ? meta.tags.map(t => t.startsWith('#') ? t : '#' + t).join(' ') : '#Shorts');
        $('#publishDescription').value = `${meta.description}\n\n${hashtags}`;
      }
    }).catch(() => { });

    modal.style.display = 'flex';
    modal.hidden = false;
  }

  function closePublish() {
    if (modal) {
      modal.style.display = 'none';
      modal.hidden = true;
    }
  }

  window.openPublishModal = openPublish;
  window.closePublishModal = closePublish;

  featuredPublish?.addEventListener('click', () => {
    const cur = state.outputs?.[state.currentOutputIndex] || state.reviewFile || 'short_01.mp4';
    openPublish(state.jobId, cur);
  });
  reviewPublish?.addEventListener('click', () => {
    const curFile = state.reviewFile || state.outputs?.[state.currentOutputIndex] || 'short_01.mp4';
    openPublish(state.jobId, curFile);
  });
  closeBtn?.addEventListener('click', closePublish);
  cancelBtn?.addEventListener('click', closePublish);

  pubTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      pubTabs.forEach(t => {
        t.classList.remove('active');
        t.style.background = 'transparent';
        t.style.border = '1px solid transparent';
        t.style.color = 'var(--muted,#c9b9a4)';
      });
      tab.classList.add('active');
      tab.style.background = 'rgba(215,187,148,0.22)';
      tab.style.border = '1px solid rgba(215,187,148,0.4)';
      tab.style.color = 'var(--text,#f3eadf)';
      const platform = tab.dataset.platform;
      $('#publishPlatform').value = platform;
      const submitBtn = $('#submitPublish span');
      if (submitBtn) {
        submitBtn.textContent = platform === 'package' ? '📦 Export Package' : `🚀 Publish to ${tab.textContent}`;
      }
    });
  });

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const jobId = $('#publishJobId').value;
    const filename = $('#publishFilename').value;
    const platform = $('#publishPlatform').value;
    const title = $('#publishTitle').value.trim();
    const description = $('#publishDescription').value.trim();
    const privacy = $('#publishPrivacy').value;
    const submitBtn = $('#submitPublish');

    if (submitBtn) { submitBtn.disabled = true; submitBtn.querySelector('span').textContent = 'Publishing…'; }
    if (statusMsg) {
      statusMsg.style.display = 'block';
      statusMsg.style.background = 'rgba(215,187,148,0.12)';
      statusMsg.style.color = 'var(--text,#f3eadf)';
      statusMsg.textContent = `Preparing ${platform.toUpperCase()} distribution…`;
    }

    try {
      const resp = await fetch('/api/publish/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, filename, platform, title, description, privacy })
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || 'Publishing failed.');

      if (statusMsg) {
        statusMsg.style.background = 'rgba(74,222,128,0.15)';
        statusMsg.style.border = '1px solid rgba(74,222,128,0.4)';
        statusMsg.style.color = '#4ade80';
        if (data.status === 'published' && data.url) {
          statusMsg.innerHTML = `✓ Successfully published to ${platform}! <a href="${data.url}" target="_blank" style="color:#60a5fa;text-decoration:underline;margin-left:8px;">View Short ↗</a>`;
        } else if (data.status === 'manual_action_ready') {
          statusMsg.innerHTML = `✓ Ready to publish! ${data.message || ''} ${data.studio_url ? `<a href="${data.studio_url}" target="_blank" style="color:#60a5fa;text-decoration:underline;margin-left:8px;">Open Studio Upload ↗</a>` : ''}`;
        } else {
          statusMsg.innerHTML = `✓ Package exported to: <code>${data.export_directory || data.copy_file || 'social_export'}</code>`;
        }
      }
    } catch (err) {
      if (statusMsg) {
        statusMsg.style.background = 'rgba(239,68,68,0.15)';
        statusMsg.style.border = '1px solid rgba(239,68,68,0.4)';
        statusMsg.style.color = '#ef4444';
        statusMsg.textContent = `Error: ${err.message}`;
      }
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.querySelector('span').textContent = '🚀 Publish Now';
      }
    }
  });
}
initSocialPublishing();


// --- AI Model & Cloud Integration (Hugging Face + Ollama) ---
function initAIModelManagement() {
  const tabOllama = $('#provTabOllama');
  const tabHf = $('#provTabHuggingFace');
  const hfPanel = $('#hfConfigPanel');
  const ollamaRow = $('#ollamaDownloadRow');
  const hfTokenInput = $('#hfTokenInput');
  const hfModelSelect = $('#hfModelSelect');
  const btnVerifyHf = $('#btnVerifyHfToken');
  const hfStatusMsg = $('#hfStatusMsg');
  const btnDownloadOllama = $('#btnDownloadOllama');
  const ollamaInput = $('#ollamaDownloadInput');
  const dlProgress = $('#modelDlProgress');
  const dlBar = $('#dlProgressBar');
  const dlText = $('#dlStatusText');

  let currentProvider = 'ollama';

  async function loadConfig() {
    try {
      const res = await fetch('/api/models/config');
      const data = await res.json();
      if (data.ok) {
        currentProvider = data.provider || 'ollama';
        if (hfModelSelect && data.hf_model) hfModelSelect.value = data.hf_model;
        if (hfTokenInput && data.hf_token_masked) hfTokenInput.value = data.hf_token_masked;
        updateUI();
      }
    } catch (_) { }
  }

  function updateUI() {
    if (currentProvider === 'huggingface') {
      tabHf?.classList.add('active');
      tabOllama?.classList.remove('active');
      if (hfPanel) hfPanel.style.display = 'block';
      if (ollamaRow) ollamaRow.style.display = 'none';
      if ($('#healthText')) $('#healthText').textContent = 'Hugging Face API (Cloud)';
      if ($('#statusPill')) $('#statusPill').innerHTML = '<span></span> HF Cloud Mode';
    } else {
      tabOllama?.classList.add('active');
      tabHf?.classList.remove('active');
      if (hfPanel) hfPanel.style.display = 'none';
      if (ollamaRow) ollamaRow.style.display = 'block';
    }
  }

  tabOllama?.addEventListener('click', async () => {
    currentProvider = 'ollama';
    updateUI();
    try {
      await fetch('/api/models/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'ollama' })
      });
      loadOptions();
    } catch (_) { }
  });

  tabHf?.addEventListener('click', async () => {
    currentProvider = 'huggingface';
    updateUI();
    try {
      await fetch('/api/models/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'huggingface' })
      });
    } catch (_) { }
  });

  hfModelSelect?.addEventListener('change', async () => {
    try {
      await fetch('/api/models/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hf_model: hfModelSelect.value })
      });
    } catch (_) { }
  });

  btnVerifyHf?.addEventListener('click', async () => {
    const token = hfTokenInput?.value.trim();
    if (!token) {
      if (hfStatusMsg) hfStatusMsg.textContent = 'Please paste a valid Hugging Face token (starts with hf_).';
      return;
    }
    btnVerifyHf.disabled = true;
    btnVerifyHf.textContent = 'Verifying…';
    if (hfStatusMsg) hfStatusMsg.textContent = 'Connecting to Hugging Face API…';
    try {
      const res = await fetch('/api/models/huggingface/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      });
      const data = await res.json();
      if (data.ok) {
        if (hfStatusMsg) {
          hfStatusMsg.innerHTML = `<span style="color:#4ade80;">✓ Verified & Connected as <b>${data.name}</b> (${data.type})</span>`;
        }
        if ($('#healthDot')) $('#healthDot').classList.add('online');
        if ($('#healthText')) $('#healthText').textContent = 'Hugging Face API connected';
      } else {
        if (hfStatusMsg) {
          hfStatusMsg.innerHTML = `<span style="color:#ef4444;">✗ ${data.error || 'Invalid token'}</span>`;
        }
      }
    } catch (err) {
      if (hfStatusMsg) hfStatusMsg.innerHTML = `<span style="color:#ef4444;">✗ Error: ${err.message}</span>`;
    } finally {
      btnVerifyHf.disabled = false;
      btnVerifyHf.textContent = 'Verify Token';
    }
  });

  const modelPresetSelect = $('#ollamaModelPresetSelect');
  modelPresetSelect?.addEventListener('change', () => {
    const val = modelPresetSelect.value;
    if (val && val !== 'custom') {
      if (ollamaInput) ollamaInput.value = val;
    } else if (val === 'custom') {
      if (ollamaInput) {
        ollamaInput.value = '';
        ollamaInput.focus();
      }
    }
  });

  let pollInterval = null;
  btnDownloadOllama?.addEventListener('click', async () => {
    const model = ollamaInput?.value.trim();
    if (!model) {
      alert('Please enter an Ollama model tag (e.g. qwen2.5:3b, llama3.2:3b).');
      return;
    }
    btnDownloadOllama.disabled = true;
    if (dlProgress) dlProgress.style.display = 'block';
    if (dlBar) dlBar.style.width = '0%';
    if (dlText) dlText.textContent = `Requesting pull of ${model}…`;

    try {
      const res = await fetch('/api/models/ollama/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model })
      });
      const data = await res.json();
      if (!data.ok) {
        alert(data.error || 'Failed to start download.');
        btnDownloadOllama.disabled = false;
        return;
      }
      pollInterval = setInterval(async () => {
        try {
          const sRes = await fetch('/api/models/ollama/download-status');
          const sData = await sRes.json();
          if (dlBar) dlBar.style.width = `${sData.percent || 0}%`;
          if (dlText) dlText.textContent = sData.status || 'Downloading…';
          if (!sData.active) {
            clearInterval(pollInterval);
            btnDownloadOllama.disabled = false;
            if (sData.percent === 100) {
              await loadOptions();
              if (ollamaInput) ollamaInput.value = '';
            } else if (sData.error) {
              alert(sData.error);
            }
          }
        } catch (_) { }
      }, 1200);
    } catch (err) {
      alert('Error initiating model pull: ' + err.message);
      btnDownloadOllama.disabled = false;
    }
  });

  loadConfig();
}

initAIModelManagement();
initWatermarkAndCaptionsUI();
initBetaTestingSection();

// --- Watermark & Caption UI Setup ---
function initWatermarkAndCaptionsUI() {
  const premToggle = $('#premiumCaptionsToggle');
  const premDrawer = $('#premiumCaptionDrawer');
  if (premToggle && premDrawer) {
    premToggle.addEventListener('change', () => {
      premDrawer.style.display = premToggle.checked ? 'block' : 'none';
    });
  }

  const wmToggle = $('#watermarkTextEnabled');
  const wmDrawer = $('#watermarkControlsDrawer');
  if (wmToggle && wmDrawer) {
    wmToggle.addEventListener('change', () => {
      wmDrawer.style.display = wmToggle.checked ? 'block' : 'none';
      updatePreview();
    });
  }

  const wmPos = $('#watermarkTextPosition');
  const wmCoords = $('#watermarkCustomCoords');
  if (wmPos && wmCoords) {
    wmPos.addEventListener('change', () => {
      wmCoords.style.display = wmPos.value === 'custom' ? 'grid' : 'none';
      updatePreview();
    });
  }

  const bindSlider = (sliderId, outId, suffix = '') => {
    const s = $(sliderId);
    const o = $(outId);
    if (s && o) {
      s.addEventListener('input', () => {
        o.textContent = s.value + suffix;
        updatePreview();
      });
    }
  };

  bindSlider('#watermarkTextOpacity', '#watermarkTextOpacityOut', '%');
  bindSlider('#watermarkTextAngle', '#watermarkTextAngleOut', '°');
  bindSlider('#watermarkTextSize', '#watermarkTextSizeOut', '%');
  bindSlider('#watermarkTextX', '#watermarkTextXOut', '%');
  bindSlider('#watermarkTextY', '#watermarkTextYOut', '%');

  ['#watermarkTextInput', '#watermarkTextColor', '#captionPresetSelect', '#captionAccentSelect'].forEach(sel => {
    $(sel)?.addEventListener('input', updatePreview);
  });
}

// --- Beta Testing Section Controller ---
function initBetaTestingSection() {
  const dropZone = $('#betaDropZone');
  const fileInput = $('#betaFileInput');
  const ytUrl = $('#betaYtUrl');
  const ytImportBtn = $('#betaYtImportBtn');
  const sourceInfo = $('#betaSourceInfo');
  const sourceName = $('#betaSourceName');
  const sourceMeta = $('#betaSourceMeta');
  const clearSource = $('#betaClearSource');
  const runBtn = $('#betaRunPipelineBtn');
  const progressBox = $('#betaProgressBox');
  const progressBar = $('#betaProgressBar');
  const progressPct = $('#betaProgressPct');
  const stageText = $('#betaStageText');
  const logBox = $('#betaLog');
  const resultVideo = $('#betaResultVideo');
  const placeholder = $('#betaPlaceholder');
  const clipSwitcher = $('#betaClipSwitcher');
  const downloadBtn = $('#betaDownloadBtn');
  const openInEditorBtn = $('#betaOpenInEditor');

  let betaState = window.betaState = {
    sourceFile: null,
    jobId: null,
    downloading: false,
    running: false,
    outputs: [],
    selectedClip: null,
  };

  const bindBetaSlider = (sliderId, outId, suffix = '') => {
    const s = $(sliderId);
    const o = $(outId);
    if (s && o) {
      s.addEventListener('input', () => { o.textContent = s.value + suffix; });
    }
  };
  bindBetaSlider('#betaWmOpacity', '#betaWmOpacityOut', '%');
  bindBetaSlider('#betaWmAngle', '#betaWmAngleOut', '°');

  // Draggable Split Screen Resizer
  const betaLayout = $('#betaLayout');
  const betaSplitRow = $('#betaSplitRatioRow');
  const betaSplitSlider = $('#betaSplitRatio');
  const betaSplitText = $('#betaSplitRatioText');
  const betaSplitOverlay = $('#betaSplitOverlay');
  const betaSplitTop = $('#betaSplitTop');
  const betaSplitBottom = $('#betaSplitBottom');
  const betaSplitHandle = $('#betaSplitHandle');
  const betaSplitBadge = $('#betaSplitBadge');
  const betaPreviewFrame = $('#betaPreviewFrame');

  function updateSplitRatioUI(pct) {
    pct = Math.round(Math.max(30, Math.min(70, pct)));
    if (betaSplitSlider) betaSplitSlider.value = pct;
    if (betaSplitText) betaSplitText.textContent = `Top ${pct}% / Bottom ${100 - pct}%`;
    if (betaSplitTop) betaSplitTop.style.height = `${pct}%`;
    if (betaSplitBottom) betaSplitBottom.style.height = `${100 - pct}%`;
    if (betaSplitHandle) betaSplitHandle.style.top = `${pct}%`;
    if (betaSplitBadge) betaSplitBadge.textContent = `⇕ Top ${pct}% · Bottom ${100 - pct}%`;
  }

  function syncBetaLayoutVisibility() {
    const isSplit = betaLayout && (betaLayout.value === 'gaming_split' || betaLayout.value === 'two_person');
    if (betaSplitRow) betaSplitRow.style.display = isSplit ? 'block' : 'none';
    if (betaSplitOverlay) betaSplitOverlay.style.display = isSplit ? 'flex' : 'none';
  }

  if (betaLayout) {
    betaLayout.addEventListener('change', syncBetaLayoutVisibility);
    syncBetaLayoutVisibility();
  }

  const betaCapToggle = $('#betaCaptionsToggle');
  const betaCapBadge = $('#betaCaptionsBadge');
  const betaCapSettings = $('#betaCaptionsSettingsContainer');
  if (betaCapToggle) {
    betaCapToggle.addEventListener('change', () => {
      const isEn = betaCapToggle.checked;
      if (betaCapBadge) {
        betaCapBadge.textContent = isEn ? 'ENABLED' : 'DISABLED';
        betaCapBadge.style.color = isEn ? '#ffffff' : '#71717a';
        betaCapBadge.style.background = isEn ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.03)';
        betaCapBadge.style.borderColor = isEn ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.08)';
      }
      if (betaCapSettings) {
        betaCapSettings.style.opacity = isEn ? '1' : '0.35';
        betaCapSettings.style.pointerEvents = isEn ? 'auto' : 'none';
      }
    });
  }

  if (betaSplitSlider) {
    betaSplitSlider.addEventListener('input', (e) => {
      updateSplitRatioUI(+e.target.value);
    });
  }

  if (betaSplitHandle && betaPreviewFrame) {
    let isDraggingSplit = false;

    const onSplitMove = (clientY) => {
      const rect = betaPreviewFrame.getBoundingClientRect();
      if (rect.height <= 0) return;
      const relativeY = clientY - rect.top;
      const pct = (relativeY / rect.height) * 100;
      updateSplitRatioUI(pct);
    };

    betaSplitHandle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      isDraggingSplit = true;
      betaSplitHandle.classList.add('dragging');
      document.body.style.cursor = 'row-resize';
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDraggingSplit) return;
      e.preventDefault();
      onSplitMove(e.clientY);
    });

    window.addEventListener('mouseup', () => {
      if (isDraggingSplit) {
        isDraggingSplit = false;
        betaSplitHandle.classList.remove('dragging');
        document.body.style.cursor = '';
      }
    });

    // Touch support for mobile / touchscreens
    betaSplitHandle.addEventListener('touchstart', (e) => {
      if (e.touches && e.touches[0]) {
        isDraggingSplit = true;
        betaSplitHandle.classList.add('dragging');
      }
    }, { passive: true });

    window.addEventListener('touchmove', (e) => {
      if (isDraggingSplit && e.touches && e.touches[0]) {
        onSplitMove(e.touches[0].clientY);
      }
    }, { passive: true });

    window.addEventListener('touchend', () => {
      if (isDraggingSplit) {
        isDraggingSplit = false;
        betaSplitHandle.classList.remove('dragging');
      }
    });
  }

  if (dropZone && fileInput) {
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.style.borderColor = '#ffffff'; });
    dropZone.addEventListener('dragleave', () => { dropZone.style.borderColor = 'rgba(255,255,255,0.18)'; });
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.style.borderColor = 'rgba(255,255,255,0.18)';
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleBetaFile(e.dataTransfer.files[0]);
      }
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files[0]) {
        handleBetaFile(fileInput.files[0]);
      }
    });
  }

  async function handleBetaFile(file) {
    betaState.sourceFile = file;
    betaState.jobId = null;
    dropZone.style.display = 'none';
    sourceInfo.style.display = 'flex';
    sourceName.textContent = file.name;
    sourceMeta.textContent = `${(file.size / (1024 * 1024)).toFixed(1)} MB · Local Upload`;

    // Immediately show video in preview and reveal the dual-handle timeline trimmer under it!
    try {
      const objUrl = URL.createObjectURL(file);
      placeholder.style.display = 'none';
      if (betaSplitOverlay) betaSplitOverlay.style.display = 'none';
      resultVideo.style.display = 'block';
      resultVideo.src = objUrl;
      resultVideo.load();
      resultVideo.onloadedmetadata = () => {
        const dur = Math.round(resultVideo.duration || 0);
        const scrubber = $('#betaScrubberTimeline');
        if (scrubber) scrubber.style.display = 'block';
        if (betaTextEnd) betaTextEnd.value = dur.toFixed(1);
        syncTextOverlayStyles();
      };
    } catch (e) {
      console.warn('Could not preview local file:', e);
    }
  }

  if (clearSource) {
    clearSource.addEventListener('click', () => {
      betaState.sourceFile = null;
      betaState.jobId = null;
      dropZone.style.display = 'block';
      sourceInfo.style.display = 'none';
      if (fileInput) fileInput.value = '';
      placeholder.style.display = 'flex';
      resultVideo.style.display = 'none';
      resultVideo.src = '';
      const scrubber = $('#betaScrubberTimeline');
      if (scrubber) scrubber.style.display = 'none';
    });
  }

  if (ytImportBtn && ytUrl) {
    ytImportBtn.addEventListener('click', async () => {
      const url = ytUrl.value.trim();
      if (!url) return alert('Enter a valid YouTube URL first.');
      ytImportBtn.disabled = true;
      ytImportBtn.textContent = 'Fetching...';
      betaState.downloading = true;
      if (runBtn) {
        runBtn.disabled = true;
        runBtn.textContent = '⏳ Downloading YouTube video…';
      }
      try {
        const res = await fetch('/api/import-youtube', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (!res.ok || (!data.ok && !data.job_id)) throw new Error(data.error || 'Failed to import YouTube video');
        const jobId = data.job_id;
        betaState.jobId = jobId;
        betaState.sourceFile = null;
        dropZone.style.display = 'none';
        sourceInfo.style.display = 'flex';
        sourceName.textContent = 'Connecting to YouTube...';
        sourceMeta.textContent = `Project ${jobId} · Downloading...`;

        // Poll /api/status/${jobId} until uploaded or error
        await new Promise((resolve, reject) => {
          let pollCount = 0;
          const pollTimer = setInterval(async () => {
            pollCount++;
            try {
              const sr = await fetch(`/api/status/${jobId}`, { cache: 'no-store' });
              if (!sr.ok) return;
              const sd = await sr.json();
              if (sd.status === 'uploaded') {
                clearInterval(pollTimer);
                betaState.downloading = false;
                sourceName.textContent = sd.filename || 'YouTube Video';
                sourceMeta.textContent = `Project ${jobId} · Ready to Clip`;
                if (runBtn) {
                  runBtn.disabled = false;
                  runBtn.textContent = '⚡ Run Beta AI Pipeline';
                }

                // Show YouTube preview in Beta workspace and reveal timeline trimmer
                const mediaUrl = `/project-media/${encodeURIComponent(jobId)}/input/${encodeURIComponent(sd.filename || 'video.mp4')}`;
                placeholder.style.display = 'none';
                if (betaSplitOverlay) betaSplitOverlay.style.display = 'none';
                resultVideo.style.display = 'block';
                resultVideo.src = mediaUrl;
                resultVideo.load();
                resultVideo.onloadedmetadata = () => {
                  const dur = Math.round(resultVideo.duration || 0);
                  const scrubber = $('#betaScrubberTimeline');
                  if (scrubber) scrubber.style.display = 'block';
                  if (betaTextEnd) betaTextEnd.value = dur.toFixed(1);
                  syncTextOverlayStyles();
                };

                // Sync with main Create tab so switching tabs works seamlessly
                state.jobId = jobId;
                state.source = {
                  name: sd.filename || 'video.mp4',
                  size: 0,
                  origin: 'youtube',
                  jobId: jobId
                };
                if (create) create.disabled = false;
                const mainPrev = $('#sourcePreview');
                if (mainPrev) {
                  mainPrev.src = mediaUrl;
                  mainPrev.load();
                  mainPrev.hidden = false;
                }
                const mainPlace = $('.preview-placeholder');
                if (mainPlace) mainPlace.style.display = 'none';
                if (nameEl) nameEl.textContent = sd.filename;
                if (sizeEl) sizeEl.textContent = 'Downloaded locally';
                if (chip) chip.hidden = false;

                resolve();
              } else if (sd.status === 'error') {
                clearInterval(pollTimer);
                betaState.downloading = false;
                if (runBtn) {
                  runBtn.disabled = false;
                  runBtn.textContent = 'Run Beta AI Pipeline';
                }
                reject(new Error(sd.detail || sd.error || 'YouTube download failed'));
              } else {
                sourceName.textContent = sd.stage || 'Downloading YouTube video...';
                sourceMeta.textContent = `${sd.progress || 0}% · ${sd.detail || 'Connecting...'}`;
              }
            } catch (err) {
              if (pollCount > 180) {
                clearInterval(pollTimer);
                betaState.downloading = false;
                if (runBtn) {
                  runBtn.disabled = false;
                  runBtn.textContent = 'Run Beta AI Pipeline';
                }
                reject(err);
              }
            }
          }, 1000);
        });
      } catch (err) {
        dropZone.style.display = 'block';
        sourceInfo.style.display = 'none';
        betaState.jobId = null;
        betaState.downloading = false;
        if (runBtn) {
          runBtn.disabled = false;
          runBtn.textContent = 'Run Beta AI Pipeline';
        }
        alert(err.message || 'Failed to import YouTube video');
      } finally {
        ytImportBtn.disabled = false;
        ytImportBtn.textContent = 'Fetch Link';
      }
    });
  }

  if (runBtn) {
    runBtn.addEventListener('click', async () => {
      if (betaState.downloading) {
        alert('YouTube video is still downloading. Please wait for the download to finish before running the pipeline.');
        return;
      }
      if (!betaState.sourceFile && !betaState.jobId) {
        alert('Please select a video file or fetch a YouTube link first.');
        return;
      }
      runBtn.disabled = true;
      progressBox.style.display = 'block';
      progressBar.style.width = '3%';
      progressPct.textContent = '3%';
      stageText.textContent = 'Uploading / Preparing workspace...';
      logBox.textContent = '[Beta] Initializing run...\n';

      try {
        if (!betaState.jobId && betaState.sourceFile) {
          const upForm = new FormData();
          upForm.append('video', betaState.sourceFile);
          stageText.textContent = `Uploading ${betaState.sourceFile.name}… (0%)`;
          const upData = await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/upload');
            xhr.upload.onprogress = (e) => {
              if (e.lengthComputable && e.total > 0) {
                const pct = Math.min(99, Math.round((e.loaded / e.total) * 100));
                progressBar.style.width = pct + '%';
                progressPct.textContent = pct + '%';
                stageText.textContent = `Uploading ${betaState.sourceFile.name}… (${pct}%)`;
              }
            };
            xhr.onload = () => {
              if (xhr.status >= 200 && xhr.status < 300) {
                try { resolve(JSON.parse(xhr.responseText)); } catch (err) { reject(err); }
              } else {
                try {
                  const res = JSON.parse(xhr.responseText);
                  reject(new Error(res.error || `Upload failed (${xhr.status})`));
                } catch { reject(new Error(`Upload failed (${xhr.status})`)); }
              }
            };
            xhr.onerror = () => reject(new Error('Network error uploading video.'));
            xhr.send(upForm);
          });
          if (!upData.job_id) throw new Error(upData.error || 'Failed to upload video');
          betaState.jobId = upData.job_id;
          logBox.textContent += `[Upload] Created project ${betaState.jobId}\n`;
        }

        const layout = $('#betaLayout')?.value || 'gaming_split';
        const splitScreen = layout !== 'normal' ? '1' : '0';
        const gamingSplit = layout === 'gaming_split' ? '1' : '0';

        const captionsEnabled = $('#betaCaptionsToggle')?.checked ?? true;
        const selectedLanguage = $('#betaLanguageSelect')?.value || 'auto';

        const brandingPayload = {
          watermark_text_enabled: $('#betaWatermarkEnabled')?.checked || false,
          watermark_text: $('#betaWatermarkText')?.value || '',
          watermark_text_position: $('#betaWatermarkPosition')?.value || 'center',
          watermark_text_opacity: +($('#betaWmOpacity')?.value || 35),
          watermark_text_angle: +($('#betaWmAngle')?.value || -20),
          watermark_text_size: 6,
          watermark_text_color: '#FFFFFF',
          captions_enabled: captionsEnabled,
          disable_captions: !captionsEnabled,
          language: selectedLanguage,
          premium_captions: captionsEnabled && ($('#betaPremiumCaptions')?.checked ?? true),
          situational_cues: captionsEnabled && ($('#betaSituationalCues')?.checked ?? true),
          caption_preset: $('#betaCaptionPreset')?.value || 'center_seam',
          caption_accent: $('#betaCaptionAccent')?.value || 'gold_yellow',
        };

        const splitRatioVal = parseInt($('#betaSplitRatio')?.value || 50);

        const startPayload = {
          job_id: betaState.jobId,
          mode: 'viral',
          clips: $('#betaClipsCount')?.value || 2,
          min_duration: 25,
          max_duration: 60,
          trim_start: +(betaTextStart?.value || 0),
          trim_end: +(betaTextEnd?.value || 0),
          split_screen: splitScreen,
          gaming_split: gamingSplit,
          split_ratio: splitRatioVal,
          fast_whisper: '1',
          branding: brandingPayload,
          captions_enabled: captionsEnabled,
          disable_captions: !captionsEnabled,
          language: selectedLanguage,
          caption_language: selectedLanguage,
          font: !captionsEnabled ? 'none' : 'Montserrat Extra Bold',
          premium_captions: captionsEnabled && ($('#betaPremiumCaptions')?.checked ?? true),
          situational_cues: captionsEnabled && ($('#betaSituationalCues')?.checked ?? true),
          caption_preset: $('#betaCaptionPreset')?.value || 'center_seam',
          caption_accent: $('#betaCaptionAccent')?.value || 'gold_yellow',
        };

        if (window.captionPlaygroundState) {
          if (window.captionPlaygroundState.yPercent) {
            const yPct = window.captionPlaygroundState.yPercent;
            startPayload.caption_y_pct = yPct;
            startPayload.caption_preset = 'custom';
            startPayload.caption_margin_v = Math.round(1920 * (100 - yPct) / 100);
            brandingPayload.caption_preset = 'custom';
            brandingPayload.caption_margin_v = Math.round(1920 * (100 - yPct) / 100);
          }
          if (window.captionPlaygroundState.fontSize) {
            startPayload.caption_font_size = window.captionPlaygroundState.fontSize;
            brandingPayload.caption_font_size = window.captionPlaygroundState.fontSize;
          }
          if (window.captionPlaygroundState.styleId) {
            startPayload.caption_accent = window.captionPlaygroundState.styleId;
            brandingPayload.caption_accent = window.captionPlaygroundState.styleId;
          }
        }

        const startRes = await fetch('/api/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(startPayload)
        });
        const startData = await startRes.json();
        if (!startRes.ok || !startData.ok) throw new Error(startData.error || 'Failed to start pipeline');

        logBox.textContent += `[Pipeline] Job ${betaState.jobId} started with Premium Captions & Watermark...\n`;

        let terminal = false;
        let pollTimer = null;

        const updateBetaUI = (info) => {
          if (!info) return;
          const rawProg = info.progress !== undefined ? info.progress : (info.message && info.message.progress);
          if (rawProg !== undefined) {
            const pct = Math.min(100, Math.max(0, parseInt(rawProg)));
            progressBar.style.width = `${pct}%`;
            progressPct.textContent = `${pct}%`;
          }
          const stage = info.stage || (info.message && info.message.stage);
          if (stage) stageText.textContent = stage;
          const detail = info.detail || (info.message && info.message.detail);
          if (detail && detail !== stage) stageText.title = detail;
        };

        const onFinished = () => {
          if (terminal) return;
          terminal = true;
          if (pollTimer) clearInterval(pollTimer);
          try { sse.close(); } catch (_) {}
          progressBar.style.width = '100%';
          progressPct.textContent = '100%';
          stageText.textContent = 'Finished rendering all Shorts!';
          runBtn.disabled = false;
          loadBetaOutputs(betaState.jobId);
        };

        const onError = (msg) => {
          if (terminal) return;
          terminal = true;
          if (pollTimer) clearInterval(pollTimer);
          try { sse.close(); } catch (_) {}
          runBtn.disabled = false;
          stageText.textContent = 'Pipeline stopped';
          logBox.textContent += `[Error] ${msg || 'Pipeline stopped before completion.'}\n`;
        };

        const sse = new EventSource(`/api/events/${betaState.jobId}`);
        sse.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            const kind = data.kind || data.type;

            if (kind === 'log') {
              const line = data.message || data.text || '';
              if (line) {
                logBox.textContent += `${line}\n`;
                logBox.scrollTop = logBox.scrollHeight;
              }
              return;
            }

            if (kind === 'progress' || kind === 'status') {
              updateBetaUI(data);
              if (data.status === 'done' || data.status === 'complete') {
                onFinished();
              } else if (data.status === 'error') {
                onError(data.detail || data.message);
              }
              return;
            }

            if (kind === 'complete' || kind === 'done') {
              onFinished();
              return;
            }

            if (kind === 'error') {
              onError(data.message || data.detail);
              return;
            }
          } catch (_) {}
        };

        sse.onerror = () => {
          if (terminal) return;
        };

        // Resilient polling backup: polls status every 1.5 seconds so UI is never stuck
        pollTimer = setInterval(async () => {
          if (terminal) return;
          try {
            const res = await fetch(`/api/status/${betaState.jobId}`, { cache: 'no-store' });
            if (!res.ok) return;
            const statusData = await res.json();
            updateBetaUI(statusData);
            if (statusData.status === 'done') {
              onFinished();
            } else if (statusData.status === 'error') {
              onError(statusData.detail || statusData.error);
            }
          } catch (_) {}
        }, 1500);

      } catch (err) {
        alert(err.message);
        runBtn.disabled = false;
        stageText.textContent = 'Run failed';
      }
    });
  }

  async function loadBetaOutputs(jobId) {
    try {
      const res = await fetch(`/api/job/${jobId}`);
      const data = await res.json();
      const outputs = data.outputs || [];
      if (!outputs.length) {
        logBox.textContent += '[Warning] No outputs returned.\n';
        return;
      }
      betaState.outputs = outputs;
      clipSwitcher.innerHTML = '';
      outputs.forEach((filename, idx) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `ghost ${idx === 0 ? 'active' : ''}`;
        btn.style.padding = '5px 12px';
        btn.style.fontSize = '0.78rem';
        btn.textContent = `Short #${idx + 1}`;
        fetchMetadata(jobId, filename).then(m => {
          if (m && m.duration) {
            const mSec = Math.round(m.duration);
            const mMin = Math.floor(mSec / 60);
            const sSec = String(mSec % 60).padStart(2, '0');
            btn.textContent = `Short #${idx + 1} (${mMin}:${sSec})`;
            if (m.title) btn.title = `${m.title} · ${m.duration}s`;
          }
        });
        btn.addEventListener('click', () => {
          $$('#betaClipSwitcher button').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          playBetaClip(jobId, filename);
        });
        clipSwitcher.appendChild(btn);
      });

      playBetaClip(jobId, outputs[0]);
    } catch (err) {
      logBox.textContent += `[Error] Failed to fetch job outputs: ${err.message}\n`;
    }
  }

  function playBetaClip(jobId, filename) {
    betaState.selectedClip = filename;
    const url = `/media/${jobId}/${encodeURIComponent(filename)}`;
    placeholder.style.display = 'none';
    if (betaSplitOverlay) betaSplitOverlay.style.display = 'none';
    resultVideo.style.display = 'block';
    resultVideo.src = url;
    resultVideo.load();
    resultVideo.play().catch(() => { });

    const clipMeta = $('#betaClipMeta');
    if (clipMeta) {
      clipMeta.style.display = 'flex';
      clipMeta.innerHTML = `<span style="color:#ffffff;font-weight:600;">⏱️ Result Time:</span> <span>Loading duration…</span>`;
    }

    resultVideo.onloadedmetadata = () => {
      const dur = Math.round(resultVideo.duration || 0);
      const dm = Math.floor(dur / 60);
      const ds = String(dur % 60).padStart(2, '0');
      if (clipMeta && !clipMeta.dataset.hasMeta) {
        clipMeta.innerHTML = `<span style="color:#ffffff;font-weight:600;">⏱️ Result Time:</span> <b>${dm}:${ds}</b> (${dur}s duration) &nbsp;·&nbsp; <span style="color:var(--accent);">📐 1080×1920</span>`;
      }
      // Reveal timeline trimmer under video preview
      const scrubber = $('#betaScrubberTimeline');
      if (scrubber) scrubber.style.display = 'block';
      if (betaTextEnd && (!+betaTextEnd.value || +betaTextEnd.value > dur)) {
        betaTextEnd.value = dur.toFixed(1);
      }
      syncTextOverlayStyles();
    };

    fetchMetadata(jobId, filename).then((m) => {
      if (m && clipMeta) {
        clipMeta.dataset.hasMeta = '1';
        const dur = Math.round(m.duration || resultVideo.duration || 0);
        const dm = Math.floor(dur / 60);
        const ds = String(dur % 60).padStart(2, '0');
        const st = Math.round(m.start_time || 0);
        const sm = Math.floor(st / 60);
        const ss = String(st % 60).padStart(2, '0');
        const et = Math.round(m.end_time || (st + dur));
        const em = Math.floor(et / 60);
        const es = String(et % 60).padStart(2, '0');
        clipMeta.innerHTML = `<span style="color:#ffffff;font-weight:600;">⏱️ Result Time:</span> <b>${dm}:${ds}</b> (${dur}s) &nbsp;·&nbsp; <span>📍 Cut: ${sm}:${ss} – ${em}:${es}</span> &nbsp;·&nbsp; <span style="color:var(--accent);">📐 1080×1920</span>`;
      }
    });

    downloadBtn.href = `${url}?download=1`;
    downloadBtn.style.pointerEvents = 'auto';
    downloadBtn.style.opacity = '1';

    openInEditorBtn.disabled = false;
    openInEditorBtn.onclick = () => {
      window.location.hash = `#editor?video=${encodeURIComponent(url)}&title=${encodeURIComponent(filename)}`;
    };

    // Store original and current clip for text modification workflow
    betaState.originalClipUrl = url;
    betaState.originalFilename = filename;
    betaState.currentClipUrl = url;
    betaState.currentFilename = filename;

    // Initialize interactive text overlay for this clip
    if (betaTextDragOverlay) {
      betaTextDragOverlay.style.display = 'block';
      syncTextOverlayStyles();
    }
  }

  // ==========================================
  // Interactive Timed & Draggable Text Overlay
  // ==========================================
  const betaTextDragOverlay = $('#betaTextDragOverlay');
  const betaTextDragContent = $('#betaTextDragContent');
  const betaDragCoordBadge = $('#betaDragCoordBadge');
  const betaDragTimeBadge = $('#betaDragTimeBadge');
  const betaTextInput = $('#betaTextInput');
  const betaTextEnableToggle = $('#betaTextEnableToggle');
  const betaTextStart = $('#betaTextStart');
  const betaTextEnd = $('#betaTextEnd');
  const betaBtnSetStart = $('#betaBtnSetStart');
  const betaBtnSetEnd = $('#betaBtnSetEnd');
  const betaBtnFullDuration = $('#betaBtnFullDuration');
  const betaTimelineSpanBar = $('#betaTimelineSpanBar');
  const betaTimelineCurrentMarker = $('#betaTimelineCurrentMarker');
  const betaTimelineActiveLabel = $('#betaTimelineActiveLabel');
  const betaTimelineEndLabel = $('#betaTimelineEndLabel');
  const betaTextX = $('#betaTextX');
  const betaTextY = $('#betaTextY');
  const betaTextXOut = $('#betaTextXOut');
  const betaTextYOut = $('#betaTextYOut');
  const betaPosTop = $('#betaPosTop');
  const betaPosCenter = $('#betaPosCenter');
  const betaPosBottom = $('#betaPosBottom');
  const betaTextSize = $('#betaTextSize');
  const betaTextSizeOut = $('#betaTextSizeOut');
  const betaTextColor = $('#betaTextColor');
  const betaTextFont = $('#betaTextFont');
  const betaTextBgEnable = $('#betaTextBgEnable');
  const betaTextBgColor = $('#betaTextBgColor');
  const betaApplyTextBtn = $('#betaApplyTextBtn');
  const betaResetTextBtn = $('#betaResetTextBtn');
  const betaTextStatusMsg = $('#betaTextStatusMsg');

  function syncTextOverlayStyles() {
    if (!betaTextDragOverlay || !betaTextDragContent) return;

    const text = (betaTextInput && betaTextInput.value) ? betaTextInput.value : 'WAIT FOR IT! 😱';
    betaTextDragContent.textContent = text;

    const xVal = betaTextX ? +betaTextX.value : 50;
    const yVal = betaTextY ? +betaTextY.value : 25;
    if (betaTextXOut) betaTextXOut.textContent = `${xVal}%`;
    if (betaTextYOut) betaTextYOut.textContent = `${yVal}%`;

    betaTextDragOverlay.style.left = `${xVal}%`;
    betaTextDragOverlay.style.top = `${yVal}%`;

    if (betaDragCoordBadge) betaDragCoordBadge.textContent = `${xVal}%, ${yVal}%`;

    const sizeVal = betaTextSize ? +betaTextSize.value : 42;
    if (betaTextSizeOut) betaTextSizeOut.textContent = `${sizeVal}px`;
    const frame = betaPreviewFrame || $('#betaPreviewFrame');
    const frameWidth = (frame && frame.clientWidth > 0) ? frame.clientWidth : 320;
    // In FFmpeg app.py: fs_canvas = max(24, round(sizeVal * 2.4)) on 1080px canvas
    // Proportional video aspect ratio match:
    const betaFs = Math.max(11, Math.round(frameWidth * ((sizeVal * 2.4) / 1080)));
    betaTextDragContent.style.fontSize = `${betaFs}px`;
    const betaBadge = $('#betaTextSizeBadge');
    if (betaBadge) betaBadge.textContent = `${sizeVal}px`;

    if (betaTextColor) betaTextDragContent.style.color = betaTextColor.value;
    if (betaTextFont) betaTextDragContent.style.fontFamily = `"${betaTextFont.value}", Impact, sans-serif`;

    const bgOn = betaTextBgEnable ? betaTextBgEnable.checked : true;
    const bgCol = betaTextBgColor ? betaTextBgColor.value : '#000000';
    if (bgOn) {
      betaTextDragContent.style.background = `${bgCol}b3`;
      betaTextDragContent.style.border = '2px dashed rgba(250, 204, 21, 0.7)';
    } else {
      betaTextDragContent.style.background = 'transparent';
      betaTextDragContent.style.border = '2px dashed rgba(255, 255, 255, 0.4)';
    }

    function fmtMinSec(sec) {
      if (isNaN(sec) || sec < 0) sec = 0;
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      return `${m}:${String(s).padStart(2, '0')}`;
    }
    function fmtDurMinSec(sec) {
      if (isNaN(sec) || sec < 0) sec = 0;
      const m = Math.floor(sec / 60);
      const s = Math.round(sec % 60);
      if (m > 0) return `${m}m ${s}s`;
      return `0m ${s}s`;
    }

    const sTime = betaTextStart ? Math.max(0, +betaTextStart.value) : 0;
    const eTime = betaTextEnd ? Math.max(sTime + 0.1, +betaTextEnd.value) : 5.0;
    if (betaDragTimeBadge) betaDragTimeBadge.textContent = `${fmtMinSec(sTime)} – ${fmtMinSec(eTime)} (${fmtDurMinSec(eTime - sTime)})`;
    if (betaTimelineActiveLabel) betaTimelineActiveLabel.textContent = `Active: ${fmtMinSec(sTime)} – ${fmtMinSec(eTime)}`;

    const dur = (resultVideo && resultVideo.duration) ? resultVideo.duration : Math.max(10, eTime);
    if (betaTimelineEndLabel && resultVideo && resultVideo.duration) {
      betaTimelineEndLabel.textContent = fmtMinSec(dur);
    }

    const handleStart = $('#betaHandleStart');
    const handleEnd = $('#betaHandleEnd');
    const scrubHighlight = $('#betaScrubHighlight');
    const tooltipStart = $('#betaTooltipStart');
    const tooltipEnd = $('#betaTooltipEnd');
    const trimSpanBadge = $('#betaTrimSpanBadge');
    const trackMaxLabel = $('#betaTrackMaxLabel');

    if (dur > 0) {
      const sPct = Math.max(0, Math.min(100, (sTime / dur) * 100));
      const ePct = Math.max(sPct, Math.min(100, (eTime / dur) * 100));
      if (handleStart) handleStart.style.left = `${sPct}%`;
      if (handleEnd) handleEnd.style.left = `${ePct}%`;
      if (scrubHighlight) {
        scrubHighlight.style.left = `${sPct}%`;
        scrubHighlight.style.width = `${Math.max(1, ePct - sPct)}%`;
      }
      if (tooltipStart) tooltipStart.textContent = fmtMinSec(sTime);
      if (tooltipEnd) tooltipEnd.textContent = fmtMinSec(eTime);
      if (trimSpanBadge) {
        const diff = Math.max(0.1, eTime - sTime);
        trimSpanBadge.textContent = `${fmtMinSec(sTime)} – ${fmtMinSec(eTime)} (${fmtDurMinSec(diff)})`;
      }
      if (trackMaxLabel) {
        trackMaxLabel.textContent = fmtMinSec(dur);
      }
    }

    if (betaTimelineSpanBar) {
      const sPct = Math.max(0, Math.min(100, (sTime / dur) * 100));
      const ePct = Math.max(sPct, Math.min(100, (eTime / dur) * 100));
      betaTimelineSpanBar.style.left = `${sPct}%`;
      betaTimelineSpanBar.style.width = `${Math.max(2, ePct - sPct)}%`;
    }

    const enabled = betaTextEnableToggle ? betaTextEnableToggle.checked : true;
    if (!enabled) {
      betaTextDragOverlay.style.display = 'none';
      return;
    }

    if (resultVideo && resultVideo.src) {
      const cur = resultVideo.currentTime || 0;
      const inRange = (cur >= sTime && cur <= eTime);
      if (!resultVideo.paused) {
        betaTextDragOverlay.style.display = inRange ? 'block' : 'none';
      } else {
        betaTextDragOverlay.style.display = 'block';
        if (inRange) {
          betaTextDragOverlay.classList.remove('inactive-time');
        } else {
          betaTextDragOverlay.classList.add('inactive-time');
        }
      }
    }
  }
  window.syncTextOverlayStyles = syncTextOverlayStyles;

  // Draggable logic for text overlay
  if (betaTextDragOverlay && betaPreviewFrame) {
    let isDraggingText = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let initialXPct = 50;
    let initialYPct = 25;

    const onTextDragStart = (clientX, clientY) => {
      isDraggingText = true;
      dragStartX = clientX;
      dragStartY = clientY;
      initialXPct = betaTextX ? +betaTextX.value : 50;
      initialYPct = betaTextY ? +betaTextY.value : 25;
      betaTextDragOverlay.classList.add('dragging');
      document.body.style.cursor = 'grabbing';
    };

    const onTextDragMove = (clientX, clientY) => {
      if (!isDraggingText) return;
      const rect = betaPreviewFrame.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;

      const deltaX = clientX - dragStartX;
      const deltaY = clientY - dragStartY;

      const deltaXPct = (deltaX / rect.width) * 100;
      const deltaYPct = (deltaY / rect.height) * 100;

      const newX = Math.round(Math.max(5, Math.min(95, initialXPct + deltaXPct)));
      const newY = Math.round(Math.max(5, Math.min(95, initialYPct + deltaYPct)));

      if (betaTextX) betaTextX.value = newX;
      if (betaTextY) betaTextY.value = newY;

      syncTextOverlayStyles();
    };

    const onTextDragEnd = () => {
      if (isDraggingText) {
        isDraggingText = false;
        betaTextDragOverlay.classList.remove('dragging');
        document.body.style.cursor = '';
      }
    };

    betaTextDragOverlay.addEventListener('mousedown', (e) => {
      if (e.target.closest('.ctrl-btn-size') || e.target.closest('.overlay-resize-handle')) {
        return;
      }
      e.preventDefault();
      onTextDragStart(e.clientX, e.clientY);
    });

    window.addEventListener('mousemove', (e) => {
      if (isDraggingText) {
        e.preventDefault();
        onTextDragMove(e.clientX, e.clientY);
      }
    });

    window.addEventListener('mouseup', onTextDragEnd);

    // Touch support for drag
    betaTextDragOverlay.addEventListener('touchstart', (e) => {
      if (e.target.closest('.ctrl-btn-size') || e.target.closest('.overlay-resize-handle')) {
        return;
      }
      if (e.touches && e.touches[0]) {
        onTextDragStart(e.touches[0].clientX, e.touches[0].clientY);
      }
    }, { passive: true });

    window.addEventListener('touchmove', (e) => {
      if (isDraggingText && e.touches && e.touches[0]) {
        onTextDragMove(e.touches[0].clientX, e.touches[0].clientY);
      }
    }, { passive: true });

    window.addEventListener('touchend', onTextDragEnd);
  }

  // Input event bindings
  [betaTextInput, betaTextColor, betaTextFont, betaTextBgColor].forEach((el) => {
    if (el) el.addEventListener('input', syncTextOverlayStyles);
  });

  [betaTextX, betaTextY, betaTextSize].forEach((el) => {
    if (el) el.addEventListener('input', syncTextOverlayStyles);
  });

  [betaTextStart, betaTextEnd, betaTextBgEnable, betaTextEnableToggle].forEach((el) => {
    if (el) el.addEventListener('change', syncTextOverlayStyles);
  });

  // Quick alignment pills
  if (betaPosTop) betaPosTop.addEventListener('click', () => { if (betaTextY) betaTextY.value = 15; syncTextOverlayStyles(); });
  if (betaPosCenter) betaPosCenter.addEventListener('click', () => { if (betaTextY) betaTextY.value = 50; syncTextOverlayStyles(); });
  if (betaPosBottom) betaPosBottom.addEventListener('click', () => { if (betaTextY) betaTextY.value = 75; syncTextOverlayStyles(); });

  // Playhead timing buttons
  if (betaBtnSetStart && resultVideo) {
    betaBtnSetStart.addEventListener('click', () => {
      const cur = +(resultVideo.currentTime || 0).toFixed(1);
      if (betaTextStart) betaTextStart.value = cur;
      if (betaBtnSetStart) betaBtnSetStart.textContent = `Start: ${cur}s`;
      syncTextOverlayStyles();
    });
  }

  if (betaBtnSetEnd && resultVideo) {
    betaBtnSetEnd.addEventListener('click', () => {
      const cur = +(resultVideo.currentTime || 0).toFixed(1);
      if (betaTextEnd) betaTextEnd.value = Math.max(+(betaTextStart?.value || 0) + 0.1, cur);
      if (betaBtnSetEnd) betaBtnSetEnd.textContent = `End: ${cur}s`;
      syncTextOverlayStyles();
    });
  }

  if (betaBtnFullDuration && resultVideo) {
    betaBtnFullDuration.addEventListener('click', () => {
      const dur = +(resultVideo.duration || 10).toFixed(1);
      if (betaTextStart) betaTextStart.value = 0.0;
      if (betaTextEnd) betaTextEnd.value = dur;
      syncTextOverlayStyles();
    });
  }

  // Dual-Handle Scrubber Timeline Dragging
  const handleStartEl = $('#betaHandleStart');
  const handleEndEl = $('#betaHandleEnd');
  const trackContainerEl = $('#betaScrubTrackContainer');
  const trimResetFullBtn = $('#betaTrimResetFull');

  if (trimResetFullBtn) {
    trimResetFullBtn.addEventListener('click', () => {
      const dur = (resultVideo && resultVideo.duration) ? resultVideo.duration : 60;
      if (betaTextStart) betaTextStart.value = '0.0';
      if (betaTextEnd) betaTextEnd.value = dur.toFixed(1);
      syncTextOverlayStyles();
    });
  }

  function setupScrubberHandleDrag(handleEl, isStart) {
    if (!handleEl || !trackContainerEl) return;
    let dragging = false;

    const onStart = (e) => {
      dragging = true;
      e.preventDefault();
      handleEl.classList.add('active-drag');
      document.body.style.userSelect = 'none';
    };

    const onMove = (clientX) => {
      if (!dragging) return;
      const rect = trackContainerEl.getBoundingClientRect();
      if (rect.width <= 0) return;
      const rawPct = Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100));
      const dur = (resultVideo && resultVideo.duration) ? resultVideo.duration : 60;

      if (isStart) {
        const curEndSec = betaTextEnd ? +betaTextEnd.value : dur;
        const curEndPct = Math.min(100, (curEndSec / dur) * 100);
        const clampedPct = Math.min(rawPct, Math.max(0, curEndPct - 1.0));
        const newSec = Math.max(0, (clampedPct / 100) * dur);
        if (betaTextStart) betaTextStart.value = newSec.toFixed(1);
        if (resultVideo) resultVideo.currentTime = newSec;
      } else {
        const curStartSec = betaTextStart ? +betaTextStart.value : 0;
        const curStartPct = Math.max(0, (curStartSec / dur) * 100);
        const clampedPct = Math.max(rawPct, Math.min(100, curStartPct + 1.0));
        const newSec = Math.min(dur, (clampedPct / 100) * dur);
        if (betaTextEnd) betaTextEnd.value = newSec.toFixed(1);
        if (resultVideo) resultVideo.currentTime = newSec;
      }
      syncTextOverlayStyles();
    };

    const onEnd = () => {
      if (dragging) {
        dragging = false;
        handleEl.classList.remove('active-drag');
        document.body.style.userSelect = '';
      }
    };

    handleEl.addEventListener('mousedown', onStart);
    window.addEventListener('mousemove', (e) => { if (dragging) onMove(e.clientX); });
    window.addEventListener('mouseup', onEnd);

    handleEl.addEventListener('touchstart', (e) => {
      if (e.touches.length > 0) onStart(e);
    }, { passive: false });
    window.addEventListener('touchmove', (e) => {
      if (dragging && e.touches.length > 0) onMove(e.touches[0].clientX);
    }, { passive: true });
    window.addEventListener('touchend', onEnd);
  }

  setupScrubberHandleDrag(handleStartEl, true);
  setupScrubberHandleDrag(handleEndEl, false);

  // Synchronize playback timeline and active overlay display
  if (resultVideo) {
    resultVideo.addEventListener('timeupdate', () => {
      const dur = resultVideo.duration || 1;
      const cur = resultVideo.currentTime || 0;
      if (betaTimelineCurrentMarker) {
        betaTimelineCurrentMarker.style.left = `${Math.min(100, Math.max(0, (cur / dur) * 100))}%`;
      }
      syncTextOverlayStyles();
    });

    resultVideo.addEventListener('play', () => syncTextOverlayStyles());
    resultVideo.addEventListener('pause', () => syncTextOverlayStyles());
  }

  // Burn & Apply Text to Short
  if (betaApplyTextBtn) {
    betaApplyTextBtn.addEventListener('click', async () => {
      if (!betaState.jobId || !betaState.selectedClip) {
        alert('Please run or select a Short first.');
        return;
      }
      const text = betaTextInput ? betaTextInput.value.trim() : '';
      if (!text) {
        alert('Enter some text to burn onto the video.');
        return;
      }

      betaApplyTextBtn.disabled = true;
      betaApplyTextBtn.innerHTML = '<span class="btn-update-icon spinning">↻</span> Rendering Text onto Short…';
      if (betaTextStatusMsg) {
        betaTextStatusMsg.style.display = 'block';
        betaTextStatusMsg.style.color = '#facc15';
        betaTextStatusMsg.textContent = 'Rendering timed text overlay with FFmpeg…';
      }

      try {
        const payload = {
          job_id: betaState.jobId,
          filename: betaState.selectedClip,
          text: text,
          start_time: betaTextStart ? +betaTextStart.value : 0.0,
          end_time: betaTextEnd ? +betaTextEnd.value : 5.0,
          x: betaTextX ? +betaTextX.value : 50,
          y: betaTextY ? +betaTextY.value : 25,
          font_size: betaTextSize ? +betaTextSize.value : 42,
          font_name: betaTextFont ? betaTextFont.value : 'Montserrat Extra Bold',
          color: betaTextColor ? betaTextColor.value : '#facc15',
          bg_enabled: betaTextBgEnable ? betaTextBgEnable.checked : true,
          bg_color: betaTextBgColor ? betaTextBgColor.value : '#000000',
          bg_opacity: 65,
        };

        const res = await fetch('/api/beta/apply-text', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || 'Failed to burn text');

        // Update video to the newly rendered clip
        betaState.currentClipUrl = data.url;
        betaState.currentFilename = data.filename;
        resultVideo.src = data.url;
        resultVideo.load();
        resultVideo.play().catch(() => {});

        // Update download button
        downloadBtn.href = `${data.url}&download=1`;
        downloadBtn.download = data.filename;

        if (betaTextStatusMsg) {
          betaTextStatusMsg.style.color = '#4ade80';
          betaTextStatusMsg.textContent = `✓ Text overlay successfully burned into video! (${data.filename})`;
        }
      } catch (err) {
        if (betaTextStatusMsg) {
          betaTextStatusMsg.style.color = '#ef4444';
          betaTextStatusMsg.textContent = `Error: ${err.message}`;
        }
        alert('Could not apply text overlay: ' + err.message);
      } finally {
        betaApplyTextBtn.disabled = false;
        betaApplyTextBtn.innerHTML = '<span>✨ Burn & Apply Text to Short</span>';
      }
    });
  }

  // Reset to original clip
  if (betaResetTextBtn) {
    betaResetTextBtn.addEventListener('click', () => {
      if (betaState.originalClipUrl && resultVideo) {
        resultVideo.src = betaState.originalClipUrl;
        resultVideo.load();
        resultVideo.play().catch(() => {});
        downloadBtn.href = `${betaState.originalClipUrl}?download=1`;
        downloadBtn.download = betaState.originalFilename || 'short.mp4';
        if (betaTextStatusMsg) {
          betaTextStatusMsg.style.color = '#38bdf8';
          betaTextStatusMsg.textContent = 'Restored unmodified original Short.';
        }
      }
    });
  }
}

// ============================================================================
// INSTANT CLIPPING LAB CONTROLLER (ISOLATED ULTRA-FAST 9:16 PIPELINE)
// ============================================================================
function initInstantClippingSection() {
  const dropzone = $('#instantDropzone');
  const fileInput = $('#instantFileInput');
  const selectedBadge = $('#instantSelectedFile');
  const selectedName = $('#instantSelectedFileName');
  const selectedDur = $('#instantSelectedFileDur');
  const clearFileBtn = $('#btnInstantClearFile');
  const ytInput = $('#instantYtUrl');
  const ytFetchBtn = $('#btnInstantFetchYt');
  const durationBtns = $$('#instantDurationGroup .instant-choice-btn');
  const layoutBtns = $$('#instantLayoutGroup .instant-choice-btn');
  const captionsBtns = $$('#instantCaptionsGroup .instant-choice-btn');
  const clipsCountBtns = $$('#instantClipsCountGroup .instant-choice-btn');
  const startBtns = $$('#instantStartGroup .instant-choice-btn');
  const customStartBox = $('#instantCustomStartBox');
  const customStartSec = $('#instantCustomStartSec');
  const startClipBtn = $('#btnStartInstantClip');
  const statusPill = $('#instantStatusPill');
  const previewBox = $('#instantPreviewFrame');
  const videoPlayer = $('#instantVideoPlayer');
  const emptyPreview = $('#instantEmptyPreview');
  const multiClipBar = $('#instantMultiClipBar');
  const exportActions = $('#instantExportActions');
  const generateAnotherBtn = $('#btnInstantGenerateAnother');
  const downloadBtn = $('#btnInstantDownload');
  const downloadAllBtn = $('#btnInstantDownloadAll');
  const openEditorBtn = $('#btnInstantOpenEditor');
  const consoleLog = $('#instantConsoleLog');
  const copyLogBtn = $('#btnCopyInstantLog');

  let instantState = window.instantState = {
    jobId: null,
    sourceFile: null,
    sourceFileName: '',
    sourceDuration: 0,
    youtubeUrl: '',
    loadedYtUrl: '',
    clipIteration: 0,
    duration: 30,
    layout: 'center_crop',
    captions: 'yes',
    numClips: 1,
    startMode: 'auto',
    running: false,
    outputUrl: null,
    outputFile: null,
    outputs: [],
    activeClipIndex: 0
  };

  function addLog(msg, type = 'info') {
    if (!consoleLog) return;
    const line = document.createElement('div');
    line.className = `console-line ${type}`;
    line.textContent = msg;
    consoleLog.appendChild(line);
    consoleLog.scrollTop = consoleLog.scrollHeight;
  }

  // --- Button Group Helpers ---
  function setupChoiceGroup(buttons, onSelect) {
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        buttons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        onSelect(btn.dataset.val);
      });
    });
  }

  setupChoiceGroup(durationBtns, (val) => {
    instantState.duration = parseFloat(val) || 30;
    addLog(`[Instant] Target duration set to ${instantState.duration}s`);
  });

  setupChoiceGroup(layoutBtns, (val) => {
    instantState.layout = val || 'center_crop';
    addLog(`[Instant] Framing preset set to: ${val}`);
  });

  setupChoiceGroup(captionsBtns, (val) => {
    instantState.captions = val || 'yes';
    addLog(`[Instant] Captions mode set to: ${val === 'yes' ? 'Kinetic Captions (Animated)' : 'Clean (No Captions)'}`);
  });

  setupChoiceGroup(clipsCountBtns, (val) => {
    instantState.numClips = parseInt(val, 10) || 1;
    addLog(`[Instant] Number of output clips set to: ${instantState.numClips}`);
  });

  setupChoiceGroup(startBtns, (val) => {
    instantState.startMode = val || 'auto';
    if (customStartBox) {
      customStartBox.style.display = val === 'custom' ? 'block' : 'none';
    }
    addLog(`[Instant] Hook selection mode: ${val}`);
  });

  // --- File Upload & Dropzone Handling ---
  if (dropzone && fileInput) {
    dropzone.addEventListener('click', (e) => {
      if (e.target.closest('.instant-file-clear')) return;
      fileInput.click();
    });

    ['dragenter', 'dragover'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
      });
    });

    dropzone.addEventListener('drop', (e) => {
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) {
        handleFileSelection(files[0]);
      }
    });

    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length > 0) {
        handleFileSelection(fileInput.files[0]);
      }
    });
  }

  async function handleFileSelection(file) {
    if (!file || !file.type.startsWith('video/')) {
      alert('Please select a valid video file (.mp4, .mov, .mkv).');
      return;
    }
    instantState.sourceFile = file;
    instantState.sourceFileName = file.name;
    if (selectedBadge) selectedBadge.style.display = 'flex';
    if (selectedName) selectedName.textContent = file.name;
    if (selectedDur) selectedDur.textContent = 'Uploading...';
    addLog(`[Instant] Uploading ${file.name} to isolated workspace...`);

    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch('/api/instant/upload', {
        method: 'POST',
        body: form
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Upload failed');

      instantState.jobId = data.job_id;
      instantState.clipIteration = 0;
      instantState.loadedYtUrl = '';
      instantState.youtubeUrl = '';
      instantState.sourceDuration = data.duration || 0;
      if (selectedDur) selectedDur.textContent = `${(data.duration || 0).toFixed(1)}s`;
      addLog(`[Instant] Video ready: ${data.filename} (${(data.duration || 0).toFixed(1)}s)`, 'success');
      if (ytInput) ytInput.value = '';
    } catch (err) {
      addLog(`[Instant] Upload error: ${err.message}`, 'warn');
      alert(`Upload failed: ${err.message}`);
    }
  }

  if (clearFileBtn) {
    clearFileBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      instantState.sourceFile = null;
      instantState.jobId = null;
      instantState.sourceFileName = '';
      instantState.sourceDuration = 0;
      instantState.clipIteration = 0;
      if (fileInput) fileInput.value = '';
      if (selectedBadge) selectedBadge.style.display = 'none';
      addLog('[Instant] Source video cleared.');
    });
  }

  // --- YouTube Input & Fetch Listeners ---
  if (ytInput) {
    const handleYtInputChange = () => {
      const currentUrl = ytInput.value.trim();
      if (currentUrl && currentUrl !== instantState.loadedYtUrl) {
        // Different video link entered: reset old job so new video is fetched fresh
        instantState.jobId = null;
        instantState.sourceFile = null;
        instantState.clipIteration = 0;
        instantState.loadedYtUrl = currentUrl;
        instantState.youtubeUrl = currentUrl;
        if (selectedBadge) selectedBadge.style.display = 'none';
      }
    };
    ytInput.addEventListener('input', handleYtInputChange);
    ytInput.addEventListener('change', handleYtInputChange);
    ytInput.addEventListener('paste', () => setTimeout(handleYtInputChange, 50));
  }

  if (ytFetchBtn && ytInput) {
    ytFetchBtn.addEventListener('click', () => {
      const url = ytInput.value.trim();
      if (!url) {
        alert('Please paste a YouTube URL first.');
        return;
      }
      if (!url.includes('youtube.com') && !url.includes('youtu.be')) {
        alert('Please enter a valid YouTube video link.');
        return;
      }
      // If URL changed from before, reset job and iteration
      if (url !== instantState.loadedYtUrl) {
        instantState.jobId = null;
        instantState.clipIteration = 0;
      }
      instantState.youtubeUrl = url;
      instantState.loadedYtUrl = url;
      instantState.sourceFile = null;
      if (selectedBadge) selectedBadge.style.display = 'none';
      addLog(`[Instant] YouTube stream link loaded: ${url}`, 'step');
      alert('YouTube link ready! Choose your preset and click "Generate Instant Short".');
    });
  }

  // --- Copy Console Log ---
  if (copyLogBtn && consoleLog) {
    copyLogBtn.addEventListener('click', async () => {
      const text = consoleLog.innerText || consoleLog.textContent;
      try {
        await navigator.clipboard.writeText(text);
        copyLogBtn.textContent = 'Copied! ✓';
        setTimeout(() => { copyLogBtn.textContent = 'Copy Log'; }, 1800);
      } catch (_) {
        alert('Could not copy log text.');
      }
    });
  }

  // --- Core Instant Clip Runner ---
  async function runInstantClip(isAnother = false) {
    if (instantState.running) return;

    const currentYt = ytInput ? ytInput.value.trim() : '';

    if (!isAnother) {
      // If user typed/pasted a new YouTube link, reset old job
      if (currentYt && currentYt !== instantState.loadedYtUrl) {
        instantState.jobId = null;
        instantState.sourceFile = null;
        instantState.clipIteration = 0;
        instantState.loadedYtUrl = currentYt;
        instantState.youtubeUrl = currentYt;
      }
    }

    if (!instantState.jobId && !currentYt && !instantState.sourceFile) {
      if (state.jobId) {
        instantState.jobId = state.jobId;
        addLog(`[Instant] Reusing active project video: ${state.jobId}`);
      } else {
        alert('Please drop a source video or enter a YouTube link before generating.');
        return;
      }
    }

    instantState.running = true;
    startClipBtn.disabled = true;
    if (generateAnotherBtn) {
      generateAnotherBtn.disabled = true;
      generateAnotherBtn.innerHTML = '<span>⚡ Rendering Next Hook...</span>';
    }

    const iterDisplay = instantState.clipIteration > 0 ? ` (Clip #${instantState.clipIteration + 1})` : '';
    startClipBtn.innerHTML = `<span>⚡ Rendering Instant Short${iterDisplay}...</span>`;
    if (statusPill) {
      statusPill.className = 'instant-status-pill status-running';
      statusPill.textContent = isAnother ? `Rendering Clip #${instantState.clipIteration + 1}...` : 'Processing...';
    }

    if (isAnother) {
      addLog(`[Instant] ⚡ Finding and cutting a completely different hook (Iteration #${instantState.clipIteration + 1})...`, 'step');
    } else {
      addLog('[Instant] Launching isolated high-speed render...', 'step');
    }

    try {
      const payload = {
        job_id: instantState.jobId,
        youtube_url: currentYt || instantState.youtubeUrl,
        duration: instantState.duration,
        layout: instantState.layout,
        captions: instantState.captions,
        num_clips: instantState.numClips,
        start_mode: isAnother ? 'auto' : instantState.startMode,
        custom_start: customStartSec ? parseFloat(customStartSec.value) || 0 : 0,
        iteration: instantState.clipIteration
      };

      const res = await fetch('/api/instant/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'Failed to start instant pipeline');

      const activeJobId = data.job_id;
      instantState.jobId = activeJobId;
      addLog(`[Instant] Engine worker running for Job: ${activeJobId}`);

      // Poll instant status
      let seenLogs = 0;
      const pollInterval = setInterval(async () => {
        try {
          const pollRes = await fetch(`/api/instant/status/${activeJobId}`, { cache: 'no-store' });
          if (!pollRes.ok) return;
          const statusData = await pollRes.json();
          if (!statusData.ok) return;

          // Stream new logs
          if (Array.isArray(statusData.logs) && statusData.logs.length > seenLogs) {
            const newLines = statusData.logs.slice(seenLogs);
            newLines.forEach(l => {
              let type = 'info';
              if (l.includes('ERROR:')) type = 'warn';
              else if (l.includes('✔') || l.includes('🎉')) type = 'success';
              else if (l.includes('⚡') || l.includes('Applying')) type = 'step';
              addLog(l, type);
            });
            seenLogs = statusData.logs.length;
          }

          // Update button label
          if (statusData.progress) {
            startClipBtn.innerHTML = `<span>⚡ Rendering Instant Shorts (${statusData.progress}%)...</span>`;
          }

          if (statusData.status === 'done') {
            clearInterval(pollInterval);
            instantState.running = false;
            startClipBtn.disabled = false;
            startClipBtn.innerHTML = '<span>⚡ Generate Instant Shorts (Fast Mode)</span>';
            if (generateAnotherBtn) {
              generateAnotherBtn.disabled = false;
              generateAnotherBtn.innerHTML = '<span>⚡ Generate Another Clip</span>';
            }
            if (statusPill) {
              statusPill.className = 'instant-status-pill status-done';
              statusPill.textContent = 'Finished ✔';
            }

            // Multi-clip and display setup
            const outputs = Array.isArray(statusData.outputs) && statusData.outputs.length > 0
              ? statusData.outputs
              : [statusData.filename || 'instant_short.mp4'];
            instantState.outputs = outputs;
            instantState.activeClipIndex = 0;

            function selectClip(idx) {
              instantState.activeClipIndex = idx;
              const filename = outputs[idx];
              const clipUrl = `/media/${activeJobId}/${filename}`;
              instantState.outputUrl = clipUrl;
              instantState.outputFile = filename;

              if (videoPlayer) {
                videoPlayer.src = clipUrl;
                videoPlayer.style.display = 'block';
                videoPlayer.load();
                videoPlayer.play().catch(() => {});
              }
              if (emptyPreview) emptyPreview.style.display = 'none';

              if (downloadBtn) {
                downloadBtn.href = `${clipUrl}?download=1`;
                downloadBtn.download = filename;
                downloadBtn.textContent = outputs.length > 1 ? `Download Clip ${idx + 1} ↓` : `Download Short ↓`;
              }

              if (multiClipBar) {
                multiClipBar.querySelectorAll('.instant-clip-tab').forEach((tab, tIdx) => {
                  tab.classList.toggle('active', tIdx === idx);
                });
              }
            }

            if (multiClipBar) {
              if (outputs.length > 1) {
                multiClipBar.style.display = 'flex';
                multiClipBar.innerHTML = '';
                outputs.forEach((out, i) => {
                  const tab = document.createElement('button');
                  tab.type = 'button';
                  tab.className = `instant-clip-tab ${i === 0 ? 'active' : ''}`;
                  tab.textContent = `Clip ${i + 1}`;
                  tab.addEventListener('click', () => selectClip(i));
                  multiClipBar.appendChild(tab);
                });

                if (downloadAllBtn) {
                  downloadAllBtn.style.display = 'block';
                  downloadAllBtn.onclick = () => {
                    outputs.forEach((out, i) => {
                      setTimeout(() => {
                        const a = document.createElement('a');
                        a.href = `/media/${activeJobId}/${out}?download=1`;
                        a.download = out;
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                      }, i * 350);
                    });
                  };
                }
              } else {
                multiClipBar.style.display = 'none';
                if (downloadAllBtn) downloadAllBtn.style.display = 'none';
              }
            }

            if (exportActions) exportActions.style.display = 'flex';
            selectClip(0);

            const clipLabel = isAnother ? `Different Clip #${instantState.clipIteration + 1}` : 'Instant Short';
            addLog(`[Instant] ✔ ${clipLabel} ready! (${outputs.length} clip${outputs.length > 1 ? 's' : ''})`, 'success');
          } else if (statusData.status === 'error') {
            clearInterval(pollInterval);
            instantState.running = false;
            startClipBtn.disabled = false;
            startClipBtn.innerHTML = '<span>⚡ Retry Instant Short</span>';
            if (generateAnotherBtn) {
              generateAnotherBtn.disabled = false;
              generateAnotherBtn.innerHTML = '<span>⚡ Generate Another Clip</span>';
            }
            if (statusPill) {
              statusPill.className = 'instant-status-pill status-ready';
              statusPill.textContent = 'Failed';
            }
            alert(`Instant render failed: ${statusData.detail || statusData.error || 'Unknown error'}`);
          }
        } catch (err) {
          console.error('[Instant] Status poll error:', err);
        }
      }, 1000);

    } catch (err) {
      instantState.running = false;
      startClipBtn.disabled = false;
      startClipBtn.innerHTML = '<span>⚡ Generate Instant Shorts (Fast Mode)</span>';
      if (generateAnotherBtn) {
        generateAnotherBtn.disabled = false;
        generateAnotherBtn.innerHTML = '<span>⚡ Generate Another Clip</span>';
      }
      if (statusPill) {
        statusPill.className = 'instant-status-pill status-ready';
        statusPill.textContent = 'Ready';
      }
      addLog(`[Instant] Launch error: ${err.message}`, 'warn');
      alert(`Could not start instant clipping: ${err.message}`);
    }
  }

  // --- Wire Buttons ---
  if (startClipBtn) {
    startClipBtn.addEventListener('click', () => {
      runInstantClip(false);
    });
  }

  if (generateAnotherBtn) {
    generateAnotherBtn.addEventListener('click', () => {
      if (instantState.running) return;
      instantState.clipIteration += 1;
      runInstantClip(true);
    });
  }

  // --- Open in Editor Action ---
  if (openEditorBtn) {
    openEditorBtn.addEventListener('click', () => {
      if (!instantState.jobId || !instantState.outputFile) {
        alert('No instant short rendered yet.');
        return;
      }
      state.jobId = instantState.jobId;
      state.reviewFile = instantState.outputFile;
      if (typeof selectReview === 'function') {
        selectReview(instantState.jobId, instantState.outputFile);
      }
      navigateTo('editor');
    });
  }
}

// Auto-initialize Instant Clipping Lab
initInstantClippingSection();
