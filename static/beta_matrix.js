/**
 * Clipify AI - Interactive Matrix Symbol Background for Beta Testing Lab
 * Features:
 * - Fluid grid of delicate ASCII symbols spanning 100% width and height (left to right)
 * - Exact 1:1 pixel-accurate mouse repulsion & dynamic halo animation wherever cursor moves
 * - Random symbols highlighted pulsing & shifting across the entire workspace (!@#$% 0 1)
 * - Periodic Clipify Mascot Cat Logo glowing in purple/cyan aura at random places and vanishing
 * - Dynamic "CLIPIFY" ASCII block typography shimmering and spawning at random locations
 * - Auto-pauses when tab is inactive to guarantee 0% idle CPU overhead
 */
(function () {
  'use strict';

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
    const rows = GLYPHS[letter] || GLYPHS['C'];
    for (let r = 0; r < 7; r++) {
      const line = rows[r] || "     ";
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

  // Clipify Mascot Logo (Cat Face with Crown & Whiskers)
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

  const SYMBOLS = ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+', '0', '1', 'X', 'Q', 'G', 'N', 'A', '8', '?', '/', '\\', '|', '~', ':', ';', '.'];
  const LOGO_SYMBOLS = ['✦', '★', '●', '■', '◆', '▲', '▼', '#', '%', '&', '8', '0'];

  let canvas = null;
  let ctx = null;
  let betaSection = null;
  let animId = null;
  let running = false;

  let width = 0;
  let height = 0;
  let cols = 0;
  let rows = 0;
  const SPACING = 16;

  let grid = [];
  let gridMap = {};
  let mouse = { x: -9999, y: -9999, active: false };

  // "CLIPIFY" word state
  let textState = {
    startCol: 4,
    startRow: 4,
    alpha: 0,
    targetAlpha: 1,
    phase: 'fadeIn', // 'fadeIn', 'hold', 'fadeOut'
    timer: 0,
    holdDuration: 4.0,
    fadeSpeed: 1.1,
    charOverrides: {}
  };

  // Mascot Logo spawns
  let logoSpawns = [];
  let lastLogoSpawn = Date.now() - 1500;

  // Dynamic glitching/highlighted symbols
  let highlights = [];

  function pickRandomTextPosition() {
    const maxCol = Math.max(2, cols - WORD_TOTAL_COLS - 2);
    const maxRow = Math.max(2, rows - WORD_TOTAL_ROWS - 2);
    textState.startCol = Math.floor(2 + Math.random() * maxCol);
    textState.startRow = Math.floor(2 + Math.random() * maxRow);
    textState.alpha = 0;
    textState.phase = 'fadeIn';
    textState.timer = 0;

    textState.charOverrides = {};
    WORD_MAP.forEach((pt, idx) => {
      textState.charOverrides[idx] = LOGO_SYMBOLS[Math.floor(Math.random() * LOGO_SYMBOLS.length)];
    });
  }

  function spawnLogoInstance() {
    if (cols < 26 || rows < 20) return;
    // Choose random center covering left, right, or middle bands
    const centerC = Math.floor(12 + Math.random() * (cols - 24));
    const centerR = Math.floor(10 + Math.random() * (rows - 20));

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
        holdDuration: 2.5 + Math.random() * 1.5
      });
    }
  }

  function spawnHighlights() {
    if (highlights.length < 45 && Math.random() < 0.45) {
      const randPt = grid[Math.floor(Math.random() * grid.length)];
      if (randPt) {
        highlights.push({
          pt: randPt,
          char: SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)],
          alpha: 0.25,
          targetAlpha: 0.85 + Math.random() * 0.15,
          phase: 'in',
          timer: 0,
          life: 1.2 + Math.random() * 1.8,
          cycleTimer: 0
        });
      }
    }
  }

  function resize() {
    if (!canvas || !betaSection) return;
    const rect = betaSection.getBoundingClientRect();
    const parent = betaSection.parentElement || document.body;

    // Expand width across the entire container and viewport
    width = canvas.width = Math.round(Math.max(window.innerWidth, betaSection.offsetWidth || 0, rect.width || 0, parent.clientWidth || 0, 1200));
    height = canvas.height = Math.round(Math.max(window.innerHeight, betaSection.offsetHeight || 0, rect.height || 0, betaSection.scrollHeight || 0, 900));

    cols = Math.floor(width / SPACING);
    rows = Math.floor(height / SPACING);

    grid = [];
    gridMap = {};

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const bx = c * SPACING + SPACING / 2;
        const by = r * SPACING + SPACING / 2;
        const sym = SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)];
        const pt = {
          col: c,
          row: r,
          baseX: bx,
          baseY: by,
          x: bx,
          y: by,
          vx: (Math.random() - 0.5) * 0.25,
          vy: (Math.random() - 0.5) * 0.25,
          char: sym,
          baseAlpha: 0.16 + Math.random() * 0.12,
          alpha: 0.16 + Math.random() * 0.12,
          charTimer: Math.random() * 2.0
        };
        grid.push(pt);
        gridMap[`${c},${r}`] = pt;
      }
    }

    highlights = [];
    logoSpawns = [];
    pickRandomTextPosition();
    spawnLogoInstance();
  }

  function render(time) {
    if (!running || !ctx) return;

    ctx.clearRect(0, 0, width, height);
    const dt = 0.016;

    // 1. Text animation timer & phases
    textState.timer += dt;
    if (textState.phase === 'fadeIn') {
      textState.alpha += dt * textState.fadeSpeed;
      if (textState.alpha >= 1) {
        textState.alpha = 1;
        textState.phase = 'hold';
        textState.timer = 0;
      }
    } else if (textState.phase === 'hold') {
      if (textState.timer >= textState.holdDuration) {
        textState.phase = 'fadeOut';
        textState.timer = 0;
      }
    } else if (textState.phase === 'fadeOut') {
      textState.alpha -= dt * textState.fadeSpeed;
      if (textState.alpha <= 0) {
        textState.alpha = 0;
        pickRandomTextPosition();
      }
    }

    // Occasional symbol shift in "CLIPIFY"
    if (Math.random() < 0.25) {
      const randIdx = Math.floor(Math.random() * WORD_MAP.length);
      textState.charOverrides[randIdx] = LOGO_SYMBOLS[Math.floor(Math.random() * LOGO_SYMBOLS.length)];
    }

    // 2. Spawn mascot logo periodically
    const now = Date.now();
    if (logoSpawns.length < 2 && (now - lastLogoSpawn) > 3200) {
      spawnLogoInstance();
      lastLogoSpawn = now;
    }

    // 3. Spawn individual highlights
    spawnHighlights();

    // 4. Update highlights
    for (let j = highlights.length - 1; j >= 0; j--) {
      const h = highlights[j];
      h.timer += dt;
      h.cycleTimer += dt;
      if (h.cycleTimer > 0.10) {
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
        }
      }
    }

    // 5. Update mascot logo spawns
    for (let m = logoSpawns.length - 1; m >= 0; m--) {
      const l = logoSpawns[m];
      l.timer += dt;
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
        }
      }
    }

    // Setup rendering context
    ctx.font = '11px "Courier New", monospace, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const repelRadius = 110;
    const repelRadiusSq = repelRadius * repelRadius;

    // 6. Physics step and render background moving symbols
    for (let i = 0; i < grid.length; i++) {
      const pt = grid[i];

      // Slow constant drift
      pt.x += pt.vx;
      pt.y += pt.vy;
      if (Math.abs(pt.x - pt.baseX) > 8) pt.vx *= -1;
      if (Math.abs(pt.y - pt.baseY) > 8) pt.vy *= -1;

      // Mouse repulsion physics (pixel-accurate)
      if (mouse.active) {
        const dx = pt.x - mouse.x;
        const dy = pt.y - mouse.y;
        const dSq = dx * dx + dy * dy;
        if (dSq < repelRadiusSq && dSq > 0.001) {
          const dist = Math.sqrt(dSq);
          const force = (1 - dist / repelRadius) * 16;
          pt.x += (dx / dist) * force * 0.45;
          pt.y += (dy / dist) * force * 0.45;
          pt.alpha = Math.min(0.75, pt.baseAlpha + (1 - dist / repelRadius) * 0.55);
        } else {
          pt.alpha += (pt.baseAlpha - pt.alpha) * 0.05;
        }
      } else {
        pt.alpha += (pt.baseAlpha - pt.alpha) * 0.05;
      }

      // Spring back to base
      pt.x += (pt.baseX - pt.x) * 0.05;
      pt.y += (pt.baseY - pt.y) * 0.05;

      // Occasional symbol shift
      pt.charTimer += dt;
      if (pt.charTimer > 2.8) {
        pt.charTimer = 0;
        if (Math.random() < 0.25) {
          pt.char = SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)];
        }
      }

      ctx.fillStyle = `rgba(255, 255, 255, ${pt.alpha.toFixed(2)})`;
      ctx.fillText(pt.char, pt.x, pt.y);
    }

    // 7. Render dynamic individual highlighted symbols
    for (let j = 0; j < highlights.length; j++) {
      const h = highlights[j];
      ctx.fillStyle = `rgba(255, 255, 255, ${Math.max(0, h.alpha).toFixed(2)})`;
      ctx.shadowColor = 'rgba(255, 255, 255, 0.85)';
      ctx.shadowBlur = 6;
      ctx.fillText(h.char, h.pt.x, h.pt.y);
      ctx.shadowBlur = 0;
    }

    // 8. Render Mascot Logo Formations with purple/cyan aura
    ctx.font = 'bold 12px "Courier New", monospace';
    ctx.shadowColor = 'rgba(168, 85, 247, 0.95)';
    ctx.shadowBlur = 12;
    for (let m = 0; m < logoSpawns.length; m++) {
      const l = logoSpawns[m];
      const a = Math.max(0, l.alpha);
      if (a < 0.02) continue;
      for (const item of l.points) {
        item.cycleTimer += dt;
        if (item.cycleTimer > 0.18) {
          item.cycleTimer = 0;
          item.char = LOGO_SYMBOLS[Math.floor(Math.random() * LOGO_SYMBOLS.length)];
        }
        ctx.fillStyle = `rgba(235, 215, 255, ${a.toFixed(2)})`;
        ctx.fillText(item.char, item.pt.x, item.pt.y);
      }
    }
    ctx.shadowBlur = 0;

    // 9. Render "CLIPIFY" word formation
    if (textState.alpha > 0.02) {
      ctx.font = 'bold 12px "Courier New", monospace';
      ctx.shadowColor = 'rgba(160, 220, 255, 0.85)';
      ctx.shadowBlur = 8;
      WORD_MAP.forEach((pt, idx) => {
        const c = textState.startCol + pt.relCol;
        const r = textState.startRow + pt.relRow;
        const targetPt = gridMap[`${c},${r}`];
        if (targetPt) {
          const ch = textState.charOverrides[idx] || '#';
          ctx.fillStyle = `rgba(240, 248, 255, ${textState.alpha.toFixed(2)})`;
          ctx.fillText(ch, targetPt.x, targetPt.y);
        }
      });
      ctx.shadowBlur = 0;
    }

    animId = requestAnimationFrame(render);
  }

  function start() {
    if (running) return;
    running = true;
    resize();
    animId = requestAnimationFrame(render);
  }

  function stop() {
    running = false;
    if (animId) {
      cancelAnimationFrame(animId);
      animId = null;
    }
  }

  function init() {
    canvas = document.getElementById('betaMatrixCanvas');
    betaSection = document.getElementById('beta');
    if (!canvas || !betaSection) return;

    ctx = canvas.getContext('2d');

    // 1:1 Pixel-Accurate Mouse Event Tracking
    betaSection.addEventListener('mousemove', (e) => {
      const rect = canvas.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        mouse.x = (e.clientX - rect.left) * (canvas.width / rect.width);
        mouse.y = (e.clientY - rect.top) * (canvas.height / rect.height);
        mouse.active = true;
      }
    });

    betaSection.addEventListener('mouseleave', () => {
      mouse.active = false;
    });

    window.addEventListener('resize', () => {
      if (running) resize();
    });

    function checkVisibility() {
      const isVisible = betaSection.classList.contains('visible') ||
        (window.location.hash || '').toLowerCase().includes('beta');
      if (isVisible) {
        start();
      } else {
        stop();
      }
    }

    window.addEventListener('hashchange', checkVisibility);
    const observer = new MutationObserver(checkVisibility);
    observer.observe(betaSection, { attributes: true, attributeFilter: ['class', 'style'] });

    checkVisibility();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.initBetaMatrix = init;
})();
