'use strict';

/**
 * "Clipify Runner" - the waiting game.
 *
 * An original endless-runner built for this installer. It borrows the genre idea
 * of the classic offline dinosaur game (jump over things, speed ramps up, score
 * climbs) but every visual is drawn procedurally here: a small round mascot,
 * rounded bushes, simple rocks and birds. No third-party artwork, no sprites.
 *
 * It is intentionally cheap: one canvas, one requestAnimationFrame loop, and
 * roughly a dozen shape draws per frame. It pauses when the window is not
 * focused so it never competes with a download that is trying to saturate the
 * network or disk.
 */

(function () {
  const GRAVITY = 0.62;
  const JUMP = -11.4;
  const MAX_JUMPS = 2;
  const GROUND = 148;
  const W = 520;
  const H = 180;
  const BEST_KEY = 'clipify.runner.best';

  function bestScore() {
    try {
      return Number(localStorage.getItem(BEST_KEY) || 0) || 0;
    } catch {
      return 0;
    }
  }

  function setBest(value) {
    try {
      localStorage.setItem(BEST_KEY, String(value));
    } catch {
      /* storage may be unavailable; the score still shows for this session */
    }
  }

  class Runner {
    constructor(canvas, scoreEl, bestEl) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.scoreEl = scoreEl;
      this.bestEl = bestEl;
      this.dpr = Math.min(2, window.devicePixelRatio || 1);

      this.paused = false;
      this.running = false;
      this.raf = 0;
      this.last = 0;
      this.onJump = null;

      this.reset();
      this.bindInput();
      this.resize();
      window.addEventListener('resize', () => this.resize(), { passive: true });
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width) return;
      this.cssW = rect.width;
      this.scale = rect.width / W;
      this.canvas.width = Math.round(rect.width * this.dpr);
      this.canvas.height = Math.round(H * this.scale * this.dpr);
      this.ctx.setTransform(
        this.dpr * this.scale, 0, 0, this.dpr * this.scale, 0, 0
      );
    }

    reset() {
      this.player = { x: 84, y: GROUND - 34, w: 34, h: 34, vy: 0, grounded: true, jumpsUsed: 0, legs: 0 };
      this.obstacles = [];
      this.clouds = [];
      this.shrubs = [];
      this.score = 0;
      this.speed = 3.1;
      this.spawnIn = this.speed * 70;
      this.night = false;

      for (let i = 0; i < 3; i += 1) {
        this.clouds.push({ x: Math.random() * W, y: 16 + Math.random() * 34, s: 0.6 + Math.random() * 0.7 });
      }
      for (let i = 0; i < 7; i += 1) {
        this.shrubs.push({ x: Math.random() * W, s: 0.7 + Math.random() * 0.6 });
      }
      this.render();
      this.paintScore();
    }

    bindInput() {
      const jump = (event) => {
        if (event) {
          const tag = (event.target && event.target.tagName) || '';
          if (tag === 'INPUT' || tag === 'BUTTON') return;
          if (event.type === 'keydown' && event.key !== ' ' && event.key !== 'ArrowUp' && event.key !== 'Spacebar') return;
          if (event.type === 'keydown' && event.repeat) return;
          if (event.preventDefault) event.preventDefault();
        }
        this.doJump();
      };
      window.addEventListener('keydown', jump);
      this.canvas.addEventListener('pointerdown', jump);
    }

    doJump() {
      if (!this.running) this.start();
      if (this.player.jumpsUsed < MAX_JUMPS) {
        this.player.vy = JUMP;
        this.player.grounded = false;
        this.player.jumpsUsed += 1;
      }
    }

    start() {
      if (this.running) return;
      this.running = true;
      this.last = 0;
      this.raf = window.requestAnimationFrame((t) => this.frame(t));
    }

    setPaused(value) {
      this.paused = value;
    }

    stop() {
      this.running = false;
      if (this.raf) window.cancelAnimationFrame(this.raf);
      this.raf = 0;
    }

    paintScore() {
      const best = bestScore();
      this.scoreEl.textContent = String(Math.floor(this.score)).padStart(6, '0');
      this.bestEl.textContent = String(best).padStart(6, '0');
    }

    frame(time) {
      if (!this.running) return;
      this.raf = window.requestAnimationFrame((t) => this.frame(t));
      const dt = Math.min(32, time - (this.last || time));
      this.last = time;
      if (this.paused) {
        this.draw();
        return;
      }
      this.update(dt);
      this.draw();
    }

    update(dt) {
      const step = dt / 16.67;
      const p = this.player;

      p.vy += GRAVITY * step;
      p.y += p.vy * step;
      if (p.y + p.h >= GROUND) {
        p.y = GROUND - p.h;
        p.vy = 0;
        p.grounded = true;
        p.jumpsUsed = 0;
      }
      p.legs += step * (p.grounded ? Math.abs(this.speed) * 0.42 : 2);

      this.speed = Math.min(8.6, 3.1 + this.score / 2600);
      this.score += this.speed * 0.34 * step;

      this.spawnIn -= this.speed * step;
      if (this.spawnIn <= 0) this.spawnObstacle();

      for (let i = 0; i < this.obstacles.length; i += 1) {
        const o = this.obstacles[i];
        o.x -= this.speed * step;
        if (o.kind === 'bush') { o.w = 30; o.h = 28; o.y = GROUND - o.h; }
        else if (o.kind === 'rock') { o.w = 24; o.h = 20; o.y = GROUND - o.h; }
        else { o.w = o.w || 26; o.h = o.h || 16; }
        if (o.x + o.w < -40) this.obstacles.splice(i--, 1);
        else if (!this.dead && this.hits(p, o)) this.die();
      }

      for (const c of this.clouds) {
        c.x -= (0.12 + this.speed * 0.014) * step;
        if (c.x < -80) { c.x = W + 40; c.y = 16 + Math.random() * 34; }
      }
      for (const s of this.shrubs) {
        s.x -= (0.5 + this.speed * 0.06) * step;
        if (s.x < -50) s.x = W + Math.random() * 200;
      }

      if (Math.floor(this.score) % 5 === 0) this.paintScore();
    }

    spawnObstacle() {
      const roll = Math.random();
      const kind = roll < 0.22 ? 'bee' : roll < 0.40 ? 'rock' : 'bush';
      this.obstacles.push({
        x: W + 20,
        kind,
        w: kind === 'bee' ? 26 : 0,
        h: kind === 'bee' ? 16 : 0,
        y: kind === 'bee' ? GROUND - 62 : 0,
        fly: kind === 'bee',
      });
      // Gaps are measured in world distance. Scale them with speed to preserve
      // at least 64 frames for reacting and landing, even late in a run.
      const gapFrames = 64 + Math.random() * 28;
      this.spawnIn = this.speed * gapFrames;
    }

    hits(p, o) {
      const px = p.x + 5;
      const pw = p.w - 10;
      const py = p.y + 5;
      const ph = p.h - 8;
      return px < o.x + o.w - 4 && px + pw > o.x + 4 && py < o.y + o.h - 2 && py + ph > o.y + 2;
    }

    die() {
      this.dead = true;
      const score = Math.floor(this.score);
      if (score > bestScore()) setBest(score);
      this.paintScore();
      window.setTimeout(() => {
        this.dead = false;
        this.reset();
      }, 900);
    }

    // ------------------------------------------------------------ drawing

    draw() {
      const ctx = this.ctx;
      this.night = document.body && document.body.dataset.weather === 'night';
      const night = this.night;

      const sky = ctx.createLinearGradient(0, 0, 0, H);
      if (night) {
        sky.addColorStop(0, '#22314a');
        sky.addColorStop(0.62, '#2c3f4d');
        sky.addColorStop(1, '#26402f');
      } else {
        sky.addColorStop(0, '#cfe9f4');
        sky.addColorStop(0.62, '#e8f3e2');
        sky.addColorStop(1, '#bcd9a8');
      }
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, W, H);

      this.drawClouds(night);
      this.drawHills(night);
      this.drawGround(night);
      for (const s of this.shrubs) this.drawShrub(s.x, s.s, night);
      for (const o of this.obstacles) this.drawObstacle(o, night);
      this.drawPlayer(night);

      if (this.paused) {
        ctx.fillStyle = 'rgba(20,24,30,0.34)';
        ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = '#fff';
        ctx.font = '600 15px "Segoe UI", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Paused', W / 2, H / 2 + 5);
      }
    }

    drawClouds(night) {
      const ctx = this.ctx;
      ctx.fillStyle = night ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.82)';
      for (const c of this.clouds) {
        const r = 15 * c.s;
        ctx.beginPath();
        ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
        ctx.arc(c.x + r * 0.9, c.y + 3, r * 0.72, 0, Math.PI * 2);
        ctx.arc(c.x - r * 0.85, c.y + 4, r * 0.62, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    drawHills(night) {
      const ctx = this.ctx;
      ctx.fillStyle = night ? '#24333f' : '#9dc4ab';
      ctx.beginPath();
      ctx.ellipse(W * 0.22, GROUND + 6, 168, 74, 0, Math.PI, 0);
      ctx.fill();
      ctx.fillStyle = night ? '#1e2b33' : '#7fae7a';
      ctx.beginPath();
      ctx.ellipse(W * 0.78, GROUND + 8, 150, 58, 0, Math.PI, 0);
      ctx.fill();
    }

    drawGround(night) {
      const ctx = this.ctx;
      ctx.fillStyle = night ? '#2c4438' : '#6f9c5f';
      ctx.fillRect(0, GROUND, W, H - GROUND);
      ctx.fillStyle = night ? 'rgba(255,255,255,0.07)' : 'rgba(255,255,255,0.2)';
      ctx.fillRect(0, GROUND, W, 3);

      ctx.strokeStyle = night ? 'rgba(255,255,255,0.13)' : 'rgba(40,70,35,0.22)';
      ctx.lineWidth = 1;
      const offset = -(this.speed * 2) % 22;
      for (let x = offset; x < W; x += 22) {
        ctx.beginPath();
        ctx.moveTo(x, GROUND + 9);
        ctx.lineTo(x + 6, GROUND + 4);
        ctx.stroke();
      }
    }

    drawShrub(x, s, night) {
      const ctx = this.ctx;
      const r = 15 * s;
      ctx.fillStyle = night ? 'rgba(70,110,80,0.75)' : 'rgba(88,138,74,0.85)';
      ctx.beginPath();
      ctx.arc(x, GROUND - r * 0.5, r, 0, Math.PI * 2);
      ctx.arc(x - r * 0.8, GROUND - r * 0.25, r * 0.7, 0, Math.PI * 2);
      ctx.arc(x + r * 0.8, GROUND - r * 0.25, r * 0.66, 0, Math.PI * 2);
      ctx.fill();
    }

    drawObstacle(o, night) {
      const ctx = this.ctx;
      if (o.kind === 'bush') {
        ctx.fillStyle = night ? 'rgba(52,88,62,0.95)' : '#4f7f42';
        ctx.beginPath();
        ctx.arc(o.x + 12, GROUND - 12, 12, 0, Math.PI * 2);
        ctx.arc(o.x + 24, GROUND - 14, 14, 0, Math.PI * 2);
        ctx.arc(o.x + 6, GROUND - 6, 9, 0, Math.PI * 2);
        ctx.fill();
      } else if (o.kind === 'rock') {
        ctx.fillStyle = night ? '#4a5560' : '#9aa3ab';
        ctx.beginPath();
        ctx.moveTo(o.x, GROUND);
        ctx.lineTo(o.x + 7, o.y + 3);
        ctx.lineTo(o.x + 17, o.y);
        ctx.lineTo(o.x + 24, GROUND);
        ctx.closePath();
        ctx.fill();
      } else {
        const flap = Math.sin(this.player.legs * 1.6) * 2;
        ctx.fillStyle = night ? 'rgba(248, 224, 156, 0.92)' : '#f2c14e';
        ctx.beginPath();
        ctx.ellipse(o.x + 13, o.y + 9, 10, 6, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = night ? 'rgba(235,240,246,0.8)' : 'rgba(255,255,255,0.9)';
        ctx.beginPath();
        ctx.ellipse(o.x + 9, o.y + 2 - flap, 5, 3, -0.25, 0, Math.PI * 2);
        ctx.ellipse(o.x + 17, o.y + 2 + flap, 5, 3, 0.25, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = night ? '#43505d' : '#6a4b16';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(o.x + 11, o.y + 4);
        ctx.lineTo(o.x + 11, o.y + 14);
        ctx.moveTo(o.x + 17, o.y + 4);
        ctx.lineTo(o.x + 17, o.y + 14);
        ctx.stroke();
      }
    }

    /** The Clipify mascot: a rounded creature with a leaf crest, drawn in code. */
    drawPlayer(night) {
      const ctx = this.ctx;
      const p = this.player;
      const bob = p.grounded ? Math.sin(p.legs * 2) * 1.3 : 0;
      const cx = p.x + p.w / 2;
      const cy = p.y + p.h / 2 + bob;
      // How far the feet are below the body. On the ground this reaches the
      // grass; in the air the legs tuck up so they are NOT stretched down to
      // the floor (which previously pinned the mascot to the ground while it
      // was clearly airborne).
      const gap = GROUND - (p.y + p.h);
      const grounded = p.grounded && gap < 2;

      ctx.save();
      // body
      const body = ctx.createLinearGradient(0, p.y, 0, p.y + p.h);
      body.addColorStop(0, night ? '#f0a17f' : '#f6a882');
      body.addColorStop(1, night ? '#c9704f' : '#dd8460');
      ctx.fillStyle = body;
      ctx.beginPath();
      ctx.ellipse(cx, cy, 15, 14, 0, 0, Math.PI * 2);
      ctx.fill();

      // leaf crest - the Clipify mark
      ctx.fillStyle = night ? '#7fb894' : '#6ea497';
      ctx.beginPath();
      ctx.moveTo(cx - 1, p.y + 1);
      ctx.quadraticCurveTo(cx + 8, p.y - 9, cx + 13, p.y + 1);
      ctx.quadraticCurveTo(cx + 5, p.y + 4, cx - 1, p.y + 1);
      ctx.fill();

      // eyes
      ctx.fillStyle = '#2b1d16';
      ctx.beginPath();
      ctx.arc(cx - 5, cy - 2, 2.5, 0, Math.PI * 2);
      ctx.arc(cx + 5, cy - 2, 2.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#fff';
      ctx.beginPath();
      ctx.arc(cx - 5.8, cy - 2.9, 0.9, 0, Math.PI * 2);
      ctx.arc(cx + 4.2, cy - 2.9, 0.9, 0, Math.PI * 2);
      ctx.fill();

      // feet
      ctx.strokeStyle = '#b4623f';
      ctx.lineWidth = 2.4;
      ctx.lineCap = 'round';
      const hipY = p.y + p.h - 2;
      if (grounded) {
        // Alternating stride, landing exactly on the grass line.
        const stride = Math.sin(p.legs * 2) * 5;
        ctx.beginPath();
        ctx.moveTo(cx - 4, hipY);
        ctx.lineTo(cx - 4 - stride, GROUND);
        ctx.moveTo(cx + 4, hipY);
        ctx.lineTo(cx + 4 + stride, GROUND);
        ctx.stroke();
      } else {
        // Tucked: short legs bent under the body, never reaching the ground.
        const tuck = Math.min(9, 3 + Math.max(0, -p.vy) * 0.7);
        ctx.beginPath();
        ctx.moveTo(cx - 4, hipY);
        ctx.lineTo(cx - 6, hipY + tuck);
        ctx.moveTo(cx + 4, hipY);
        ctx.lineTo(cx + 6, hipY + tuck * 0.8);
        ctx.stroke();
      }
      ctx.restore();
    }

    render() {
      this.draw();
    }
  }

  window.ClipifyRunner = { Runner };
})();
