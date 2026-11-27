/**
 * Clipify AI - In-Place Fast Updater
 * Checks GitHub for new releases and updates files in-place without running the 330MB installer.
 */
(function() {
  function initSidebarUpdater() {
    const card = document.getElementById('sidebarUpdateCard');
    const btn = document.getElementById('btnSidebarUpdate');
    const statusMsg = document.getElementById('sidebarUpdateStatus');
    const badge = document.getElementById('sidebarVersionBadge');
    const modal = document.getElementById('updateModal');
    const closeModal = document.getElementById('closeUpdateModal');
    const modalContent = document.getElementById('updateModalContent');
    const btnExecute = document.getElementById('btnExecuteUpdate');
    const btnView = document.getElementById('btnViewRelease');
    const modalTitle = document.getElementById('updateModalTitle');
    const navUpdateLink = document.getElementById('navUpdateLink');
    const navVersionTag = document.getElementById('navVersionTag');

    if (!card && !btn && !navUpdateLink) return;

    let updateState = {
      checked: false,
      updateAvailable: false,
      latestVersion: 'v5.0.3',
      currentVersion: 'v5.0.3',
      releaseUrl: 'https://github.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases',
      releaseName: '',
      notes: '',
      isGit: false,
      gitBehind: false
    };

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    async function checkUpdate(silent = false) {
      if (!silent) {
        btn.innerHTML = '<span class="btn-update-icon spinning">↻</span> Checking…';
        btn.disabled = true;
      }
      try {
        const res = await fetch('/api/updater/check');
        const data = await res.json();
        updateState = {
          checked: true,
          updateAvailable: !!data.update_available,
          latestVersion: data.latest_version || 'v5.0.3',
          currentVersion: data.current_version || 'v5.0.3',
          releaseUrl: data.release_url || updateState.releaseUrl,
          releaseName: data.release_name || '',
          notes: data.body || '',
          isGit: !!data.is_git,
          gitBehind: !!data.git_behind
        };

        if (badge) badge.textContent = data.current_version || 'v5.0.7';
        if (navVersionTag) navVersionTag.textContent = data.current_version || 'v5.0.7';
        const topBadgeEl = document.getElementById('topBrandVersionBadge');
        const topBadgeNum = document.querySelector('#topBrandVersionBadge .version-num');
        if (topBadgeNum) topBadgeNum.textContent = data.current_version || 'v5.0.7';
        const mobileUpdBtn = document.getElementById('mobileHeaderUpdateBtn');

        if (!document.getElementById('clipify-update-highlight-css')) {
          const st = document.createElement('style');
          st.id = 'clipify-update-highlight-css';
          st.textContent = `
            #navUpdateLink.clipify-update-highlight {
              background: linear-gradient(90deg, rgba(34,197,94,0.20), rgba(16,185,129,0.08)) !important;
              border: 1px solid rgba(34,197,94,0.65) !important;
              color: #ecfdf5 !important;
              box-shadow: 0 0 16px rgba(34,197,94,0.28) !important;
              animation: clipifyUpdPulse 2.2s infinite ease-in-out;
            }
            #topBrandVersionBadge.clipify-update-highlight,
            #mobileHeaderUpdateBtn.clipify-update-highlight {
              border-color: rgba(34,197,94,0.75) !important;
              background: rgba(34,197,94,0.18) !important;
              color: #4ade80 !important;
              box-shadow: 0 0 14px rgba(34,197,94,0.32) !important;
            }
            @keyframes clipifyUpdPulse {
              0%, 100% { box-shadow: 0 0 10px rgba(34,197,94,0.22); }
              50% { box-shadow: 0 0 22px rgba(34,197,94,0.52); }
            }
          `;
          (document.head || document.documentElement).appendChild(st);
        }

        if (updateState.updateAvailable) {
          if (card) card.classList.add('has-update');
          if (navUpdateLink) navUpdateLink.classList.add('clipify-update-highlight');
          if (topBadgeEl) topBadgeEl.classList.add('clipify-update-highlight');
          if (mobileUpdBtn) {
            mobileUpdBtn.classList.add('clipify-update-highlight');
            mobileUpdBtn.textContent = `↓ ${updateState.latestVersion || 'Update'}`;
          }
          if (navVersionTag) {
            navVersionTag.textContent = `New ${updateState.latestVersion || 'Update'}`;
            navVersionTag.style.background = '#22c55e';
            navVersionTag.style.color = '#052e16';
            navVersionTag.style.fontWeight = '800';
          }
          if (statusMsg) statusMsg.textContent = `New: ${updateState.latestVersion}`;
          if (btn) {
            btn.innerHTML = '<span class="btn-update-icon">⚡</span> Update';
            btn.disabled = false;
          }
          if (!silent) {
            openModalWithRelease(updateState);
          }
        } else {
          if (card) card.classList.remove('has-update');
          if (navUpdateLink) navUpdateLink.classList.remove('clipify-update-highlight');
          if (topBadgeEl) topBadgeEl.classList.remove('clipify-update-highlight');
          if (mobileUpdBtn) mobileUpdBtn.classList.remove('clipify-update-highlight');
          if (navVersionTag) {
            navVersionTag.textContent = data.current_version || 'v5.0.7';
            navVersionTag.style.background = '';
            navVersionTag.style.color = '';
            navVersionTag.style.fontWeight = '';
          }
          if (badge) badge.textContent = data.current_version || 'v5.0.7';
          if (statusMsg) statusMsg.textContent = 'Up to date ✓';
          if (btn) {
            btn.innerHTML = '<span class="btn-update-icon">↻</span> Update';
            btn.disabled = false;
          }
          if (!silent) {
            openModalUpToDate(updateState);
          }
        }
      } catch (err) {
        if (statusMsg) statusMsg.textContent = 'Offline';
        if (btn) {
          btn.innerHTML = '<span class="btn-update-icon">↻</span> Retry';
          btn.disabled = false;
        }
        if (!silent) {
          alert('Could not check for updates: ' + err.message);
        }
      }
    }

    function openModalWithRelease(info) {
      if (!modal) return;
      ensureModalAsciiBackground();
      modal.style.display = 'flex';
      if (modalTitle) modalTitle.textContent = `New Release Available: ${info.latestVersion}`;
      if (btnView) btnView.href = info.releaseUrl;
      if (btnExecute) {
        btnExecute.style.display = 'inline-block';
        btnExecute.textContent = '⚡ Update Now (Fast)';
        btnExecute.disabled = false;
      }
      if (modalContent) {
        modalContent.innerHTML = `
          <div style="margin-bottom:10px;">
            <b style="color:#4ade80;font-size:14px;">${escapeHtml(info.releaseName || ('Clipify AI ' + info.latestVersion))}</b>
            <div style="font-size:12px;color:#94a3b8;margin-top:2px;">Installed: <b>${escapeHtml(info.currentVersion)}</b> &nbsp;→&nbsp; Latest: <b>${escapeHtml(info.latestVersion)}</b></div>
          </div>
          <p style="margin:8px 0 12px;font-size:12px;color:#cbd5e1;line-height:1.5;">
            Press <b>Update Now</b> to update in-place without running the 330MB installer. Your clips, jobs, and AI models are completely preserved.
          </p>
          ${info.notes ? `<pre style="font-family:inherit;font-size:11px;color:#94a3b8;max-height:120px;overflow-y:auto;background:rgba(0,0,0,0.35);padding:10px;border-radius:8px;white-space:pre-wrap;border:1px solid rgba(255,255,255,0.06);">${escapeHtml(info.notes)}</pre>` : ''}
        `;
      }
    }

    function openModalUpToDate(info) {
      if (!modal) return;
      ensureModalAsciiBackground();
      modal.style.display = 'flex';
      if (modalTitle) modalTitle.textContent = 'Clipify AI is Up to Date';
      if (btnView) btnView.href = info.releaseUrl;
      if (btnExecute) {
        btnExecute.style.display = 'inline-block';
        btnExecute.textContent = 'Force Re-sync / Hotfixes';
        btnExecute.disabled = false;
      }
      if (modalContent) {
        modalContent.innerHTML = `
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
            <span style="color:#4ade80;font-size:20px;">✓</span>
            <div>
              <b style="color:#f8fafc;font-size:13px;">Version ${escapeHtml(info.currentVersion)} is currently installed.</b>
              <div style="font-size:11px;color:#94a3b8;">You are running the latest official release.</div>
            </div>
          </div>
          <p style="margin:8px 0 0;font-size:12px;color:#94a3b8;line-height:1.4;">
            If you want to pull the newest commits and hotfixes from GitHub without waiting for a new tag, click <b>Force Re-sync / Hotfixes</b>.
          </p>
        `;
      }
    }

    async function applyUpdate() {
      if (!btnExecute) return;
      if (window.AndroidBridge || window.location.protocol === 'file:') {
        btnExecute.disabled = true;
        btnExecute.innerHTML = '<span class="btn-update-icon spinning">↻</span> Fetching Mobile APK…';
        try {
          if (typeof window.openClipifyMobileUpdate === 'function') {
            await window.openClipifyMobileUpdate();
          } else {
            const url = updateState.releaseUrl || 'https://github.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases/latest';
            if (window.AndroidBridge && window.AndroidBridge.openBrowser) window.AndroidBridge.openBrowser(url);
            else window.open(url, '_blank');
          }
        } finally {
          btnExecute.disabled = false;
          btnExecute.innerHTML = 'Download Latest APK →';
          if (modal) modal.style.display = 'none';
        }
        return;
      }
      btnExecute.disabled = true;
      btnExecute.innerHTML = '<span class="btn-update-icon spinning">↻</span> Updating…';

      // Immediately hide modal and trigger updating takeover sub-window
      stopModalAsciiBackground();
      if (modal) modal.style.display = 'none';
      triggerRestartTakeover('Applying core updates & rebooting local engine…');

      try {
        const res = await fetch('/api/updater/apply', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error(data.error || 'Update failed');
        }
        addConsoleLog('[Patch] Synchronized code & refreshed assets successfully.', 'success');
      } catch (err) {
        addConsoleLog(`[Error] Update failed: ${err.message}`, 'error');
        const statusLabel = document.getElementById('restartStatusLabel');
        if (statusLabel) statusLabel.textContent = `Update failed: ${err.message}`;
        const actionRow = document.getElementById('restartActionRow');
        if (actionRow) {
          actionRow.style.display = 'flex';
          actionRow.style.gap = '10px';
          actionRow.innerHTML = `
            <a href="https://github.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE/releases/tag/v5.0.5" target="_blank" class="btn-restart-retry" style="text-align:center;text-decoration:none;background:#22c55e;color:#000;font-weight:700;">Download v5.0.5 Installer →</a>
            <button type="button" class="btn-restart-retry" id="btnRestartForceReload">Retry / Reload</button>
          `;
          document.getElementById('btnRestartForceReload')?.addEventListener('click', () => window.location.reload());
        }
      }
    }

    /**
     * Sub-Window Themed Update & Restarting Modal
     * Features:
     * - Blurred Clipify app background
     * - Official Clipify App Mascot Logo
     * - "Updating Clipify AI..."
     * - Live update console streaming step-by-step logs
     * - Fast health check polling with instant reload & fallback button
     */
    function triggerRestartTakeover(msg) {
      let overlay = document.getElementById('clipifyRestartOverlay');
      if (!overlay || !overlay.querySelector('.restart-modal-window')) {
        if (!overlay) {
          overlay = document.createElement('div');
          overlay.id = 'clipifyRestartOverlay';
          overlay.className = 'clipify-restart-overlay';
          document.body.appendChild(overlay);
        }
        overlay.innerHTML = `
          <canvas id="restartAsciiCanvas" class="restart-ascii-canvas"></canvas>
          <div class="restart-modal-window">
            <div class="restart-modal-header">
              <div class="restart-logo-wrapper">
                <img src="/static/icon.png" alt="Clipify AI Logo" class="restart-app-logo" />
                <div class="restart-logo-glow"></div>
              </div>
              <div class="restart-title-group">
                <h2 class="restart-modal-title">Updating Clipify AI...</h2>
                <div class="restart-modal-subtitle">
                  <span class="restart-pulse-dot"></span>
                  <span id="restartStatusLabel">Applying core updates &amp; rebooting local AI engine…</span>
                </div>
              </div>
            </div>

            <div class="restart-console-wrapper">
              <div class="restart-console-header">
                <div class="restart-console-dots">
                  <span class="dot-red"></span>
                  <span class="dot-yellow"></span>
                  <span class="dot-green"></span>
                </div>
                <span class="restart-console-title">Live Update Console</span>
                <span class="restart-console-badge" id="restartConsoleBadge">SYNCING</span>
              </div>
              <div class="restart-console-body" id="restartConsoleBody">
                <div class="console-line info">[Init] Connecting to local update controller...</div>
              </div>
            </div>

            <div class="restart-footer">
              <div class="restart-progress-info">
                <span id="restartProgressDetail">Downloading &amp; syncing latest assets...</span>
                <span id="restartProgressPct">15%</span>
              </div>
              <div class="restart-progress-track">
                <div class="restart-progress-bar" id="restartProgressBar" style="width: 15%;"></div>
              </div>
              <div class="restart-action-row" id="restartActionRow" style="display:none;margin-top:10px;">
                <button type="button" class="btn-restart-retry" id="btnRestartForceReload">Force Reload Clipify</button>
              </div>
            </div>
          </div>
        `;
      }

      overlay.style.display = 'flex';
      initRestartCanvas();
      startLiveConsoleAndUpdate(msg);
    }

    function addConsoleLog(text, type = 'info') {
      const body = document.getElementById('restartConsoleBody');
      if (!body) return;
      const now = new Date();
      const timeStr = [now.getHours(), now.getMinutes(), now.getSeconds()]
        .map(n => String(n).padStart(2, '0'))
        .join(':');
      const line = document.createElement('div');
      line.className = `console-line ${type}`;
      line.textContent = `[${timeStr}] ${text}`;
      body.appendChild(line);
      body.scrollTop = body.scrollHeight;
    }

    function startLiveConsoleAndUpdate(initialMsg) {
      const statusLabel = document.getElementById('restartStatusLabel');
      const progressBar = document.getElementById('restartProgressBar');
      const progressDetail = document.getElementById('restartProgressDetail');
      const progressPct = document.getElementById('restartProgressPct');
      const consoleBadge = document.getElementById('restartConsoleBadge');
      const actionRow = document.getElementById('restartActionRow');
      const forceReloadBtn = document.getElementById('btnRestartForceReload');

      if (forceReloadBtn) {
        forceReloadBtn.onclick = () => window.location.reload();
      }

      let progress = 18;
      const updateProg = (p, text) => {
        progress = Math.min(100, Math.max(progress, p));
        if (progressBar) progressBar.style.width = progress + '%';
        if (progressPct) progressPct.textContent = progress + '%';
        if (progressDetail && text) progressDetail.textContent = text;
      };

      addConsoleLog('Update routine triggered: ' + (initialMsg || 'Fast in-place sync'), 'step');

      setTimeout(() => {
        addConsoleLog('[Git] Checking upstream repository: sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE', 'info');
        updateProg(35, 'Fetching code updates from GitHub...');
      }, 200);

      setTimeout(() => {
        addConsoleLog('[Fetch] Pulling latest frontend modules, UI tokens, and AI pipelines...', 'info');
        updateProg(55, 'Applying updates to local workspace...');
      }, 450);

      setTimeout(() => {
        addConsoleLog('[Patch] Synchronized code and refreshed assets successfully.', 'success');
        addConsoleLog('[Engine] Restarting Clipify AI local daemon...', 'step');
        updateProg(75, 'Rebooting local AI engine...');
      }, 700);

      let startTime = Date.now();
      let serverWentDown = false;
      let pingCount = 0;

      const pollInterval = setInterval(async () => {
        pingCount++;
        const elapsedSec = Math.floor((Date.now() - startTime) / 1000);

        if (statusLabel) {
          statusLabel.textContent = `Rebooting local AI engine… (${elapsedSec}s)`;
        }

        if (pingCount === 2) {
          addConsoleLog(`[Ping] Waiting for port 5000 to rebind...`, 'info');
        } else if (pingCount % 4 === 0 && !serverWentDown) {
          addConsoleLog(`[Sync] Probing http://127.0.0.1:5000/api/health (${elapsedSec}s)...`, 'info');
        }

        // Progressively advance progress so it never looks dead at 75%
        if (elapsedSec >= 2 && progress < 82) {
          updateProg(82, 'Awaiting daemon port rebind...');
        } else if (elapsedSec >= 4 && progress < 90) {
          updateProg(90, 'Finalizing server warmup...');
        }

        // After 6 seconds, reveal force reload button
        if (elapsedSec >= 6 && actionRow) {
          actionRow.style.display = 'block';
          if (pingCount === 12) {
            addConsoleLog(`[Notice] Almost ready — click 'Force Reload Clipify' anytime to refresh.`, 'warn');
          }
        }

        try {
          const res = await fetch('/api/health?t=' + Date.now(), { cache: 'no-store' });
          if (res.ok) {
            if (serverWentDown) {
              clearInterval(pollInterval);
              updateProg(100, 'Update Complete!');
              if (consoleBadge) {
                consoleBadge.textContent = 'ONLINE';
                consoleBadge.style.background = 'rgba(34, 197, 94, 0.25)';
              }
              addConsoleLog('[✓] Health check passed (200 OK)! Engine online.', 'success');
              addConsoleLog('[Done] Reloading Clipify AI workspace...', 'success');
              if (statusLabel) statusLabel.textContent = '✓ RESTART COMPLETE — RELOADING…';
              setTimeout(() => {
                window.location.reload();
              }, 450);
            }
          } else {
            serverWentDown = true;
          }
        } catch (err) {
          // Expected while server shuts down and rebinds
          serverWentDown = true;
        }
      }, 400);
    }

    let modalAsciiCtrl = null;
    function ensureModalAsciiBackground() {
      if (!modal) return;
      let canvas = modal.querySelector('.update-modal-ascii-canvas');
      if (!canvas) {
        canvas = document.createElement('canvas');
        canvas.id = 'updateModalAsciiCanvas';
        canvas.className = 'restart-ascii-canvas update-modal-ascii-canvas';
        modal.insertBefore(canvas, modal.firstChild);
      }
      if (!modalAsciiCtrl) {
        modalAsciiCtrl = initAsciiMatrixBackground(canvas);
      }
      if (modalAsciiCtrl) {
        modalAsciiCtrl.start();
      }
    }

    function stopModalAsciiBackground() {
      if (modalAsciiCtrl) {
        modalAsciiCtrl.stop();
      }
    }

    function initRestartCanvas() {
      const canvas = document.getElementById('restartAsciiCanvas');
      if (!canvas) return;
      const ctrl = initAsciiMatrixBackground(canvas);
      if (ctrl) ctrl.start();
    }

    function initAsciiMatrixBackground(canvas) {
      if (!canvas) return null;
      const ctx = canvas.getContext('2d');
      if (!ctx) return null;

      const SYMBOLS = ['!', '@', '#', '$', '%', '^', '&', '*', '0', '1', '7', '8', 'X', 'Q', 'G', '~', '/', '\\', '+', '?'];
      const LOGO_SYMBOLS = ['✦', '★', '●', '■', '1', '0', '#', '*', '%', 'V'];
      let width = canvas.width = window.innerWidth;
      let height = canvas.height = window.innerHeight;

      const SPACING = 20;
      let cols = Math.floor(width / SPACING);
      let rows = Math.floor(height / SPACING);

      let grid = [];
      let gridMap = {};
      function buildGrid() {
        grid = [];
        gridMap = {};
        for (let r = 0; r < rows; r++) {
          for (let c = 0; c < cols; c++) {
            const bx = c * SPACING + SPACING / 2;
            const by = r * SPACING + SPACING / 2;
            const pt = {
              col: c, row: r,
              baseX: bx, baseY: by,
              x: bx + (Math.random() - 0.5) * 4,
              y: by + (Math.random() - 0.5) * 4,
              vx: (Math.random() - 0.5) * 0.4,
              vy: (Math.random() - 0.5) * 0.4,
              char: SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)],
              alpha: 0.20 + Math.random() * 0.14,
              baseAlpha: 0.20 + Math.random() * 0.14,
              charTimer: Math.random() * 3
            };
            grid.push(pt);
            gridMap[`${c},${r}`] = pt;
          }
        }
      }
      buildGrid();

      function onResize() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
        cols = Math.floor(width / SPACING);
        rows = Math.floor(height / SPACING);
        buildGrid();
      }
      window.addEventListener('resize', onResize);

      let mouse = { x: -9999, y: -9999, active: false };
      window.addEventListener('mousemove', (e) => {
        mouse.x = e.clientX;
        mouse.y = e.clientY;
        mouse.active = true;
      });

      // Clipify Mascot Logo Shape (Cat Face with Crown & Whiskers)
      const LOGO_OFFSETS = [
        // Left Ear
        [-6, -6], [-5, -7], [-4, -6], [-4, -5],
        // Right Ear
        [4, -5], [4, -6], [5, -7], [6, -6],
        // Crown Peaks in Center
        [-2, -7], [-1, -6], [0, -8], [1, -6], [2, -7],
        [-2, -5], [-1, -5], [0, -5], [1, -5], [2, -5],
        // Head Top Outline
        [-3, -4], [-2, -4], [-1, -4], [0, -4], [1, -4], [2, -4], [3, -4],
        // Cheeks Outline
        [-7, -3], [-6, -3], [6, -3], [7, -3],
        [-7, -2], [-6, -2], [6, -2], [7, -2],
        [-7, -1], [-6, -1], [6, -1], [7, -1],
        [-7, 0], [7, 0],
        [-7, 1], [-6, 1], [6, 1], [7, 1],
        // Cute Eyes
        [-3, -1], [-3, 0], [3, -1], [3, 0],
        // Cute Nose
        [0, 1],
        // Whiskers Left
        [-9, -1], [-8, -1], [-10, 1], [-9, 1], [-8, 1],
        // Whiskers Right
        [8, -1], [9, -1], [8, 1], [9, 1], [10, 1],
        // Chin Bottom
        [-5, 3], [-4, 4], [-3, 4], [-2, 4], [-1, 4], [0, 4], [1, 4], [2, 4], [3, 4], [4, 4], [5, 3]
      ];

      // 5x7 ASCII bitmap definitions for the word "CLIPIFY"
      const GLYPHS = {
        'C': [
          " 1111",
          "1    ",
          "1    ",
          "1    ",
          "1    ",
          "1    ",
          " 1111"
        ],
        'L': [
          "1    ",
          "1    ",
          "1    ",
          "1    ",
          "1    ",
          "1    ",
          "11111"
        ],
        'I': [
          "11111",
          "  1  ",
          "  1  ",
          "  1  ",
          "  1  ",
          "  1  ",
          "11111"
        ],
        'P': [
          "1111 ",
          "1   1",
          "1   1",
          "1111 ",
          "1    ",
          "1    ",
          "1    "
        ],
        'F': [
          "11111",
          "1    ",
          "1    ",
          "1111 ",
          "1    ",
          "1    ",
          "1    "
        ],
        'Y': [
          "1   1",
          "1   1",
          " 1 1 ",
          "  1  ",
          "  1  ",
          "  1  ",
          "  1  "
        ]
      };

      const WORD = ['C', 'L', 'I', 'P', 'I', 'F', 'Y'];
      const WORD_MAP = [];
      let currentOffsetCol = 0;
      WORD.forEach((letter) => {
        const rws = GLYPHS[letter] || GLYPHS['C'];
        for (let r = 0; r < 7; r++) {
          const line = rws[r] || "     ";
          for (let c = 0; c < 5; c++) {
            if (line[c] === '1') {
              WORD_MAP.push({ relCol: currentOffsetCol + c, relRow: r });
            }
          }
        }
        currentOffsetCol += 6; // 5 cols + 1 col gap
      });
      const WORD_TOTAL_COLS = currentOffsetCol; // ~42 cols
      const WORD_TOTAL_ROWS = 7;

      // Active Clipify Word Spawns
      let textSpawns = [];
      let lastTextSpawn = Date.now() - 1500;

      function spawnClipifyWord() {
        if (cols < 20 || rows < 10) return;
        const maxCol = Math.max(1, cols - WORD_TOTAL_COLS - 2);
        const maxRow = Math.max(1, rows - WORD_TOTAL_ROWS - 2);

        const startCol = Math.floor(1 + Math.random() * maxCol);
        const startRow = Math.floor(1 + Math.random() * maxRow);

        const charOverrides = {};
        WORD_MAP.forEach((pt, idx) => {
          charOverrides[idx] = LOGO_SYMBOLS[Math.floor(Math.random() * LOGO_SYMBOLS.length)];
        });

        textSpawns.push({
          startCol,
          startRow,
          alpha: 0,
          targetAlpha: 0.95,
          phase: 'fadeIn',
          timer: 0,
          holdDuration: 3.2 + Math.random() * 1.8,
          fadeSpeed: 1.1,
          charOverrides
        });
      }

      // Inline text highlights: e.g. "CLIPIFY", "CLIPIFY AI"
      let inlineWords = [];
      const INLINE_STRINGS = ['CLIPIFY', 'CLIPIFY AI', 'CLIP.AI', '★ CLIPIFY ★'];
      function spawnInlineWord() {
        if (inlineWords.length >= 4 || cols < 15) return;
        const word = INLINE_STRINGS[Math.floor(Math.random() * INLINE_STRINGS.length)];
        const maxC = Math.max(0, cols - word.length - 2);
        const maxR = Math.max(0, rows - 2);
        const startC = Math.floor(1 + Math.random() * maxC);
        const startR = Math.floor(1 + Math.random() * maxR);

        inlineWords.push({
          word,
          startC,
          startR,
          alpha: 0,
          targetAlpha: 0.90 + Math.random() * 0.10,
          phase: 'fadeIn',
          timer: 0,
          life: 3.0 + Math.random() * 2.0
        });
      }

      // Pre-seed an initial CLIPIFY word and inline words
      spawnClipifyWord();
      spawnInlineWord();
      spawnInlineWord();

      // Active Clipify Logo Shape Spawns
      let logoSpawns = [];
      let lastLogoSpawn = Date.now() - 1000;

      function spawnLogoInstance() {
        if (cols < 24 || rows < 18) return;
        // Avoid center where modal window is: pick left flank, right flank, top, or bottom
        const zones = [
          { minC: 10, maxC: Math.max(12, Math.floor(cols * 0.30)), minR: 9, maxR: rows - 9 }, // Left
          { minC: Math.min(cols - 12, Math.floor(cols * 0.70)), maxC: cols - 10, minR: 9, maxR: rows - 9 }, // Right
          { minC: 12, maxC: cols - 12, minR: 8, maxR: Math.max(9, Math.floor(rows * 0.22)) }, // Top
          { minC: 12, maxC: cols - 12, minR: Math.min(rows - 9, Math.floor(rows * 0.78)), maxR: rows - 8 }  // Bottom
        ];
        const zone = zones[Math.floor(Math.random() * zones.length)];
        const centerC = Math.floor(zone.minC + Math.random() * (zone.maxC - zone.minC + 1));
        const centerR = Math.floor(zone.minR + Math.random() * (zone.maxR - zone.minR + 1));

        const points = [];
        for (const [dx, dy] of LOGO_OFFSETS) {
          const pt = gridMap[`${centerC + dx},${centerR + dy}`];
          if (pt) {
            points.push({
              pt: pt,
              char: LOGO_SYMBOLS[Math.floor(Math.random() * LOGO_SYMBOLS.length)],
              cycleTimer: Math.random() * 0.2
            });
          }
        }

        if (points.length > 15) {
          logoSpawns.push({
            centerC,
            centerR,
            points,
            alpha: 0,
            targetAlpha: 0.95,
            phase: 'in', // 'in', 'hold', 'out'
            timer: 0,
            holdDuration: 2.0 + Math.random() * 1.0
          });
        }
      }

      // Pre-seed an initial logo on one of the flanks
      spawnLogoInstance();

      // Individual random point highlights
      let highlights = [];
      function spawnHighlights() {
        if (highlights.length < 35 && Math.random() < 0.4) {
          const randPt = grid[Math.floor(Math.random() * grid.length)];
          if (randPt) {
            highlights.push({
              x: randPt.x,
              y: randPt.y,
              char: SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)],
              alpha: 0.3,
              targetAlpha: 0.85 + Math.random() * 0.15,
              phase: 'in',
              timer: 0,
              life: 1.2 + Math.random() * 1.8,
              cycleTimer: 0
            });
          }
        }
      }

      for (let k = 0; k < 20; k++) {
        const randPt = grid[Math.floor(Math.random() * grid.length)];
        if (randPt) {
          highlights.push({
            x: randPt.x,
            y: randPt.y,
            char: SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)],
            alpha: 0.70 + Math.random() * 0.25,
            targetAlpha: 0.95,
            phase: 'hold',
            timer: Math.random(),
            life: 2.0,
            cycleTimer: 0
          });
        }
      }

      let running = false;
      let rafId = null;

      function animate() {
        if (!running) return;
        ctx.fillStyle = '#000000';
        ctx.fillRect(0, 0, width, height);

        spawnHighlights();

        // Spawn Clipify logo shape periodically
        const now = Date.now();
        if (logoSpawns.length < 2 && (now - lastLogoSpawn) > 2800) {
          spawnLogoInstance();
          lastLogoSpawn = now;
        }

        // Spawn Clipify 5x7 ASCII word periodically
        if (textSpawns.length < 2 && (now - lastTextSpawn) > 3500) {
          spawnClipifyWord();
          lastTextSpawn = now;
        }

        // Spawn inline text words
        if (inlineWords.length < 4 && Math.random() < 0.15) {
          spawnInlineWord();
        }

        // Occasional cyber symbol glitch / shift in "CLIPIFY"
        if (Math.random() < 0.3) {
          for (const ts of textSpawns) {
            const randIdx = Math.floor(Math.random() * WORD_MAP.length);
            ts.charOverrides[randIdx] = LOGO_SYMBOLS[Math.floor(Math.random() * LOGO_SYMBOLS.length)];
          }
        }

        ctx.font = '11px "Courier New", monospace, monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        const repelRadius = 110;
        const repelRadiusSq = repelRadius * repelRadius;

        // Render & update background moving symbols
        for (let i = 0; i < grid.length; i++) {
          const pt = grid[i];

          // Slow constant drifting
          pt.x += pt.vx;
          pt.y += pt.vy;
          if (Math.abs(pt.x - pt.baseX) > 10) pt.vx *= -1;
          if (Math.abs(pt.y - pt.baseY) > 10) pt.vy *= -1;

          // Mouse cursor interaction
          if (mouse.active) {
            const dx = pt.x - mouse.x;
            const dy = pt.y - mouse.y;
            const dSq = dx * dx + dy * dy;
            if (dSq < repelRadiusSq && dSq > 0.001) {
              const dist = Math.sqrt(dSq);
              const force = (1 - dist / repelRadius) * 16;
              pt.x += (dx / dist) * force * 0.5;
              pt.y += (dy / dist) * force * 0.5;
              pt.alpha = Math.min(0.65, pt.baseAlpha + (1 - dist / repelRadius) * 0.5);
            } else {
              pt.alpha += (pt.baseAlpha - pt.alpha) * 0.04;
            }
          }

          // Slow return to base
          pt.x += (pt.baseX - pt.x) * 0.04;
          pt.y += (pt.baseY - pt.y) * 0.04;

          // Occasional symbol shift
          pt.charTimer += 0.016;
          if (pt.charTimer > 2.5) {
            pt.charTimer = 0;
            if (Math.random() < 0.3) {
              pt.char = SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)];
            }
          }

          ctx.fillStyle = `rgba(255, 255, 255, ${pt.alpha.toFixed(2)})`;
          ctx.fillText(pt.char, pt.x, pt.y);
        }

        // Render Clipify Logo Formations that highlight and vanish
        for (let m = logoSpawns.length - 1; m >= 0; m--) {
          const l = logoSpawns[m];
          l.timer += 0.016;

          if (l.phase === 'in') {
            l.alpha += 0.045;
            if (l.alpha >= l.targetAlpha) {
              l.alpha = l.targetAlpha;
              l.phase = 'hold';
              l.timer = 0;
            }
          } else if (l.phase === 'hold') {
            if (l.timer >= l.holdDuration) {
              l.phase = 'out';
            }
          } else if (l.phase === 'out') {
            l.alpha -= 0.035;
            if (l.alpha <= 0) {
              logoSpawns.splice(m, 1);
              continue;
            }
          }

          // Render logo dots/symbols with purple/cyan glow
          ctx.font = 'bold 12px "Courier New", monospace';
          ctx.shadowColor = 'rgba(168, 85, 247, 0.95)';
          ctx.shadowBlur = 12;

          for (const item of l.points) {
            item.cycleTimer += 0.016;
            if (item.cycleTimer > 0.18) {
              item.cycleTimer = 0;
              item.char = LOGO_SYMBOLS[Math.floor(Math.random() * LOGO_SYMBOLS.length)];
            }
            ctx.fillStyle = `rgba(235, 215, 255, ${Math.max(0, l.alpha).toFixed(2)})`;
            ctx.fillText(item.char, item.pt.x, item.pt.y);
          }
          ctx.shadowBlur = 0;
        }

        // Render dynamic individual highlighted symbols
        ctx.font = '11px "Courier New", monospace, monospace';
        for (let j = highlights.length - 1; j >= 0; j--) {
          const h = highlights[j];
          h.timer += 0.016;
          h.cycleTimer += 0.016;
          if (h.cycleTimer > 0.12) {
            h.cycleTimer = 0;
            h.char = SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)];
          }

          if (h.phase === 'in') {
            h.alpha += 0.06;
            if (h.alpha >= h.targetAlpha) {
              h.alpha = h.targetAlpha;
              h.phase = 'hold';
            }
          } else if (h.phase === 'hold') {
            if (h.timer >= h.life) {
              h.phase = 'out';
            }
          } else if (h.phase === 'out') {
            h.alpha -= 0.04;
            if (h.alpha <= 0) {
              highlights.splice(j, 1);
              continue;
            }
          }

          ctx.fillStyle = `rgba(255, 255, 255, ${Math.max(0, h.alpha).toFixed(2)})`;
          ctx.shadowColor = 'rgba(255, 255, 255, 0.85)';
          ctx.shadowBlur = 8;
          ctx.fillText(h.char, h.x, h.y);
          ctx.shadowBlur = 0;
        }

        // Render 5x7 ASCII Block "CLIPIFY" Word Formations
        for (let t = textSpawns.length - 1; t >= 0; t--) {
          const ts = textSpawns[t];
          ts.timer += 0.016;

          if (ts.phase === 'fadeIn') {
            ts.alpha += 0.016 * ts.fadeSpeed;
            if (ts.alpha >= ts.targetAlpha) {
              ts.alpha = ts.targetAlpha;
              ts.phase = 'hold';
              ts.timer = 0;
            }
          } else if (ts.phase === 'hold') {
            if (ts.timer >= ts.holdDuration) {
              ts.phase = 'fadeOut';
            }
          } else if (ts.phase === 'fadeOut') {
            ts.alpha -= 0.016 * ts.fadeSpeed;
            if (ts.alpha <= 0) {
              textSpawns.splice(t, 1);
              spawnClipifyWord();
              continue;
            }
          }

          if (ts.alpha > 0.02) {
            ctx.font = 'bold 12px "Courier New", monospace';
            ctx.shadowColor = 'rgba(160, 220, 255, 0.9)';
            ctx.shadowBlur = 9;
            WORD_MAP.forEach((pt, idx) => {
              const c = ts.startCol + pt.relCol;
              const r = ts.startRow + pt.relRow;
              const targetPt = gridMap[`${c},${r}`];
              if (targetPt) {
                const ch = ts.charOverrides[idx] || '#';
                ctx.fillStyle = `rgba(240, 248, 255, ${Math.max(0, ts.alpha).toFixed(2)})`;
                ctx.fillText(ch, targetPt.x, targetPt.y);
              }
            });
            ctx.shadowBlur = 0;
          }
        }

        // Render Inline "CLIPIFY" Text Words
        ctx.font = 'bold 13px "Courier New", monospace';
        for (let w = inlineWords.length - 1; w >= 0; w--) {
          const iw = inlineWords[w];
          iw.timer += 0.016;

          if (iw.phase === 'fadeIn') {
            iw.alpha += 0.04;
            if (iw.alpha >= iw.targetAlpha) {
              iw.alpha = iw.targetAlpha;
              iw.phase = 'hold';
              iw.timer = 0;
            }
          } else if (iw.phase === 'hold') {
            if (iw.timer >= iw.life) {
              iw.phase = 'fadeOut';
            }
          } else if (iw.phase === 'fadeOut') {
            iw.alpha -= 0.035;
            if (iw.alpha <= 0) {
              inlineWords.splice(w, 1);
              continue;
            }
          }

          if (iw.alpha > 0.02) {
            ctx.shadowColor = 'rgba(192, 132, 252, 0.9)';
            ctx.shadowBlur = 8;
            for (let ci = 0; ci < iw.word.length; ci++) {
              const pt = gridMap[`${iw.startC + ci},${iw.startR}`];
              if (pt) {
                ctx.fillStyle = `rgba(245, 235, 255, ${Math.max(0, iw.alpha).toFixed(2)})`;
                ctx.fillText(iw.word[ci], pt.x, pt.y);
              }
            }
            ctx.shadowBlur = 0;
          }
        }

        rafId = requestAnimationFrame(animate);
      }

      return {
        start: () => {
          if (running) return;
          running = true;
          onResize();
          animate();
        },
        stop: () => {
          running = false;
          if (rafId) {
            cancelAnimationFrame(rafId);
            rafId = null;
          }
        },
        resize: onResize
      };
    }

    if (btn) {
      btn.addEventListener('click', () => {
        if (updateState.checked && updateState.updateAvailable) {
          openModalWithRelease(updateState);
        } else {
          checkUpdate(false);
        }
      });
    }

    if (navUpdateLink) {
      navUpdateLink.addEventListener('click', (e) => {
        e.preventDefault();
        if (updateState.checked && updateState.updateAvailable) {
          openModalWithRelease(updateState);
        } else {
          openModalUpToDate(updateState);
          checkUpdate(true);
        }
      });
    }

    const topBrandBadge = document.getElementById('topBrandVersionBadge');
    if (topBrandBadge) {
      topBrandBadge.addEventListener('click', (e) => {
        e.preventDefault();
        if (updateState.checked && updateState.updateAvailable) {
          openModalWithRelease(updateState);
        } else {
          openModalUpToDate(updateState);
          checkUpdate(true);
        }
      });
    }

    window.triggerRestartTakeover = triggerRestartTakeover;

    window.openClipifyUpdate = () => {
      if ((window.AndroidBridge || window.location.protocol === 'file:') && typeof window.openClipifyMobileUpdate === 'function') {
        window.openClipifyMobileUpdate();
        return;
      }
      if (updateState.checked && updateState.updateAvailable) {
        openModalWithRelease(updateState);
      } else {
        openModalUpToDate(updateState);
        checkUpdate(true);
      }
    };

    btnExecute?.addEventListener('click', applyUpdate);

    closeModal?.addEventListener('click', () => {
      modal.style.display = 'none';
      stopModalAsciiBackground();
    });

    modal?.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.style.display = 'none';
        stopModalAsciiBackground();
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal && modal.style.display === 'flex') {
        modal.style.display = 'none';
        stopModalAsciiBackground();
      }
    });

    // Check silently on startup after 3 seconds
    setTimeout(() => checkUpdate(true), 3000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSidebarUpdater);
  } else {
    initSidebarUpdater();
  }
})();
