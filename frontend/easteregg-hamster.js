/* ================================================================
   Motorinador Easter Egg — Hámster Edition
   Cedar dust · Sunflower seeds · Spinning wheels · Speed lines
   Trigger: 5 clicks on .app-logo within 2 seconds
   ================================================================ */

(function () {
  'use strict';

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

  const PI2 = Math.PI * 2;
  const rand  = (a, b) => a + Math.random() * (b - a);
  const lerp  = (a, b, t) => a + (b - a) * t;
  const clamp = (v, a, b) => Math.min(Math.max(v, a), b);

  let W, H, cx, cy;

  function buildOverlay() {
    const el = document.createElement('div');
    el.id = 'mo-egg-overlay';
    el.style.cssText = `
      position:fixed;inset:0;z-index:9999;background:#1a0f04;
      display:flex;align-items:center;justify-content:center;
      opacity:0;transition:opacity 0.35s ease;overflow:hidden;cursor:pointer;
    `;
    el.innerHTML = `
      <canvas id="mo-main-canvas" style="position:absolute;inset:0;"></canvas>

      <!-- HUD corners -->
      <div style="position:absolute;top:20px;left:20px;width:40px;height:40px;
        border-top:1.5px solid rgba(241,176,74,0.75);border-left:1.5px solid rgba(241,176,74,0.75);
        opacity:0;animation:hmIn 0.4s ease 0.9s both;"></div>
      <div style="position:absolute;top:20px;right:20px;width:40px;height:40px;
        border-top:1.5px solid rgba(241,176,74,0.75);border-right:1.5px solid rgba(241,176,74,0.75);
        opacity:0;animation:hmIn 0.4s ease 0.9s both;"></div>
      <div style="position:absolute;bottom:20px;left:20px;width:40px;height:40px;
        border-bottom:1.5px solid rgba(241,176,74,0.75);border-left:1.5px solid rgba(241,176,74,0.75);
        opacity:0;animation:hmIn 0.4s ease 0.9s both;"></div>
      <div style="position:absolute;bottom:20px;right:20px;width:40px;height:40px;
        border-bottom:1.5px solid rgba(241,176,74,0.75);border-right:1.5px solid rgba(241,176,74,0.75);
        opacity:0;animation:hmIn 0.4s ease 0.9s both;"></div>

      <!-- HUD telemetry -->
      <div style="position:absolute;top:68px;left:24px;font-family:'IBM Plex Mono',monospace;
        font-size:8px;color:rgba(241,176,74,0.55);line-height:1.9;letter-spacing:0.04em;
        opacity:0;animation:hmIn 0.4s ease 1.3s both;">
        SYS: HAMSTER-LABS v3.1<br>MODE: WHEEL-RUN<br>CH: NEMA17-L/R<br>LOOP: CLOSED
      </div>
      <div style="position:absolute;top:68px;right:24px;text-align:right;font-family:'IBM Plex Mono',monospace;
        font-size:8px;color:rgba(241,176,74,0.55);line-height:1.9;letter-spacing:0.04em;
        opacity:0;animation:hmIn 0.4s ease 1.3s both;">
        RPM: <span id="hudRpm">000.0</span><br>ω: 12.6 rad/s<br>LAT: 2.1 ms<br>SNR: 34.2 dB
      </div>
      <div style="position:absolute;bottom:80px;left:24px;font-family:'IBM Plex Mono',monospace;
        font-size:8px;color:rgba(241,176,74,0.55);line-height:1.9;letter-spacing:0.04em;
        opacity:0;animation:hmIn 0.4s ease 1.3s both;">
        SEEDS: 4,291<br>SHAVINGS: 88%<br>CEDAR: PREMIUM
      </div>
      <div style="position:absolute;bottom:80px;right:24px;text-align:right;font-family:'IBM Plex Mono',monospace;
        font-size:8px;color:rgba(241,176,74,0.55);line-height:1.9;letter-spacing:0.04em;
        opacity:0;animation:hmIn 0.4s ease 1.3s both;">
        STEPS: 1,600 / rev<br>µSTEP: 1/8<br>STATUS: ██ HAPPY
      </div>

      <!-- Center -->
      <div id="hm-center" style="position:relative;z-index:10;display:flex;flex-direction:column;
        align-items:center;gap:24px;pointer-events:none;">
        <!-- spinning wheel glyph -->
        <div id="hm-wheel-wrap" style="position:relative;width:104px;height:104px;
             animation:hmLogoIn 0.8s ease 0.4s both;">
          <svg id="hm-wheel-svg" viewBox="0 0 100 100" style="width:100%;height:100%;
              filter:drop-shadow(0 0 12px rgba(241,176,74,0.55));">
            <defs>
              <radialGradient id="hmWm" cx="50%" cy="50%" r="50%">
                <stop offset="0%"  stop-color="#fff3cf"/>
                <stop offset="60%" stop-color="#f1b04a"/>
                <stop offset="100%" stop-color="#a05a18"/>
              </radialGradient>
            </defs>
            <g id="hm-wheel-spin" style="transform-origin:50px 50px;">
              <circle cx="50" cy="50" r="44" fill="none" stroke="url(#hmWm)" stroke-width="4"/>
              <g stroke="#f1b04a" stroke-width="2.5" stroke-linecap="round">
                <line x1="50" y1="8"  x2="50" y2="18"/>
                <line x1="50" y1="82" x2="50" y2="92"/>
                <line x1="8"  y1="50" x2="18" y2="50"/>
                <line x1="82" y1="50" x2="92" y2="50"/>
                <line x1="20" y1="20" x2="27" y2="27"/>
                <line x1="73" y1="73" x2="80" y2="80"/>
                <line x1="80" y1="20" x2="73" y2="27"/>
                <line x1="27" y1="73" x2="20" y2="80"/>
              </g>
              <circle cx="50" cy="50" r="6" fill="#3a2412"/>
              <circle cx="50" cy="50" r="2.5" fill="#f1b04a"/>
            </g>
            <!-- tiny mouse silhouette on bottom -->
            <g transform="translate(50 78)">
              <ellipse cx="0" cy="0" rx="12" ry="7" fill="#3a2412"/>
              <ellipse cx="9" cy="-2" rx="6" ry="5" fill="#3a2412"/>
              <circle cx="13" cy="-3" r="1" fill="#ffb56a"/>
              <path d="M -10 1 q -7 -3 -12 2" fill="none" stroke="#3a2412" stroke-width="1.4" stroke-linecap="round"/>
            </g>
          </svg>
          <div style="position:absolute;inset:0;overflow:hidden;pointer-events:none;border-radius:50%;">
            <div style="position:absolute;left:0;right:0;height:2px;
              background:linear-gradient(90deg,transparent,rgba(241,176,74,0.9),transparent);
              animation:hmScan 1.8s linear 1s infinite;box-shadow:0 0 10px rgba(241,176,74,0.7);"></div>
          </div>
        </div>

        <div id="hm-brand" style="font-family:'Fraunces',serif;font-size:42px;font-weight:900;
          letter-spacing:-0.01em;background:linear-gradient(135deg,#ffd089,#f1b04a 35%,#e8601f 80%);
          -webkit-background-clip:text;background-clip:text;color:transparent;
          text-transform:uppercase;min-height:48px;"></div>
        <div id="hm-sub" style="font-family:'IBM Plex Mono',monospace;font-size:10px;
          letter-spacing:0.45em;color:rgba(241,212,160,0.42);text-transform:uppercase;
          min-height:18px;"></div>
      </div>
      <!-- Author credit, anchored above the close hint so it's always visible -->
      <div id="hm-author" style="position:absolute;left:50%;bottom:62px;transform:translateX(-50%);
        font-family:'IBM Plex Mono',monospace;font-size:11px;
        letter-spacing:0.34em;color:rgba(255,220,170,0.75);text-transform:uppercase;
        text-align:center;line-height:1.9;z-index:11;
        opacity:0;animation:hmIn 0.7s ease 2.4s both;">
        <span style="color:#ffd089;font-weight:600;">MEGAOMEGA</span>
        <span style="opacity:.55;margin:0 8px;">&middot;</span>
        ENGINEERING FOR WELL-BEING
        <div style="font-size:9px;letter-spacing:0.5em;color:rgba(241,212,160,0.55);margin-top:6px;">&copy; 2026</div>
      </div>

      <div style="position:absolute;bottom:22px;left:50%;transform:translateX(-50%);
        font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:0.22em;
        color:rgba(255,220,170,0.22);text-transform:uppercase;
        opacity:0;animation:hmIn 0.5s ease 3.5s both;">
        click para cerrar · esc · hámster feliz
      </div>
    `;

    const style = document.createElement('style');
    style.id = 'hm-egg-styles';
    style.textContent = `
      @keyframes hmIn { from{opacity:0} to{opacity:1} }
      @keyframes hmLogoIn {
        0%  { opacity:0; transform:scale(2.5) rotate(-90deg); filter:brightness(3) drop-shadow(0 0 60px #f1b04a); }
        60% { opacity:1; transform:scale(0.95) rotate(20deg); }
        100%{ opacity:1; transform:scale(1) rotate(0deg); }
      }
      @keyframes hmSpin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
      @keyframes hmGlow {
        from { text-shadow: 0 0 0 rgba(241,176,74,0); filter:brightness(0.95); }
        to   { text-shadow: 0 0 12px rgba(241,176,74,0.55); filter:brightness(1.15); }
      }
      @keyframes hmScan {
        0%  { top:-2px; opacity:0; }
        8%  { opacity:1; }
        92% { opacity:1; }
        100%{ top:100%; opacity:0; }
      }
      #hm-wheel-spin { animation: hmSpin 1.4s linear infinite; transform-origin:50px 50px; transform-box:fill-box; }
    `;
    document.head.appendChild(style);
    document.body.appendChild(el);
    return el;
  }

  /* ── Typewriter ── */
  const GLITCH = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#@*';
  function glitchTypewrite(el, text, delay, speed, cb) {
    setTimeout(() => {
      let i = 0, frame = 0;
      el.textContent = '';
      (function step() {
        if (i >= text.length) { el.textContent = text; if (cb) cb(); return; }
        frame++;
        let display = text.slice(0, i);
        const remaining = text.length - i;
        const showGlitch = Math.min(4, remaining);
        for (let g = 0; g < showGlitch; g++) {
          if (frame % 2 === 0 && g === 0) { display += text[i]; i++; }
          else display += GLITCH[Math.floor(Math.random() * GLITCH.length)];
        }
        el.textContent = display;
        setTimeout(step, speed);
      })();
    }, delay);
  }

  /* ── Canvas scene ── */
  function runCanvas(canvas) {
    function resize() {
      W = canvas.width = window.innerWidth;
      H = canvas.height = window.innerHeight;
      cx = W/2; cy = H/2;
    }
    resize();
    window.addEventListener('resize', resize);

    const ctx = canvas.getContext('2d');
    let alive = true;
    let startT = null;

    /* Shockwaves (rings) */
    const shockwaves = [
      { r: 0, maxR: Math.max(W,H)*0.9, speed: 6,   width: 3,   alpha: 1   },
      { r: 0, maxR: Math.max(W,H)*0.7, speed: 4,   width: 1.5, alpha: 0.6 },
      { r: 0, maxR: Math.max(W,H)*0.5, speed: 2.5, width: 1,   alpha: 0.4 },
    ];

    /* Spinning hamster-wheel orbiters (instead of neural nodes) */
    const INNER = 8, OUTER = 14;
    const wheels = [
      ...Array.from({length: INNER}, (_, i) => ({
        angle: (PI2/INNER)*i + rand(-0.15, 0.15),
        orbitR: 170 + rand(-12, 12),
        orbitSpeed: rand(0.0010, 0.0020) * (Math.random()<0.5 ? 1 : -1),
        spin: 0,
        spinSpeed: rand(0.04, 0.10) * (Math.random()<0.5 ? 1 : -1),
        size: rand(20, 28),
        x: 0, y: 0,
        active: false, activeCooldown: 0,
        pulse: Math.random(),
      })),
      ...Array.from({length: OUTER}, (_, i) => ({
        angle: (PI2/OUTER)*i + rand(-0.1, 0.1),
        orbitR: 290 + rand(-20, 20),
        orbitSpeed: rand(0.0005, 0.0012) * (Math.random()<0.5 ? 1 : -1),
        spin: 0,
        spinSpeed: rand(0.03, 0.08) * (Math.random()<0.5 ? 1 : -1),
        size: rand(14, 20),
        x: 0, y: 0,
        active: false, activeCooldown: 0,
        pulse: Math.random(),
      })),
    ];

    /* Edges connecting near wheels (treadbelt-style links) */
    const K = 3;
    const edges = [];
    wheels.forEach((n, i) => {
      const dists = wheels
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

    /* Signals — seeds shooting between wheels */
    const signals = [];
    function spawnSignal(fromIdx, toIdx, hue = 38, bright = 1) {
      signals.push({ from: fromIdx, to: toIdx, t: 0, speed: rand(0.014, 0.024), hue, bright });
    }
    function triggerCascade(startIdx, depth = 0) {
      if (depth > 4) return;
      wheels[startIdx].active = true;
      wheels[startIdx].activeCooldown = 40;
      const connected = edges
        .filter(e => e.a === startIdx || e.b === startIdx)
        .map(e => (e.a === startIdx ? e.b : e.a));
      connected.forEach(j => {
        if (!wheels[j].active) {
          setTimeout(() => {
            spawnSignal(startIdx, j, depth === 0 ? 30 : 42, 1 - depth * 0.15);
            setTimeout(() => triggerCascade(j, depth + 1), rand(60, 180));
          }, rand(20, 120));
        }
      });
    }

    /* Speed sparks (instead of lightning) */
    const sparks = [];
    function spawnSpark() {
      const a = Math.floor(Math.random()*wheels.length);
      let b = Math.floor(Math.random()*wheels.length);
      while (b === a) b = Math.floor(Math.random()*wheels.length);
      const segs = [];
      let px = wheels[a].x, py = wheels[a].y;
      const tx = wheels[b].x, ty = wheels[b].y;
      const steps = 6 + Math.floor(Math.random()*5);
      for (let s = 1; s <= steps; s++) {
        const bx = lerp(px, tx, 1/steps);
        const by = lerp(py, ty, 1/steps);
        segs.push({ x: bx + rand(-14, 14), y: by + rand(-14, 14) });
        px = segs[segs.length-1].x; py = segs[segs.length-1].y;
      }
      segs[segs.length-1] = { x: tx, y: ty };
      sparks.push({ from: a, to: b, segs, life: 1, decay: rand(0.06, 0.12) });
    }

    /* Sunflower seed particles burst */
    const SEED_COUNT = 220;
    const seeds = Array.from({length: SEED_COUNT}, () => {
      const angle = rand(0, PI2);
      const speed = rand(0.8, 3.5);
      return {
        x: cx, y: cy,
        vx: Math.cos(angle)*speed,
        vy: Math.sin(angle)*speed,
        life: rand(0.4, 1), maxLife: 1,
        r: rand(1.4, 3.2),
        rot: rand(0, PI2),
        rotSpeed: rand(-0.15, 0.15),
        kind: Math.random() < 0.6 ? 'seed' : 'shaving',
      };
    });

    /* Wheel spokes radial vortex (early) */
    const vortex = Array.from({length: 60}, (_, i) => ({
      angle: (PI2/60)*i,
      len: rand(30, 90),
      speed: rand(0.008, 0.022) * (Math.random()<0.5 ? 1 : -1),
      r: rand(100, 160),
    }));

    let cascadeScheduled = false;

    /* draw a tiny rotating wheel */
    function drawWheel(x, y, size, spin, active) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(spin);
      const glow = active ? 'rgba(255,220,120,0.95)' : 'rgba(241,176,74,0.55)';
      // halo
      const g = ctx.createRadialGradient(0,0,0, 0,0, size*2);
      g.addColorStop(0, active ? 'rgba(255,220,120,0.35)' : 'rgba(241,176,74,0.18)');
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(0,0,size*2,0,PI2); ctx.fill();
      // rim
      ctx.strokeStyle = glow;
      ctx.lineWidth = active ? 2.5 : 1.5;
      ctx.beginPath(); ctx.arc(0,0,size,0,PI2); ctx.stroke();
      // spokes
      ctx.strokeStyle = active ? 'rgba(255,220,120,0.8)' : 'rgba(241,176,74,0.5)';
      ctx.lineWidth = 1;
      for (let i = 0; i < 8; i++) {
        const a = (PI2/8)*i;
        ctx.beginPath();
        ctx.moveTo(Math.cos(a)*size*0.25, Math.sin(a)*size*0.25);
        ctx.lineTo(Math.cos(a)*size*0.92, Math.sin(a)*size*0.92);
        ctx.stroke();
      }
      // hub
      ctx.fillStyle = active ? '#ffe2a0' : '#f1b04a';
      ctx.beginPath(); ctx.arc(0,0,size*0.18,0,PI2); ctx.fill();
      ctx.restore();
    }

    /* draw a seed (small almond) */
    function drawSeed(s, alpha) {
      ctx.save();
      ctx.translate(s.x, s.y);
      ctx.rotate(s.rot);
      if (s.kind === 'seed') {
        // sunflower seed: dark almond with cream stripe
        ctx.fillStyle = `rgba(58,36,18,${alpha*0.95})`;
        ctx.beginPath();
        ctx.ellipse(0, 0, s.r*1.4, s.r*0.7, 0, 0, PI2);
        ctx.fill();
        ctx.fillStyle = `rgba(245,220,170,${alpha*0.7})`;
        ctx.beginPath();
        ctx.ellipse(0, 0, s.r*1.1, s.r*0.18, 0, 0, PI2);
        ctx.fill();
      } else {
        // cedar shaving curl
        ctx.strokeStyle = `rgba(201,140,70,${alpha*0.8})`;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(0, 0, s.r*1.6, 0, Math.PI*1.4);
        ctx.stroke();
      }
      ctx.restore();
    }

    function frame(ts) {
      if (!alive) return;
      if (!startT) startT = ts;
      const elapsed = (ts - startT)/1000;

      ctx.clearRect(0, 0, W, H);

      // Background (warm wood gradient)
      const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(W,H)*0.75);
      bg.addColorStop(0,   'rgba(45,28,12,0.97)');
      bg.addColorStop(0.5, 'rgba(28,16,6,0.99)');
      bg.addColorStop(1,   'rgba(10,5,2,1)');
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      // Subtle hex grid (wire mesh of cage)
      drawHexGrid(ctx, W, H, elapsed);

      // Shockwaves
      shockwaves.forEach(sw => {
        if (sw.r > sw.maxR) return;
        sw.r += sw.speed;
        const a = clamp(1 - sw.r/sw.maxR, 0, 1) * sw.alpha;
        ctx.beginPath();
        ctx.arc(cx, cy, sw.r, 0, PI2);
        ctx.strokeStyle = `rgba(241,176,74,${a})`;
        ctx.lineWidth = sw.width;
        ctx.stroke();
      });

      // Vortex (early)
      if (elapsed < 2) {
        const vA = clamp(1 - elapsed/2, 0, 1) * 0.4;
        vortex.forEach(v => {
          v.angle += v.speed;
          const x1 = cx + Math.cos(v.angle)*(v.r*0.3);
          const y1 = cy + Math.sin(v.angle)*(v.r*0.3);
          const x2 = cx + Math.cos(v.angle)*v.r;
          const y2 = cy + Math.sin(v.angle)*v.r;
          ctx.beginPath();
          ctx.moveTo(x1,y1); ctx.lineTo(x2,y2);
          ctx.strokeStyle = `rgba(255,200,120,${vA})`;
          ctx.lineWidth = 0.6;
          ctx.stroke();
        });
      }

      // Update wheels
      wheels.forEach(n => {
        n.angle += n.orbitSpeed;
        n.spin += n.spinSpeed;
        n.x = cx + Math.cos(n.angle)*n.orbitR;
        n.y = cy + Math.sin(n.angle)*n.orbitR;
        if (n.activeCooldown > 0) n.activeCooldown--;
        else n.active = false;
      });

      // Trigger first cascade
      if (elapsed > 0.8 && !cascadeScheduled) {
        cascadeScheduled = true;
        const seedIdx = Math.floor(Math.random()*INNER);
        triggerCascade(seedIdx);
        setInterval(() => {
          if (!alive) return;
          triggerCascade(Math.floor(Math.random()*wheels.length));
          if (Math.random() < 0.5) spawnSpark();
        }, 2500);
      }

      // Edges
      edges.forEach(e => {
        const a = wheels[e.a], b = wheels[e.b];
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.sqrt(dx*dx + dy*dy);
        const maxD = 280;
        if (dist > maxD) return;
        const alpha = (1 - dist/maxD) * 0.10;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = `rgba(241,176,74,${alpha})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
      });

      // Wheels
      wheels.forEach(n => drawWheel(n.x, n.y, n.size, n.spin, n.active));

      // Signals (seeds zipping)
      for (let i = signals.length-1; i >= 0; i--) {
        const sig = signals[i];
        sig.t += sig.speed;
        if (sig.t >= 1) { signals.splice(i, 1); continue; }
        const from = wheels[sig.from], to = wheels[sig.to];
        const px = lerp(from.x, to.x, sig.t);
        const py = lerp(from.y, to.y, sig.t);
        const a = 1 - sig.t*0.5;
        // seed body
        ctx.save();
        ctx.translate(px, py);
        ctx.rotate(Math.atan2(to.y-from.y, to.x-from.x));
        ctx.fillStyle = `hsla(${sig.hue},85%,68%,${a*sig.bright})`;
        ctx.beginPath();
        ctx.ellipse(0,0, 5, 2.4, 0, 0, PI2);
        ctx.fill();
        ctx.restore();
        // trail
        for (let tr = 1; tr <= 4; tr++) {
          const tt = Math.max(0, sig.t - tr*0.025);
          const tx = lerp(from.x, to.x, tt);
          const ty = lerp(from.y, to.y, tt);
          ctx.beginPath();
          ctx.arc(tx, ty, 3.5 - tr*0.6, 0, PI2);
          ctx.fillStyle = `hsla(${sig.hue},85%,68%,${a*sig.bright*(0.25-tr*0.05)})`;
          ctx.fill();
        }
      }

      // Sparks
      for (let i = sparks.length-1; i >= 0; i--) {
        const lt = sparks[i];
        lt.life -= lt.decay;
        if (lt.life <= 0) { sparks.splice(i, 1); continue; }
        const from = wheels[lt.from];
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        lt.segs.forEach(s => ctx.lineTo(s.x, s.y));
        ctx.strokeStyle = `rgba(255,230,140,${lt.life*0.85})`;
        ctx.lineWidth = 1.3;
        ctx.shadowColor = 'rgba(255,200,80,0.8)';
        ctx.shadowBlur = 8;
        ctx.stroke();
        ctx.shadowBlur = 0;
      }

      // Seeds / shavings
      seeds.forEach(s => {
        if (s.life <= 0) return;
        s.life -= 0.007;
        s.x += s.vx; s.y += s.vy;
        s.vx *= 0.991; s.vy *= 0.991;
        s.vy += 0.01; // tiny gravity
        s.rot += s.rotSpeed;
        const a = s.life/s.maxLife;
        drawSeed(s, a);
      });

      // Center glow (breathe)
      const breathe = 0.5 + 0.5*Math.sin(elapsed*1.6);
      const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, 130);
      cg.addColorStop(0,   `rgba(241,176,74,${0.10 + breathe*0.08})`);
      cg.addColorStop(0.6, `rgba(232,96,31,${0.03 + breathe*0.03})`);
      cg.addColorStop(1,   'rgba(241,176,74,0)');
      ctx.fillStyle = cg;
      ctx.fillRect(0, 0, W, H);

      // RPM strip (bottom, replaces EEG)
      drawRPMStrip(ctx, W, H, elapsed);

      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    return () => { alive = false; window.removeEventListener('resize', resize); };
  }

  /* Hex cage grid */
  function drawHexGrid(ctx, W, H, t) {
    const size = 42;
    const cols = Math.ceil(W / (size*1.73)) + 2;
    const rows = Math.ceil(H / (size*1.5)) + 2;
    const alpha = 0.022 + 0.012*Math.sin(t*0.4);
    ctx.strokeStyle = `rgba(241,176,74,${alpha})`;
    ctx.lineWidth = 0.5;
    for (let r = -1; r < rows; r++) {
      for (let c = -1; c < cols; c++) {
        const ox = r % 2 === 0 ? 0 : size*0.865;
        hexPath(ctx, c*size*1.73 + ox, r*size*1.5, size - 2);
        ctx.stroke();
      }
    }
  }
  function hexPath(ctx, x, y, r) {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI/3)*i - Math.PI/6;
      i === 0
        ? ctx.moveTo(x + r*Math.cos(a), y + r*Math.sin(a))
        : ctx.lineTo(x + r*Math.cos(a), y + r*Math.sin(a));
    }
    ctx.closePath();
  }

  /* RPM strip — square wave + pulses, suggesting STEP signal */
  function drawRPMStrip(ctx, W, H, t) {
    const y0 = H - 52;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, y0 - 22, W, 44);
    ctx.clip();

    // step signal
    ctx.strokeStyle = 'rgba(241,176,74,0.45)';
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    const period = 36;
    for (let x = 0; x <= W; x += 1) {
      const phase = ((x + t*120) % period) / period;
      const hi = phase < 0.5;
      const y = y0 + (hi ? -10 : 10);
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();

    // wavy RPM line on top
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(232,96,31,0.55)';
    ctx.lineWidth = 1.4;
    for (let x = 0; x <= W; x += 1) {
      const ph = (x/W)*Math.PI*22 - t*3.2;
      const amp = (Math.sin(ph)*0.55 + Math.sin(ph*2.1+1)*0.25 + Math.sin(ph*0.5)*0.2) * 13;
      x === 0 ? ctx.moveTo(x, y0 + amp) : ctx.lineTo(x, y0 + amp);
    }
    ctx.stroke();
    ctx.restore();
  }

  /* ── Launch ── */
  function launchEgg() {
    const overlay = buildOverlay();

    requestAnimationFrame(() => requestAnimationFrame(() => {
      overlay.style.opacity = '1';
    }));

    const canvas = document.getElementById('mo-main-canvas');
    const stopCanvas = runCanvas(canvas);

    // Texts
    const brand = document.getElementById('hm-brand');
    const sub   = document.getElementById('hm-sub');
    glitchTypewrite(brand, 'MOTORINADOR', 700, 50, () => {
      glitchTypewrite(sub, 'POWERED BY HÁMSTERS · CEDAR EDITION', 150, 28);
    });

    // author credit pulses gently
    setTimeout(() => {
      const auth = document.getElementById('hm-author');
      if (auth) auth.style.animation = 'hmIn 0.6s ease both, hmGlow 2.4s ease-in-out 0.6s infinite alternate';
    }, 3000);

    // Animate fake RPM HUD
    let hudRpm = 0;
    const hudEl = document.getElementById('hudRpm');
    const hudInt = setInterval(() => {
      hudRpm = Math.min(120, hudRpm + Math.random()*8);
      if (hudEl) hudEl.textContent = hudRpm.toFixed(1).padStart(5,'0');
    }, 90);

    function close() {
      overlay.style.opacity = '0';
      overlay.style.transition = 'opacity 0.5s ease';
      stopCanvas();
      clearInterval(hudInt);
      setTimeout(() => {
        overlay.remove();
        const s = document.getElementById('hm-egg-styles');
        if (s) s.remove();
      }, 500);
    }

    overlay.addEventListener('click', close);
    document.addEventListener('keydown', function onKey(e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); }
    });
    setTimeout(close, 10000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLogoTrigger);
  } else {
    initLogoTrigger();
  }
})();
