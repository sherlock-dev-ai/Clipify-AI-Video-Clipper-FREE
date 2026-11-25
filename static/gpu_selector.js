/**
 * Clipify AI — Hardware Accelerator & GPU Switcher Controller
 * Connects UI button and dropdown with GET /api/system/gpus & POST /api/system/gpus/select
 */
(function() {
  'use strict';

  function initGpuSelector() {
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
        let shortName = active.name.replace(/NVIDIA\s+/i, '').replace(/Laptop GPU/i, '').replace(/\(R\)/gi, '').trim();
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
              <span class="gpu-item-name">${escapeHtml(g.name)}</span>
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
              showToast(`Switched active accelerator to ${gpuName}! All operations now use this device.`);
            }
          } catch (err) {
            console.error('Failed to switch GPU:', err);
          } finally {
            wrapper.classList.remove('open');
          }
        });
      });
    }

    function showToast(msg) {
      const existing = document.getElementById('gpuToast');
      if (existing) existing.remove();

      const toast = document.createElement('div');
      toast.id = 'gpuToast';
      toast.textContent = msg;
      toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#10b981;color:#022c22;padding:10px 20px;border-radius:12px;font-size:13px;font-weight:700;box-shadow:0 10px 25px rgba(0,0,0,0.5);z-index:99999;transition:opacity 0.25s ease;';
      document.body.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 280);
      }, 3500);
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
