/**
 * Clipify AI - Interactive Guided Onboarding Tour
 */
(function() {
  const TOUR_STORAGE_KEY = 'clipify_tour_completed';

  const TOUR_STEPS = [
    {
      target: '#dropzone',
      title: '1. Create & Import',
      desc: 'Drop your video file here or paste a YouTube link. Clipify AI automatically fetches footage and prepares it for processing.',
      pos: 'bottom'
    },
    {
      target: '.mode-strip',
      title: '2. Smart AI Modes & Split Screen',
      desc: 'Pick your editing style (Viral Hooks, Flow, Highlights, Gaming). Enable Split-Screen for podcasts to frame one speaker on top and the other at the bottom.',
      pos: 'bottom'
    },
    {
      target: 'a[href="/narrate"]',
      title: '3. Voice & Narrate Studio',
      desc: 'Generate voiceovers and narrated AI stories using high-quality local offline text-to-speech models.',
      pos: 'right'
    },
    {
      target: 'a[data-nav="projects"]',
      title: '4. Workspace & Saved Projects',
      desc: 'All generated Shorts, clips, transcripts and assets are saved locally. Review, download, or re-edit them anytime.',
      pos: 'right'
    },
    {
      target: 'a[data-nav="editor"]',
      title: '5. Editor & Social MCP',
      desc: 'Customize subtitles, add logo watermarks, and publish your finished Shorts directly to YouTube, TikTok and Instagram.',
      pos: 'right'
    },
    {
      isFinal: true,
      title: 'Support Clipify AI ⭐',
      desc: 'I built Clipify AI completely free, local, and unrestricted so everyone can create viral Shorts without paying subscriptions. A star on GitHub means the world and helps keep updates coming!'
    }
  ];

  let currentStepIndex = 0;
  let overlayEl = null;
  let spotlightEl = null;
  let cardEl = null;

  function initTourElements() {
    if (overlayEl) return;

    overlayEl = document.createElement('div');
    overlayEl.id = 'tourOverlay';

    spotlightEl = document.createElement('div');
    spotlightEl.id = 'tourSpotlight';
    overlayEl.appendChild(spotlightEl);

    cardEl = document.createElement('div');
    cardEl.id = 'tourCard';
    overlayEl.appendChild(cardEl);

    document.body.appendChild(overlayEl);

    // Keyboard listener
    window.addEventListener('keydown', (e) => {
      if (!overlayEl || !overlayEl.classList.contains('active')) return;
      if (e.key === 'Escape') endTour();
      else if (e.key === 'ArrowRight' || e.key === 'Enter') nextStep();
      else if (e.key === 'ArrowLeft') prevStep();
    });

    // Window resize handler
    window.addEventListener('resize', () => {
      if (overlayEl && overlayEl.classList.contains('active')) {
        renderCurrentStep();
      }
    });
  }

  function startTour(force = false) {
    if (!force && localStorage.getItem(TOUR_STORAGE_KEY)) {
      return;
    }
    initTourElements();
    currentStepIndex = 0;
    overlayEl.classList.add('active');
    renderCurrentStep();
  }

  function endTour() {
    if (!overlayEl) return;
    overlayEl.classList.remove('active');
    localStorage.setItem(TOUR_STORAGE_KEY, 'true');
  }

  function nextStep() {
    if (currentStepIndex < TOUR_STEPS.length - 1) {
      currentStepIndex++;
      renderCurrentStep();
    } else {
      endTour();
    }
  }

  function prevStep() {
    if (currentStepIndex > 0) {
      currentStepIndex--;
      renderCurrentStep();
    }
  }

  function renderCurrentStep() {
    const step = TOUR_STEPS[currentStepIndex];
    if (!step) return;

    if (step.isFinal) {
      renderFinalStep(step);
      return;
    }

    const targetEl = document.querySelector(step.target);
    if (!targetEl) {
      nextStep();
      return;
    }

    // Scroll element immediately into view
    targetEl.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'nearest' });

    const rect = targetEl.getBoundingClientRect();
    const pad = 8;

    // Position moving spotlight
    spotlightEl.style.display = 'block';
    spotlightEl.style.top = Math.max(0, rect.top - pad) + 'px';
    spotlightEl.style.left = Math.max(0, rect.left - pad) + 'px';
    spotlightEl.style.width = (rect.width + pad * 2) + 'px';
    spotlightEl.style.height = (rect.height + pad * 2) + 'px';
    spotlightEl.style.borderRadius = '16px';

    // Card content
    cardEl.innerHTML = `
      <div class="tour-card-header">
        <span class="tour-step-badge">Step ${currentStepIndex + 1} of ${TOUR_STEPS.length - 1}</span>
        <button class="tour-skip-btn" type="button" aria-label="Skip tour">Skip</button>
      </div>
      <h3 class="tour-title">${step.title}</h3>
      <p class="tour-desc">${step.desc}</p>
      <div class="tour-footer">
        <button class="tour-btn prev" type="button" ${currentStepIndex === 0 ? 'disabled' : ''}>← Previous</button>
        <div class="tour-nav-btns">
          <button class="tour-btn next" type="button">Next →</button>
        </div>
      </div>
    `;

    cardEl.querySelector('.tour-skip-btn')?.addEventListener('click', endTour);
    cardEl.querySelector('.tour-btn.prev')?.addEventListener('click', prevStep);
    cardEl.querySelector('.tour-btn.next')?.addEventListener('click', nextStep);

    // Position tooltip card smartly
    positionCard(rect, step.pos);
  }

  function positionCard(targetRect, preferredPos) {
    const cardW = 350;
    const cardH = cardEl.offsetHeight || 220;
    const margin = 14;

    let top = 0;
    let left = 0;

    const spaceBelow = window.innerHeight - targetRect.bottom;
    const spaceAbove = targetRect.top;
    const spaceRight = window.innerWidth - targetRect.right;

    if (preferredPos === 'right' && spaceRight >= cardW + margin) {
      left = targetRect.right + margin;
      top = Math.max(margin, Math.min(window.innerHeight - cardH - margin, targetRect.top));
    } else if (spaceBelow >= cardH + margin) {
      top = targetRect.bottom + margin;
      left = Math.max(margin, Math.min(window.innerWidth - cardW - margin, targetRect.left));
    } else if (spaceAbove >= cardH + margin) {
      top = targetRect.top - cardH - margin;
      left = Math.max(margin, Math.min(window.innerWidth - cardW - margin, targetRect.left));
    } else if (spaceRight >= cardW + margin) {
      left = targetRect.right + margin;
      top = Math.max(margin, (window.innerHeight - cardH) / 2);
    } else {
      top = Math.max(margin, Math.min(window.innerHeight - cardH - margin, 24));
      left = Math.max(margin, Math.min(window.innerWidth - cardW - margin, 24));
    }

    cardEl.style.top = `${Math.round(top)}px`;
    cardEl.style.left = `${Math.round(left)}px`;
  }

  function renderFinalStep(step) {
    // Hide spotlight for center modal
    spotlightEl.style.display = 'none';

    cardEl.innerHTML = `
      <div class="tour-github-card">
        <div class="tour-avatar-wrap">
          <img class="tour-avatar-img" src="/static/author-avatar.png" alt="Sherlock Dev AI" onerror="this.src='/static/icon.png'">
          <div class="tour-star-badge" aria-hidden="true">★</div>
        </div>
        <h3 class="tour-title" style="font-size:1.4rem;margin-bottom:8px;">${step.title}</h3>
        <p class="tour-desc" style="font-size:13.5px;margin-bottom:18px;">${step.desc}</p>
        <a class="tour-star-btn" href="https://github.com/sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE" target="_blank" rel="noopener noreferrer">
          <span>⭐ Star on GitHub</span>
          <span style="font-size:11px;opacity:0.85;">(github.com)</span>
        </a>
        <button class="tour-finish-btn" type="button">Let's Clip Some Videos →</button>
      </div>
    `;

    cardEl.querySelector('.tour-finish-btn')?.addEventListener('click', endTour);

    // Center the card in viewport
    const cardRect = cardEl.getBoundingClientRect();
    const top = Math.max(20, (window.innerHeight - cardRect.height) / 2);
    const left = Math.max(20, (window.innerWidth - cardRect.width) / 2);
    cardEl.style.top = `${top}px`;
    cardEl.style.left = `${left}px`;
  }

  // Expose API
  window.startClipifyTour = () => startTour(true);

  // Auto-run on first load
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
      startTour(false);
    }, 150);
  });
})();
