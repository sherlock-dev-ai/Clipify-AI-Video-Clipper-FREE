'use strict';

(function () {
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const randomBetween = (low, high) => low + Math.random() * (high - low);

  class World {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      if (!this.ctx) throw new Error('The forest animation canvas could not be initialized');
      this.clock = 0;
      this.previousFrame = 0;
      this.frameId = 0;
      this.visible = !document.hidden;
      this.currentNight = document.body.dataset.theme === 'night' ? 1 : 0;
      this.targetNight = this.currentNight;
      this.width = 1;
      this.height = 1;
      this.dpr = 1;
      this.wind = 0;
      this.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.leaves = [];
      this.bees = [];
      this.fireflies = [];
      this.lastParticleCounts = { leaves: 0, bees: 0, fireflies: 0 };

      this.onResize = () => this.resize();
      this.onVisibility = () => {
        this.visible = !document.hidden;
        if (this.visible) {
          this.previousFrame = 0;
          this.draw();
          this.schedule();
        } else {
          this.stopFrame();
        }
      };
      this.onMotionChange = (event) => {
        this.reducedMotion = event.matches;
        this.previousFrame = 0;
        if (this.reducedMotion) {
          this.currentNight = this.targetNight;
          this.draw();
        }
        this.schedule();
      };

      window.addEventListener('resize', this.onResize, { passive: true });
      this.motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.motionQuery.addEventListener('change', this.onMotionChange);
      document.addEventListener('visibilitychange', this.onVisibility);
      this.resize();
      this.schedule();
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      this.width = Math.max(1, rect.width || window.innerWidth || 1024);
      this.height = Math.max(1, rect.height || window.innerHeight || 768);
      this.dpr = clamp(window.devicePixelRatio || 1, 1, 1.5);
      const pixelWidth = Math.round(this.width * this.dpr);
      const pixelHeight = Math.round(this.height * this.dpr);
      if (this.canvas.width !== pixelWidth || this.canvas.height !== pixelHeight) {
        this.canvas.width = pixelWidth;
        this.canvas.height = pixelHeight;
      }
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      this.populateParticles();
      this.draw();
    }

    populateParticles() {
      const leafCount = clamp(
        Math.round(this.width / (this.reducedMotion ? 88 : 48)),
        this.reducedMotion ? 10 : 20,
        32
      );
      this.leaves = Array.from({ length: leafCount }, (_, index) => ({
        x: randomBetween(0, this.width),
        y: randomBetween(-this.height * 0.1, this.height),
        size: randomBetween(6, 11),
        speed: randomBetween(this.reducedMotion ? 14 : 22, this.reducedMotion ? 22 : 42),
        drift: randomBetween(-8, 8),
        rotation: randomBetween(0, Math.PI * 2),
        spin: randomBetween(-1.4, 1.4),
        hue: index % 4,
      }));
      this.bees = Array.from({ length: 4 }, () => ({
        x: randomBetween(this.width * 0.12, this.width * 0.88),
        y: randomBetween(this.height * 0.52, this.height * 0.82),
        phase: randomBetween(0, Math.PI * 2),
        homeX: randomBetween(this.width * 0.12, this.width * 0.88),
        homeY: randomBetween(this.height * 0.5, this.height * 0.82),
        radius: randomBetween(3.2, 4.5),
      }));
      this.fireflies = Array.from({ length: 14 }, () => ({
        x: randomBetween(this.width * 0.06, this.width * 0.94),
        y: randomBetween(this.height * 0.32, this.height * 0.82),
        phase: randomBetween(0, Math.PI * 2),
        radius: randomBetween(1.3, 2.2),
        speed: randomBetween(0.35, 0.8),
        drift: randomBetween(-5, 5),
      }));
    }

    setTheme(night) {
      this.targetNight = night ? 1 : 0;
      if (this.reducedMotion) {
        this.currentNight = this.targetNight;
        this.draw();
        return;
      }
      this.schedule();
    }

    schedule() {
      if (this.visible && !this.frameId) {
        this.frameId = requestAnimationFrame((time) => this.tick(time));
      }
    }

    stopFrame() {
      if (this.frameId) cancelAnimationFrame(this.frameId);
      this.frameId = 0;
      this.previousFrame = 0;
    }

    tick(timestamp) {
      this.frameId = 0;
      if (!this.visible) return;
      if (this.reducedMotion && this.previousFrame && timestamp - this.previousFrame < 100) {
        this.schedule();
        return;
      }
      const maxDelta = this.reducedMotion ? 0.12 : 0.05;
      const delta = this.previousFrame
        ? clamp((timestamp - this.previousFrame) / 1000, 0, maxDelta)
        : 1 / 60;
      this.previousFrame = timestamp;
      const motionScale = this.reducedMotion ? 0.4 : 1;
      this.clock += delta * motionScale;
      this.currentNight += (this.targetNight - this.currentNight) * (1 - Math.exp(-delta * 1.8));
      this.wind = Math.sin(this.clock * 0.31) * 15 + Math.sin(this.clock * 0.73) * 6;
      this.updateParticles(delta * motionScale);
      this.draw();
      this.schedule();
    }

    updateParticles(delta) {
      for (const leaf of this.leaves) {
        leaf.y += leaf.speed * delta;
        leaf.x += (leaf.drift + this.wind * 0.42) * delta;
        leaf.rotation += leaf.spin * delta;
        if (leaf.y > this.height + 16) {
          leaf.y = randomBetween(-this.height * 0.12, -12);
          leaf.x = randomBetween(0, this.width);
        }
        if (leaf.x < -18) leaf.x = this.width + 12;
        if (leaf.x > this.width + 18) leaf.x = -12;
      }
      for (const bee of this.bees) {
        bee.phase += delta * 1.6;
        bee.x += (bee.homeX + Math.sin(bee.phase) * 22 - bee.x) * delta * 0.45;
        bee.y += (bee.homeY + Math.cos(bee.phase * 1.23) * 15 - bee.y) * delta * 0.45;
      }
      for (const firefly of this.fireflies) {
        firefly.phase += delta * firefly.speed;
        firefly.x += (firefly.drift + Math.sin(firefly.phase * 0.7) * 5) * delta;
        firefly.y += Math.cos(firefly.phase) * delta * 2;
        if (firefly.x < 0) firefly.x = this.width;
        if (firefly.x > this.width) firefly.x = 0;
      }
    }

    draw() {
      const ctx = this.ctx;
      const day = 1 - this.currentNight;
      ctx.clearRect(0, 0, this.width, this.height);
      this.drawLeaves();
      this.drawBees(day);
      this.drawFireflies(this.currentNight);
      this.lastParticleCounts = {
        leaves: this.leaves.length,
        bees: day > 0.12 ? this.bees.length : 0,
        fireflies: this.currentNight > 0.02 ? this.fireflies.length : 0,
      };
      this.drawnFrames = (this.drawnFrames || 0) + 1;
    }

    drawLeaves() {
      const ctx = this.ctx;
      const colors = ['#d4a65f', '#b86f48', '#c4bc70', '#9eae69'];
      for (const leaf of this.leaves) {
        ctx.save();
        ctx.translate(leaf.x, leaf.y);
        ctx.rotate(leaf.rotation);
        ctx.scale(leaf.size / 7, leaf.size / 7);
        ctx.fillStyle = colors[leaf.hue];
        ctx.globalAlpha = 0.92;
        ctx.beginPath();
        ctx.moveTo(0, -6);
        ctx.bezierCurveTo(6, -4, 7, 1, 0, 6);
        ctx.bezierCurveTo(-7, 3, -6, -3, 0, -6);
        ctx.fill();
        ctx.strokeStyle = 'rgba(77,67,43,.52)';
        ctx.lineWidth = 0.7;
        ctx.beginPath();
        ctx.moveTo(0, -5);
        ctx.quadraticCurveTo(0, 1, 0, 5);
        ctx.stroke();
        ctx.restore();
      }
    }

    drawBees(day) {
      if (day <= 0.12) return;
      const ctx = this.ctx;
      ctx.save();
      ctx.globalAlpha = day * 0.86;
      for (const bee of this.bees) {
        const wing = Math.sin(this.clock * 24 + bee.phase) * 2;
        ctx.save();
        ctx.translate(bee.x, bee.y);
        ctx.rotate(Math.sin(bee.phase) * 0.22);
        ctx.fillStyle = 'rgba(230,239,209,.88)';
        ctx.beginPath();
        ctx.ellipse(-1.5, -bee.radius * 0.58 - wing * 0.16, bee.radius * 0.58, bee.radius * 0.32, -0.5, 0, Math.PI * 2);
        ctx.ellipse(1.8, -bee.radius * 0.56 + wing * 0.16, bee.radius * 0.52, bee.radius * 0.3, 0.45, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#d7aa43';
        ctx.beginPath();
        ctx.ellipse(0, 0, bee.radius, bee.radius * 0.7, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#4f4529';
        ctx.lineWidth = Math.max(0.8, bee.radius * 0.23);
        ctx.beginPath();
        ctx.moveTo(-0.2, -bee.radius * 0.62);
        ctx.lineTo(-0.2, bee.radius * 0.62);
        ctx.moveTo(1.8, -bee.radius * 0.48);
        ctx.lineTo(1.8, bee.radius * 0.48);
        ctx.stroke();
        ctx.restore();
      }
      ctx.restore();
    }

    drawFireflies(night) {
      if (night <= 0.02) return;
      const ctx = this.ctx;
      for (const firefly of this.fireflies) {
        const pulse = (0.5 + Math.sin(firefly.phase * 2.1) * 0.5) * night;
        if (pulse < 0.04) continue;
        const radius = 7 + pulse * 7;
        const glow = ctx.createRadialGradient(firefly.x, firefly.y, 0, firefly.x, firefly.y, radius);
        glow.addColorStop(0, `rgba(255,221,143,${pulse * 0.58})`);
        glow.addColorStop(1, 'rgba(255,221,143,0)');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(firefly.x, firefly.y, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = `rgba(255,237,182,${pulse * 0.92})`;
        ctx.beginPath();
        ctx.arc(firefly.x, firefly.y, firefly.radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    destroy() {
      this.stopFrame();
      window.removeEventListener('resize', this.onResize);
      this.motionQuery.removeEventListener('change', this.onMotionChange);
      document.removeEventListener('visibilitychange', this.onVisibility);
    }
  }

  function init() {
    const canvas = document.getElementById('forest-world');
    if (!canvas || window.clipifyForestWorld) return;
    window.clipifyForestWorld = new World(canvas);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
  window.ClipifyForestWorldApi = { World };
})();
