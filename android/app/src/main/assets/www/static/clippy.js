/**
 * Clipify AI - Assistant Drawer & Chat (v5.0.0)
 * Persistent chat history via localStorage, direct Instagram group support,
 * v5.0.0 Instant Clipping & CUDA 12 GPU intelligence, modern obsidian pill UI, and smooth animations.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'clipify_clippy_chat_history_v5';

  // State
  const state = {
    open: false,
    history: [],
    modelName: 'Detecting...',
    modelSpeed: '',
    isThinking: false,
  };

  // Load persisted history from localStorage
  function loadPersistedHistory() {
    try {
      const keys = [STORAGE_KEY, 'clipify_clippy_chat_history_v3', 'clipify_clippy_history', 'clipify_clippy_chat_history'];
      for (const k of keys) {
        const raw = localStorage.getItem(k);
        if (raw) {
          let parsed = JSON.parse(raw);
          if (Array.isArray(parsed) && parsed.length > 0) {
            // Strip any legacy [NAVIGATE:...] commands so historical messages never trigger auto-redirects
            parsed = parsed.map(item => {
              if (item && item.content && typeof item.content === 'string') {
                return {
                  ...item,
                  content: item.content.replace(/\[NAVIGATE:[a-z0-9_-]+\]\s*/gi, '').trim()
                };
              }
              return item;
            });
            state.history = parsed;
            try { localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed)); } catch (_) {}
            return parsed;
          }
        }
      }
    } catch (_) {}
    return null;
  }

  // Save history to localStorage
  function savePersistedHistory() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.history));
    } catch (_) {}
  }

  function renderWelcomeCard(messagesContainer) {
    const welcomeDiv = document.createElement('div');
    welcomeDiv.id = 'clippyWelcomeCard';
    welcomeDiv.className = 'clippy-msg clippy-msg-ai clippy-welcome-msg';
    welcomeDiv.innerHTML = `
      <div class="clippy-msg-bubble clippy-welcome-bubble">
        <p class="clippy-welcome-title"><strong>Hey! I'm your Clipify AI assistant.</strong></p>
        <p class="clippy-welcome-desc">Ask me anything about Clipify AI v6.0.0 — Instant 9:16 Clipping, Storage Manager, reusing existing subtitles, GPU switching, Live Studio, or Narration Studio.</p>
        <div class="clippy-chips">
          <button class="clippy-chip" data-prompt="What's new in the latest version?">✨ What's New</button>
          <button class="clippy-chip" data-prompt="How do I change storage folders?">💾 Storage Manager</button>
          <button class="clippy-chip" data-prompt="How does Instant Clipping work?">⚡ Instant 9:16 Shorts</button>
          <button class="clippy-chip" data-prompt="How do I clip a live stream?">🔴 Live Studio</button>
        </div>
      </div>
      <span class="clippy-msg-time">Just now</span>
    `;
    const typing = document.getElementById('clippyTyping');
    messagesContainer.insertBefore(welcomeDiv, typing);
  }

  function initClippy() {
    // Avoid double initialization
    if (document.getElementById('clippyContainer')) return;

    // Inject DOM structure
    const container = document.createElement('div');
    container.id = 'clippyContainer';
    container.className = 'clippy-container';
    container.innerHTML = `
      <!-- Backdrop Dimmer for Smooth Click-Outside Dismiss -->
      <div id="clippyBackdrop" class="clippy-backdrop"></div>

      <!-- Minimalist Flush Edge Arrow Toggle Button -->
      <button id="clippyToggleBtn" class="clippy-toggle-btn" title="Open Clipify AI Assistant" aria-label="Open Clipify AI assistant" type="button">
        <span class="clippy-toggle-dot"></span>
        <svg class="clippy-toggle-arrow-svg" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
      </button>

      <!-- Vertical Sideways "NEED HELP?" / "SUPPORT" / "FOUND A BUG?" Tab Under Chat Arrow -->
      <button id="clippyHelpSideBtn" class="clippy-help-side-btn" title="Need Help? Join Clipify Clipping on Discord" aria-label="Need Help and Discord Support" type="button">
        <span class="clippy-help-side-text" id="clippyHelpSideText">NEED HELP?</span>
      </button>

      <!-- Help & Discord Sidebar Backdrop + Animated Drawer -->
      <div id="clippyHelpBackdrop" class="clippy-help-backdrop"></div>
      <aside id="clippyHelpDrawer" class="clippy-help-drawer" role="dialog" aria-modal="true" aria-label="Clipify Clipping Discord Support" aria-hidden="true">
        <canvas id="clippyHelpBgCanvas" class="clippy-help-bg-canvas"></canvas>
        <button id="clippyHelpCloseBtn" class="clippy-help-close-btn" title="Close" aria-label="Close support sidebar" type="button">✕</button>
        <div class="clippy-help-content">
          <div class="clippy-help-logo-wrap">
            <img src="static/icon.png" alt="Clipify AI Logo" class="clippy-help-logo" onerror="this.src='static/clipify-ai-mark.png'">
          </div>
          <span class="clippy-help-kicker">OFFICIAL DISCORD SERVER</span>
          <h2 class="clippy-help-server-name">Clipify Clipping</h2>
          <p class="clippy-help-desc">Need help, found a bug, or want creator presets &amp; live support? Join our official Discord community.</p>
          <a href="https://discord.gg/5ZBsasgryX" target="_blank" rel="noopener noreferrer" class="clippy-help-join-btn">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
              <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
            </svg>
            <span>Join Discord</span>
          </a>
        </div>
      </aside>

      <!-- Slide-Out Sidebar Drawer -->
      <div id="clippyDrawer" class="clippy-drawer" role="dialog" aria-modal="true" aria-labelledby="clippyTitle" aria-hidden="true">
        <!-- Drawer Header -->
        <div class="clippy-header">
          <div class="clippy-header-left">
            <div class="clippy-avatar-box">
              <img src="static/icon.png" alt="Clipify AI" class="clippy-avatar-img" onerror="this.src='static/favicon.ico'">
            </div>
            <div class="clippy-title-info">
              <h3 id="clippyTitle" class="clippy-title">Clipify AI</h3>
              <div class="clippy-model-badge" id="clippyModelBadge" title="Local AI Engine">
                <span class="clippy-badge-dot"></span>
                <span id="clippyModelText">Loading Local AI...</span>
              </div>
            </div>
          </div>
          <div class="clippy-header-actions">
            <button id="clippyClearBtn" class="clippy-icon-btn" title="Clear chat history" aria-label="Clear chat history">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
            <button id="clippyCloseBtn" class="clippy-icon-btn clippy-close-btn" title="Close Assistant" aria-label="Close sidebar">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
        </div>

        <!-- Messages Scroll Area -->
        <div class="clippy-messages" id="clippyMessages">
          <!-- Typing / Thinking Indicator Row -->
          <div class="clippy-msg clippy-msg-ai clippy-typing-row" id="clippyTyping" style="display: none;">
            <div class="clippy-msg-bubble clippy-typing-bubble">
              <span class="clippy-typing-label">Clippy is thinking</span>
              <div class="clippy-typing-indicator">
                <span class="clippy-dot"></span>
                <span class="clippy-dot"></span>
                <span class="clippy-dot"></span>
              </div>
            </div>
          </div>
        </div>

        <!-- Chat Input Footer -->
        <div class="clippy-footer">
          <form id="clippyForm" class="clippy-input-bar" onsubmit="return false;">
            <textarea
              id="clippyInput"
              class="clippy-input"
              rows="1"
              placeholder="Ask anything about Clipify AI..."
              aria-label="Message input"
              autocomplete="off"
              autocorrect="off"
              autocapitalize="off"
              spellcheck="false"
              data-gramm="false"
              data-gramm_editor="false"
              data-enable-grammarly="false"
            ></textarea>
            <button type="submit" id="clippySendBtn" class="clippy-send-btn" title="Send message" aria-label="Send message">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </form>
          <div class="clippy-footer-note">Press Enter to send · Shift+Enter for new line</div>
        </div>
      </div>
    `;

    document.body.appendChild(container);

    // Bind DOM elements
    const toggleBtn = document.getElementById('clippyToggleBtn');
    const backdrop = document.getElementById('clippyBackdrop');
    const closeBtn = document.getElementById('clippyCloseBtn');
    const clearBtn = document.getElementById('clippyClearBtn');
    const drawer = document.getElementById('clippyDrawer');
    const input = document.getElementById('clippyInput');
    const form = document.getElementById('clippyForm');
    const messages = document.getElementById('clippyMessages');

    // Restore persistent history
    const saved = loadPersistedHistory();
    if (saved && saved.length > 0) {
      saved.forEach((item) => {
        if (item.role === 'user') {
          appendUserMessage(item.content, false);
        } else if (item.role === 'assistant') {
          appendAiMessage(item.content, item.model || '', false);
        }
      });
    } else {
      renderWelcomeCard(messages);
    }

    // Toggle Drawer with hardware acceleration & zero missed clicks
    function openDrawer() {
      state.open = true;
      drawer.classList.add('clippy-open');
      if (backdrop) backdrop.classList.add('clippy-backdrop-active');
      toggleBtn.classList.add('clippy-toggle-hidden');
      drawer.setAttribute('aria-hidden', 'false');
      setTimeout(() => input.focus(), 120);
    }

    function closeDrawer() {
      state.open = false;
      drawer.classList.remove('clippy-open');
      if (backdrop) backdrop.classList.remove('clippy-backdrop-active');
      toggleBtn.classList.remove('clippy-toggle-hidden');
      drawer.setAttribute('aria-hidden', 'true');
    }

    // Immediate 1-press trigger
    let lastToggleTime = 0;
    function handleToggle(e) {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      const now = Date.now();
      if (now - lastToggleTime < 180) return;
      lastToggleTime = now;
      if (state.open) {
        closeDrawer();
      } else {
        openDrawer();
      }
    }

    toggleBtn.addEventListener('pointerdown', handleToggle);
    toggleBtn.addEventListener('click', handleToggle);
    closeBtn.addEventListener('click', closeDrawer);
    if (backdrop) backdrop.addEventListener('click', closeDrawer);

    // Clear history handler
    clearBtn.addEventListener('click', () => {
      if (confirm('Clear assistant conversation history?')) {
        state.history = [];
        try {
          localStorage.removeItem(STORAGE_KEY);
        } catch (_) {}
        // Clear rendered messages except typing row
        const typing = document.getElementById('clippyTyping');
        messages.innerHTML = '';
        messages.appendChild(typing);
        renderWelcomeCard(messages);
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && state.open) {
        closeDrawer();
      }
    });

    // Auto-expand textarea
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 110) + 'px';
    });

    // Enter to submit (Shift+Enter for newline)
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      sendMessage();
    });

    const sendBtn = document.getElementById('clippySendBtn');
    if (sendBtn) {
      sendBtn.addEventListener('click', (e) => {
        e.preventDefault();
        sendMessage();
      });
    }

    // Chip click delegation
    messages.addEventListener('click', (e) => {
      const chip = e.target.closest('.clippy-chip');
      if (chip && chip.dataset.prompt) {
        input.value = chip.dataset.prompt;
        sendMessage();
      }
    });

    // ── Vertical "NEED HELP?" / "SUPPORT" / "FOUND A BUG?" Side Tab & Discord Drawer ──
    const helpBtn = document.getElementById('clippyHelpSideBtn');
    const helpTxt = document.getElementById('clippyHelpSideText');
    const helpDrawer = document.getElementById('clippyHelpDrawer');
    const helpBackdrop = document.getElementById('clippyHelpBackdrop');
    const helpClose = document.getElementById('clippyHelpCloseBtn');
    const helpCanvas = document.getElementById('clippyHelpBgCanvas');

    const HELP_LABELS = ['NEED HELP?', 'SUPPORT', 'FOUND A BUG?'];
    let helpLabelIdx = 0;
    if (helpTxt) {
      setInterval(() => {
        helpTxt.classList.add('is-swapping');
        setTimeout(() => {
          helpLabelIdx = (helpLabelIdx + 1) % HELP_LABELS.length;
          helpTxt.textContent = HELP_LABELS[helpLabelIdx];
          helpTxt.classList.remove('is-swapping');
        }, 200);
      }, 2600);
    }

    let helpAnimId = null;
    function startHelpBgAnimation() {
      if (!helpCanvas) return;
      const ctx = helpCanvas.getContext('2d');
      if (!ctx) return;
      const resize = () => {
        helpCanvas.width = helpDrawer.clientWidth || 360;
        helpCanvas.height = helpDrawer.clientHeight || window.innerHeight;
      };
      resize();
      const dots = Array.from({ length: 42 }, () => ({
        x: Math.random() * helpCanvas.width,
        y: Math.random() * helpCanvas.height,
        vx: (Math.random() - 0.5) * 0.55,
        vy: (Math.random() - 0.5) * 0.55,
        r: 1.1 + Math.random() * 1.6,
        a: 0.25 + Math.random() * 0.45
      }));
      let pulse = 0;
      const tick = () => {
        if (!helpDrawer.classList.contains('open')) return;
        if (helpCanvas.width !== helpDrawer.clientWidth || helpCanvas.height !== helpDrawer.clientHeight) resize();
        const w = helpCanvas.width;
        const h = helpCanvas.height;
        ctx.clearRect(0, 0, w, h);

        pulse += 0.015;
        for (let k = 0; k < 3; k++) {
          const rad = ((pulse * 40 + k * 55) % 165) + 28;
          const alpha = Math.max(0, (1 - rad / 195) * 0.14);
          ctx.beginPath();
          ctx.arc(w / 2, h * 0.34, rad, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(255,255,255,${alpha.toFixed(3)})`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        for (let i = 0; i < dots.length; i++) {
          const d = dots[i];
          d.x += d.vx;
          d.y += d.vy;
          if (d.x < 0 || d.x > w) d.vx *= -1;
          if (d.y < 0 || d.y > h) d.vy *= -1;
          ctx.fillStyle = `rgba(255,255,255,${d.a})`;
          ctx.beginPath();
          ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
          ctx.fill();
          for (let j = i + 1; j < dots.length; j++) {
            const o = dots[j];
            const dx = d.x - o.x;
            const dy = d.y - o.y;
            const distSq = dx * dx + dy * dy;
            if (distSq < 8100) {
              const lineA = (1 - Math.sqrt(distSq) / 90) * 0.16;
              ctx.strokeStyle = `rgba(255,255,255,${lineA.toFixed(3)})`;
              ctx.lineWidth = 0.8;
              ctx.beginPath();
              ctx.moveTo(d.x, d.y);
              ctx.lineTo(o.x, o.y);
              ctx.stroke();
            }
          }
        }
        helpAnimId = requestAnimationFrame(tick);
      };
      if (helpAnimId) cancelAnimationFrame(helpAnimId);
      helpAnimId = requestAnimationFrame(tick);
    }

    function openHelpDrawer() {
      if (!helpDrawer) return;
      if (state.open && typeof closeDrawer === 'function') closeDrawer();
      helpDrawer.classList.add('open');
      helpDrawer.setAttribute('aria-hidden', 'false');
      if (helpBackdrop) helpBackdrop.classList.add('open');
      if (helpBtn) helpBtn.classList.add('clippy-toggle-hidden');
      startHelpBgAnimation();
    }

    function closeHelpDrawer() {
      if (!helpDrawer) return;
      helpDrawer.classList.remove('open');
      helpDrawer.setAttribute('aria-hidden', 'true');
      if (helpBackdrop) helpBackdrop.classList.remove('open');
      if (helpBtn) helpBtn.classList.remove('clippy-toggle-hidden');
      if (helpAnimId) {
        cancelAnimationFrame(helpAnimId);
        helpAnimId = null;
      }
    }

    if (helpBtn) helpBtn.addEventListener('click', openHelpDrawer);
    if (helpClose) helpClose.addEventListener('click', closeHelpDrawer);
    if (helpBackdrop) helpBackdrop.addEventListener('click', closeHelpDrawer);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && helpDrawer && helpDrawer.classList.contains('open')) {
        closeHelpDrawer();
      }
    });

    // Fetch fastest model info
    fetchModelInfo();

    // Deep-link auto-open support: ?clippy=open or ?clippy=chat
    if (window.location.search.includes('clippy=open') || window.location.search.includes('clippy=chat')) {
      openDrawer();
    }
  }

  // Handle in-app automatic page navigation
  function navigateApp(section) {
    if (!section) return;
    const s = section.toLowerCase().trim();
    if (s === 'live') {
      if (!window.location.pathname.includes('/live')) {
        window.location.href = '/live?clippy=open';
      }
      return;
    }
    if (s === 'narrate') {
      if (!window.location.pathname.includes('/narrate')) {
        window.location.href = '/narrate?clippy=open';
      }
      return;
    }
    // Target is a section on index.html (create, beta, editor, projects)
    if (window.location.pathname.includes('/live') || window.location.pathname.includes('/narrate')) {
      window.location.href = '/#' + s + '?clippy=open';
    } else if (typeof window.navigateTo === 'function') {
      window.navigateTo(s);
    } else {
      window.location.hash = '#' + s;
    }
  }

  function handleActionNavigation(text, shouldNavigate = false) {
    if (!text) return text;
    const match = text.match(/\[NAVIGATE:([a-z0-9_-]+)\]/i);
    if (match) {
      const target = match[1].toLowerCase();
      if (shouldNavigate) {
        setTimeout(() => navigateApp(target), 250);
      }
      return text.replace(/\[NAVIGATE:[a-z0-9_-]+\]\s*/gi, '').trim();
    }
    return text;
  }

  // Fetch model info from backend
  async function fetchModelInfo() {
    try {
      const res = await fetch('/api/clippy/model');
      if (res.ok) {
        const data = await res.json();
        const badge = document.getElementById('clippyModelText');
        if (badge) {
          if (data.model) {
            state.modelName = data.model;
            state.modelSpeed = data.speed || 'Fastest AI';
            badge.textContent = `⚡ ${data.model} (${state.modelSpeed})`;
          } else {
            badge.textContent = '⚡ Clipify AI Local';
          }
        }
      }
    } catch (_) {
      const badge = document.getElementById('clippyModelText');
      if (badge) badge.textContent = '⚡ Clipify AI Local';
    }
  }

  // Format simple markdown into HTML with rich link parsing
  function formatMarkdown(text) {
    if (!text) return '';
    let html = text
      // Escape raw HTML tags
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Code blocks ```code```
    html = html.replace(/```([a-z]*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code `code`
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Headers ### Title
    html = html.replace(/^### (.*$)/gim, '<h4 class="clippy-md-h4">$1</h4>');
    html = html.replace(/^## (.*$)/gim, '<h3 class="clippy-md-h3">$1</h3>');
    // Bold **text**
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Markdown links [text](url)
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="clippy-link"><span class="clippy-link-text">$1</span> <span class="clippy-link-icon">↗</span></a>');

    // Bare URLs that weren't wrapped in <a> yet
    html = html.replace(/(^|[^"'])(https?:\/\/[a-zA-Z0-9_\-\.\/]+(\?[a-zA-Z0-9_\-=&]*)?)/g, function(match, prefix, url) {
      if (match.includes('href=')) return match;
      return `${prefix}<a href="${url}" target="_blank" rel="noopener noreferrer" class="clippy-link">${url} <span class="clippy-link-icon">↗</span></a>`;
    });

    // Bullet lists
    html = html.replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/gis, '<ul>$1</ul>');
    // Paragraph breaks
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br/>');

    return `<p>${html}</p>`;
  }

  function appendUserMessage(text, shouldSave = true) {
    const messages = document.getElementById('clippyMessages');
    const msgDiv = document.createElement('div');
    msgDiv.className = 'clippy-msg clippy-msg-user';
    msgDiv.innerHTML = `
      <div class="clippy-msg-bubble">
        <p>${text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br/>')}</p>
      </div>
      <span class="clippy-msg-time">You</span>
    `;
    const typing = document.getElementById('clippyTyping');
    messages.insertBefore(msgDiv, typing);
    messages.scrollTop = messages.scrollHeight;

    if (shouldSave) {
      state.history.push({ role: 'user', content: text });
      savePersistedHistory();
    }
  }

  function appendAiMessage(rawText, model, shouldSave = true) {
    const messages = document.getElementById('clippyMessages');
    const msgDiv = document.createElement('div');
    msgDiv.className = 'clippy-msg clippy-msg-ai';

    // Only execute automatic page navigation if this is a live response (shouldSave === true), NEVER when restoring history!
    const cleanText = handleActionNavigation(rawText, shouldSave === true);
    const formatted = formatMarkdown(cleanText);

    msgDiv.innerHTML = `
      <div class="clippy-msg-bubble">
        ${formatted}
      </div>
      <span class="clippy-msg-time">${model ? `⚡ ${model} · ` : ''}Clipify AI</span>
    `;
    const typing = document.getElementById('clippyTyping');
    messages.insertBefore(msgDiv, typing);
    messages.scrollTop = messages.scrollHeight;

    if (shouldSave) {
      // Store clean text in history so future reloads never contain navigation triggers
      state.history.push({ role: 'assistant', content: cleanText, model: model || '' });
      savePersistedHistory();
    }
  }

  async function sendMessage() {
    const input = document.getElementById('clippyInput');
    const text = (input.value || '').trim();
    if (!text || state.isThinking) return;

    // Remove welcome card if this is the first interaction
    const welcome = document.getElementById('clippyWelcomeCard');
    if (welcome) welcome.remove();

    // Clear input
    input.value = '';
    input.style.height = 'auto';

    // Append user message
    appendUserMessage(text, true);

    // Show smooth thinking animation
    state.isThinking = true;
    const typing = document.getElementById('clippyTyping');
    if (typing) typing.style.display = 'flex';
    const messages = document.getElementById('clippyMessages');
    messages.scrollTop = messages.scrollHeight;

    try {
      const res = await fetch('/api/clippy/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          history: state.history.slice(-10),
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      const reply = data.reply || 'I am sorry, I could not generate a response right now.';
      appendAiMessage(reply, data.model, true);
    } catch (err) {
      appendAiMessage(
        `### ⚠️ Notice\nCould not connect to AI service: ${err.message}.\n\nMake sure Clipify AI is running properly and try again!`,
        'Error',
        true
      );
    } finally {
      state.isThinking = false;
      if (typing) typing.style.display = 'none';
      messages.scrollTop = messages.scrollHeight;
    }
  }

  // Initialize once DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initClippy);
  } else {
    initClippy();
  }
})();
