/**
 * Caption Design Showcase & Interactive Mouse Playground
 * Provides visual preset cards, interactive 9:16 phone canvas with mouse dragging & resizing.
 */
(function() {
  'use strict';

  const CAPTION_STYLES = [
    {
      id: 'gold_yellow',
      name: 'Viral Yellow Punch',
      font: 'Montserrat Black',
      cssClass: 'cap-style-gold',
      accentColor: '#FFE500',
      sampleHtml: 'MAKE EVERY CLIP <span class="cap-word-pop">VIRAL</span> TODAY'
    },
    {
      id: 'lime_green',
      name: 'Cyber Lime Green',
      font: 'Komika Axis / Impact',
      cssClass: 'cap-style-lime',
      accentColor: '#39FF14',
      sampleHtml: 'THIS MOMENT WAS <span class="cap-word-pop">INSANE</span>'
    },
    {
      id: 'hormozi',
      name: 'Hormozi Bold White',
      font: 'TheBoldFont / ExtraBold',
      cssClass: 'cap-style-hormozi',
      accentColor: '#FFD700',
      sampleHtml: 'GROW YOUR AUDIENCE <span class="cap-word-pop">FASTER</span>'
    },
    {
      id: 'cyan_sky',
      name: 'TikTok Cyan Pop',
      font: 'Proxima / Inter Black',
      cssClass: 'cap-style-cyan',
      accentColor: '#00F2FE',
      sampleHtml: 'STREAM HIGHLIGHTS <span class="cap-word-pop">PERFECTED</span>'
    },
    {
      id: 'coral_red',
      name: 'Crimson Fire',
      font: 'Futura / Arial Black',
      cssClass: 'cap-style-fire',
      accentColor: '#FF3344',
      sampleHtml: 'HIGH INTENSITY <span class="cap-word-pop">CLUTCH</span> PLAY'
    },
    {
      id: 'retro',
      name: 'Typewriter Retro',
      font: 'Courier Prime Mono',
      cssClass: 'cap-style-retro',
      accentColor: '#00FF66',
      sampleHtml: 'MINIMAL <span class="cap-word-pop">SUBTITLES</span> ON POINT'
    },
    {
      id: 'pink_lavender',
      name: 'Neon Lavender',
      font: 'Poppins Bold',
      cssClass: 'cap-style-lavender',
      accentColor: '#E879F9',
      sampleHtml: 'AESTHETIC <span class="cap-word-pop">SHORT</span> EDIT'
    }
  ];

  // State
  let currentStyle = CAPTION_STYLES[0];
  let currentYPercent = 75; // 75% down = Lower Safe area
  let currentFontSize = 44; // px on stage

  // DOM Elements
  let stylesGrid = null;
  let phoneStage = null;
  let dragBox = null;
  let dragText = null;
  let resizeCorner = null;
  let posTag = null;
  let sizeSlider = null;
  let sizeBadge = null;
  let posPills = null;
  let sizeDecBtn = null;
  let sizeIncBtn = null;

  function init() {
    stylesGrid = document.getElementById('captionStylesGrid');
    phoneStage = document.getElementById('captionPhoneStage');
    dragBox = document.getElementById('captionDragBox');
    dragText = document.getElementById('captionDragText');
    resizeCorner = document.getElementById('captionResizeCorner');
    posTag = document.getElementById('captionPosTag');
    sizeSlider = document.getElementById('captionSizeSlider');
    sizeBadge = document.getElementById('captionSizeBadge');
    posPills = document.querySelectorAll('.caption-pos-pill');
    sizeDecBtn = document.getElementById('captionSizeDec');
    sizeIncBtn = document.getElementById('captionSizeInc');

    if (!stylesGrid || !phoneStage || !dragBox) return;

    renderStyleCards();
    setupMouseDrag();
    setupMouseResize();
    setupControls();
    updateStage();
  }

  function renderStyleCards() {
    stylesGrid.innerHTML = CAPTION_STYLES.map(style => `
      <div class="caption-style-card ${style.id === currentStyle.id ? 'active' : ''}" data-style-id="${style.id}">
        <div class="caption-card-meta">
          <span class="caption-card-name">${escapeHtml(style.name)}</span>
          <span class="caption-card-font">${escapeHtml(style.font)}</span>
        </div>
        <div class="caption-card-preview ${style.cssClass}">
          ${style.sampleHtml}
        </div>
      </div>
    `).join('');

    stylesGrid.querySelectorAll('.caption-style-card').forEach(card => {
      card.addEventListener('click', () => {
        const styleId = card.dataset.styleId;
        const found = CAPTION_STYLES.find(s => s.id === styleId);
        if (found) {
          selectStyle(found);
        }
      });
    });
  }

  function selectStyle(style) {
    currentStyle = style;
    stylesGrid.querySelectorAll('.caption-style-card').forEach(c => {
      c.classList.toggle('active', c.dataset.styleId === style.id);
    });

    // Sync with existing backend dropdowns
    const accentSelect = document.getElementById('betaCaptionAccent');
    if (accentSelect) {
      if (['gold_yellow', 'lime_green', 'cyan_sky', 'coral_red', 'pink_lavender'].includes(style.id)) {
        accentSelect.value = style.id;
      }
    }

    updateStage();
    publishState();
  }

  function setupMouseDrag() {
    let isDragging = false;
    let startY = 0;
    let startPercent = 0;

    function onPointerDown(e) {
      if (e.target === resizeCorner) return; // let resize handle deal with resize
      isDragging = true;
      dragBox.classList.add('dragging');
      startY = e.clientY;
      startPercent = currentYPercent;
      e.preventDefault();

      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', onPointerUp);
    }

    function onPointerMove(e) {
      if (!isDragging) return;
      const rect = phoneStage.getBoundingClientRect();
      const deltaY = e.clientY - startY;
      const deltaPercent = (deltaY / rect.height) * 100;
      let newY = startPercent + deltaPercent;

      // Clamp between 15% and 88%
      newY = Math.max(15, Math.min(88, newY));

      // Snapping near 25% (Top Safe), 50% (Center Seam), 75% (Lower Safe)
      if (Math.abs(newY - 50) < 2.5) newY = 50;
      else if (Math.abs(newY - 75) < 2.5) newY = 75;
      else if (Math.abs(newY - 25) < 2.5) newY = 25;

      currentYPercent = Math.round(newY);
      updateStage();
      publishState();
    }

    function onPointerUp() {
      isDragging = false;
      dragBox.classList.remove('dragging');
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    }

    dragBox.addEventListener('pointerdown', onPointerDown);
    // Also allow clicking directly on the phone stage to jump caption there
    phoneStage.addEventListener('pointerdown', (e) => {
      if (e.target === dragBox || dragBox.contains(e.target)) return;
      const rect = phoneStage.getBoundingClientRect();
      const clickY = e.clientY - rect.top;
      let newY = (clickY / rect.height) * 100;
      newY = Math.max(15, Math.min(88, newY));
      currentYPercent = Math.round(newY);
      updateStage();
      publishState();
    });
  }

  function setupMouseResize() {
    let isResizing = false;
    let startY = 0;
    let startSize = 0;

    if (resizeCorner) {
      resizeCorner.addEventListener('pointerdown', (e) => {
        isResizing = true;
        startY = e.clientY;
        startSize = currentFontSize;
        e.stopPropagation();
        e.preventDefault();

        function onResizeMove(ev) {
          if (!isResizing) return;
          const delta = ev.clientY - startY;
          // Moving down makes it bigger, moving up makes it smaller
          let newSize = startSize + (delta * 0.4);
          newSize = Math.max(24, Math.min(76, Math.round(newSize)));
          currentFontSize = newSize;
          updateStage();
          publishState();
        }

        function onResizeUp() {
          isResizing = false;
          window.removeEventListener('pointermove', onResizeMove);
          window.removeEventListener('pointerup', onResizeUp);
        }

        window.addEventListener('pointermove', onResizeMove);
        window.addEventListener('pointerup', onResizeUp);
      });
    }

    // Mouse wheel over caption resizes smoothly
    dragBox.addEventListener('wheel', (e) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 2 : -2;
      currentFontSize = Math.max(24, Math.min(76, currentFontSize + delta));
      updateStage();
      publishState();
    }, { passive: false });
  }

  function setupControls() {
    // Quick position buttons
    posPills.forEach(btn => {
      btn.addEventListener('click', () => {
        posPills.forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const pos = btn.dataset.pos;
        if (pos === 'top') currentYPercent = 25;
        else if (pos === 'center') currentYPercent = 50;
        else if (pos === 'lower') currentYPercent = 75;
        else if (pos === 'bottom') currentYPercent = 84;
        updateStage();
        publishState();
      });
    });

    // Size Slider
    if (sizeSlider) {
      sizeSlider.addEventListener('input', (e) => {
        currentFontSize = parseInt(e.target.value, 10);
        updateStage();
        publishState();
      });
    }

    // Step buttons [-] and [+]
    if (sizeDecBtn) {
      sizeDecBtn.addEventListener('click', () => {
        currentFontSize = Math.max(24, currentFontSize - 4);
        updateStage();
        publishState();
      });
    }

    if (sizeIncBtn) {
      sizeIncBtn.addEventListener('click', () => {
        currentFontSize = Math.min(76, currentFontSize + 4);
        updateStage();
        publishState();
      });
    }

    // Quick size preset pills
    document.querySelectorAll('.caption-size-preset-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('.caption-size-preset-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        currentFontSize = parseInt(pill.dataset.size, 10) || 44;
        updateStage();
        publishState();
      });
    });
  }

  function updateStage() {
    if (!dragBox || !dragText) return;

    // 1. Position
    dragBox.style.top = `${currentYPercent}%`;

    // Label position tag
    let posLabel = `Y: ${currentYPercent}%`;
    if (Math.abs(currentYPercent - 75) <= 3) posLabel += ' · Lower Safe';
    else if (Math.abs(currentYPercent - 50) <= 3) posLabel += ' · Center Seam';
    else if (Math.abs(currentYPercent - 25) <= 3) posLabel += ' · Top Safe';

    if (posTag) posTag.textContent = posLabel;

    // Update position pills active state
    posPills.forEach(p => {
      const pos = p.dataset.pos;
      const isMatch = (pos === 'top' && Math.abs(currentYPercent - 25) <= 3) ||
                      (pos === 'center' && Math.abs(currentYPercent - 50) <= 3) ||
                      (pos === 'lower' && Math.abs(currentYPercent - 75) <= 3) ||
                      (pos === 'bottom' && currentYPercent > 80);
      p.classList.toggle('active', isMatch);
    });

    // 2. Font Size (scaled proportionally to mockup canvas width)
    // Canvas is 220px wide; real video is 1080px wide (factor: 220/1080 ~ 0.204)
    // Scale for crisp visibility on phone canvas
    const displayFontSize = Math.max(11, Math.round(currentFontSize * 0.32));
    dragText.style.fontSize = `${displayFontSize}px`;

    if (sizeSlider) sizeSlider.value = currentFontSize;
    if (sizeBadge) sizeBadge.textContent = `${currentFontSize}px`;

    // 3. Caption Style & Content
    dragText.className = `caption-drag-text ${currentStyle.cssClass}`;
    dragText.innerHTML = currentStyle.sampleHtml;
  }

  function publishState() {
    window.captionPlaygroundState = {
      styleId: currentStyle.id,
      font: currentStyle.font,
      yPercent: currentYPercent,
      fontSize: currentFontSize
    };

    // Update preset dropdown if match
    const presetSelect = document.getElementById('betaCaptionPreset');
    if (presetSelect) {
      if (Math.abs(currentYPercent - 50) <= 4) presetSelect.value = 'center_seam';
      else if (Math.abs(currentYPercent - 75) <= 4) presetSelect.value = 'lower_safe';
      else if (Math.abs(currentYPercent - 25) <= 4) presetSelect.value = 'top_safe';
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  window.initCaptionPlayground = init;

  document.addEventListener('DOMContentLoaded', () => {
    init();
  });
})();
