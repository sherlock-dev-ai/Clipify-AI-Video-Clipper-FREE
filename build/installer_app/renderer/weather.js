'use strict';

/**
 * Ambient weather for the setup window.
 *
 * Deliberately slow: each state holds for a long while and cross-fades over a
 * few seconds, because this is an installer, not a game launcher. The scene is
 * CSS-driven, so this file only sets `data-weather` and seeds the decorative
 * elements (stars, trees, grass, rain) once.
 */

(function () {
  // A plausible day, not a shuffle. Held long so it never feels like a gimmick.
  const SEQUENCE = [
    'morning', 'morning', 'cloudy', 'cloudy', 'rain', 'cloudy',
    'sunset', 'sunset', 'night', 'night', 'morning',
  ];
  const HOLD_MS = 68000;
  const MAX = 100;

  const rand = (min, max) => min + Math.random() * (max - min);

  function seedStars(host, count) {
    if (!host || host.childElementCount) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const star = document.createElement('span');
      star.className = 'star';
      star.style.left = `${rand(0, 100).toFixed(2)}%`;
      star.style.top = `${rand(0, 100).toFixed(2)}%`;
      const size = rand(1, 2.6);
      star.style.width = `${size.toFixed(2)}px`;
      star.style.height = `${size.toFixed(2)}px`;
      star.style.animationDelay = `${rand(0, 3.6).toFixed(2)}s`;
      frag.appendChild(star);
    }
    host.appendChild(frag);
  }

  function seedTrees(host, count) {
    if (!host || host.childElementCount) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const tree = document.createElement('span');
      tree.className = 'tree';
      tree.style.left = `${(i * (100 / count) + rand(-3, 3)).toFixed(2)}%`;
      tree.style.transform = `scale(${rand(0.6, 1.15).toFixed(2)})`;
      tree.style.transformOrigin = '50% 100%';
      tree.style.bottom = `${rand(-14, 12).toFixed(1)}px`;
      frag.appendChild(tree);
    }
    host.appendChild(frag);
  }

  function seedGrass(host, count) {
    if (!host || host.childElementCount) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const blade = document.createElement('span');
      blade.className = 'blade';
      blade.style.height = `${rand(14, 46).toFixed(1)}px`;
      blade.style.animationDelay = `${rand(0, 4.2).toFixed(2)}s`;
      blade.style.animationDuration = `${rand(3.2, 5.6).toFixed(2)}s`;
      frag.appendChild(blade);
    }
    host.appendChild(frag);
  }

  function seedFlowers(host, count) {
    if (!host || host.childElementCount) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const flower = document.createElement('span');
      flower.className = 'flower';
      flower.style.left = `${rand(1, 96).toFixed(2)}%`;
      flower.style.animationDelay = `${rand(0, 5).toFixed(2)}s`;
      flower.style.opacity = rand(0.55, 0.95).toFixed(2);
      frag.appendChild(flower);
    }
    host.appendChild(frag);
  }

  function seedFireflies(host, count) {
    if (!host || host.childElementCount) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const fly = document.createElement('span');
      fly.className = 'firefly';
      fly.style.left = `${rand(2, 96).toFixed(2)}%`;
      fly.style.top = `${rand(4, 92).toFixed(2)}%`;
      fly.style.animationDelay = `${rand(0, 6.5).toFixed(2)}s`;
      fly.style.animationDuration = `${rand(5, 9).toFixed(2)}s`;
      frag.appendChild(fly);
    }
    host.appendChild(frag);
  }

  function seedRain(host, count) {
    if (!host || host.childElementCount) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const drop = document.createElement('span');
      drop.className = 'drop';
      drop.style.left = `${rand(0, 100).toFixed(2)}%`;
      drop.style.animationDuration = `${rand(0.5, 1.1).toFixed(2)}s`;
      drop.style.animationDelay = `${rand(0, 1.4).toFixed(2)}s`;
      drop.style.opacity = rand(0.35, 0.9).toFixed(2);
      frag.appendChild(drop);
    }
    host.appendChild(frag);
  }

  /** Bees and birds drifting across the sky on a light canvas. */
  function startDrift(canvas) {
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const flyers = [];
    let raf = 0;
    let last = 0;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const spawn = () => {
      const w = canvas.getBoundingClientRect().width;
      const h = canvas.getBoundingClientRect().height;
      // Bees are the common case; birds are occasional.
      const bird = Math.random() < 0.22;
      // Bees live in the upper-to-middle band of the scene and very rarely
      // drop to the floor, so they never sit on top of the text and controls.
      const yMax = bird ? 0.62 : 0.5;
      const fromLeft = Math.random() < 0.5;
      const bee = {
        x: fromLeft ? -20 : w + 20,
        y: rand(0.1 * h, yMax * h),
        vx: (fromLeft ? 1 : -1) * rand(0.35, 0.95),
        vy: 0,
        phase: rand(0, Math.PI * 2),
        bird,
        size: bird ? rand(3, 5) : rand(2.4, 3.4),
        wobble: rand(0.6, 1.5),
        // Semi-random steering: target re-rolled on a timer so paths never
        // loop visibly, plus occasional direction changes.
        tx: 0,
        ty: 0,
        turn: 0,
        ceiling: yMax * h,
      };
      bee.tx = bee.x;
      bee.ty = bee.y;
      flyers.push(bee);
    };

    const draw = (time) => {
      raf = window.requestAnimationFrame(draw);
      const dt = Math.min(48, time - (last || time));
      last = time;
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      const night = document.body.dataset.weather === 'night';

      if (flyers.length < 9) spawn();

      for (let i = flyers.length - 1; i >= 0; i -= 1) {
        const f = flyers[i];
        f.phase += (dt / 1000) * f.wobble * 2;
        if (f.x > rect.width + 40 || f.x < -40) flyers.splice(i, 1);

        if (f.bird) {
          f.x += f.vx * (dt / 16);
        } else {
          // Re-roll a wander target every so often, biased upward and sideways.
          f.turn -= dt;
          if (f.turn <= 0) {
            f.turn = rand(700, 2400);
            f.tx = f.x + rand(-190, 190);
            f.ty = rand(0.08 * rect.height, f.ceiling);
          }
          const dx = f.tx - f.x;
          const dy = f.ty - f.y;
          const dist = Math.hypot(dx, dy) || 1;
          f.x += (dx / dist) * 0.55 * (dt / 16);
          f.y += (dy / dist) * 0.55 * (dt / 16);
          f.vx = (dx / dist) * 0.5;
          // Keep them off the floor and off the very top of the frame.
          if (f.y > f.ceiling) f.y = f.ceiling;
          if (f.y < rect.height * 0.05) f.y = rect.height * 0.05;
        }

        ctx.save();
        if (f.bird) {
          // A simple two-stroke bird, not artwork.
          const flap = Math.sin(f.phase) * 3;
          ctx.strokeStyle = night ? 'rgba(226,232,240,0.5)' : 'rgba(60,50,45,0.42)';
          ctx.lineWidth = 1.3;
          ctx.beginPath();
          ctx.moveTo(f.x - f.size, f.y + flap);
          ctx.quadraticCurveTo(f.x, f.y - f.size * 0.7, f.x + f.size, f.y + flap);
          ctx.stroke();
        } else {
          // Bee: small body with a lazy figure-eight drift.
          const bob = Math.sin(f.phase) * 9;
          const x = f.x;
          const y = f.y + bob;
          ctx.fillStyle = night ? 'rgba(255,226,140,0.75)' : 'rgba(214,160,60,0.8)';
          ctx.beginPath();
          ctx.ellipse(x, y, f.size, f.size * 0.72, 0, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = night ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.8)';
          ctx.beginPath();
          ctx.ellipse(x - 1, y - f.size * 0.8, f.size * 0.9, f.size * 0.45, -0.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.beginPath();
          ctx.ellipse(x + 1.4, y - f.size * 0.85, f.size * 0.9, f.size * 0.45, 0.5, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }
    };

    resize();
    window.addEventListener('resize', resize, { passive: true });
    raf = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(raf);
  }

  /** A few bats gliding across the upper sky. They only show at night. */
  function startBats(host) {
    if (!host || host.childElementCount) return;
    const frag = document.createDocumentFragment();
    const bats = [];
    for (let i = 0; i < 5; i += 1) {
      const el = document.createElement('span');
      el.className = 'bat';
      const size = rand(0.7, 1.25);
      el.style.width = `${(13 * size).toFixed(1)}px`;
      el.style.height = `${(7 * size).toFixed(1)}px`;
      host.appendChild(el);
      bats.push({
        el,
        x: rand(0, 100),
        y: rand(8, 52),
        vx: (Math.random() < 0.5 ? -1 : 1) * rand(0.25, 0.7),
        turn: rand(800, 3200),
        size,
      });
    }
    const frag2 = document.createDocumentFragment();
    frag2.appendChild(frag);

    let raf = 0;
    let last = 0;
    const step = (time) => {
      raf = window.requestAnimationFrame(step);
      const dt = Math.min(48, time - (last || time));
      last = time;
      for (const b of bats) {
        b.turn -= dt;
        if (b.turn <= 0) {
          b.turn = rand(900, 3400);
          if (Math.random() < 0.35) b.vx = -b.vx;
          b.y = Math.max(6, Math.min(54, b.y + rand(-16, 16)));
        }
        b.x += b.vx * (dt / 16);
        if (b.x > 104) { b.x = 104; b.vx = -Math.abs(b.vx); }
        if (b.x < -4) { b.x = -4; b.vx = Math.abs(b.vx); }
        b.el.style.left = `${b.x}%`;
        b.el.style.top = `${b.y}%`;
        // Face the direction of travel.
        b.el.style.transform = `scaleX(${b.vx < 0 ? -1 : 1})`;
      }
    };
    raf = window.requestAnimationFrame(step);
  }

  function init() {
    const body = document.body;
    seedStars($('stars'), MAX);
    seedTrees($('trees'), 16);
    seedGrass($('grass'), 74);
    seedFlowers($('flowers'), 20);
    seedRain($('rain'), 80);
    seedFireflies($('fireflies'), 18);
    startDrift($('drift'));
    startBats($('bats'));

    let index = 0;
    let manual = false;
    const apply = () => {
      // Once the user picks a sky with the sun or the moon, that choice is
      // theirs and the automatic cycle stops overriding it. Without this the
      // timer quietly drifts the scene back and the toggle looks broken.
      if (manual) return;
      const next = SEQUENCE[index % SEQUENCE.length];
      // Stepping back to daylight after a night stretch: pick a daytime state
      // rather than dropping straight into another night.
      body.dataset.weather = next === 'night' ? 'day' : next;
      index += 1;
    };
    apply();

    // The user asked for variation without rapid change, so the swap is rare
    // and the CSS transition does the cross-fade.
    window.setInterval(apply, HOLD_MS);

    /** Called when the sun or moon is clicked: stop the cycle, take over. */
    const lock = () => {
      manual = true;
    };
    /** Hand control back to the ambient cycle. */
    const unlock = () => {
      manual = false;
    };

    window.ClipifyWeather = { init, lock, unlock };
  }

  function $(id) {
    return document.getElementById(id);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
