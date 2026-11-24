/**
 * Clipify AI - Live Studio Frontend Controller
 * Minimal Monochrome Workspace (Tweak IDE Inspired)
 */
(function() {
  'use strict';

  let pollInterval = null;
  let currentSourceType = 'youtube';
  let isSessionActive = false;
  let lastPreviewFetch = 0;

  // DOM Elements
  const sourceTabs = document.querySelectorAll('.source-tab');
  const liveSourceUrl = document.getElementById('liveSourceUrl');
  const btnConnectStream = document.getElementById('btnConnectStream');
  const btnDisconnectStream = document.getElementById('btnDisconnectStream');
  const btnConnectObs = document.getElementById('btnConnectObs');
  const btnDisconnectObs = document.getElementById('btnDisconnectObs');
  const btnRetryConnection = document.getElementById('btnRetryConnection');
  const btnInstantClip = document.getElementById('btnInstantClip');
  const streamLiveBadge = document.getElementById('streamLiveBadge');
  const streamLiveText = document.getElementById('streamLiveText');
  const monitorTitle = document.getElementById('monitorTitle');
  const streamAuthor = document.getElementById('streamAuthor');
  const streamOverlayTitle = document.getElementById('streamOverlayTitle');
  const telemetryElapsed = document.getElementById('telemetryElapsed');
  const telemetryBuffer = document.getElementById('telemetryBuffer');
  const telemetryChunks = document.getElementById('telemetryChunks');
  const overlayElapsed = document.getElementById('overlayElapsed');
  const overlayBuffer = document.getElementById('overlayBuffer');

  // Monitor screen states
  const monitorIdleView = document.getElementById('monitorIdleView');
  const monitorLoadingView = document.getElementById('monitorLoadingView');
  const monitorLoadingTitle = document.getElementById('monitorLoadingTitle');
  const monitorLoadingDetail = document.getElementById('monitorLoadingDetail');
  const monitorLiveView = document.getElementById('monitorLiveView');
  const monitorVideoFrame = document.getElementById('monitorVideoFrame');
  const monitorFailedView = document.getElementById('monitorFailedView');
  const monitorFailedTitle = document.getElementById('monitorFailedTitle');
  const monitorFailedDetail = document.getElementById('monitorFailedDetail');

  // Feeds and Gallery
  const transcriptFeed = document.getElementById('transcriptFeed');
  const liveClipsGrid = document.getElementById('liveClipsGrid');
  const emptyClipsMsg = document.getElementById('emptyClipsMsg');
  const clipsCount = document.getElementById('clipsCount');
  const obsConfigBox = document.getElementById('obsConfigBox');
  const youtubeInputGroup = document.getElementById('youtubeInputGroup');

  // Preferences
  const sensitivitySlider = document.getElementById('sensitivitySlider');
  const sensitivityOut = document.getElementById('sensitivityOut');
  const toggleAutoClip = document.getElementById('toggleAutoClip');
  const chipAutoClip = document.getElementById('chipAutoClip');
  const chipSensitivity = document.getElementById('chipSensitivity');
  const bufferWindowSelect = document.getElementById('bufferWindowSelect');
  const liveModelSelect = document.getElementById('liveModelSelect');
  const clipFormatSelect = document.getElementById('clipFormatSelect');

  // AI Smart Editing Preferences
  const toggleAutoEdit = document.getElementById('toggleAutoEdit');
  const toggleFaceTrack = document.getElementById('toggleFaceTrack');
  const toggleGamingLayout = document.getElementById('toggleGamingLayout');
  const toggleAutoCaptions = document.getElementById('toggleAutoCaptions');
  const captionStyleSelect = document.getElementById('captionStyleSelect');
  const captionFontSelect = document.getElementById('captionFontSelect');
  const bgStyleSelect = document.getElementById('bgStyleSelect');
  const bgColorWrapper = document.getElementById('bgColorWrapper');
  const bgColorPicker = document.getElementById('bgColorPicker');
  const bgColorHex = document.getElementById('bgColorHex');
  const toggleCustomText = document.getElementById('toggleCustomText');
  const customTextSection = document.getElementById('customTextSection');
  const customTextInput = document.getElementById('customTextInput');
  const customTextPos = document.getElementById('customTextPos');
  const customTextColorPicker = document.getElementById('customTextColorPicker');
  const customTextColorHex = document.getElementById('customTextColorHex');
  const prefTargetClips = document.getElementById('prefTargetClips');
  const autoClipTargetInput = document.getElementById('autoClipTargetInput');

  // AI Clip Ranking & Batch Selection Elements
  const btnRankClipsAi = document.getElementById('btnRankClipsAi');
  const rankingConsolePanel = document.getElementById('rankingConsolePanel');
  const rankingConsoleBody = document.getElementById('rankingConsoleBody');
  const rankingStatusBadge = document.getElementById('rankingStatusBadge');
  const btnCloseRankingConsole = document.getElementById('btnCloseRankingConsole');

  const chkSelectAllClips = document.getElementById('chkSelectAllClips');
  const selectedClipsCounter = document.getElementById('selectedClipsCounter');
  const btnDeleteSelectedClips = document.getElementById('btnDeleteSelectedClips');

  const rankedClipsSection = document.getElementById('rankedClipsSection');
  const rankedClipsGrid = document.getElementById('rankedClipsGrid');
  const chkSelectAllRanked = document.getElementById('chkSelectAllRanked');
  const selectedRankedCounter = document.getElementById('selectedRankedCounter');
  const btnDeleteSelectedRanked = document.getElementById('btnDeleteSelectedRanked');

  // Selection & Ranking State
  const selectedClipIds = new Set();
  const selectedRankedClipIds = new Set();
  let rankingPollTimer = null;
  let isRankingActive = false;
  let lastRankingLogIndex = 0;

  // Live Stream Player & Connected Controls
  const monitorLiveEmbed = document.getElementById('monitorLiveEmbed');
  const monitorViewToggles = document.getElementById('monitorViewToggles');
  const btnToggleLivePlayer = document.getElementById('btnToggleLivePlayer');
  const btnToggleSnapshot = document.getElementById('btnToggleSnapshot');
  const liveConnectedControls = document.getElementById('liveConnectedControls');
  const btnLiveClipNow = document.getElementById('btnLiveClipNow');
  const liveBatchCountSelect = document.getElementById('liveBatchCountSelect');
  const btnBatchClip = document.getElementById('btnBatchClip');
  const batchCountNum = document.getElementById('batchCountNum');

  let currentSelectedDuration = 30;
  let showingSnapshotMode = false;

  // Modal and Notice elements
  const clipPreviewModal = document.getElementById('clipPreviewModal');
  const modalClipTitle = document.getElementById('modalClipTitle');
  const modalVideoPlayer = document.getElementById('modalVideoPlayer');
  const modalClipDesc = document.getElementById('modalClipDesc');
  const modalClipTags = document.getElementById('modalClipTags');
  const btnGenClipDesc = document.getElementById('btnGenClipDesc');
  const btnCopyClipMeta = document.getElementById('btnCopyClipMeta');
  const modalDownloadBtn = document.getElementById('modalDownloadBtn');
  const modalDownloadOrigBtn = document.getElementById('modalDownloadOrigBtn');
  const modalPreviewEditBtn = document.getElementById('modalPreviewEditBtn');
  const closeClipModal = document.getElementById('closeClipModal');
  const captionLanguageSelect = document.getElementById('captionLanguageSelect');

  // Clip Quick Edit Modal elements
  const clipEditModal = document.getElementById('clipEditModal');
  const closeEditClipModal = document.getElementById('closeEditClipModal');
  const editModalVideoPlayer = document.getElementById('editModalVideoPlayer');
  const editClipTitle = document.getElementById('editClipTitle');
  const editClipCategory = document.getElementById('editClipCategory');
  const editClipText = document.getElementById('editClipText');
  const saveEditClipBtn = document.getElementById('saveEditClipBtn');
  const openFullEditorBtn = document.getElementById('openFullEditorBtn');

  let activeEditingClip = null;
  let activePreviewClip = null;

  // Studio Console and Auto-Clip Notice
  const studioConsolePanel = document.getElementById('studioConsolePanel');
  const studioConsoleBody = document.getElementById('studioConsoleBody');
  const btnClearConsole = document.getElementById('btnClearConsole');
  const autoClipStorageModal = document.getElementById('autoClipStorageModal');
  const closeAutoClipModal = document.getElementById('closeAutoClipModal');
  const btnConfirmAutoClip = document.getElementById('btnConfirmAutoClip');
  const btnCancelAutoClip = document.getElementById('btnCancelAutoClip');
  const autoClipIntervalSelect = document.getElementById('autoClipIntervalSelect');
  const modalAutoClipIntervalSelect = document.getElementById('modalAutoClipIntervalSelect');
  const modalIntervalLabel = document.getElementById('modalIntervalLabel');

  const renderedConsoleTimestamps = new Set();

  function appendConsoleLog(message, level = 'info', timeStr = null) {
    if (!studioConsoleBody) return;
    const now = timeStr || (new Date()).toTimeString().split(' ')[0];
    const logKey = `${now}_${message}`;
    if (renderedConsoleTimestamps.has(logKey)) return;
    renderedConsoleTimestamps.add(logKey);
    if (renderedConsoleTimestamps.size > 300) {
      const firstKey = renderedConsoleTimestamps.values().next().value;
      renderedConsoleTimestamps.delete(firstKey);
    }

    const line = document.createElement('div');
    line.className = `console-line ${level}`;
    line.innerHTML = `<span class="log-time">[${escapeHtml(now)}]</span> <span class="log-msg">${escapeHtml(message)}</span>`;
    studioConsoleBody.appendChild(line);
    studioConsoleBody.scrollTop = studioConsoleBody.scrollHeight;
  }

  function init() {
    setupTabs();
    setupActions();
    setupPreferences();
    setupBatchActions();
    setupRankingConsole();
    setupModal();
    setupConsole();
    setupCopyButtons();
    loadOllamaModels();
    fetchRankedClips();
    startPolling();
    checkIncomingStreamUrl();
  }

  function checkIncomingStreamUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      const streamUrl = params.get('stream_url') || params.get('url');
      if (streamUrl && liveSourceUrl) {
        liveSourceUrl.value = streamUrl;
        if (streamUrl.includes('twitch.tv')) {
          const tab = document.querySelector('.source-tab[data-source="twitch"]');
          if (tab) tab.click();
        } else if (streamUrl.includes('kick.com')) {
          const tab = document.querySelector('.source-tab[data-source="kick"]');
          if (tab) tab.click();
        } else {
          const tab = document.querySelector('.source-tab[data-source="youtube"]');
          if (tab) tab.click();
        }
        setTimeout(() => {
          if (btnConnectStream && !btnConnectStream.disabled) {
            btnConnectStream.click();
          }
        }, 450);
      }
    } catch (e) {
      console.warn('Error checking incoming stream URL:', e);
    }
  }

  async function loadOllamaModels() {
    if (!liveModelSelect) return;
    try {
      const resp = await fetch('/api/models');
      const data = await resp.json();
      const models = (data && Array.isArray(data.models)) ? data.models : [];
      if (models.length > 0) {
        const prevVal = liveModelSelect.value;
        liveModelSelect.innerHTML = '';
        models.forEach((m) => {
          const opt = document.createElement('option');
          opt.value = m;
          opt.textContent = `${m} (Local)`;
          liveModelSelect.appendChild(opt);
        });
        const fastOpt = document.createElement('option');
        fastOpt.value = 'heuristic';
        fastOpt.textContent = 'Built-in Fast AI';
        liveModelSelect.appendChild(fastOpt);

        const saved = localStorage.getItem('clipify_live_model');
        if (saved && Array.from(liveModelSelect.options).some(o => o.value === saved)) {
          liveModelSelect.value = saved;
        } else if (Array.from(liveModelSelect.options).some(o => o.value === prevVal)) {
          liveModelSelect.value = prevVal;
        } else if (data.default && Array.from(liveModelSelect.options).some(o => o.value === data.default)) {
          liveModelSelect.value = data.default;
        }
      }
    } catch (e) {
      console.warn('Could not load Ollama models for Live Studio:', e);
    }
  }

  function setupConsole() {
    if (btnClearConsole && studioConsoleBody) {
      btnClearConsole.addEventListener('click', () => {
        renderedConsoleTimestamps.clear();
        studioConsoleBody.innerHTML = '<div class="console-line system"><span class="log-time">[' + (new Date()).toTimeString().split(' ')[0] + ']</span> Studio activity console cleared.</div>';
      });
    }
  }

  function setupTabs() {
    sourceTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        sourceTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        currentSourceType = tab.dataset.source;

        if (currentSourceType === 'obs') {
          obsConfigBox.style.display = 'block';
          youtubeInputGroup.style.display = 'none';
        } else {
          obsConfigBox.style.display = 'none';
          youtubeInputGroup.style.display = 'block';
          if (currentSourceType === 'youtube') {
            liveSourceUrl.placeholder = 'https://www.youtube.com/watch?v=... or https://www.youtube.com/live/...';
            const hint = document.getElementById('sourceHelpText');
            if (hint) hint.textContent = 'Supports standard YouTube Live stream links and channel /live URLs.';
          } else if (currentSourceType === 'twitch') {
            liveSourceUrl.placeholder = 'https://www.twitch.tv/channel or channel name';
            const hint = document.getElementById('sourceHelpText');
            if (hint) hint.textContent = 'Twitch live broadcast link (e.g. twitch.tv/channel) or channel username.';
          } else if (currentSourceType === 'kick') {
            liveSourceUrl.placeholder = 'https://kick.com/channel or channel username';
            const hint = document.getElementById('sourceHelpText');
            if (hint) hint.textContent = 'Kick live broadcast link (e.g. kick.com/channel) or channel username.';
          }
        }
      });
    });
  }

  function setupPreferences() {
    if (sensitivitySlider && sensitivityOut) {
      sensitivitySlider.addEventListener('input', (e) => {
        const val = parseInt(e.target.value, 10);
        let label = 'Balanced';
        if (val <= 3) label = 'Conservative';
        else if (val >= 8) label = 'High Frequency';
        sensitivityOut.textContent = `${val} (${label})`;
        if (chipSensitivity) chipSensitivity.textContent = `Sensitivity: ${val}`;
      });
    }

    if (toggleAutoClip && chipAutoClip) {
      toggleAutoClip.addEventListener('change', () => {
        if (toggleAutoClip.checked) {
          if (modalIntervalLabel && autoClipIntervalSelect) {
            modalIntervalLabel.textContent = autoClipIntervalSelect.value;
          }
          if (autoClipStorageModal) autoClipStorageModal.style.display = 'flex';
          chipAutoClip.textContent = 'Auto-Clip: ON';
        } else {
          chipAutoClip.textContent = 'Auto-Clip: OFF';
          sendLivePrefs();
        }
      });
    }

    if (closeAutoClipModal && autoClipStorageModal) {
      closeAutoClipModal.addEventListener('click', () => {
        autoClipStorageModal.style.display = 'none';
      });
    }

    if (btnConfirmAutoClip && autoClipStorageModal) {
      btnConfirmAutoClip.addEventListener('click', () => {
        if (modalAutoClipIntervalSelect && autoClipIntervalSelect) {
          autoClipIntervalSelect.value = modalAutoClipIntervalSelect.value;
        }
        autoClipStorageModal.style.display = 'none';
        if (toggleAutoClip) toggleAutoClip.checked = true;
        if (chipAutoClip) chipAutoClip.textContent = 'Auto-Clip: ON';
        appendConsoleLog(`Auto-clipping enabled (interval: ${autoClipIntervalSelect ? autoClipIntervalSelect.value : 5}m). Background monitoring active.`, 'info');
        sendLivePrefs();
      });
    }

    if (btnCancelAutoClip && autoClipStorageModal) {
      btnCancelAutoClip.addEventListener('click', () => {
        autoClipStorageModal.style.display = 'none';
        if (toggleAutoClip) toggleAutoClip.checked = false;
        if (chipAutoClip) chipAutoClip.textContent = 'Auto-Clip: OFF';
        appendConsoleLog('Auto-clipping disabled by user.', 'info');
        sendLivePrefs();
      });
    }

    if (autoClipIntervalSelect) {
      autoClipIntervalSelect.addEventListener('change', () => {
        if (modalAutoClipIntervalSelect) modalAutoClipIntervalSelect.value = autoClipIntervalSelect.value;
        if (modalIntervalLabel) modalIntervalLabel.textContent = autoClipIntervalSelect.value;
        appendConsoleLog(`Auto-clip interval updated to ${autoClipIntervalSelect.value} minutes.`, 'info');
        sendLivePrefs();
      });
    }

    if (autoClipTargetInput) {
      autoClipTargetInput.addEventListener('change', () => {
        let val = parseInt(autoClipTargetInput.value, 10);
        if (isNaN(val) || val < 1) val = 1;
        if (val > 100) val = 100;
        autoClipTargetInput.value = val;
        appendConsoleLog(`Auto-clip target limit set to ${val} clips.`, 'info');
        sendLivePrefs();
      });
    }

    if (modalAutoClipIntervalSelect) {
      modalAutoClipIntervalSelect.addEventListener('change', () => {
        if (autoClipIntervalSelect) autoClipIntervalSelect.value = modalAutoClipIntervalSelect.value;
        if (modalIntervalLabel) modalIntervalLabel.textContent = modalAutoClipIntervalSelect.value;
      });
    }

    function sendLivePrefs() {
      const payload = {
        auto_edit: toggleAutoEdit ? toggleAutoEdit.checked : true,
        face_tracking: toggleFaceTrack ? toggleFaceTrack.checked : true,
        gaming_layout: toggleGamingLayout ? toggleGamingLayout.checked : true,
        auto_captions: toggleAutoCaptions ? toggleAutoCaptions.checked : true,
        auto_clip_interval: autoClipIntervalSelect ? parseInt(autoClipIntervalSelect.value, 10) : 5,
        auto_clip_target: autoClipTargetInput ? parseInt(autoClipTargetInput.value, 10) : 10,
        model_name: liveModelSelect ? liveModelSelect.value : 'qwen2.5:3b',
        caption_style: captionStyleSelect ? captionStyleSelect.value : 'highlight',
        caption_font: captionFontSelect ? captionFontSelect.value : 'Montserrat Extra Bold',
        caption_language: captionLanguageSelect ? captionLanguageSelect.value : 'en',
        background_style: bgStyleSelect ? bgStyleSelect.value : 'soft_blur',
        background_color: bgColorHex ? bgColorHex.value : '#000000',
        custom_text: (toggleCustomText && toggleCustomText.checked && customTextInput) ? customTextInput.value.trim() : '',
        custom_text_pos: customTextPos ? customTextPos.value : 'top-center',
        custom_text_color: customTextColorHex ? customTextColorHex.value : '#FFFFFF',
      };
      fetch('/api/live/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).catch(() => {});
    }

    if (liveModelSelect) {
      liveModelSelect.addEventListener('change', () => {
        localStorage.setItem('clipify_live_model', liveModelSelect.value);
        appendConsoleLog(`Active AI model switched to: ${liveModelSelect.value}`, 'info');
        sendLivePrefs();
      });
    }

    [toggleAutoEdit, toggleFaceTrack, toggleGamingLayout, toggleAutoCaptions, captionStyleSelect, captionFontSelect].forEach(el => {
      if (el) el.addEventListener('change', sendLivePrefs);
    });

    if (bgStyleSelect && bgColorWrapper) {
      bgStyleSelect.addEventListener('change', () => {
        bgColorWrapper.style.display = (bgStyleSelect.value === 'custom_color') ? 'block' : 'none';
        sendLivePrefs();
      });
    }

    if (bgColorPicker && bgColorHex) {
      bgColorPicker.addEventListener('input', () => {
        bgColorHex.value = bgColorPicker.value;
        sendLivePrefs();
      });
      bgColorHex.addEventListener('input', () => {
        if (/^#[0-9A-Fa-f]{6}$/.test(bgColorHex.value)) {
          bgColorPicker.value = bgColorHex.value;
          sendLivePrefs();
        }
      });
    }

    if (toggleCustomText && customTextSection) {
      toggleCustomText.addEventListener('change', () => {
        customTextSection.style.display = toggleCustomText.checked ? 'block' : 'none';
        sendLivePrefs();
      });
    }

    if (customTextInput) {
      customTextInput.addEventListener('input', () => {
        sendLivePrefs();
      });
    }

    if (captionLanguageSelect) {
      captionLanguageSelect.addEventListener('change', () => {
        appendConsoleLog(`Caption language set to: ${captionLanguageSelect.options[captionLanguageSelect.selectedIndex].text}`, 'info');
        sendLivePrefs();
      });
    }

    if (customTextPos) {
      customTextPos.addEventListener('change', sendLivePrefs);
    }

    if (customTextColorPicker && customTextColorHex) {
      customTextColorPicker.addEventListener('input', () => {
        customTextColorHex.value = customTextColorPicker.value;
        sendLivePrefs();
      });
      customTextColorHex.addEventListener('input', () => {
        if (/^#[0-9A-Fa-f]{6}$/.test(customTextColorHex.value)) {
          customTextColorPicker.value = customTextColorHex.value;
          sendLivePrefs();
        }
      });
    }
  }

  function setupCopyButtons() {
    document.querySelectorAll('.copy-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetId = btn.dataset.target;
        const input = document.getElementById(targetId);
        if (input) {
          input.select();
          navigator.clipboard.writeText(input.value);
          const orig = btn.textContent;
          btn.textContent = 'Copied!';
          setTimeout(() => { btn.textContent = orig; }, 1500);
        }
      });
    });

    const btnObsGuide = document.getElementById('btnObsGuide');
    if (btnObsGuide) {
      btnObsGuide.addEventListener('click', () => {
        const obsTab = document.querySelector('.source-tab[data-source="obs"]');
        if (obsTab) obsTab.click();
      });
    }
  }

  function setupActions() {
    // Connect YouTube or TikTok
    btnConnectStream.addEventListener('click', () => startConnection(false));

    // Connect OBS
    if (btnConnectObs) {
      btnConnectObs.addEventListener('click', () => startConnection(true));
    }

    // Disconnect YouTube or TikTok
    btnDisconnectStream.addEventListener('click', stopConnection);

    // Disconnect OBS
    if (btnDisconnectObs) {
      btnDisconnectObs.addEventListener('click', stopConnection);
    }

    // Retry button on failure
    if (btnRetryConnection) {
      btnRetryConnection.addEventListener('click', () => {
        setMonitorState('idle');
        liveSourceUrl.focus();
      });
    }

    // Instant Clip in Header (30s)
    btnInstantClip.addEventListener('click', async () => {
      triggerInstantClip(currentSelectedDuration || 30, btnInstantClip);
    });

    // Duration quick pills
    document.querySelectorAll('.clip-duration-pills .pill-btn').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('.clip-duration-pills .pill-btn').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        currentSelectedDuration = parseInt(pill.dataset.dur, 10) || 30;
        if (btnLiveClipNow) {
          const small = btnLiveClipNow.querySelector('small');
          if (small) small.textContent = `Capture & auto-edit ${currentSelectedDuration}s Short`;
        }
      });
    });

    // Dedicated Live Clip Button (Under Monitor)
    if (btnLiveClipNow) {
      btnLiveClipNow.addEventListener('click', async () => {
        if (toggleAutoClip && !toggleAutoClip.checked) {
          toggleAutoClip.checked = true;
          if (chipAutoClip) chipAutoClip.textContent = 'Auto-Clip: ON';
          sendLivePrefs();
          appendConsoleLog('[AUTO-CLIP] Highlight triggered: auto-clipping enabled automatically.', 'success');
        }
        triggerInstantClip(currentSelectedDuration, btnLiveClipNow);
      });
    }

    // Number of Clips selector & Batch Clip button
    if (liveBatchCountSelect && batchCountNum) {
      liveBatchCountSelect.addEventListener('change', () => {
        batchCountNum.textContent = liveBatchCountSelect.value;
        if (prefTargetClips) prefTargetClips.value = liveBatchCountSelect.value;
      });
    }
    if (prefTargetClips && liveBatchCountSelect) {
      prefTargetClips.addEventListener('change', () => {
        if (prefTargetClips.value !== 'auto') {
          liveBatchCountSelect.value = prefTargetClips.value;
          if (batchCountNum) batchCountNum.textContent = prefTargetClips.value;
        }
      });
    }

    if (btnBatchClip) {
      btnBatchClip.addEventListener('click', async () => {
        const count = parseInt(liveBatchCountSelect ? liveBatchCountSelect.value : 4, 10) || 4;
        btnBatchClip.disabled = true;
        const origHtml = btnBatchClip.innerHTML;
        btnBatchClip.innerHTML = `<span>⏳ Creating ${count} Shorts…</span>`;
        appendConsoleLog(`[ACTION] Batch Clipping triggered: generating ${count} Shorts (${currentSelectedDuration}s each)...`, 'info');
        try {
          const resp = await fetch('/api/live/batch-clip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ count: count, duration: currentSelectedDuration }),
          });
          const data = await resp.json();
          if (resp.ok) {
            appendConsoleLog(`Batch process started: generating ${count} Shorts in background. Watch the export gallery below as each Short completes!`, 'success');
            await fetchClips();
          } else {
            appendConsoleLog(`Batch clip error: ${data.error || 'Failed generating clips'}`, 'error');
            alert(data.error || 'Could not generate batch clips.');
          }
        } catch (err) {
          appendConsoleLog(`Batch clip network error: ${err.message}`, 'error');
          alert('Batch clip error: ' + err.message);
        } finally {
          setTimeout(() => {
            btnBatchClip.disabled = false;
            btnBatchClip.innerHTML = origHtml;
          }, 3500);
        }
      });
    }

    // Live Stream Player vs Snapshot Toggles
    if (btnToggleLivePlayer && btnToggleSnapshot) {
      btnToggleLivePlayer.addEventListener('click', () => {
        showingSnapshotMode = false;
        btnToggleLivePlayer.classList.add('active');
        btnToggleSnapshot.classList.remove('active');
        if (monitorLiveEmbed && monitorLiveEmbed.src) {
          monitorLiveEmbed.style.display = 'block';
          if (monitorVideoFrame) monitorVideoFrame.style.display = 'none';
        }
      });
      btnToggleSnapshot.addEventListener('click', () => {
        showingSnapshotMode = true;
        btnToggleSnapshot.classList.add('active');
        btnToggleLivePlayer.classList.remove('active');
        if (monitorLiveEmbed) monitorLiveEmbed.style.display = 'none';
        if (monitorVideoFrame) monitorVideoFrame.style.display = 'block';
      });
    }

    // Refresh Clips Button with live spinner and feedback
    const btnRefreshClips = document.getElementById('btnRefreshClips');
    if (btnRefreshClips) {
      btnRefreshClips.addEventListener('click', async () => {
        const orig = btnRefreshClips.innerHTML;
        btnRefreshClips.disabled = true;
        btnRefreshClips.innerHTML = '↻ Refreshing…';
        btnRefreshClips.classList.add('refresh-spinning');
        try {
          await fetchClips();
          btnRefreshClips.innerHTML = '✓ Refreshed';
        } catch (e) {
          btnRefreshClips.innerHTML = '⚠ Failed';
        } finally {
          setTimeout(() => {
            btnRefreshClips.innerHTML = orig;
            btnRefreshClips.disabled = false;
            btnRefreshClips.classList.remove('refresh-spinning');
          }, 800);
        }
      });
    }
  }

  async function triggerInstantClip(duration, triggerBtn) {
    if (triggerBtn) {
      triggerBtn.disabled = true;
      const originalText = triggerBtn.innerHTML;
      triggerBtn.innerHTML = `<span>⏳ Rendering ${duration}s Short…</span>`;
      appendConsoleLog(`[ACTION] Instant Clip triggered: capturing ${duration}s slice...`, 'info');
      appendConsoleLog('Aligning audio and video presentation timestamps (aresample=async=1:first_pts=0)...', 'info');
      appendConsoleLog('Transcribing clip speech for word-level karaoke subtitles & smart cropping...', 'info');
      try {
        const resp = await fetch('/api/live/instant-clip', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ duration: duration }),
        });
        const data = await resp.json();
        if (resp.ok && data.clip) {
          appendConsoleLog(`Instant Short ready: "${data.clip.title}" (${data.clip.duration}s, layout: ${data.clip.layout})`, 'success');
          await fetchClips();
        } else {
          appendConsoleLog(`Instant Clip failed: ${data.error || 'Server error'}`, 'error');
          alert(data.error || 'Could not generate instant clip.');
        }
      } catch (err) {
        appendConsoleLog(`Instant Clip error: ${err.message}`, 'error');
        alert('Instant clip error: ' + err.message);
      } finally {
        triggerBtn.disabled = false;
        triggerBtn.innerHTML = originalText;
      }
    }
  }

  async function startConnection(isObs) {
    const connectBtn = isObs ? btnConnectObs : btnConnectStream;
    connectBtn.disabled = true;
    connectBtn.textContent = 'Connecting...';

    let sourceUrl = isObs ? 'rtmp://0.0.0.0:1935/live/stream' : liveSourceUrl.value.trim();
    const sourceType = isObs ? 'obs' : currentSourceType;

    setMonitorState('loading', 'Connecting...', 'Initiating live stream session');
    appendConsoleLog(`Connecting to ${sourceType.toUpperCase()} stream: ${sourceUrl || 'OBS Studio RTMP'}...`, 'info');

    try {
      const resp = await fetch('/api/live/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_type: sourceType,
          source_url: sourceUrl,
          auto_clip: toggleAutoClip ? toggleAutoClip.checked : false,
          caption_language: captionLanguageSelect ? captionLanguageSelect.value : 'en',
          auto_clip_interval: autoClipIntervalSelect ? parseInt(autoClipIntervalSelect.value, 10) : 5,
          auto_clip_target: autoClipTargetInput ? parseInt(autoClipTargetInput.value, 10) : 10,
          sensitivity: sensitivitySlider ? parseInt(sensitivitySlider.value, 10) : 5,
          buffer_minutes: bufferWindowSelect ? parseInt(bufferWindowSelect.value, 10) : 10,
          model_name: liveModelSelect ? liveModelSelect.value : 'qwen2.5:3b',
          auto_edit: toggleAutoEdit ? toggleAutoEdit.checked : true,
          face_tracking: toggleFaceTrack ? toggleFaceTrack.checked : true,
          gaming_layout: toggleGamingLayout ? toggleGamingLayout.checked : true,
          auto_captions: toggleAutoCaptions ? toggleAutoCaptions.checked : true,
          caption_style: captionStyleSelect ? captionStyleSelect.value : 'highlight',
          caption_font: captionFontSelect ? captionFontSelect.value : 'Montserrat Extra Bold',
          background_style: bgStyleSelect ? bgStyleSelect.value : 'soft_blur',
          background_color: bgColorHex ? bgColorHex.value : '#000000',
          custom_text: (toggleCustomText && toggleCustomText.checked && customTextInput) ? customTextInput.value.trim() : '',
          custom_text_pos: customTextPos ? customTextPos.value : 'top-center',
          custom_text_color: customTextColorHex ? customTextColorHex.value : '#FFFFFF',
        }),
      });

      const data = await resp.json();
      if (!resp.ok) {
        setMonitorState('failed', 'Connection Failed', data.error || 'Could not connect');
        appendConsoleLog(`Connection failed: ${data.error || 'Could not connect'}`, 'error');
        connectBtn.disabled = false;
        connectBtn.textContent = isObs ? 'Start Listening for OBS' : 'Connect & Start Clipping';
        return;
      }

      appendConsoleLog(`Connection initialized. Ingestion pipeline active.`, 'success');
      updateUIStatus(data.status);
    } catch (err) {
      setMonitorState('failed', 'Network Error', err.message);
      connectBtn.disabled = false;
      connectBtn.textContent = isObs ? 'Start Listening for OBS' : 'Connect & Start Clipping';
    }
  }

  async function stopConnection() {
    btnDisconnectStream.disabled = true;
    if (btnDisconnectObs) btnDisconnectObs.disabled = true;

    try {
      await fetch('/api/live/disconnect', { method: 'POST' });
      fetchStatus();
    } catch (err) {
      console.error('Disconnect error:', err);
    } finally {
      btnDisconnectStream.disabled = false;
      if (btnDisconnectObs) btnDisconnectObs.disabled = false;
    }
  }

  function setMonitorState(state, title, detail) {
    if (monitorIdleView) monitorIdleView.style.display = 'none';
    if (monitorLoadingView) monitorLoadingView.style.display = 'none';
    if (monitorLiveView) monitorLiveView.style.display = 'none';
    if (monitorFailedView) monitorFailedView.style.display = 'none';

    if (state === 'idle') {
      if (monitorIdleView) monitorIdleView.style.display = 'flex';
    } else if (state === 'loading') {
      if (monitorLoadingView) monitorLoadingView.style.display = 'flex';
      if (monitorLoadingTitle && title) monitorLoadingTitle.textContent = title;
      if (monitorLoadingDetail && detail) monitorLoadingDetail.textContent = detail;
    } else if (state === 'live') {
      if (monitorLiveView) monitorLiveView.style.display = 'flex';
    } else if (state === 'failed') {
      if (monitorFailedView) monitorFailedView.style.display = 'flex';
      if (monitorFailedTitle && title) monitorFailedTitle.textContent = title;
      if (monitorFailedDetail && detail) monitorFailedDetail.textContent = detail;
    }
  }

  function setupModal() {
    closeClipModal?.addEventListener('click', () => {
      modalVideoPlayer.pause();
      modalVideoPlayer.src = '';
      clipPreviewModal.style.display = 'none';
      activePreviewClip = null;
    });

    clipPreviewModal?.addEventListener('click', (e) => {
      if (e.target === clipPreviewModal) {
        modalVideoPlayer.pause();
        modalVideoPlayer.src = '';
        clipPreviewModal.style.display = 'none';
        activePreviewClip = null;
      }
    });

    modalPreviewEditBtn?.addEventListener('click', () => {
      if (!activePreviewClip) return;
      const clipToEdit = activePreviewClip;
      modalVideoPlayer.pause();
      modalVideoPlayer.src = '';
      clipPreviewModal.style.display = 'none';
      openEditModal(clipToEdit);
    });

    closeEditClipModal?.addEventListener('click', () => {
      if (editModalVideoPlayer) {
        editModalVideoPlayer.pause();
        editModalVideoPlayer.src = '';
      }
      if (clipEditModal) clipEditModal.style.display = 'none';
      activeEditingClip = null;
    });

    clipEditModal?.addEventListener('click', (e) => {
      if (e.target === clipEditModal) {
        if (editModalVideoPlayer) {
          editModalVideoPlayer.pause();
          editModalVideoPlayer.src = '';
        }
        clipEditModal.style.display = 'none';
        activeEditingClip = null;
      }
    });

    saveEditClipBtn?.addEventListener('click', async () => {
      if (!activeEditingClip) return;
      saveEditClipBtn.disabled = true;
      saveEditClipBtn.textContent = 'Saving...';
      try {
        const payload = {
          title: editClipTitle.value.trim() || activeEditingClip.title,
          category: editClipCategory.value || activeEditingClip.category,
          subtitle_text: editClipText.value.trim(),
        };
        const resp = await fetch(`/api/live/clips/${activeEditingClip.id}/update`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (resp.ok) {
          appendConsoleLog(`[EDIT] Saved changes for "${payload.title}"`, 'success');
          if (editModalVideoPlayer) {
            editModalVideoPlayer.pause();
            editModalVideoPlayer.src = '';
          }
          if (clipEditModal) clipEditModal.style.display = 'none';
          activeEditingClip = null;
          await fetchClips();
          await fetchRankedClips();
        } else {
          alert('Failed to update clip metadata.');
        }
      } catch (err) {
        alert('Edit save error: ' + err.message);
      } finally {
        saveEditClipBtn.disabled = false;
        saveEditClipBtn.textContent = '💾 Save Metadata';
      }
    });

    openFullEditorBtn?.addEventListener('click', () => {
      if (!activeEditingClip) return;
      const videoSrc = activeEditingClip.vertical_video || '';
      window.location.href = `/#editor?video=${encodeURIComponent(videoSrc)}&title=${encodeURIComponent(activeEditingClip.title)}`;
    });
  }

  function startPolling() {
    fetchStatus();
    fetchClips();
    fetchTranscripts();

    pollInterval = setInterval(() => {
      fetchStatus();
      if (isSessionActive) {
        fetchTranscripts();
      }
      fetchClips();
    }, 2000);
  }

  async function fetchStatus() {
    try {
      const resp = await fetch('/api/live/status');
      if (!resp.ok) return;
      const data = await resp.json();
      updateUIStatus(data);
    } catch (err) {
      console.debug('Status fetch error:', err);
    }
  }

  function updateUIStatus(statusData) {
    if (!statusData) return;
    const st = (statusData.status || 'idle').toLowerCase();
    isSessionActive = Boolean(statusData.session_active);

    // Auto-clip target limit sync
    if (statusData.auto_clip_target && autoClipTargetInput && document.activeElement !== autoClipTargetInput) {
      autoClipTargetInput.value = statusData.auto_clip_target;
    }

    // Telemetry numbers
    const elapsedStr = statusData.elapsed_seconds ? formatDuration(statusData.elapsed_seconds) : '00:00:00';
    const bufferSec = Math.round(statusData.buffer_duration_seconds || 0);
    const chunksCount = statusData.buffer_chunks || 0;

    if (telemetryElapsed) telemetryElapsed.textContent = elapsedStr;
    if (telemetryBuffer) telemetryBuffer.textContent = `Buffer: ${bufferSec}s`;
    if (telemetryChunks) telemetryChunks.textContent = `${chunksCount} chunks`;
    if (overlayElapsed) overlayElapsed.textContent = elapsedStr;
    if (overlayBuffer) overlayBuffer.textContent = `${bufferSec}s buf`;

    // Metadata
    if (statusData.metadata && statusData.metadata.title) {
      if (monitorTitle) monitorTitle.textContent = statusData.metadata.title;
      if (streamOverlayTitle) streamOverlayTitle.textContent = statusData.metadata.title;
      if (statusData.metadata.author && streamAuthor) {
        streamAuthor.textContent = statusData.metadata.author;
      }
    }

    // State handling
    if (st === 'live') {
      streamLiveBadge.className = 'live-badge active';
      streamLiveText.textContent = '● LIVE';

      btnConnectStream.style.display = 'none';
      btnDisconnectStream.style.display = 'inline-flex';
      if (btnConnectObs) btnConnectObs.style.display = 'none';
      if (btnDisconnectObs) btnDisconnectObs.style.display = 'inline-flex';

      btnInstantClip.disabled = false;
      if (liveConnectedControls) liveConnectedControls.style.display = 'flex';
      setMonitorState('live');

      // Check YouTube or Twitch or Kick live stream URL for embedded playback
      const streamUrl = statusData.source_url || (liveSourceUrl ? liveSourceUrl.value.trim() : '');
      const ytId = extractYoutubeId(streamUrl);
      const twitchCh = (statusData.source_type === 'twitch' || currentSourceType === 'twitch') ? extractTwitchChannel(streamUrl) : null;
      const kickCh = (statusData.source_type === 'kick' || currentSourceType === 'kick') ? extractKickChannel(streamUrl) : null;

      if (ytId && monitorLiveEmbed) {
        const expectedSrc = `https://www.youtube-nocookie.com/embed/${ytId}?autoplay=1&mute=0&controls=1&modestbranding=1&rel=0`;
        if (!monitorLiveEmbed.src || !monitorLiveEmbed.src.includes(ytId)) {
          monitorLiveEmbed.src = expectedSrc;
        }
        if (monitorViewToggles) monitorViewToggles.style.display = 'inline-flex';
        if (!showingSnapshotMode) {
          monitorLiveEmbed.style.display = 'block';
          if (monitorVideoFrame) monitorVideoFrame.style.display = 'none';
        } else {
          monitorLiveEmbed.style.display = 'none';
          if (monitorVideoFrame) monitorVideoFrame.style.display = 'block';
        }
      } else if (twitchCh && monitorLiveEmbed) {
        const expectedSrc = `https://player.twitch.tv/?channel=${twitchCh}&parent=localhost&parent=127.0.0.1&muted=false`;
        if (!monitorLiveEmbed.src || !monitorLiveEmbed.src.includes(`channel=${twitchCh}`)) {
          monitorLiveEmbed.src = expectedSrc;
        }
        if (monitorViewToggles) monitorViewToggles.style.display = 'inline-flex';
        if (!showingSnapshotMode) {
          monitorLiveEmbed.style.display = 'block';
          if (monitorVideoFrame) monitorVideoFrame.style.display = 'none';
        } else {
          monitorLiveEmbed.style.display = 'none';
          if (monitorVideoFrame) monitorVideoFrame.style.display = 'block';
        }
      } else if (kickCh && monitorLiveEmbed) {
        const expectedSrc = `https://player.kick.com/${kickCh}?autoplay=true&muted=false`;
        if (!monitorLiveEmbed.src || !monitorLiveEmbed.src.includes(`player.kick.com/${kickCh}`)) {
          monitorLiveEmbed.src = expectedSrc;
        }
        if (monitorViewToggles) monitorViewToggles.style.display = 'inline-flex';
        if (!showingSnapshotMode) {
          monitorLiveEmbed.style.display = 'block';
          if (monitorVideoFrame) monitorVideoFrame.style.display = 'none';
        } else {
          monitorLiveEmbed.style.display = 'none';
          if (monitorVideoFrame) monitorVideoFrame.style.display = 'block';
        }
      } else {
        if (monitorLiveEmbed) {
          monitorLiveEmbed.style.display = 'none';
          monitorLiveEmbed.src = '';
        }
        if (monitorVideoFrame) monitorVideoFrame.style.display = 'block';
        if (monitorViewToggles) monitorViewToggles.style.display = 'none';
      }

      // Refresh live video preview frame every 2 seconds for snapshot mode / OBS
      const now = Date.now();
      if (now - lastPreviewFetch > 2000 && monitorVideoFrame) {
        lastPreviewFetch = now;
        monitorVideoFrame.src = `/api/live/preview-frame?t=${now}`;
      }
    } else if (st === 'resolving' || st === 'connecting' || st === 'buffering' || st === 'listening') {
      streamLiveBadge.className = 'live-badge';
      streamLiveText.textContent = st.toUpperCase();

      btnConnectStream.style.display = 'none';
      btnDisconnectStream.style.display = 'inline-flex';
      if (btnConnectObs) btnConnectObs.style.display = 'none';
      if (btnDisconnectObs) btnDisconnectObs.style.display = 'inline-flex';

      btnInstantClip.disabled = true;
      if (liveConnectedControls) liveConnectedControls.style.display = 'none';
      if (monitorLiveEmbed) {
        monitorLiveEmbed.style.display = 'none';
        monitorLiveEmbed.src = '';
      }
      if (monitorViewToggles) monitorViewToggles.style.display = 'none';

      let title = 'Resolving Stream...';
      if (st === 'connecting') title = 'Starting Ingestion Pipeline...';
      else if (st === 'buffering') title = 'Buffering Media Packets...';
      else if (st === 'listening') title = 'Listening for OBS Studio...';

      setMonitorState('loading', title, statusData.status_detail || 'Processing live media feed');
    } else if (st === 'failed') {
      streamLiveBadge.className = 'live-badge';
      streamLiveText.textContent = 'FAILED';

      btnConnectStream.style.display = 'inline-flex';
      btnConnectStream.disabled = false;
      btnConnectStream.textContent = 'Connect & Start Clipping';
      btnDisconnectStream.style.display = 'none';

      if (btnConnectObs) {
        btnConnectObs.style.display = 'inline-flex';
        btnConnectObs.disabled = false;
        btnConnectObs.textContent = 'Start Listening for OBS';
      }
      if (btnDisconnectObs) btnDisconnectObs.style.display = 'none';

      btnInstantClip.disabled = true;
      if (liveConnectedControls) liveConnectedControls.style.display = 'none';
      if (monitorLiveEmbed) {
        monitorLiveEmbed.style.display = 'none';
        monitorLiveEmbed.src = '';
      }
      if (monitorViewToggles) monitorViewToggles.style.display = 'none';

      setMonitorState('failed', 'Connection Failed', statusData.status_detail || 'Stream is offline or URL is invalid');
    } else {
      // Idle or disconnected
      streamLiveBadge.className = 'live-badge';
      streamLiveText.textContent = 'IDLE';

      btnConnectStream.style.display = 'inline-flex';
      btnConnectStream.disabled = false;
      btnConnectStream.textContent = 'Connect & Start Clipping';
      btnDisconnectStream.style.display = 'none';

      if (btnConnectObs) {
        btnConnectObs.style.display = 'inline-flex';
        btnConnectObs.disabled = false;
        btnConnectObs.textContent = 'Start Listening for OBS';
      }
      if (btnDisconnectObs) btnDisconnectObs.style.display = 'none';

      btnInstantClip.disabled = true;
      if (liveConnectedControls) liveConnectedControls.style.display = 'none';
      if (monitorLiveEmbed) {
        monitorLiveEmbed.style.display = 'none';
        monitorLiveEmbed.src = '';
      }
      if (monitorViewToggles) monitorViewToggles.style.display = 'none';

      setMonitorState('idle');
    }

    // Stream console logs from status
    if (statusData.console_logs && Array.isArray(statusData.console_logs)) {
      statusData.console_logs.forEach(log => {
        appendConsoleLog(log.message, log.level || 'info', log.time);
      });
    }
  }

  function extractYoutubeId(url) {
    if (!url) return null;
    const match = url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=|live\/))([\w-]{11})/);
    return (match && match[1]) ? match[1] : null;
  }

  function extractTwitchChannel(url) {
    if (!url) return null;
    const clean = url.trim().replace(/^https?:\/\//i, '').replace(/^(www\.)?twitch\.tv\//i, '').replace(/^\/+/, '').split(/[\/?#]/)[0];
    return clean ? clean.replace(/^@/, '') : null;
  }

  function extractKickChannel(url) {
    if (!url) return null;
    const clean = url.trim().replace(/^https?:\/\//i, '').replace(/^(www\.)?kick\.com\//i, '').replace(/^\/+/, '').split(/[\/?#]/)[0];
    return clean ? clean.replace(/^@/, '') : null;
  }

  async function fetchTranscripts() {
    try {
      const resp = await fetch('/api/live/transcript');
      if (!resp.ok) return;
      const data = await resp.json();
      const segments = data.segments || [];

      if (segments.length === 0) {
        if (!isSessionActive) {
          transcriptFeed.innerHTML = '<div class="empty-feed">Speech will transcribe here in real-time as the stream plays...</div>';
        }
        return;
      }

      transcriptFeed.innerHTML = '';
      segments.slice(-25).forEach(seg => {
        const item = document.createElement('div');
        item.className = 'transcript-item';
        item.innerHTML = `
          <span class="transcript-time">${formatDuration(seg.start)}</span>
          <p class="transcript-text">${escapeHtml(seg.text)}</p>
        `;
        transcriptFeed.appendChild(item);
      });

      transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
    } catch (err) {
      console.debug('Transcript error:', err);
    }
  }


  // ==========================================================================
  // Batch Selection & Batch Actions
  // ==========================================================================

  function updateBatchClipsToolbar(totalClipsCount = 0) {
    if (selectedClipsCounter) {
      const count = selectedClipIds.size;
      selectedClipsCounter.textContent = `${count} selected`;
      if (count > 0) {
        selectedClipsCounter.classList.add('has-selected');
      } else {
        selectedClipsCounter.classList.remove('has-selected');
      }
    }
    if (btnDeleteSelectedClips) {
      btnDeleteSelectedClips.disabled = (selectedClipIds.size === 0);
    }
    if (chkSelectAllClips && totalClipsCount > 0) {
      chkSelectAllClips.checked = (selectedClipIds.size === totalClipsCount);
      chkSelectAllClips.indeterminate = (selectedClipIds.size > 0 && selectedClipIds.size < totalClipsCount);
    } else if (chkSelectAllClips) {
      chkSelectAllClips.checked = false;
      chkSelectAllClips.indeterminate = false;
    }
  }

  function updateBatchRankedToolbar(totalRankedCount = 0) {
    if (selectedRankedCounter) {
      const count = selectedRankedClipIds.size;
      selectedRankedCounter.textContent = `${count} selected`;
      if (count > 0) {
        selectedRankedCounter.classList.add('has-selected');
      } else {
        selectedRankedCounter.classList.remove('has-selected');
      }
    }
    if (btnDeleteSelectedRanked) {
      btnDeleteSelectedRanked.disabled = (selectedRankedClipIds.size === 0);
    }
    if (chkSelectAllRanked && totalRankedCount > 0) {
      chkSelectAllRanked.checked = (selectedRankedClipIds.size === totalRankedCount);
      chkSelectAllRanked.indeterminate = (selectedRankedClipIds.size > 0 && selectedRankedClipIds.size < totalRankedCount);
    } else if (chkSelectAllRanked) {
      chkSelectAllRanked.checked = false;
      chkSelectAllRanked.indeterminate = false;
    }
  }

  function setupBatchActions() {
    if (chkSelectAllClips) {
      chkSelectAllClips.addEventListener('change', () => {
        const checkboxes = liveClipsGrid.querySelectorAll('.clip-select-check');
        const cards = liveClipsGrid.querySelectorAll('.live-clip-card');
        if (chkSelectAllClips.checked) {
          checkboxes.forEach(chk => {
            chk.checked = true;
            selectedClipIds.add(chk.dataset.id);
          });
          cards.forEach(card => card.classList.add('selected'));
        } else {
          checkboxes.forEach(chk => {
            chk.checked = false;
          });
          selectedClipIds.clear();
          cards.forEach(card => card.classList.remove('selected'));
        }
        updateBatchClipsToolbar(checkboxes.length);
      });
    }

    if (btnDeleteSelectedClips) {
      btnDeleteSelectedClips.addEventListener('click', async () => {
        if (selectedClipIds.size === 0) return;
        const count = selectedClipIds.size;
        if (!confirm(`Delete ${count} selected clip(s)? This cannot be undone.`)) return;
        btnDeleteSelectedClips.disabled = true;
        try {
          const resp = await fetch('/api/live/clips/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ clip_ids: Array.from(selectedClipIds) }),
          });
          const data = await resp.json();
          appendConsoleLog(`[BATCH] Deleted ${data.deleted_count || count} clip(s).`, 'info');
          selectedClipIds.clear();
          await fetchClips();
          await fetchRankedClips();
        } catch (err) {
          alert('Batch delete error: ' + err.message);
        } finally {
          btnDeleteSelectedClips.disabled = false;
        }
      });
    }

    if (chkSelectAllRanked) {
      chkSelectAllRanked.addEventListener('change', () => {
        const checkboxes = rankedClipsGrid.querySelectorAll('.ranked-clip-check');
        const cards = rankedClipsGrid.querySelectorAll('.ranked-clip-card');
        if (chkSelectAllRanked.checked) {
          checkboxes.forEach(chk => {
            chk.checked = true;
            selectedRankedClipIds.add(chk.dataset.id);
          });
          cards.forEach(card => card.classList.add('selected'));
        } else {
          checkboxes.forEach(chk => {
            chk.checked = false;
          });
          selectedRankedClipIds.clear();
          cards.forEach(card => card.classList.remove('selected'));
        }
        updateBatchRankedToolbar(checkboxes.length);
      });
    }

    if (btnDeleteSelectedRanked) {
      btnDeleteSelectedRanked.addEventListener('click', async () => {
        if (selectedRankedClipIds.size === 0) return;
        const count = selectedRankedClipIds.size;
        if (!confirm(`Delete ${count} selected ranked clip(s)? This cannot be undone.`)) return;
        btnDeleteSelectedRanked.disabled = true;
        try {
          const resp = await fetch('/api/live/clips/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ clip_ids: Array.from(selectedRankedClipIds) }),
          });
          const data = await resp.json();
          appendConsoleLog(`[BATCH] Deleted ${data.deleted_count || count} ranked clip(s).`, 'info');
          selectedRankedClipIds.clear();
          await fetchRankedClips();
          await fetchClips();
        } catch (err) {
          alert('Batch delete error: ' + err.message);
        } finally {
          btnDeleteSelectedRanked.disabled = false;
        }
      });
    }

    // Horizontal Shelf Navigation Controls
    const btnScrollClipsLeft = document.getElementById('btnScrollClipsLeft');
    const btnScrollClipsRight = document.getElementById('btnScrollClipsRight');
    if (btnScrollClipsLeft && liveClipsGrid) {
      btnScrollClipsLeft.addEventListener('click', () => {
        liveClipsGrid.scrollBy({ left: -360, behavior: 'smooth' });
      });
    }
    if (btnScrollClipsRight && liveClipsGrid) {
      btnScrollClipsRight.addEventListener('click', () => {
        liveClipsGrid.scrollBy({ left: 360, behavior: 'smooth' });
      });
    }

    const btnScrollRankedLeft = document.getElementById('btnScrollRankedLeft');
    const btnScrollRankedRight = document.getElementById('btnScrollRankedRight');
    if (btnScrollRankedLeft && rankedClipsGrid) {
      btnScrollRankedLeft.addEventListener('click', () => {
        rankedClipsGrid.scrollBy({ left: -360, behavior: 'smooth' });
      });
    }
    if (btnScrollRankedRight && rankedClipsGrid) {
      btnScrollRankedRight.addEventListener('click', () => {
        rankedClipsGrid.scrollBy({ left: 360, behavior: 'smooth' });
      });
    }

    // Mouse wheel horizontal scroll on sideways shelves
    [liveClipsGrid, rankedClipsGrid].forEach(el => {
      if (el) {
        el.addEventListener('wheel', (e) => {
          if (e.deltaY !== 0 && !e.shiftKey) {
            e.preventDefault();
            el.scrollBy({ left: e.deltaY * 1.5, behavior: 'smooth' });
          }
        }, { passive: false });
      }
    });
  }

  // ==========================================================================
  // AI Clip Ranking & Live Process Console
  // ==========================================================================

  function setupRankingConsole() {
    if (btnCloseRankingConsole && rankingConsolePanel) {
      btnCloseRankingConsole.addEventListener('click', () => {
        rankingConsolePanel.style.display = 'none';
      });
    }

    if (btnRankClipsAi) {
      btnRankClipsAi.addEventListener('click', () => {
        startAiClipRanking();
      });
    }
  }

  async function startAiClipRanking() {
    if (isRankingActive) return;
    isRankingActive = true;
    lastRankingLogIndex = 0;

    if (rankingConsolePanel) rankingConsolePanel.style.display = 'block';
    if (rankingStatusBadge) rankingStatusBadge.textContent = 'Ranking with Ollama AI...';
    if (rankingConsoleBody) {
      rankingConsoleBody.innerHTML = '<div class="console-line system"><span class="log-time">[' + (new Date()).toTimeString().split(' ')[0] + ']</span> Initializing neural viral potential ranking engine...</div>';
    }
    if (btnRankClipsAi) {
      btnRankClipsAi.disabled = true;
      btnRankClipsAi.innerHTML = '<span class="sparkle-icon">⏳</span><span>RANKING CLIPS...</span>';
    }

    try {
      const chosenModel = liveModelSelect ? liveModelSelect.value : null;
      const resp = await fetch('/api/live/clips/rank', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ top_n: 10, model_name: chosenModel }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        appendRankingLog(data.error || 'Failed to start ranking', 'error');
        finishRanking();
        return;
      }

      // Start polling status
      if (rankingPollTimer) clearInterval(rankingPollTimer);
      rankingPollTimer = setInterval(pollRankingStatus, 600);
    } catch (err) {
      appendRankingLog('Ranking error: ' + err.message, 'error');
      finishRanking();
    }
  }

  async function pollRankingStatus() {
    try {
      const resp = await fetch('/api/live/clips/rank/status');
      if (!resp.ok) return;
      const data = await resp.json();

      // Render new logs
      const logs = data.logs || [];
      if (logs.length > lastRankingLogIndex) {
        for (let i = lastRankingLogIndex; i < logs.length; i++) {
          const l = logs[i];
          appendRankingLog(l.message, l.level, l.time);
        }
        lastRankingLogIndex = logs.length;
      }

      if (!data.is_ranking) {
        if (rankingPollTimer) {
          clearInterval(rankingPollTimer);
          rankingPollTimer = null;
        }
        finishRanking(data.ranked_clips || []);
      }
    } catch (err) {
      console.debug('Ranking poll error:', err);
    }
  }

  function appendRankingLog(msg, level = 'info', timeStr = null) {
    if (!rankingConsoleBody) return;
    const line = document.createElement('div');
    line.className = `console-line ${level}`;
    const t = timeStr || (new Date()).toTimeString().split(' ')[0];
    line.innerHTML = `<span class="log-time">[${t}]</span> ${escapeHtml(msg)}`;
    rankingConsoleBody.appendChild(line);
    rankingConsoleBody.scrollTop = rankingConsoleBody.scrollHeight;
  }

  function finishRanking(rankedClips = null) {
    isRankingActive = false;
    if (rankingStatusBadge) rankingStatusBadge.textContent = 'Ranking Complete';
    if (btnRankClipsAi) {
      btnRankClipsAi.disabled = false;
      btnRankClipsAi.innerHTML = '<span class="sparkle-icon">✨</span><span>RANK CLIPS AI</span>';
    }
    fetchRankedClips(rankedClips);
  }

  async function fetchRankedClips(preloaded = null) {
    try {
      let ranked = preloaded;
      if (!ranked) {
        const resp = await fetch('/api/live/clips/ranked');
        if (resp.ok) {
          const data = await resp.json();
          ranked = data.ranked_clips || [];
        }
      }

      if (!ranked || ranked.length === 0) {
        if (rankedClipsSection) rankedClipsSection.style.display = 'none';
        return;
      }

      if (rankedClipsSection) rankedClipsSection.style.display = 'block';
      if (rankedClipsGrid) {
        rankedClipsGrid.innerHTML = '';
        ranked.forEach((clip, idx) => {
          const rankNum = idx + 1;
          const card = document.createElement('div');
          const isSelected = selectedRankedClipIds.has(clip.id);
          card.className = `ranked-clip-card ${isSelected ? 'selected' : ''}`;

          const rankClass = rankNum === 1 ? 'rank-1' : (rankNum === 2 ? 'rank-2' : (rankNum === 3 ? 'rank-3' : ''));
          const rankLabel = rankNum === 1 ? '👑 #1 BEST' : `#${rankNum}`;
          const viralScore = (clip.viral_score !== undefined) ? clip.viral_score : 9.0;
          const hookGrade = clip.hook_grade || 'A';
          const verdict = clip.ai_verdict || 'High retention potential with engaging speech cadence.';

          card.innerHTML = `
            <div class="clip-thumb-wrap">
              <label class="clip-card-checkbox-wrap" title="Select ranked clip">
                <input type="checkbox" class="ranked-clip-check" data-id="${clip.id}" ${isSelected ? 'checked' : ''}>
              </label>
              <div class="rank-position-badge ${rankClass}">${rankLabel}</div>
              <img src="${clip.thumbnail}" alt="" onerror="this.src='/static/icon.png'">
              <span class="clip-category-tag">${escapeHtml(clip.category || 'Viral Short')}</span>
              <span class="clip-duration-tag">${clip.duration}s</span>
            </div>
            <div class="ranked-metrics-bar">
              <span class="viral-score-tag">⚡ ${viralScore}/10</span>
              <span class="hook-grade-tag">Hook: ${escapeHtml(hookGrade)}</span>
            </div>
            <div class="ai-verdict-quote">"${escapeHtml(verdict)}"</div>
            <div class="clip-card-info">
              <div class="clip-card-title">${escapeHtml(clip.title)}</div>
              <div class="clip-card-actions">
                <button type="button" class="primary play-clip-btn" title="Watch Short">Preview ▶</button>
                <button type="button" class="ghost edit-clip-btn" title="Edit Clip">Edit ✂️</button>
                <a href="${clip.vertical_video}" download="${escapeHtml(clip.title)}.mp4" class="ghost save-clip-btn" title="Download Short">Save ↓</a>
                <button type="button" class="ghost delete-clip-btn" title="Delete Clip">✕</button>
              </div>
            </div>
          `;

          const chk = card.querySelector('.ranked-clip-check');
          chk.addEventListener('change', (e) => {
            e.stopPropagation();
            if (chk.checked) {
              selectedRankedClipIds.add(clip.id);
              card.classList.add('selected');
            } else {
              selectedRankedClipIds.delete(clip.id);
              card.classList.remove('selected');
            }
            updateBatchRankedToolbar(ranked.length);
          });

          card.querySelector('.play-clip-btn').addEventListener('click', () => {
            openPreviewModal(clip);
          });

          card.querySelector('.edit-clip-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            openEditModal(clip);
          });

          card.querySelector('.delete-clip-btn').addEventListener('click', async (e) => {
            e.stopPropagation();
            if (confirm('Delete this ranked clip?')) {
              await fetch(`/api/live/clips/${clip.id}`, { method: 'DELETE' });
              selectedRankedClipIds.delete(clip.id);
              fetchRankedClips();
              fetchClips();
            }
          });

          rankedClipsGrid.appendChild(card);
        });

        updateBatchRankedToolbar(ranked.length);
      }
    } catch (err) {
      console.debug('Ranked clips error:', err);
    }
  }

  async function fetchClips() {
    try {
      const resp = await fetch('/api/live/clips');
      if (!resp.ok) return;
      const data = await resp.json();
      const clips = data.clips || [];

      if (clipsCount) clipsCount.textContent = clips.length;

      if (clips.length === 0) {
        if (emptyClipsMsg) emptyClipsMsg.style.display = 'flex';
        return;
      }

      if (emptyClipsMsg) emptyClipsMsg.style.display = 'none';
      liveClipsGrid.innerHTML = '';

      clips.forEach(clip => {
        const card = document.createElement('div');
        const isChecked = selectedClipIds.has(clip.id);
        card.className = `live-clip-card ${isChecked ? 'selected' : ''}`;
        const badges = (clip.badges && clip.badges.length > 0) ? clip.badges : ['✨ Smart Fit', '💬 Auto Captions'];
        const badgesHtml = badges.map(b => `<span class="clip-badge-pill">${escapeHtml(b)}</span>`).join('');

        card.innerHTML = `
          <div class="clip-thumb-wrap">
            <label class="clip-card-checkbox-wrap" title="Select clip">
              <input type="checkbox" class="clip-select-check" data-id="${clip.id}" ${isChecked ? 'checked' : ''}>
            </label>
            <img src="${clip.thumbnail}" alt="" onerror="this.src='/static/icon.png'">
            <span class="clip-category-tag">${escapeHtml(clip.category || 'Highlight')}</span>
            <span class="clip-duration-tag">${clip.duration}s</span>
          </div>
          <div class="clip-card-info">
            <div class="clip-card-title">${escapeHtml(clip.title)}</div>
            ${badgesHtml ? `<div class="clip-badges-row">${badgesHtml}</div>` : ''}
            <div class="clip-card-actions">
              <button type="button" class="primary play-clip-btn" title="Watch Short">Preview ▶</button>
              <button type="button" class="ghost edit-clip-btn" title="Edit Clip">Edit ✂️</button>
              <a href="${clip.vertical_video}" download="${escapeHtml(clip.title)}.mp4" class="ghost save-clip-btn" title="Download Short">Save ↓</a>
              <button type="button" class="ghost delete-clip-btn" title="Delete Clip">✕</button>
            </div>
          </div>
        `;

        const chk = card.querySelector('.clip-select-check');
        chk.addEventListener('change', (e) => {
          e.stopPropagation();
          if (chk.checked) {
            selectedClipIds.add(clip.id);
            card.classList.add('selected');
          } else {
            selectedClipIds.delete(clip.id);
            card.classList.remove('selected');
          }
          updateBatchClipsToolbar(clips.length);
        });

        card.querySelector('.play-clip-btn').addEventListener('click', () => {
          openPreviewModal(clip);
        });

        card.querySelector('.edit-clip-btn').addEventListener('click', (e) => {
          e.stopPropagation();
          openEditModal(clip);
        });

        card.querySelector('.delete-clip-btn').addEventListener('click', async (e) => {
          e.stopPropagation();
          if (confirm('Delete this generated clip?')) {
            await fetch(`/api/live/clips/${clip.id}`, { method: 'DELETE' });
            selectedClipIds.delete(clip.id);
            fetchClips();
            fetchRankedClips();
          }
        });

        liveClipsGrid.appendChild(card);
      });

      updateBatchClipsToolbar(clips.length);
    } catch (err) {
      console.debug('Clips fetch error:', err);
    }
  }

  function openPreviewModal(clip) {
    activePreviewClip = clip;
    modalClipTitle.textContent = clip.title;
    modalVideoPlayer.src = clip.vertical_video;
    modalDownloadBtn.href = clip.vertical_video;
    modalDownloadBtn.download = `${clip.title}_9_16.mp4`;

    if (modalClipDesc) {
      modalClipDesc.textContent = clip.description || `🎮 ${clip.title}\n\nViral stream highlight captured with Clipify AI Live Studio. Features gaming split-screen and smart subtitles.`;
    }
    if (modalClipTags) {
      modalClipTags.textContent = clip.tags_str || (clip.tags ? clip.tags.join(' ') : '#Shorts #Gaming #LiveStream #ViralShorts #ClipifyAI');
    }

    // Auto-generate AI description if empty or default placeholder
    if (!clip.description || clip.description.includes('Viral stream highlight captured with Clipify AI')) {
      fetch(`/api/live/clips/${clip.id}/generate-description`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      .then(res => res.json())
      .then(data => {
        if (data && data.ok && activePreviewClip && activePreviewClip.id === clip.id) {
          activePreviewClip.description = data.description;
          activePreviewClip.tags = data.tags;
          activePreviewClip.tags_str = data.tags_str;
          if (modalClipDesc) modalClipDesc.textContent = data.description;
          if (modalClipTags) modalClipTags.textContent = data.tags_str;
        }
      })
      .catch(() => {});
    }

    if (clip.original_video) {
      modalDownloadOrigBtn.href = clip.original_video;
      modalDownloadOrigBtn.download = `${clip.title}_16_9.mp4`;
      modalDownloadOrigBtn.style.display = 'inline-flex';
    } else {
      modalDownloadOrigBtn.style.display = 'none';
    }

    clipPreviewModal.style.display = 'flex';
    modalVideoPlayer.play().catch(() => {});
  }

  if (btnGenClipDesc) {
    btnGenClipDesc.addEventListener('click', async () => {
      if (!activePreviewClip) return;
      const origBtnText = btnGenClipDesc.textContent;
      btnGenClipDesc.textContent = 'Generating... ⏳';
      btnGenClipDesc.disabled = true;
      try {
        const resp = await fetch(`/api/live/clips/${activePreviewClip.id}/generate-description`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        });
        const data = await resp.json();
        if (data && data.ok) {
          activePreviewClip.description = data.description;
          activePreviewClip.tags = data.tags;
          activePreviewClip.tags_str = data.tags_str;
          if (modalClipDesc) modalClipDesc.textContent = data.description;
          if (modalClipTags) modalClipTags.textContent = data.tags_str;
          btnGenClipDesc.textContent = 'Generated! ✨';
          setTimeout(() => { btnGenClipDesc.textContent = origBtnText; btnGenClipDesc.disabled = false; }, 2000);
        } else {
          alert(data.error || 'Failed to generate AI description.');
          btnGenClipDesc.textContent = origBtnText;
          btnGenClipDesc.disabled = false;
        }
      } catch (e) {
        alert('Error generating AI description: ' + e.message);
        btnGenClipDesc.textContent = origBtnText;
        btnGenClipDesc.disabled = false;
      }
    });
  }

  if (btnCopyClipMeta) {
    btnCopyClipMeta.addEventListener('click', () => {
      if (!activePreviewClip) return;
      const textToCopy = `${activePreviewClip.title || ''}\n\n${modalClipDesc ? modalClipDesc.textContent : ''}\n\n${modalClipTags ? modalClipTags.textContent : ''}`;
      navigator.clipboard.writeText(textToCopy).then(() => {
        btnCopyClipMeta.textContent = 'Copied! ✓';
        setTimeout(() => { btnCopyClipMeta.textContent = '📋 Copy All'; }, 2000);
      }).catch(() => {
        btnCopyClipMeta.textContent = 'Copied! ✓';
        setTimeout(() => { btnCopyClipMeta.textContent = '📋 Copy All'; }, 2000);
      });
    });
  }

  function openEditModal(clip) {
    activeEditingClip = clip;
    if (editModalVideoPlayer) {
      editModalVideoPlayer.src = clip.vertical_video;
      editModalVideoPlayer.load();
    }
    if (editClipTitle) editClipTitle.value = clip.title || '';
    if (editClipCategory) editClipCategory.value = clip.category || 'High-energy moments';
    if (editClipText) editClipText.value = clip.subtitle_text || clip.overlay_text || '';

    if (clipEditModal) clipEditModal.style.display = 'flex';
  }

  function formatDuration(sec) {
    const s = Math.floor(sec || 0);
    const hrs = Math.floor(s / 3600);
    const mins = Math.floor((s % 3600) / 60);
    const secs = s % 60;
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  }

  document.addEventListener('DOMContentLoaded', init);
})();
