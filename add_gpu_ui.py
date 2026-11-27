import os

# 1. Append CSS to style.css
css_path = r'L:\ClipifyAI\static\style.css'
with open(css_path, 'r', encoding='utf-8') as f:
    css_content = f.read()

gpu_css = """
/* ==========================================================================
   Hardware Accelerator & GPU Switcher Dropdown (Dark Aesthetic)
   ========================================================================== */
.gpu-dropdown-wrapper {
  position: relative;
  display: inline-flex;
  align-items: center;
  z-index: 100;
}

.gpu-dropdown-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 0 14px;
  background: rgba(18, 18, 22, 0.85);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 10px;
  color: #f1f5f9;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
  outline: none;
}

.gpu-dropdown-btn:hover {
  background: rgba(28, 28, 35, 0.95);
  border-color: rgba(255, 255, 255, 0.35);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5), 0 0 14px rgba(34, 197, 94, 0.2);
  transform: translateY(-1px);
}

.gpu-indicator-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 8px #22c55e;
  flex-shrink: 0;
  transition: background 0.2s ease, box-shadow 0.2s ease;
}

.gpu-indicator-dot.nvidia {
  background: #22c55e;
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.9);
}

.gpu-indicator-dot.intel {
  background: #38bdf8;
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.9);
}

.gpu-indicator-dot.cpu {
  background: #fbbf24;
  box-shadow: 0 0 8px rgba(251, 191, 36, 0.9);
}

.gpu-current-label {
  max-width: 175px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: -0.01em;
}

.gpu-chevron {
  opacity: 0.6;
  transition: transform 0.2s ease;
  flex-shrink: 0;
}

.gpu-dropdown-wrapper.open .gpu-chevron {
  transform: rotate(180deg);
}

.gpu-dropdown-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 290px;
  background: #0d0d12;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 14px;
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.85), 0 0 0 1px rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  padding: 8px;
  display: none;
  flex-direction: column;
  gap: 4px;
  z-index: 9999;
  animation: gpuDropdownFade 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes gpuDropdownFade {
  from { opacity: 0; transform: translateY(-6px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.gpu-dropdown-wrapper.open .gpu-dropdown-menu {
  display: flex;
}

.gpu-menu-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 4px;
}

.gpu-menu-header span:first-child {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #94a3b8;
}

.gpu-menu-subtitle {
  font-size: 0.65rem;
  font-weight: 600;
  padding: 1px 6px;
  background: rgba(34, 197, 94, 0.12);
  border: 1px solid rgba(34, 197, 94, 0.25);
  color: #4ade80;
  border-radius: 6px;
}

.gpu-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
  width: 100%;
}

.gpu-menu-item:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.12);
}

.gpu-menu-item.active {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.22);
}

.gpu-item-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.gpu-item-name {
  font-size: 0.8rem;
  font-weight: 600;
  color: #f8fafc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gpu-item-meta {
  font-size: 0.68rem;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 6px;
}

.gpu-meta-vram {
  color: #94a3b8;
  font-weight: 500;
}

.gpu-item-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 0.65rem;
  font-weight: 700;
  flex-shrink: 0;
}

.gpu-item-badge.active {
  background: #22c55e;
  color: #052e16;
}

.gpu-item-badge.rec {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
  border: 1px solid rgba(34, 197, 94, 0.3);
}
"""

if '.gpu-dropdown-wrapper' not in css_content:
    with open(css_path, 'a', encoding='utf-8') as f:
        f.write(gpu_css)
    print("Appended GPU CSS to style.css!")
else:
    print("GPU CSS already in style.css")

# 2. Add GPU Controller to app.js
app_js_path = r'L:\ClipifyAI\static\app.js'
with open(app_js_path, 'r', encoding='utf-8') as f:
    js_content = f.read()

gpu_js = """
// ==========================================================================
// Hardware Accelerator & GPU Switcher Controller
// ==========================================================================
async function initGpuSelector() {
  const wrapper = document.getElementById('gpuDropdownWrapper');
  const btn = document.getElementById('gpuDropdownBtn');
  const label = document.getElementById('gpuCurrentLabel');
  const list = document.getElementById('gpuMenuList');
  const dot = wrapper ? wrapper.querySelector('.gpu-indicator-dot') : null;

  if (!wrapper || !btn || !list) return;

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    wrapper.classList.toggle('open');
  });

  document.addEventListener('click', (e) => {
    if (!wrapper.contains(e.target)) {
      wrapper.classList.remove('open');
    }
  });

  async function loadGpus() {
    try {
      const res = await fetch('/api/system/gpus');
      if (!res.ok) return;
      const data = await res.json();
      if (!data.ok || !data.gpus) return;
      renderGpuMenu(data);
    } catch (e) {
      console.warn('Could not load GPU list:', e);
    }
  }

  function renderGpuMenu(data) {
    const gpus = data.gpus || [];
    const active = data.active || gpus[0];

    if (label && active) {
      let shortName = active.name.replace(/NVIDIA\\s+/i, '').replace(/Laptop GPU/i, '').replace(/\\(R\\)/gi, '').trim();
      label.textContent = 'GPU: ' + (shortName || active.name);
    }

    if (dot && active) {
      dot.className = 'gpu-indicator-dot ' + (active.vendor || 'cpu');
    }

    list.innerHTML = gpus.map(g => {
      const isActive = g.id === data.active_gpu;
      const badgeHtml = isActive 
        ? '<span class="gpu-item-badge active">ACTIVE</span>'
        : (g.recommended ? '<span class="gpu-item-badge rec">FASTEST</span>' : '');

      return `
        <button type="button" class="gpu-menu-item ${isActive ? 'active' : ''}" data-gpu-id="${g.id}">
          <div class="gpu-item-info">
            <span class="gpu-item-name">${g.name}</span>
            <span class="gpu-item-meta">
              <span class="gpu-meta-vram">${g.vram || ''}</span>
              ${g.type ? '· ' + g.type.toUpperCase() : ''}
              ${g.temp ? '· ' + g.temp : ''}
            </span>
          </div>
          ${badgeHtml}
        </button>
      `;
    }).join('');

    list.querySelectorAll('.gpu-menu-item').forEach(item => {
      item.addEventListener('click', async (e) => {
        e.stopPropagation();
        const gpuId = item.dataset.gpuId;
        if (!gpuId || item.classList.contains('active')) {
          wrapper.classList.remove('open');
          return;
        }

        try {
          if (label) label.textContent = 'Switching GPU…';
          const postRes = await fetch('/api/system/gpus/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ gpu_id: gpuId })
          });
          const result = await postRes.json();
          if (result.ok) {
            renderGpuMenu(result);
            const gpuName = result.selected?.name || gpuId;
            showNotificationToast(`Active accelerator switched to ${gpuName}! All operations now use this device.`);
          }
        } catch (err) {
          console.error('Failed to switch GPU:', err);
        } finally {
          wrapper.classList.remove('open');
        }
      });
    });
  }

  function showNotificationToast(msg) {
    const existing = document.getElementById('gpuToast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'gpuToast';
    toast.textContent = msg;
    toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#10b981;color:#022c22;padding:10px 20px;border-radius:12px;font-size:13px;font-weight:700;box-shadow:0 10px 25px rgba(0,0,0,0.5);z-index:99999;animation:toastPop 0.25s ease;';
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = 'opacity 0.3s ease';
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 320);
    }, 4000);
  }

  loadGpus();
}
"""

if 'initGpuSelector' not in js_content:
    old_init = """// Auto-initialize Editor enhancements
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    initEditorCaptionStudio();
    renderEditorShortsTray();
  });
} else {
  initEditorCaptionStudio();
  renderEditorShortsTray();
}"""

    new_init = gpu_js + """
// Auto-initialize enhancements
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    initEditorCaptionStudio();
    renderEditorShortsTray();
    initGpuSelector();
  });
} else {
  initEditorCaptionStudio();
  renderEditorShortsTray();
  initGpuSelector();
}"""

    assert old_init in js_content, "old_init not found in app.js"
    js_content = js_content.replace(old_init, new_init)
    with open(app_js_path, 'w', encoding='utf-8') as f:
        f.write(js_content)
    print("Added initGpuSelector to app.js!")
else:
    print("initGpuSelector already in app.js")

