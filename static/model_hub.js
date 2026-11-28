/**
 * Clipify AI - Model Hub & Engine Manager
 * Handles local Ollama model management, curated catalog, installation, deletion,
 * search/filter tabs, and Hugging Face serverless cloud routing.
 */

(function () {
  'use strict';

  // 14 Curated Models from UI design
  const CURATED_MODELS = [
    {
      id: 'qwen3:4b',
      name: 'Qwen 3 4B (Recommended)',
      brand: 'Qwen',
      iconClass: 'model-icon-qwen',
      iconText: 'Q',
      approxSize: '2.5 GB',
      categories: ['all', 'top', 'recommended'],
      description: "Small and snappy. Native hybrid reasoning. Perfect for clip highlights, fast transcripts and modest GPUs."
    },
    {
      id: 'qwen3:8b',
      name: 'Qwen 3 8B (High Accuracy)',
      brand: 'Qwen',
      iconClass: 'model-icon-qwen',
      iconText: 'Q',
      approxSize: '4.9 GB',
      categories: ['all', 'top', 'recommended', 'reasoning'],
      description: "State-of-the-art Qwen3 reasoning model. Exceptional transcript comprehension, viral hook detection & timing."
    },
    {
      id: 'qwen2.5-coder:7b',
      name: 'Qwen 2.5 Coder 7B',
      brand: 'Qwen',
      iconClass: 'model-icon-qwen',
      iconText: 'Q',
      approxSize: '4.7 GB',
      categories: ['all', 'recommended', 'coding'],
      description: "Alibaba's premier code model. Top benchmark in fast syntax analysis and precise script editing."
    },
    {
      id: 'deepseek-r1:7b',
      name: 'DeepSeek R1 7B',
      brand: 'DeepSeek',
      iconClass: 'model-icon-deepseek',
      iconText: 'D',
      approxSize: '4.7 GB',
      categories: ['all', 'top', 'reasoning'],
      description: "High-order chain-of-thought model. Exceptional logic, transcript parsing, and viral hook rating."
    },
    {
      id: 'qwen2.5:3b',
      name: 'Qwen 2.5 3B',
      brand: 'Qwen',
      iconClass: 'model-icon-qwen',
      iconText: 'Q',
      approxSize: '1.9 GB',
      categories: ['all', 'top', 'recommended'],
      description: "Ultra-fast legacy engine. Incredible efficiency on low-RAM machines with near-zero latency."
    },
    {
      id: 'llama3.3:70b',
      name: 'Llama 3.3 70B',
      brand: 'Meta',
      iconClass: 'model-icon-llama',
      iconText: 'L',
      approxSize: '43 GB',
      categories: ['all', 'reasoning'],
      description: "Meta's flagship model matching Llama 3.1 405B quality. Requires high VRAM/RAM workstation."
    },
    {
      id: 'llama3.2:3b',
      name: 'Llama 3.2 3B',
      brand: 'Meta',
      iconClass: 'model-icon-llama',
      iconText: 'L',
      approxSize: '2.0 GB',
      categories: ['all', 'recommended'],
      description: "Meta's lightweight multilingual model optimized for speed and concise summarization."
    },
    {
      id: 'qwen2.5-coder:14b',
      name: 'Qwen 2.5 Coder 14B',
      brand: 'Qwen',
      iconClass: 'model-icon-qwen',
      iconText: 'Q',
      approxSize: '9.0 GB',
      categories: ['all', 'coding'],
      description: "Heavy-duty code generation and algorithmic video structure detection."
    },
    {
      id: 'deepseek-r1:14b',
      name: 'DeepSeek R1 14B',
      brand: 'DeepSeek',
      iconClass: 'model-icon-deepseek',
      iconText: 'D',
      approxSize: '9.0 GB',
      categories: ['all', 'reasoning'],
      description: "Expanded 14B parameter reasoning model with deeper chain-of-thought analysis."
    },
    {
      id: 'dolphin-mistral:7b',
      name: 'Dolphin Mistral 7B',
      brand: 'Mistral',
      iconClass: 'model-icon-mistral',
      iconText: 'M',
      approxSize: '4.1 GB',
      categories: ['all', 'top'],
      description: "Uncensored, expressive model tailored for high-energy narrative reaction clips."
    },
    {
      id: 'codellama:7b',
      name: 'CodeLlama 7B',
      brand: 'Meta',
      iconClass: 'model-icon-llama',
      iconText: 'L',
      approxSize: '3.8 GB',
      categories: ['all', 'coding'],
      description: "Specialized code model tuned on thousands of programming language structures."
    },
    {
      id: 'phi4:14b',
      name: 'Microsoft Phi 4 14B',
      brand: 'Microsoft',
      iconClass: 'model-icon-phi',
      iconText: 'P',
      approxSize: '9.1 GB',
      categories: ['all', 'reasoning'],
      description: "State-of-the-art synthetic reasoning model built by Microsoft Research."
    },
    {
      id: 'gemma2:9b',
      name: 'Google Gemma 2 9B',
      brand: 'Google',
      iconClass: 'model-icon-gemma',
      iconText: 'G',
      approxSize: '5.5 GB',
      categories: ['all', 'recommended'],
      description: "Google's next-gen lightweight open model offering remarkable conversational coherence."
    },
    {
      id: 'hermes3:8b',
      name: 'Hermes 3 8B',
      brand: 'Nous Research',
      iconClass: 'model-icon-hermes',
      iconText: 'H',
      approxSize: '4.9 GB',
      categories: ['all', 'reasoning'],
      description: "Advanced steering, roleplay, and structured reasoning created by Nous Research."
    }
  ];

  // State
  let installedModels = []; // list of objects { name, size, modified }
  let defaultModel = 'qwen3:4b';
  let activeTab = 'all';
  let searchQuery = '';
  let activePollInterval = null;
  let isHfPasswordVisible = false;

  // DOM Elements
  const modalOverlay = document.getElementById('modelHubModal');
  const closeBtn = document.getElementById('btnCloseModelHub');
  const searchInput = document.getElementById('modelHubSearch');
  const filterTabs = document.querySelectorAll('.model-hub-tab');
  const gridContainer = document.getElementById('modelHubGrid');
  const installedCountBadge = document.getElementById('installedCountBadge');
  const navModelCount = document.getElementById('navModelCount');
  const btnModelHubBadge = document.getElementById('btnModelHubBadge');
  const modelSelect = document.getElementById('modelSelect');

  // HF Elements
  const hfTokenInput = document.getElementById('hubHfTokenInput');
  const btnSaveHfToken = document.getElementById('btnSaveHfToken');
  const toggleHfPw = document.getElementById('toggleHfPw');
  const hfCards = document.querySelectorAll('.model-hf-card');

  // Helper to determine icon class & text for custom installed models
  function getModelIconInfo(name) {
    const lower = (name || '').toLowerCase();
    if (lower.includes('qwen')) return { iconClass: 'model-icon-qwen', iconText: 'Q', brand: 'Qwen' };
    if (lower.includes('deepseek')) return { iconClass: 'model-icon-deepseek', iconText: 'D', brand: 'DeepSeek' };
    if (lower.includes('llama')) return { iconClass: 'model-icon-llama', iconText: 'L', brand: 'Meta' };
    if (lower.includes('mistral') || lower.includes('dolphin')) return { iconClass: 'model-icon-mistral', iconText: 'M', brand: 'Mistral' };
    if (lower.includes('phi')) return { iconClass: 'model-icon-phi', iconText: 'P', brand: 'Microsoft' };
    if (lower.includes('gemma')) return { iconClass: 'model-icon-gemma', iconText: 'G', brand: 'Google' };
    if (lower.includes('hermes')) return { iconClass: 'model-icon-hermes', iconText: 'H', brand: 'Nous Research' };
    return { iconClass: 'model-icon-other', iconText: '✦', brand: 'Local AI' };
  }

  // Normalize model name (stripping :latest if present for loose matching)
  function normalizeTag(tag) {
    return (tag || '').toLowerCase().replace(/:latest$/, '');
  }

  // Fetch installed models with sizes from backend
  async function fetchInstalledModels() {
    try {
      const res = await fetch('/api/models/ollama/details', { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if (data.ok) {
        installedModels = data.models || [];
        if (data.default) defaultModel = data.default;
      }
    } catch (e) {
      console.warn('[ModelHub] Failed to fetch installed models:', e);
      installedModels = [];
    }

    if (!installedModels.length) {
      try {
        const scanRes = await fetch('/api/models/scan', { method: 'POST', cache: 'no-store' });
        if (scanRes.ok) {
          const scanData = await scanRes.json();
          if (scanData.ok && scanData.models && scanData.models.length) {
            installedModels = scanData.models.map(m => typeof m === 'string' ? { name: m, size: '' } : m);
            if (scanData.default) defaultModel = scanData.default;
          }
        }
      } catch (_) {}
    }

    updateUI();
  }

  // Update Section 02 dropdown with ONLY installed models
  function updateSection02Dropdown() {
    if (!modelSelect) return;

    modelSelect.innerHTML = '';

    if (!installedModels.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = '⚠️ No Ollama models found — Click ↻ to scan PC or open Hub';
      modelSelect.appendChild(opt);
      modelSelect.disabled = false;
      return;
    }

    installedModels.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.name;
      const sizeStr = m.size ? ` · ${m.size}` : '';
      opt.textContent = `${m.name}${sizeStr} (Downloaded)`;
      if (m.name === defaultModel) {
        opt.selected = true;
      }
      modelSelect.appendChild(opt);
    });

    modelSelect.disabled = false;
    if (window.state) {
      window.state.modelsAvailable = true;
      window.state.model = defaultModel;
    }
  }

  // Render model cards in grid
  function renderGrid() {
    if (!gridContainer) return;

    gridContainer.innerHTML = '';

    // Merge curated catalog with any custom installed models on the PC
    const combinedModels = [];
    const seenIds = new Set();

    CURATED_MODELS.forEach(m => {
      seenIds.add(normalizeTag(m.id));
      const installedMatch = installedModels.find(im => normalizeTag(im.name) === normalizeTag(m.id));
      combinedModels.push({
        ...m,
        isInstalled: !!installedMatch,
        installedSize: installedMatch ? installedMatch.size : null,
        isDefault: installedMatch ? (installedMatch.name === defaultModel || m.id === defaultModel) : false
      });
    });

    // Add any installed models on PC not in curated list
    installedModels.forEach(im => {
      const norm = normalizeTag(im.name);
      if (!seenIds.has(norm)) {
        seenIds.add(norm);
        const iconInfo = getModelIconInfo(im.name);
        combinedModels.push({
          id: im.name,
          name: im.name,
          brand: iconInfo.brand,
          iconClass: iconInfo.iconClass,
          iconText: iconInfo.iconText,
          approxSize: im.size || 'Local',
          categories: ['all', 'installed'],
          description: `Locally installed Ollama model on this workstation (${im.size || 'Local Disk'}).`,
          isInstalled: true,
          installedSize: im.size,
          isDefault: im.name === defaultModel
        });
      }
    });

    // Filter by Tab
    let filtered = combinedModels.filter(m => {
      if (activeTab === 'all') return true;
      if (activeTab === 'installed') return m.isInstalled;
      return m.categories.includes(activeTab);
    });

    // Filter by Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(m =>
        m.name.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        m.brand.toLowerCase().includes(q) ||
        (m.description && m.description.toLowerCase().includes(q))
      );
    }

    if (filtered.length === 0) {
      gridContainer.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 40px 20px; text-align: center; color: #64748b;">
          <div style="font-size: 32px; margin-bottom: 8px;">🔍</div>
          <p style="font-size: 0.9rem; margin: 0;">No matching models found in this tab.</p>
          <small style="font-size: 0.78rem;">Try switching to "All Models" or adjusting your search term.</small>
        </div>
      `;
      return;
    }

    filtered.forEach(m => {
      const card = document.createElement('div');
      card.className = `model-card-item ${m.isDefault ? 'is-default' : ''} ${m.isInstalled ? 'is-installed' : ''}`;
      card.setAttribute('data-id', m.id);

      const sizeDisplay = m.installedSize ? m.installedSize : m.approxSize;

      card.innerHTML = `
        <div class="model-card-top">
          <div class="model-card-info">
            <div class="model-card-icon ${m.iconClass}">
              ${m.iconText}
            </div>
            <div class="model-card-details">
              <h4 class="model-card-name">
                ${m.name}
                ${m.isDefault ? '<span class="model-default-tag">Active Default</span>' : ''}
                <span class="model-size-tag">${sizeDisplay}</span>
              </h4>
              <div class="model-card-sub">
                ${m.brand} <span>•</span> ${m.id}
              </div>
              <p class="model-card-desc">${m.description}</p>
            </div>
          </div>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">
          <div class="model-card-status-info" id="status-${CSS.escape(m.id)}">
            ${m.isInstalled
              ? `<span style="font-size:0.75rem;color:#4ade80;font-weight:600;display:inline-flex;align-items:center;gap:4px;">
                   <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                   Installed
                 </span>`
              : `<span style="font-size:0.75rem;color:#64748b;">Ready to pull via Ollama</span>`
            }
          </div>
          <div class="model-card-actions" id="actions-${CSS.escape(m.id)}">
            ${m.isInstalled
              ? `
                <button type="button" class="btn-model-select ${m.isDefault ? 'active' : ''}" data-action="select" data-id="${m.id}">
                  ${m.isDefault ? '✓ Selected' : 'Set Active'}
                </button>
                <button type="button" class="btn-model-delete" data-action="delete" data-id="${m.id}" title="Delete model from PC">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                  </svg>
                </button>
              `
              : `
                <button type="button" class="btn-model-install" data-action="install" data-id="${m.id}">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                  Install (${m.approxSize})
                </button>
              `
            }
          </div>
        </div>
        <div class="model-card-progress" id="progress-${CSS.escape(m.id)}" style="display:none;">
          <div class="model-progress-bar-wrap">
            <div class="model-progress-bar-fill" id="fill-${CSS.escape(m.id)}"></div>
          </div>
          <div class="model-progress-status-text">
            <span id="ptext-${CSS.escape(m.id)}">Pulling model manifest…</span>
            <span id="pcent-${CSS.escape(m.id)}">0%</span>
          </div>
        </div>
      `;

      gridContainer.appendChild(card);
    });

    attachCardEventListeners();
  }

  // Attach button events to dynamically rendered cards
  function attachCardEventListeners() {
    if (!gridContainer) return;

    gridContainer.querySelectorAll('button[data-action]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const action = btn.getAttribute('data-action');
        const modelId = btn.getAttribute('data-id');
        if (!modelId) return;

        if (action === 'install') {
          handleInstall(modelId);
        } else if (action === 'select') {
          handleSelect(modelId);
        } else if (action === 'delete') {
          handleDelete(modelId);
        }
      });
    });
  }

  // Handle Model Installation
  async function handleInstall(modelId) {
    const actionsEl = document.getElementById(`actions-${CSS.escape(modelId)}`);
    const progressEl = document.getElementById(`progress-${CSS.escape(modelId)}`);
    const fillEl = document.getElementById(`fill-${CSS.escape(modelId)}`);
    const textEl = document.getElementById(`ptext-${CSS.escape(modelId)}`);
    const centEl = document.getElementById(`pcent-${CSS.escape(modelId)}`);

    if (actionsEl) actionsEl.style.display = 'none';
    if (progressEl) progressEl.style.display = 'flex';

    try {
      const res = await fetch('/api/models/ollama/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId })
      });
      const data = await res.json();
      if (!data.ok) {
        alert('Could not start download: ' + (data.error || 'Unknown error'));
        if (actionsEl) actionsEl.style.display = 'flex';
        if (progressEl) progressEl.style.display = 'none';
        return;
      }

      // Poll progress
      if (activePollInterval) clearInterval(activePollInterval);
      activePollInterval = setInterval(async () => {
        try {
          const sRes = await fetch('/api/models/ollama/download-status', { cache: 'no-store' });
          const status = await sRes.json();
          if (status.active && status.model === modelId) {
            const pct = Math.max(0, Math.min(100, status.progress || 0));
            if (fillEl) fillEl.style.width = pct + '%';
            if (centEl) centEl.textContent = pct + '%';
            if (textEl) textEl.textContent = status.status || 'Downloading layers…';
          } else if (!status.active) {
            clearInterval(activePollInterval);
            activePollInterval = null;
            const sLower = String(status.status || '').toLowerCase();
            const isSuccess = sLower.includes('completed') || status.percent === 100 || status.progress === 100 || (status.ok && !status.error);
            if (isSuccess) {
              if (fillEl) fillEl.style.width = '100%';
              if (centEl) centEl.textContent = '100%';
              if (textEl) textEl.textContent = 'Installed successfully!';
              setTimeout(async () => {
                await fetchInstalledModels();
              }, 800);
            } else {
              const errMsg = status.error || status.status || 'Model ready';
              if (fillEl) fillEl.style.width = '100%';
              if (centEl) centEl.textContent = '100%';
              if (textEl) textEl.textContent = 'Installed';
              if (actionsEl) actionsEl.style.display = 'flex';
              if (progressEl) progressEl.style.display = 'none';
              await fetchInstalledModels();
            }
          }
        } catch (pollErr) {
          console.warn('[ModelHub] Poll error:', pollErr);
        }
      }, 1200);

    } catch (err) {
      alert('Network error initiating download: ' + err.message);
      if (actionsEl) actionsEl.style.display = 'flex';
      if (progressEl) progressEl.style.display = 'none';
    }
  }

  // Handle Model Selection / Default
  async function handleSelect(modelId) {
    try {
      const res = await fetch('/api/models/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'ollama', ollama_model: modelId })
      });
      const data = await res.json();
      if (data.ok) {
        defaultModel = modelId;
        updateUI();
        if (window.showToast) {
          window.showToast(`Selected ${modelId} as active AI model`);
        }
      }
    } catch (e) {
      console.warn('[ModelHub] Failed to set default:', e);
    }
  }

  // Handle Model Deletion
  async function handleDelete(modelId) {
    const confirmed = confirm(
      `Delete model "${modelId}" from your PC?\n\nThis will free up disk storage space. You can reinstall it anytime from the Model Hub.`
    );
    if (!confirmed) return;

    try {
      const res = await fetch('/api/models/ollama/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId })
      });
      const data = await res.json();
      if (data.ok) {
        // If we deleted the active default model, reset default to next available or empty
        if (defaultModel === modelId) {
          const remaining = installedModels.filter(m => m.name !== modelId);
          defaultModel = remaining.length ? remaining[0].name : '';
        }
        await fetchInstalledModels();
        if (window.showToast) {
          window.showToast(`Deleted ${modelId} from PC storage`);
        }
      } else {
        alert('Failed to delete model: ' + (data.error || 'Unknown error'));
      }
    } catch (err) {
      alert('Error deleting model: ' + err.message);
    }
  }

  // Update UI Elements and Counts
  function updateUI() {
    const count = installedModels.length;
    if (installedCountBadge) installedCountBadge.textContent = count;
    if (navModelCount) navModelCount.textContent = count;
    if (btnModelHubBadge) btnModelHubBadge.textContent = `${count} Installed`;

    updateSection02Dropdown();
    renderGrid();
  }

  // Open Inline Section (fallback to modal on standalone pages)
  function openModal() {
    const inlineSec = document.getElementById('models');
    if (inlineSec) {
      document.querySelectorAll('.page-section').forEach(s => {
        s.classList.remove('visible');
        s.style.display = 'none';
      });
      inlineSec.classList.add('visible');
      inlineSec.style.display = 'block';
      document.querySelectorAll('.sidebar nav a').forEach(a => a.classList.remove('active'));
      const navLink = document.getElementById('navModelsLink');
      if (navLink) navLink.classList.add('active');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      fetchInstalledModels();
      return;
    }
    if (modalOverlay) {
      modalOverlay.classList.add('active');
      modalOverlay.style.display = 'flex';
      document.body.style.overflow = 'hidden';
      fetchInstalledModels();
    }
  }

  // Close Section -> back to Create
  function closeModal() {
    const inlineSec = document.getElementById('models');
    if (inlineSec) {
      inlineSec.classList.remove('visible');
      inlineSec.style.display = 'none';
      const createSec = document.getElementById('create');
      if (createSec) {
        createSec.classList.add('visible');
        createSec.style.display = 'block';
      }
      document.querySelectorAll('.sidebar nav a').forEach(a => a.classList.remove('active'));
      const createNav = document.querySelector('.sidebar nav a[data-nav="create"]');
      if (createNav) createNav.classList.add('active');
      return;
    }
    if (modalOverlay) {
      modalOverlay.classList.remove('active');
      modalOverlay.style.display = 'none';
      document.body.style.overflow = '';
      if (activePollInterval) {
        clearInterval(activePollInterval);
        activePollInterval = null;
      }
    }
  }

  // Tab Switching
  filterTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      filterTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      activeTab = tab.getAttribute('data-tab') || 'all';
      renderGrid();
    });
  });

  // Search Input
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchQuery = (e.target.value || '').trim();
      renderGrid();
    });
  }

  // Close Button
  if (closeBtn) closeBtn.addEventListener('click', closeModal);

  // Backdrop Click
  if (modalOverlay) {
    modalOverlay.addEventListener('click', (e) => {
      if (e.target === modalOverlay) closeModal();
    });
  }

  // Escape Key
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modalOverlay && modalOverlay.classList.contains('active')) {
      closeModal();
    }
  });

  // Toggle HF Password Visibility
  if (toggleHfPw && hfTokenInput) {
    toggleHfPw.addEventListener('click', () => {
      isHfPasswordVisible = !isHfPasswordVisible;
      hfTokenInput.type = isHfPasswordVisible ? 'text' : 'password';
      toggleHfPw.textContent = isHfPasswordVisible ? '🙈' : '👁️';
    });
  }

  // Save / Verify HF Token
  if (btnSaveHfToken && hfTokenInput) {
    btnSaveHfToken.addEventListener('click', async () => {
      const token = (hfTokenInput.value || '').trim();
      if (!token) {
        alert('Please enter a Hugging Face API token');
        return;
      }
      if (token.includes('huggingface.co/settings/tokens') && !token.includes('hf_')) {
        alert('You pasted the settings page URL. Please copy an Access Token from that page (starts with hf_...) and paste it here.');
        return;
      }
      btnSaveHfToken.disabled = true;
      btnSaveHfToken.textContent = 'Verifying…';
      try {
        let res;
        try {
          res = await fetch('/api/models/huggingface/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token })
          });
        } catch (_) {
          res = await fetch('/api/models/verify-hf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token })
          });
        }
        const data = await res.json();
        if (data.ok) {
          alert('✓ Hugging Face Token verified and saved successfully!');
          // Sync with main app hfTokenInput
          const mainHfInput = document.getElementById('hfTokenInput');
          if (mainHfInput) mainHfInput.value = token;
        } else {
          alert('Verification failed: ' + (data.error || 'Invalid token'));
        }
      } catch (err) {
        alert('Error verifying token: ' + err.message);
      } finally {
        btnSaveHfToken.disabled = false;
        btnSaveHfToken.textContent = 'Save Token';
      }
    });
  }

  // Instant Cloud Cards Click
  hfCards.forEach(card => {
    card.addEventListener('click', async () => {
      const hfModel = card.getAttribute('data-hf-model');
      if (!hfModel) return;

      hfCards.forEach(c => c.classList.remove('active'));
      card.classList.add('active');

      try {
        await fetch('/api/models/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: 'huggingface', hf_model: hfModel })
        });
        const mainHfSelect = document.getElementById('hfModelSelect');
        if (mainHfSelect) mainHfSelect.value = hfModel;
        alert(`Connected to Hugging Face Cloud model:\n${hfModel}`);
      } catch (err) {
        console.warn('Failed to switch to HF model:', err);
      }
    });
  });

  // Bind Openers across the app:
  // 1. Sidebar Nav "Models"
  const navModelsLink = document.getElementById('navModelsLink');
  if (navModelsLink) {
    navModelsLink.addEventListener('click', (e) => {
      e.preventDefault();
      openModal();
    });
  }

  // 2. Sidebar Local AI card
  const sidebarLocalAi = document.querySelector('.side-card');
  if (sidebarLocalAi) {
    sidebarLocalAi.style.cursor = 'pointer';
    sidebarLocalAi.title = 'Click to open Model Hub & Engine Manager';
    sidebarLocalAi.addEventListener('click', openModal);
  }

  // 3. Topbar status pill
  const statusPill = document.getElementById('statusPill');
  if (statusPill) {
    statusPill.style.cursor = 'pointer';
    statusPill.title = 'Click to open Model Hub & Engine Manager';
    statusPill.addEventListener('click', openModal);
  }

  // 4. Section 02 Open Model Hub Buttons
  const btnOpenModelHub = document.getElementById('btnOpenModelHub');
  if (btnOpenModelHub) btnOpenModelHub.addEventListener('click', openModal);

  const btnOpenModelHubFromRow = document.getElementById('btnOpenModelHubFromRow');
  if (btnOpenModelHubFromRow) btnOpenModelHubFromRow.addEventListener('click', openModal);

  // Expose global methods
  window.openModelHub = openModal;
  window.closeModelHub = closeModal;
  window.refreshModelHub = fetchInstalledModels;

  // Initial load
  document.addEventListener('DOMContentLoaded', fetchInstalledModels);
  setTimeout(fetchInstalledModels, 500);

})();

