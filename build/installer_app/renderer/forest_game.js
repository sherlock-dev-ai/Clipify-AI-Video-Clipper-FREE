'use strict';

// Compact woodland runner. It owns one RAF loop only while visible and playing;
// the installer engine has no dependency on this optional activity.
(function () {
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const randomBetween = (low, high) => low + Math.random() * (high - low);

  class Game {
    constructor(canvas, scoreElement, bestElement, statusElement, onStateChange) {
      this.canvas = canvas;
      this.context = canvas.getContext('2d', { alpha: false });
      this.scoreElement = scoreElement;
      this.bestElement = bestElement;
      this.statusElement = statusElement;
      this.onStateChange = onStateChange || (() => {});
      this.state = 'ready';
      this.visible = false;
      this.frameId = 0;
      this.lastFrameAt = 0;
      this.elapsed = 0;
      this.distance = 0;
      this.score = 0;
      this.speed = 290;
      this.spawnIn = 1.25;
      this.obstacles = [];
      this.randomSeed = 91823;
      this.lastObstacle = '';
      this.backgroundOffset = 0;
      this.keys = new Set();
      this.player = { x: 96, bottom: 0, velocityY: 0, grounded: true, runPhase: 0 };
      try { this.best = Math.max(0, Number(localStorage.getItem('clipify.runner.best')) || 0); }
      catch { this.best = 0; }
      this.bestElement.textContent = String(this.best);
      this.scoreElement.textContent = '0';

      this.onKeyDown = (event) => this.handleKeyDown(event);
      this.onKeyUp = (event) => this.handleKeyUp(event);
      this.onBlur = () => this.keys.clear();
      this.onResize = () => { this.resize(); this.draw(); };
      this.onPointer = () => {
        this.canvas.focus({ preventScroll: true });
        if (this.state === 'playing') this.jump();
      };
      this.bound = false;
      this.resize();
      this.draw();
      this.setState('ready');
    }

    setState(state) {
      this.state = state;
      const text = {
        ready: 'Ready. Press Continue or Space to begin.',
        playing: 'Running — jump with Space or ↑. Avoid the forest hazards.',
        paused: 'Paused. Press Continue when ready.',
        gameover: 'Run over. Press Continue or Space to go again.',
      }[state];
      if (this.statusElement) {
        this.statusElement.textContent = text;
        this.statusElement.dataset.gameState = state;
      }
      this.onStateChange(state);
      this.draw();
    }

    setVisible(value) {
      const visible = Boolean(value);
      if (this.visible === visible) return;
      this.visible = visible;
      if (visible) {
        this.bind();
        this.resize();
        this.draw();
      } else {
        this.unbind();
        this.stopFrame();
        this.keys.clear();
        if (this.state === 'playing') this.setState('paused');
      }
    }

    bind() {
      if (this.bound) return;
      this.bound = true;
      this.canvas.addEventListener('keydown', this.onKeyDown);
      this.canvas.addEventListener('keyup', this.onKeyUp);
      this.canvas.addEventListener('blur', this.onBlur);
      this.canvas.addEventListener('pointerdown', this.onPointer);
      window.addEventListener('resize', this.onResize, { passive: true });
      window.addEventListener('blur', this.onBlur);
    }

    unbind() {
      if (!this.bound) return;
      this.bound = false;
      this.canvas.removeEventListener('keydown', this.onKeyDown);
      this.canvas.removeEventListener('keyup', this.onKeyUp);
      this.canvas.removeEventListener('blur', this.onBlur);
      this.canvas.removeEventListener('pointerdown', this.onPointer);
      window.removeEventListener('resize', this.onResize);
      window.removeEventListener('blur', this.onBlur);
    }

    handleKeyDown(event) {
      if (!this.visible || document.activeElement !== this.canvas) return;
      const key = event.key.toLowerCase();
      if (![' ', 'spacebar', 'arrowup'].includes(key)) return;
      event.preventDefault();
      if (event.repeat) return;
      if (this.state === 'ready') this.start();
      else if (this.state === 'gameover') this.restart();
      else if (this.state === 'paused') this.resume();
      else this.jump();
      this.keys.add(key);
    }

    handleKeyUp(event) {
      this.keys.delete(event.key.toLowerCase());
    }

    resize() {
      if (!this.canvas || !this.context) return;
      const rect = this.canvas.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width || 780));
      const height = Math.max(1, Math.round(rect.height || 250));
      const ratio = clamp(window.devicePixelRatio || 1, 1, 2);
      if (this.canvas.width !== Math.round(width * ratio) || this.canvas.height !== Math.round(height * ratio)) {
        this.canvas.width = Math.round(width * ratio);
        this.canvas.height = Math.round(height * ratio);
      }
      this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
      this.width = width;
      this.height = height;
      this.groundY = height - 44;
      if (this.player.grounded || this.player.bottom === 0) this.player.bottom = this.groundY;
    }

    start() {
      if (this.state === 'gameover') return this.restart();
      if (this.state === 'paused') return this.resume();
      if (this.state !== 'ready') return;
      this.elapsed = 0;
      this.distance = 0;
      this.score = 0;
      this.speed = 290;
      this.spawnIn = 1.15;
      this.obstacles = [];
      this.backgroundOffset = 0;
      this.player.bottom = this.groundY;
      this.player.velocityY = 0;
      this.player.grounded = true;
      this.player.runPhase = 0;
      this.scoreElement.textContent = '0';
      this.setState('playing');
      this.canvas.focus({ preventScroll: true });
      this.scheduleFrame();
    }

    restart() {
      this.stopFrame();
      this.setState('ready');
      this.start();
    }

    pause() {
      if (this.state !== 'playing') return;
      this.stopFrame();
      this.keys.clear();
      this.setState('paused');
    }

    resume() {
      if (this.state !== 'paused') return;
      this.setState('playing');
      this.lastFrameAt = 0;
      this.scheduleFrame();
      this.canvas.focus({ preventScroll: true });
    }

    setPaused(value) {
      if (value) this.pause();
      else if (this.state === 'paused') this.resume();
    }

    stop() {
      this.stopFrame();
      this.keys.clear();
      if (this.state === 'playing') this.setState('paused');
    }

    destroy() {
      this.stopFrame();
      this.unbind();
      this.keys.clear();
    }

    stopFrame() {
      if (this.frameId) cancelAnimationFrame(this.frameId);
      this.frameId = 0;
      this.lastFrameAt = 0;
    }

    scheduleFrame() {
      if (!this.visible || this.state !== 'playing' || this.frameId) return;
      this.frameId = requestAnimationFrame((time) => this.tick(time));
    }

    jump() {
      if (!this.visible || this.state !== 'playing' || !this.player.grounded) return false;
      this.player.velocityY = -650;
      this.player.grounded = false;
      return true;
    }

    rand() {
      this.randomSeed = (this.randomSeed * 1664525 + 1013904223) >>> 0;
      return this.randomSeed / 4294967296;
    }

    spawnObstacle() {
      const types = ['log', 'roots', 'rocks', 'thorns', 'branch', 'trap'];
      let available = types.filter((type) => type !== this.lastObstacle);
      if (this.elapsed < 8) available = available.filter((type) => !['branch', 'trap'].includes(type));
      const type = available[Math.floor(this.rand() * available.length)] || 'log';
      const obstacle = { type, x: this.width + 36, age: 0, falling: false, landed: false };
      if (type === 'log') Object.assign(obstacle, { width: 54 + this.rand() * 38, height: 22 + this.rand() * 7 });
      if (type === 'roots') Object.assign(obstacle, { width: 58 + this.rand() * 26, height: 12 + this.rand() * 7 });
      if (type === 'rocks') Object.assign(obstacle, { width: 42 + this.rand() * 30, height: 25 + this.rand() * 19 });
      if (type === 'thorns') Object.assign(obstacle, { width: 58 + this.rand() * 26, height: 37 + this.rand() * 8 });
      if (type === 'branch') Object.assign(obstacle, { width: 74 + this.rand() * 24, height: 28, fallY: -88, warning: false });
      if (type === 'trap') Object.assign(obstacle, { width: 72 + this.rand() * 26, height: 24 });
      if (type === 'trap' && this.elapsed < 14) obstacle.type = 'log';
      this.obstacles.push(obstacle);
      this.lastObstacle = obstacle.type;
      // Spacing is measured in pixels and scales with speed, so each hazard
      // leaves at least 1.35 seconds of reaction time at the current pace.
      const gap = Math.max(420, this.speed * 1.35) + this.rand() * 170;
      this.spawnIn = gap / this.speed;
    }

    tick(timestamp) {
      this.frameId = 0;
      if (!this.visible || this.state !== 'playing') return;
      const delta = this.lastFrameAt ? clamp((timestamp - this.lastFrameAt) / 1000, 0, 0.05) : 1 / 60;
      this.lastFrameAt = timestamp;
      this.update(delta);
      this.draw();
      this.scheduleFrame();
    }

    update(delta) {
      this.elapsed += delta;
      this.speed = Math.min(475, 290 + Math.floor(this.elapsed / 20) * 18);
      this.backgroundOffset += this.speed * delta;
      this.distance += this.speed * delta;
      this.player.runPhase += delta * (this.speed / 25);
      this.player.velocityY += 1750 * delta;
      this.player.bottom += this.player.velocityY * delta;
      if (this.player.bottom >= this.groundY) {
        this.player.bottom = this.groundY;
        this.player.velocityY = 0;
        this.player.grounded = true;
      }

      this.spawnIn -= delta;
      if (this.spawnIn <= 0) this.spawnObstacle();
      for (const obstacle of this.obstacles) {
        obstacle.x -= this.speed * delta;
        obstacle.age += delta;
        if (obstacle.type === 'branch' && !obstacle.landed) {
          const warnAt = this.player.x + this.speed * 0.92;
          if (!obstacle.warning && obstacle.x <= warnAt) {
            obstacle.warning = true;
            obstacle.warnTime = 0;
          }
          if (obstacle.warning && !obstacle.falling) {
            obstacle.warnTime += delta;
            if (obstacle.warnTime >= 0.58) obstacle.falling = true;
          }
          if (obstacle.falling) {
            obstacle.fallY += 690 * delta;
            if (obstacle.fallY >= this.groundY - 30) {
              obstacle.fallY = this.groundY - 30;
              obstacle.landed = true;
            }
          }
        }
      }
      this.obstacles = this.obstacles.filter((obstacle) => obstacle.x + obstacle.width > -40);
      if (this.hasCollision()) {
        this.endRun();
        return;
      }
      this.score = Math.floor(this.distance / 13);
      this.scoreElement.textContent = String(this.score);
      if (this.score > this.best) {
        this.best = this.score;
        this.bestElement.textContent = String(this.best);
        try { localStorage.setItem('clipify.runner.best', String(this.best)); } catch { /* optional storage */ }
      }
    }

    hasCollision() {
      const playerLeft = this.player.x + 10;
      const playerRight = this.player.x + 42;
      const playerTop = this.player.bottom - 55;
      const playerFeet = this.player.bottom - 4;
      for (const obstacle of this.obstacles) {
        const obstacleLeft = obstacle.type === 'branch' && !obstacle.landed ? obstacle.x + 8 : obstacle.x;
        const obstacleRight = obstacle.x + obstacle.width - 5;
        if (playerRight <= obstacleLeft || playerLeft >= obstacleRight) continue;
        if (obstacle.type === 'trap') {
          if (this.player.grounded || playerFeet >= this.groundY - 12) return true;
          continue;
        }
        let obstacleTop = this.groundY - obstacle.height;
        if (obstacle.type === 'branch' && !obstacle.landed) {
          if (!obstacle.falling) continue;
          obstacleTop = obstacle.fallY;
        }
        if (playerFeet > obstacleTop + 5 && playerTop < this.groundY) return true;
      }
      return false;
    }

    endRun() {
      this.stopFrame();
      this.keys.clear();
      this.setState('gameover');
    }

    draw() {
      if (!this.context) return;
      // resize() is called here only when triggered by the window resize
      // event handler (this.onResize). Calling getBoundingClientRect() every
      // animation frame forces a layout reflow and allows the canvas transform
      // to reset mid-frame when installer log updates change the DOM layout,
      // causing the visible tree-glitch. The dimensions are set once on mount
      // and again on resize — not on every draw call.
      const ctx = this.context;
      const width = this.width;
      const height = this.height;
      const ground = this.groundY;
      const night = document.body.dataset.theme === 'night';
      const sky = ctx.createLinearGradient(0, 0, 0, height);
      sky.addColorStop(0, night ? '#101e2d' : '#7a9d9a');
      sky.addColorStop(0.63, night ? '#1b3540' : '#b7c8a4');
      sky.addColorStop(1, night ? '#23382e' : '#849471');
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, width, height);

      // Soft canopy and layered tree lines.
      const sunX = width * 0.77;
      const sunY = height * 0.22;
      const sun = ctx.createRadialGradient(sunX, sunY, 2, sunX, sunY, height * 0.34);
      sun.addColorStop(0, night ? 'rgba(219,231,223,.36)' : 'rgba(251,222,161,.48)');
      sun.addColorStop(1, 'rgba(251,222,161,0)');
      ctx.fillStyle = sun;
      ctx.fillRect(sunX - height * .34, 0, height * .68, height * .72);

      for (let layer = 0; layer < 3; layer += 1) {
        const factor = [0.12, 0.28, 0.52][layer];
        const spacing = [88, 112, 144][layer];
        const drift = (this.backgroundOffset * factor) % spacing;
        for (let index = -1; index < width / spacing + 2; index += 1) {
          const x = index * spacing - drift + (layer * 21);
          const treeHeight = height * ([0.38, 0.53, 0.68][layer]) * (0.86 + ((index * 13 + layer * 7) % 9) / 42);
          this.drawTree(ctx, x, ground - [48, 15, -5][layer], treeHeight, [0.50, 0.72, 1][layer], layer, index);
        }
      }

      // Soil bank and the pale path leading through the trees.
      ctx.fillStyle = night ? '#17281e' : '#49533e';
      ctx.fillRect(0, ground - 15, width, height - ground + 15);
      ctx.fillStyle = night ? '#645c45' : '#a18c66';
      ctx.beginPath();
      ctx.moveTo(0, ground + 4);
      ctx.lineTo(width, ground + 4);
      ctx.lineTo(width, height);
      ctx.lineTo(0, height);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = night ? 'rgba(221,207,162,.12)' : 'rgba(243,225,181,.25)';
      for (let i = 0; i < 19; i += 1) {
        const x = ((i * 97 - this.backgroundOffset * 0.9) % (width + 30) + width + 30) % (width + 30) - 15;
        const y = ground + 10 + ((i * 19) % Math.max(12, height - ground - 12));
        ctx.beginPath(); ctx.ellipse(x, y, 3 + (i % 3), 1.2, -0.15, 0, Math.PI * 2); ctx.fill();
      }
      ctx.fillStyle = night ? '#405f43' : '#70815a';
      ctx.fillRect(0, ground - 13, width, 3);
      for (let i = 0; i < width / 14 + 2; i += 1) {
        const x = ((i * 14 - this.backgroundOffset) % (width + 18) + width + 18) % (width + 18) - 9;
        ctx.strokeStyle = i % 2 ? '#52724b' : '#849565';
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x, ground - 12); ctx.quadraticCurveTo(x - 3, ground - 21 - (i % 4), x + 1, ground - 25 - (i % 4)); ctx.stroke();
      }

      for (const obstacle of this.obstacles) this.drawObstacle(ctx, obstacle);
      this.drawFirefly(ctx);
    }

    drawTree(ctx, x, base, height, scale, layer, index) {
      const night = document.body.dataset.theme === 'night';
      const trunkWidth = Math.max(3, height * 0.085);
      const trunk = ['#314a3d', '#293e31', '#1e3228'][layer];
      ctx.save();
      ctx.globalAlpha = [0.36, 0.60, 0.82][layer];
      ctx.fillStyle = night ? '#12261f' : trunk;
      ctx.beginPath();
      ctx.moveTo(x - trunkWidth / 2, base);
      ctx.quadraticCurveTo(x - trunkWidth * .25, base - height * .48, x - trunkWidth * .12, base - height);
      ctx.lineTo(x + trunkWidth * .25, base - height);
      ctx.quadraticCurveTo(x + trunkWidth * .18, base - height * .38, x + trunkWidth * .62, base);
      ctx.closePath(); ctx.fill();
      ctx.lineWidth = Math.max(1, trunkWidth * .42);
      ctx.strokeStyle = night ? '#1b352b' : '#49604a';
      for (let branch = 0; branch < 3; branch += 1) {
        const by = base - height * (.54 + branch * .11);
        ctx.beginPath(); ctx.moveTo(x, by); ctx.quadraticCurveTo(x + (branch % 2 ? -1 : 1) * height * .15, by - height * .09, x + (branch % 2 ? -1 : 1) * height * .25, by - height * .23); ctx.stroke();
      }
      const canopyColors = night ? ['#142d25', '#1b3b2e', '#244536'] : ['#2d5140', '#3e6549', '#56734d'];
      const canopyY = base - height * .83;
      for (let blob = 0; blob < 8; blob += 1) {
        const seed = Math.abs((index + 4) * 17 + blob * 11 + layer * 29);
        const bx = x + Math.sin(seed * 2.13) * height * .25;
        const by = canopyY + Math.cos(seed * 1.37) * height * .16;
        const rx = height * (.13 + (seed % 4) * .018);
        const ry = height * (.11 + (seed % 3) * .022);
        ctx.fillStyle = canopyColors[seed % canopyColors.length];
        ctx.beginPath(); ctx.ellipse(bx, by, rx, ry, Math.sin(seed) * .15, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = night ? 'rgba(147,180,150,.10)' : 'rgba(190,208,145,.16)';
        ctx.beginPath(); ctx.ellipse(bx - rx * .18, by - ry * .2, rx * .5, ry * .24, -.2, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
    }

    drawObstacle(ctx, obstacle) {
      const ground = this.groundY;
      const x = obstacle.x;
      if (obstacle.type === 'trap') {
        ctx.fillStyle = '#182019';
        ctx.beginPath(); ctx.ellipse(x + obstacle.width / 2, ground - 2, obstacle.width / 2, 11, 0, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = '#c3a56d'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.ellipse(x + obstacle.width / 2, ground - 2, obstacle.width / 2, 8, 0, Math.PI, Math.PI * 2); ctx.stroke();
        return;
      }
      if (obstacle.type === 'log' || obstacle.type === 'branch') {
        let top = ground - obstacle.height;
        if (obstacle.type === 'branch') {
          if (obstacle.warning && !obstacle.falling) {
            ctx.strokeStyle = 'rgba(238,190,115,.75)'; ctx.lineWidth = 2;
            ctx.setLineDash([5, 4]); ctx.beginPath(); ctx.moveTo(x + obstacle.width / 2, ground - 3); ctx.lineTo(x + obstacle.width / 2, ground - 70); ctx.stroke(); ctx.setLineDash([]);
            ctx.fillStyle = '#e8bf78'; ctx.beginPath(); ctx.moveTo(x + obstacle.width / 2, ground - 78); ctx.lineTo(x + obstacle.width / 2 - 6, ground - 68); ctx.lineTo(x + obstacle.width / 2 + 6, ground - 68); ctx.closePath(); ctx.fill();
          }
          if (!obstacle.landed) top = obstacle.fallY;
        }
        ctx.fillStyle = obstacle.type === 'branch' ? '#674e37' : '#694c35';
        ctx.beginPath(); ctx.roundRect(x, top, obstacle.width, obstacle.height, obstacle.height / 2); ctx.fill();
        ctx.strokeStyle = '#a78458'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.ellipse(x + obstacle.width - 8, top + obstacle.height / 2, 5, obstacle.height / 2 - 3, 0, 0, Math.PI * 2); ctx.stroke();
        ctx.strokeStyle = 'rgba(225,197,143,.4)'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(x + obstacle.width * .34, top + 3); ctx.lineTo(x + obstacle.width * .39, top + obstacle.height - 3); ctx.stroke();
        return;
      }
      if (obstacle.type === 'roots') {
        ctx.strokeStyle = '#725b3c'; ctx.lineWidth = obstacle.height; ctx.lineCap = 'round';
        ctx.beginPath(); ctx.moveTo(x, ground - 5); ctx.bezierCurveTo(x + 18, ground - obstacle.height, x + obstacle.width * .55, ground - obstacle.height * .6, x + obstacle.width, ground - 4); ctx.stroke();
        ctx.strokeStyle = '#ac9362'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x + 5, ground - 12); ctx.quadraticCurveTo(x + obstacle.width / 2, ground - obstacle.height, x + obstacle.width - 3, ground - 10); ctx.stroke();
        return;
      }
      if (obstacle.type === 'rocks') {
        for (let i = 0; i < 3; i += 1) {
          const rx = x + 8 + i * (obstacle.width / 3);
          const rh = obstacle.height * (.55 + (i % 2) * .3);
          ctx.fillStyle = ['#667066', '#7c8172', '#555f56'][i];
          ctx.beginPath(); ctx.ellipse(rx + 11, ground - rh / 2, 12 + i * 2, rh / 2, -.18 + i * .12, 0, Math.PI * 2); ctx.fill();
          ctx.fillStyle = 'rgba(231,231,205,.22)'; ctx.beginPath(); ctx.ellipse(rx + 8, ground - rh + 5, 5, 2, -.25, 0, Math.PI * 2); ctx.fill();
        }
        return;
      }
      if (obstacle.type === 'thorns') {
        for (let i = 0; i < 5; i += 1) {
          const tx = x + i * (obstacle.width / 5) + 6;
          ctx.fillStyle = i % 2 ? '#34543b' : '#426442';
          ctx.beginPath(); ctx.ellipse(tx + 7, ground - obstacle.height * .43, 10, obstacle.height * .4, -.22 + i * .08, 0, Math.PI * 2); ctx.fill();
          ctx.strokeStyle = '#9d8d60'; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(tx + 4, ground - obstacle.height * .63); ctx.lineTo(tx, ground - obstacle.height * .82); ctx.moveTo(tx + 12, ground - obstacle.height * .58); ctx.lineTo(tx + 17, ground - obstacle.height * .78); ctx.stroke();
        }
      }
    }

    drawFirefly(ctx) {
      const player = this.player;
      const ground = this.groundY;
      const centerX = player.x + 26;
      const bodyBottom = player.bottom;
      const jumpingHeight = ground - bodyBottom;
      const shadowScale = clamp(1 - jumpingHeight / 145, .42, 1);
      ctx.fillStyle = `rgba(14,22,15,${.28 * shadowScale})`;
      ctx.beginPath(); ctx.ellipse(centerX, ground - 1, 23 * shadowScale, 4 * shadowScale, 0, 0, Math.PI * 2); ctx.fill();
      const phase = player.runPhase;
      const bob = player.grounded ? Math.abs(Math.sin(phase * 2)) * 2.5 : 0;
      const bodyY = bodyBottom - 27 - bob;

      // Wings are separate forms that beat during the support/swing cycle.
      ctx.save(); ctx.translate(centerX, bodyY - 5); ctx.rotate(Math.sin(phase * 2.2) * .22);
      ctx.fillStyle = 'rgba(201,220,198,.72)';
      ctx.beginPath(); ctx.ellipse(-12, -7, 6, 11, -.55, 0, Math.PI * 2); ctx.ellipse(12, -7, 6, 11, .55, 0, Math.PI * 2); ctx.fill();
      ctx.restore();

      // Antennae, head, body and glowing belly echo the installer mascot.
      ctx.strokeStyle = '#bdcdb6'; ctx.lineWidth = 2; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(centerX - 5, bodyY - 18); ctx.quadraticCurveTo(centerX - 11, bodyY - 31, centerX - 13, bodyY - 29); ctx.moveTo(centerX + 5, bodyY - 18); ctx.quadraticCurveTo(centerX + 11, bodyY - 31, centerX + 13, bodyY - 29); ctx.stroke();
      ctx.fillStyle = '#7d9c78'; ctx.beginPath(); ctx.ellipse(centerX, bodyY - 13, 13, 12, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#49664c'; ctx.strokeStyle = '#b9ccb1'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.ellipse(centerX, bodyY + 1, 15, 20, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#e8bf78'; ctx.beginPath(); ctx.ellipse(centerX, bodyY + 10, 8, 6, 0, 0, Math.PI * 2); ctx.fill();
      const glow = ctx.createRadialGradient(centerX, bodyY + 10, 1, centerX, bodyY + 10, 17);
      glow.addColorStop(0, 'rgba(255,226,150,.4)'); glow.addColorStop(1, 'rgba(255,226,150,0)');
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(centerX, bodyY + 10, 17, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#f5eedc'; ctx.beginPath(); ctx.arc(centerX - 4, bodyY - 15, 1.7, 0, Math.PI * 2); ctx.arc(centerX + 4, bodyY - 15, 1.7, 0, Math.PI * 2); ctx.fill();

      // Articulated legs alternate support and swing. One reaches the ground
      // every cycle so the mascot never appears to hover while it runs.
      ctx.lineWidth = 2.5; ctx.strokeStyle = '#d7d4bb';
      const legSwing = player.grounded ? Math.sin(phase) * 10 : 0;
      const rearX = centerX - 7;
      const frontX = centerX + 7;
      ctx.beginPath();
      ctx.moveTo(rearX, bodyY + 14); ctx.lineTo(rearX - legSwing, bodyBottom - 3);
      ctx.lineTo(rearX - legSwing + 5, bodyBottom - 3);
      ctx.moveTo(frontX, bodyY + 14); ctx.lineTo(frontX + legSwing, bodyBottom - 3);
      ctx.lineTo(frontX + legSwing + 5, bodyBottom - 3);
      ctx.stroke();
    }

  }

  window.ClipifyForestGame = { Game };
})();
