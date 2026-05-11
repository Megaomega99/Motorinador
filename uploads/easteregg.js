/* ================================================================
   Megaomega Easter Egg v2 — Maximum Drama
   Shockwave · Lightning · Neural Cascade · Glitch · Portal
   ================================================================ */

(function () {
  'use strict';

  // ── Click counter ─────────────────────────────────────────────
  let clickCount = 0, clickTimer = null;

  function initLogoTrigger() {
    const logo = document.querySelector('.app-logo');
    if (!logo) return;
    logo.style.cursor = 'pointer';
    logo.addEventListener('click', () => {
      clickCount++;
      if (clickTimer) clearTimeout(clickTimer);
      clickTimer = setTimeout(() => { clickCount = 0; }, 2000);
      if (clickCount >= 5) {
        clickCount = 0;
        clearTimeout(clickTimer);
        launchEgg();
      }
    });
  }

  // ── Math helpers ──────────────────────────────────────────────
  const PI2   = Math.PI * 2;
  const rand  = (a, b) => a + Math.random() * (b - a);
  const lerp  = (a, b, t) => a + (b - a) * t;
  const clamp = (v, a, b) => Math.min(Math.max(v, a), b);

  // ── State ─────────────────────────────────────────────────────
  let W, H, cx, cy;

  // ── Overlay HTML ───────────────────────────────────────────────
  function buildOverlay() {
    const el = document.createElement('div');
    el.id = 'mo-egg-overlay';
    el.style.cssText = `
      position:fixed;inset:0;z-index:9999;background:#000;
      display:flex;align-items:center;justify-content:center;
      opacity:0;transition:opacity 0.35s ease;overflow:hidden;cursor:pointer;
    `;
    el.innerHTML = `
      <canvas id="mo-main-canvas" style="position:absolute;inset:0;"></canvas>

      <!-- HUD corners -->
      <div style="position:absolute;top:20px;left:20px;width:40px;height:40px;
        border-top:1.5px solid rgba(232,96,31,0.7);border-left:1.5px solid rgba(232,96,31,0.7);
        opacity:0;animation:moIn 0.4s ease 0.9s both;"></div>
      <div style="position:absolute;top:20px;right:20px;width:40px;height:40px;
        border-top:1.5px solid rgba(232,96,31,0.7);border-right:1.5px solid rgba(232,96,31,0.7);
        opacity:0;animation:moIn 0.4s ease 0.9s both;"></div>
      <div style="position:absolute;bottom:20px;left:20px;width:40px;height:40px;
        border-bottom:1.5px solid rgba(232,96,31,0.7);border-left:1.5px solid rgba(232,96,31,0.7);
        opacity:0;animation:moIn 0.4s ease 0.9s both;"></div>
      <div style="position:absolute;bottom:20px;right:20px;width:40px;height:40px;
        border-bottom:1.5px solid rgba(232,96,31,0.7);border-right:1.5px solid rgba(232,96,31,0.7);
        opacity:0;animation:moIn 0.4s ease 0.9s both;"></div>

      <!-- HUD data -->
      <div style="position:absolute;top:68px;left:24px;font-family:'IBM Plex Mono',monospace;
        font-size:8px;color:rgba(232,96,31,0.5);line-height:1.9;letter-spacing:0.04em;
        opacity:0;animation:moIn 0.4s ease 1.3s both;">
        SYS: aDBS-v3.1<br>MODE: ADAPTIVE<br>CH: STN-L/R<br>STIM: CLOSED-LOOP
      </div>
      <div style="position:absolute;top:68px;right:24px;text-align:right;font-family:'IBM Plex Mono',monospace;
        font-size:8px;color:rgba(232,96,31,0.5);line-height:1.9;letter-spacing:0.04em;
        opacity:0;animation:moIn 0.4s ease 1.3s both;">
        LFP: 21.0 Hz<br>PWR: 89.4 dB<br>LAT: 2.1 ms<br>SNR: 34.2 dB
      </div>
      <div style="position:absolute;bottom:80px;left:24px;font-family:'IBM Plex Mono',monospace;
        font-size:8px;color:rgba(232,96,31,0.5);line-height:1.9;letter-spacing:0.04em;
        opacity:0;animation:moIn 0.4s ease 1.3s both;">
        MVL: 0.0842<br>PHASE: −12°<br>HFO: 300 Hz
      </div>
      <div style="position:absolute;bottom:80px;right:24px;text-align:right;font-family:'IBM Plex Mono',monospace;
        font-size:8px;color:rgba(232,96,31,0.5);line-height:1.9;letter-spacing:0.04em;
        opacity:0;animation:moIn 0.4s ease 1.3s both;">
        PULSES: 4,291<br>REC: 00:42<br>STATUS: ██ OK
      </div>

      <!-- Center -->
      <div id="mo-center" style="position:relative;z-index:10;display:flex;flex-direction:column;
        align-items:center;gap:24px;pointer-events:none;">
        <div style="position:relative;">
          <img id="mo-logo" src="/static/images/with_padding.png" style="height:72px;width:auto;
            animation:moLogoIn 0.8s ease 0.4s both, moGlow 2s ease-in-out 1.2s infinite alternate;
            filter:drop-shadow(0 0 8px rgba(232,96,31,0.5));">
          <div id="mo-scan-line" style="position:absolute;inset:0;overflow:hidden;pointer-events:none;">
            <div style="position:absolute;left:0;right:0;height:2px;
              background:linear-gradient(90deg,transparent,rgba(232,96,31,0.9),transparent);
              animation:moScan 1.8s linear 1s infinite;box-shadow:0 0 10px rgba(232,96,31,0.7);"></div>
          </div>
        </div>
        <div id="mo-brand" style="font-family:'IBM Plex Mono',monospace;font-size:30px;font-weight:500;
          letter-spacing:0.22em;background:linear-gradient(135deg,#ffb347,#e8601f,#ff8c42);
          -webkit-background-clip:text;background-clip:text;color:transparent;
          text-shadow:none;text-transform:uppercase;min-height:40px;"></div>
        <div id="mo-sub" style="font-family:'IBM Plex Mono',monospace;font-size:10px;
          letter-spacing:0.45em;color:rgba(255,255,255,0.32);text-transform:uppercase;
          min-height:18px;"></div>
      </div>

      <!-- Close hint -->
      <div style="position:absolute;bottom:22px;left:50%;transform:translateX(-50%);
        font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:0.22em;
        color:rgba(255,255,255,0.18);text-transform:uppercase;
        opacity:0;animation:moIn 0.5s ease 3.5s both;">
        click para cerrar · esc
      </div>
    `;

    // Inject keyframes
    const style = document.createElement('style');
    style.id = 'mo-egg-styles';
    style.textContent = `
      @keyframes moIn { from{opacity:0} to{opacity:1} }
      @keyframes moLogoIn {
        0%  { opacity:0; transform:scale(2.5); filter:brightness(3) drop-shadow(0 0 60px #e8601f); }
        60% { opacity:1; transform:scale(0.95); }
        100%{ opacity:1; transform:scale(1); }
      }
      @keyframes moGlow {
        from { filter:drop-shadow(0 0 6px rgba(232,96,31,0.4)) brightness(0.95); }
        to   { filter:drop-shadow(0 0 28px rgba(232,96,31,1)) drop-shadow(0 0 55px rgba(255,140,66,0.5)) brightness(1.15); }
      }
      @keyframes moScan {
        0%  { top:-2px; opacity:0; }
        8%  { opacity:1; }
        92% { opacity:1; }
        100%{ top:100%; opacity:0; }
      }
    `;
    document.head.appendChild(style);
    document.body.appendChild(el);
    return el;
  }

  // ── Typewriter with glitch intro ──────────────────────────────
  const GLITCH_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#$%&*';

  function glitchTypewrite(el, text, delay, speed, cb) {
    setTimeout(() => {
      let i = 0;
      let glitchFrame = 0;
      el.textContent = '';

      function step() {
        if (i >= text.length) { el.textContent = text; if (cb) cb(); return; }
        glitchFrame++;
        // Show revealed + glitch of next chars
        let display = text.slice(0, i);
        const remaining = text.length - i;
        const showGlitch = Math.min(4, remaining);
        for (let g = 0; g < showGlitch; g++) {
          if (glitchFrame % 2 === 0 && g === 0) {
            display += text[i]; // lock in
            if (g === 0) i++;
          } else {
            display += GLITCH_CHARS[Math.floor(Math.random() * GLITCH_CHARS.length)];
          }
        }
        el.textContent = display;
        setTimeout(step, i > text.length ? 0 : speed);
      }
      step();
    }, delay);
  }

  // ── Canvas engine ─────────────────────────────────────────────
  function runCanvas(canvas) {
    function resize() {
      W = canvas.width  = window.innerWidth;
      H = canvas.height = window.innerHeight;
      cx = W / 2; cy = H / 2;
    }
    resize();
    window.addEventListener('resize', resize);

    const ctx = canvas.getContext('2d');
    let alive = true;
    let startT = null;

    // ── Shockwave rings (burst at t=0)
    const shockwaves = [
      { r: 0, maxR: Math.max(W, H) * 0.9, speed: 6, width: 3, alpha: 1 },
      { r: 0, maxR: Math.max(W, H) * 0.7, speed: 4, width: 1.5, alpha: 0.6 },
      { r: 0, maxR: Math.max(W, H) * 0.5, speed: 2.5, width: 1, alpha: 0.4 },
    ];

    // ── Neural nodes — positioned in two orbits
    const INNER = 14, OUTER = 26;
    const nodes = [
      ...Array.from({ length: INNER }, (_, i) => ({
        angle: (PI2 / INNER) * i + rand(-0.2, 0.2),
        orbitR: 170 + rand(-15, 15),
        orbitSpeed: rand(0.0008, 0.0018) * (Math.random() < 0.5 ? 1 : -1),
        r: rand(2, 3.5), pulse: Math.random(), pSpeed: rand(0.005, 0.012),
        x: 0, y: 0, active: false, activeCooldown: 0,
      })),
      ...Array.from({ length: OUTER }, (_, i) => ({
        angle: (PI2 / OUTER) * i + rand(-0.1, 0.1),
        orbitR: 280 + rand(-20, 20),
        orbitSpeed: rand(0.0004, 0.001) * (Math.random() < 0.5 ? 1 : -1),
        r: rand(1.5, 2.5), pulse: Math.random(), pSpeed: rand(0.004, 0.009),
        x: 0, y: 0, active: false, activeCooldown: 0,
      })),
    ];

    // Build edges (k-nearest)
    const K = 3;
    const edges = [];
    nodes.forEach((n, i) => {
      const dists = nodes
        .map((m, j) => ({ j, d: Math.abs(n.orbitR - m.orbitR) + Math.abs(n.angle - m.angle) * 100 }))
        .filter(x => x.j !== i)
        .sort((a, b) => a.d - b.d)
        .slice(0, K);
      dists.forEach(({ j }) => {
        if (!edges.find(e => (e.a === i && e.b === j) || (e.a === j && e.b === i))) {
          edges.push({ a: i, b: j });
        }
      });
    });

    // ── Signals (cascade chain)
    const signals = [];
    function spawnSignal(fromIdx, toIdx, hue = 30, bright = 1) {
      signals.push({ from: fromIdx, to: toIdx, t: 0, speed: rand(0.014, 0.024), hue, bright });
    }

    function triggerCascade(startIdx, depth = 0) {
      if (depth > 4) return;
      nodes[startIdx].active = true;
      nodes[startIdx].activeCooldown = 40;
      const connected = edges
        .filter(e => e.a === startIdx || e.b === startIdx)
        .map(e => (e.a === startIdx ? e.b : e.a));
      connected.forEach(j => {
        if (!nodes[j].active) {
          setTimeout(() => {
            spawnSignal(startIdx, j, depth === 0 ? 22 : 35, 1 - depth * 0.15);
            setTimeout(() => triggerCascade(j, depth + 1), rand(60, 180));
          }, rand(20, 120));
        }
      });
    }

    // ── Lightning arcs
    const lightnings = [];
    function spawnLightning() {
      const a = Math.floor(Math.random() * nodes.length);
      let b = Math.floor(Math.random() * nodes.length);
      while (b === a) b = Math.floor(Math.random() * nodes.length);
      const segs = [];
      let px = nodes[a].x, py = nodes[a].y;
      const tx = nodes[b].x, ty = nodes[b].y;
      const steps = 8 + Math.floor(Math.random() * 6);
      for (let s = 1; s <= steps; s++) {
        const t2 = s / steps;
        const bx = lerp(px, tx, 1 / steps);
        const by = lerp(py, ty, 1 / steps);
        segs.push({ x: bx + rand(-18, 18), y: by + rand(-18, 18) });
        px = segs[segs.length - 1].x;
        py = segs[segs.length - 1].y;
      }
      segs[segs.length - 1] = { x: tx, y: ty };
      lightnings.push({ from: a, to: b, segs, life: 1, decay: rand(0.06, 0.12) });
    }

    // ── Particles
    const particles = Array.from({ length: 180 }, () => {
      const angle = rand(0, PI2);
      const speed = rand(0.8, 3.5);
      return {
        x: cx, y: cy,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: rand(0.4, 1), maxLife: 1,
        r: rand(0.5, 2.2),
        hue: rand(18, 40),
      };
    });

    // ── Portal vortex lines
    const vortexLines = Array.from({ length: 60 }, (_, i) => ({
      angle: (PI2 / 60) * i,
      len: rand(30, 90),
      speed: rand(0.008, 0.02) * (Math.random() < 0.5 ? 1 : -1),
      r: rand(100, 160),
    }));

    // Schedule cascade
    let cascadeScheduled = false;

    function frame(ts) {
      if (!alive) return;
      if (!startT) startT = ts;
      const elapsed = (ts - startT) / 1000;

      ctx.clearRect(0, 0, W, H);

      // ── Background
      const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(W, H) * 0.75);
      bg.addColorStop(0,   `rgba(6,2,18,0.97)`);
      bg.addColorStop(0.5, `rgba(3,1,10,0.99)`);
      bg.addColorStop(1,   `rgba(0,0,0,1)`);
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      // ── Hex grid
      drawHexGrid(ctx, W, H, elapsed);

      // ── Shockwaves
      shockwaves.forEach(sw => {
        if (sw.r > sw.maxR) return;
        sw.r += sw.speed;
        const a = clamp(1 - sw.r / sw.maxR, 0, 1) * sw.alpha;
        ctx.beginPath();
        ctx.arc(cx, cy, sw.r, 0, PI2);
        ctx.strokeStyle = `rgba(232,96,31,${a})`;
        ctx.lineWidth = sw.width;
        ctx.stroke();
      });

      // ── Vortex (early phase)
      if (elapsed < 2) {
        const vAlpha = clamp(1 - elapsed / 2, 0, 1) * 0.35;
        vortexLines.forEach(vl => {
          vl.angle += vl.speed;
          const x1 = cx + Math.cos(vl.angle) * (vl.r * 0.3);
          const y1 = cy + Math.sin(vl.angle) * (vl.r * 0.3);
          const x2 = cx + Math.cos(vl.angle) * vl.r;
          const y2 = cy + Math.sin(vl.angle) * vl.r;
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.strokeStyle = `rgba(255,140,66,${vAlpha})`;
          ctx.lineWidth = 0.6;
          ctx.stroke();
        });
      }

      // ── Update nodes
      nodes.forEach(n => {
        n.angle += n.orbitSpeed;
        n.x = cx + Math.cos(n.angle) * n.orbitR;
        n.y = cy + Math.sin(n.angle) * n.orbitR;
        n.pulse = (n.pulse + n.pSpeed) % 1;
        if (n.activeCooldown > 0) n.activeCooldown--;
        else n.active = false;
      });

      // Trigger first cascade after 0.8s
      if (elapsed > 0.8 && !cascadeScheduled) {
        cascadeScheduled = true;
        const seedIdx = Math.floor(Math.random() * INNER); // inner ring node
        triggerCascade(seedIdx);
        // Re-trigger every 2.5s
        setInterval(() => {
          if (!alive) return;
          triggerCascade(Math.floor(Math.random() * nodes.length));
          if (Math.random() < 0.5) spawnLightning();
        }, 2500);
      }

      // ── Draw edges
      edges.forEach(e => {
        const a = nodes[e.a], b = nodes[e.b];
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const maxD = 280;
        if (dist > maxD) return;
        const alpha = (1 - dist / maxD) * 0.12;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = `rgba(232,96,31,${alpha})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
      });

      // ── Draw nodes
      nodes.forEach(n => {
        const baseAlpha = 0.25 + Math.sin(n.pulse * PI2) * 0.25;
        const glowAlpha = n.active ? 0.9 : baseAlpha;
        const glowR     = n.active ? n.r * 5 : n.r * 2.5;
        const nodeColor = n.active ? `rgba(255,220,80,${glowAlpha})` : `rgba(232,96,31,${glowAlpha})`;

        // Glow halo
        const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, glowR);
        g.addColorStop(0, nodeColor.replace(')', `, ${glowAlpha * 0.3})`).replace('rgba', 'rgba').slice(0, -1) + ')');
        g.addColorStop(0, n.active ? `rgba(255,220,80,0.35)` : `rgba(232,96,31,0.15)`);
        g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(n.x, n.y, glowR, 0, PI2);
        ctx.fill();

        // Core
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, PI2);
        ctx.fillStyle = nodeColor;
        ctx.fill();
      });

      // ── Signals
      for (let s = signals.length - 1; s >= 0; s--) {
        const sig = signals[s];
        sig.t += sig.speed;
        if (sig.t >= 1) { signals.splice(s, 1); continue; }
        const from = nodes[sig.from], to = nodes[sig.to];
        const px = lerp(from.x, to.x, sig.t);
        const py = lerp(from.y, to.y, sig.t);
        const a = 1 - sig.t * 0.5;

        ctx.beginPath();
        ctx.arc(px, py, 3.5, 0, PI2);
        ctx.fillStyle = `hsla(${sig.hue},100%,72%,${a * sig.bright})`;
        ctx.fill();

        // Trail
        for (let tr = 1; tr <= 4; tr++) {
          const tt = Math.max(0, sig.t - tr * 0.025);
          const tx = lerp(from.x, to.x, tt);
          const ty = lerp(from.y, to.y, tt);
          ctx.beginPath();
          ctx.arc(tx, ty, 3.5 - tr * 0.6, 0, PI2);
          ctx.fillStyle = `hsla(${sig.hue},100%,72%,${a * sig.bright * (0.25 - tr * 0.05)})`;
          ctx.fill();
        }
      }

      // ── Lightnings
      for (let l = lightnings.length - 1; l >= 0; l--) {
        const lt = lightnings[l];
        lt.life -= lt.decay;
        if (lt.life <= 0) { lightnings.splice(l, 1); continue; }
        const from = nodes[lt.from];
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        lt.segs.forEach(s => ctx.lineTo(s.x, s.y));
        ctx.strokeStyle = `rgba(255,230,120,${lt.life * 0.85})`;
        ctx.lineWidth = 1.2;
        ctx.shadowColor = 'rgba(255,200,80,0.8)';
        ctx.shadowBlur = 8;
        ctx.stroke();
        ctx.shadowBlur = 0;
      }

      // ── Particles
      particles.forEach(p => {
        if (p.life <= 0) return;
        p.life -= 0.007;
        p.x += p.vx; p.y += p.vy;
        p.vx *= 0.991; p.vy *= 0.991;
        const a = p.life / p.maxLife;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * a, 0, PI2);
        ctx.fillStyle = `hsla(${p.hue},100%,68%,${a * 0.75})`;
        ctx.fill();
      });

      // ── Center glow (breathe)
      const breathe = 0.5 + 0.5 * Math.sin(elapsed * 1.6);
      const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, 130);
      cg.addColorStop(0,   `rgba(232,96,31,${0.10 + breathe * 0.08})`);
      cg.addColorStop(0.6, `rgba(232,96,31,${0.03 + breathe * 0.03})`);
      cg.addColorStop(1,   'rgba(232,96,31,0)');
      ctx.fillStyle = cg;
      ctx.fillRect(0, 0, W, H);

      // ── EEG strip (bottom)
      drawEEG(ctx, W, H, elapsed);

      requestAnimationFrame(frame);
    }

    requestAnimationFrame(frame);
    return () => { alive = false; window.removeEventListener('resize', resize); };
  }

  // ── Hex grid ──────────────────────────────────────────────────
  function drawHexGrid(ctx, W, H, t) {
    const size = 38;
    const cols = Math.ceil(W / (size * 1.73)) + 2;
    const rows = Math.ceil(H / (size * 1.5)) + 2;
    const alpha = 0.025 + 0.012 * Math.sin(t * 0.4);
    ctx.strokeStyle = `rgba(232,96,31,${alpha})`;
    ctx.lineWidth = 0.5;
    for (let r = -1; r < rows; r++) {
      for (let c = -1; c < cols; c++) {
        const ox = r % 2 === 0 ? 0 : size * 0.865;
        hexPath(ctx, c * size * 1.73 + ox, r * size * 1.5, size - 2);
        ctx.stroke();
      }
    }
  }

  function hexPath(ctx, x, y, r) {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 3) * i - Math.PI / 6;
      i === 0
        ? ctx.moveTo(x + r * Math.cos(a), y + r * Math.sin(a))
        : ctx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a));
    }
    ctx.closePath();
  }

  // ── EEG strip ─────────────────────────────────────────────────
  function drawEEG(ctx, W, H, t) {
    const y0 = H - 52;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, y0 - 20, W, 40);
    ctx.clip();
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(232,96,31,0.4)';
    ctx.lineWidth = 1.2;
    for (let x = 0; x <= W; x += 1) {
      const ph = (x / W) * Math.PI * 24 - t * 3.5;
      const amp = (
        Math.sin(ph) * 0.5 +
        Math.sin(ph * 2.3 + 1) * 0.25 +
        Math.sin(ph * 0.52) * 0.25
      ) * 14;
      x === 0 ? ctx.moveTo(x, y0 + amp) : ctx.lineTo(x, y0 + amp);
    }
    ctx.stroke();
    ctx.restore();
  }

  // ── Launch ────────────────────────────────────────────────────
  function launchEgg() {
    const overlay = buildOverlay();

    requestAnimationFrame(() => requestAnimationFrame(() => {
      overlay.style.opacity = '1';
    }));

    const canvas = document.getElementById('mo-main-canvas');
    const stopCanvas = runCanvas(canvas);

    // Texts
    const brand = document.getElementById('mo-brand');
    const sub   = document.getElementById('mo-sub');
    glitchTypewrite(brand, 'MEGAOMEGA', 700, 45, () => {
      glitchTypewrite(sub, 'ENGINEERING FOR WELL-BEING', 150, 32);
    });

    // Close
    function close() {
      overlay.style.opacity = '0';
      overlay.style.transition = 'opacity 0.5s ease';
      stopCanvas();
      setTimeout(() => {
        overlay.remove();
        const s = document.getElementById('mo-egg-styles');
        if (s) s.remove();
      }, 500);
    }

    overlay.addEventListener('click', close);
    document.addEventListener('keydown', function onKey(e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); }
    });
    setTimeout(close, 10000);
  }

  // ── Boot ──────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLogoTrigger);
  } else {
    initLogoTrigger();
  }

})();
