/**
 * Clipify AI — Hardware Accelerator & GPU Switcher Controller
 * Connects UI buttons and dropdowns with GET /api/system/gpus & POST /api/system/gpus/select
 * Supports both sidebar top-row and top-bar cockpit placements.
 */
(function() {
  'use strict';

  let currentGpuData = null;

  function initGpuSelector() {
    const wrappers = Array.from(document.querySelectorAll('.gpu-dropdown-wrapper'));
    if (!wrappers.length) return;

    function closeAllGpuMenus() {
      document.querySelectorAll('.gpu-dropdown-wrapper.open').forEach(w => w.classList.remove('open'));
      document.querySelectorAll('.gpu-dropdown-menu.open').forEach(m => {
        m.classList.remove('open');
        m.style.display = '';
      });
    }

    // Toggle dropdown on button click
    wrappers.forEach(wrapper => {
      const btn = wrapper.querySelector('.gpu-dropdown-btn');
      const menu = wrapper.querySelector('.gpu-dropdown-menu');
      if (!btn || !menu) return;
      wrapper._gpuMenu = menu;
      menu._gpuWrapper = wrapper;

      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = wrapper.classList.contains('open') || menu.classList.contains('open');
        closeAllGpuMenus();
        const willOpen = !isOpen;
        if (willOpen) {
          if (wrapper.classList.contains('sidebar-gpu-wrapper')) {
            if (window.innerWidth > 768) {
              if (menu.parentElement !== document.body) {
                document.body.appendChild(menu);
              }
              const rect = btn.getBoundingClientRect();
              menu.style.position = 'fixed';
              menu.style.left = `${Math.round(rect.right + 10)}px`;
              menu.style.top = `${Math.max(12, Math.round(rect.top))}px`;
              menu.style.right = 'auto';
              menu.style.zIndex = '2147483649';
              menu.style.display = 'flex';
            } else {
              if (menu.parentElement !== wrapper) {
                wrapper.appendChild(menu);
              }
              menu.style.position = '';
              menu.style.left = '';
              menu.style.top = '';
              menu.style.right = '';
              menu.style.zIndex = '';
              menu.style.display = 'flex';
            }
          }
          wrapper.classList.add('open');
          menu.classList.add('open');
        }
      });
    });

    // Close when clicking outside
    document.addEventListener('click', (e) => {
      const clickedInsideWrapper = wrappers.some(w => w.contains(e.target));
      const clickedInsidePortaledMenu = Array.from(document.querySelectorAll('.gpu-dropdown-menu.open')).some(m => m.contains(e.target));
      if (!clickedInsideWrapper && !clickedInsidePortaledMenu) {
        closeAllGpuMenus();
      }
    });

    let gpuRetries = 0;
    try {
      const cached = sessionStorage.getItem('clipify_gpu_cache');
      if (cached) {
        const parsed = JSON.parse(cached);
        if (parsed && parsed.gpus) {
          currentGpuData = parsed;
          renderAllGpuMenus(parsed);
        }
      }
    } catch (_) {}

    async function loadGpus() {
      try {
        const res = await fetch('/api/system/gpus', { cache: 'no-store' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (!data.ok || !data.gpus) throw new Error('Invalid GPU payload');
        currentGpuData = data;
        try { sessionStorage.setItem('clipify_gpu_cache', JSON.stringify(data)); } catch (_) {}
        renderAllGpuMenus(data);
      } catch (e) {
        gpuRetries++;
        if (gpuRetries <= 3) {
          setTimeout(loadGpus, 1500);
        } else {
          document.querySelectorAll('.gpu-current-label').forEach(label => {
            if (label.textContent.includes('Detecting')) {
              label.textContent = 'GPU: Auto';
            }
          });
        }
      }
    }

    function renderAllGpuMenus(data) {
      const gpus = data.gpus || [];
      const active = data.active || gpus[0];

      // Update all labels and indicator dots across the page
      document.querySelectorAll('.gpu-current-label').forEach(label => {
        if (active) {
          let shortName = active.name
            .replace(/NVIDIA\s+/i, '')
            .replace(/Laptop GPU/i, '')
            .replace(/\(R\)/gi, '')
            .replace(/Graphics/i, '')
            .trim();
          label.textContent = 'GPU: ' + (shortName || active.name);
        }
      });

      document.querySelectorAll('.gpu-indicator-dot').forEach(dot => {
        if (active) {
          dot.className = 'gpu-indicator-dot ' + (active.vendor || 'cpu');
        }
      });

      // Render menus inside all wrappers
      document.querySelectorAll('.gpu-dropdown-wrapper').forEach(wrapper => {
        const menuHost = wrapper._gpuMenu || wrapper;
        const list = menuHost.querySelector('.gpu-menu-list');
        if (!list) return;

        list.innerHTML = gpus.map(g => {
          const isActive = g.id === data.active_gpu;
          const badgeHtml = isActive 
            ? '<span class="gpu-item-badge active">ACTIVE</span>'
            : (g.recommended ? '<span class="gpu-item-badge rec">FASTEST</span>' : '');

          const dotColorClass = g.vendor || 'cpu';

          return `
            <button type="button" class="gpu-menu-item ${isActive ? 'active' : ''}" data-gpu-id="${g.id}">
              <div class="gpu-item-info">
                <span class="gpu-item-name">
                  <span class="gpu-indicator-dot ${dotColorClass}" style="display:inline-block;margin-right:6px;width:6px;height:6px;"></span>
                  ${escapeHtml(g.name)}
                </span>
                <span class="gpu-item-meta">
                  <span class="gpu-meta-vram">${escapeHtml(g.vram || '')}</span>
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
            if (!gpuId) {
              wrapper.classList.remove('open');
              return;
            }

            try {
              document.querySelectorAll('.gpu-current-label').forEach(lbl => {
                lbl.textContent = 'Switching GPU…';
              });
              const postRes = await fetch('/api/system/gpus/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ gpu_id: gpuId })
              });
              const result = await postRes.json();
              if (result.ok) {
                currentGpuData = result;
                renderAllGpuMenus(result);
                const gpuName = result.selected?.name || gpuId;
                showToast(`✓ Switched active accelerator to ${gpuName}! All operations now use this device.`);
              }
            } catch (err) {
              console.error('Failed to switch GPU:', err);
              showToast('Could not switch GPU. Check system logs.');
            } finally {
              closeAllGpuMenus();
            }
          });
        });
      });
    }

    function showToast(msg) {
      const existing = document.getElementById('gpuToast');
      if (existing) existing.remove();

      const toast = document.createElement('div');
      toast.id = 'gpuToast';
      toast.textContent = msg;
      toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#10b981;color:#022c22;padding:12px 24px;border-radius:12px;font-size:13px;font-weight:700;box-shadow:0 10px 30px rgba(0,0,0,0.6);z-index:999999;transition:opacity 0.25s ease;letter-spacing:0.02em;';
      document.body.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 280);
      }, 4000);
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    loadGpus();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGpuSelector);
  } else {
    initGpuSelector();
  }
})();
