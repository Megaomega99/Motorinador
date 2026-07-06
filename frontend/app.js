/* =============================================================
   Motorinador — lógica de la interfaz
   Se comunica con el backend FastAPI vía WebSocket (/ws).
   Los límites de RPM (min/max/step) los dicta el backend en el
   mensaje 'params'; el HTML solo trae valores por defecto.
   ============================================================= */

/* ===== State ===== */
const state = {
  targetRPM:   30,
  realRPM:     0,
  dir:         1,
  running:     false,
  radiusCm:    12,
  stepsRev:    200,
  microsteps:  8,
  encPpr:      600,
  debounce:    50,
  angleDeg:    0,
  startedAt:   null,
  wsConnected: false,
  lastStatusTs: 0,     // llegada del último frame de estado (frescura del encoder)
  // PI controller
  usePid:     false,
  measuredRpm: 0,
  piError:     0,
  controlRpm:  0,
};

/* ===== Log ===== */
const logEl = document.getElementById('log');
function ts() { return new Date().toTimeString().slice(0,8); }
function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function logRaw(html, cls='') {
  const div = document.createElement('div');
  div.innerHTML = `<span class="ts">[${ts()}]</span> ${html}`;
  if (cls) div.classList.add(cls);
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
  while (logEl.children.length > 200) logEl.removeChild(logEl.firstChild);
}
function logLine(msg, cls='') { logRaw(escapeHtml(msg), cls); }
function fmt(n, d=1) { return (+n).toFixed(d); }

/* ===== WebSocket ===== */
const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;
let ws = null;

function wsConnect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    state.wsConnected = true;
    document.getElementById('liveDot').textContent = 'CONECTADO';
    logRaw('<span class="ok">WS</span> Backend conectado');
  };
  ws.onclose = () => {
    state.wsConnected = false;
    ledPower.classList.remove('on');
    ledEnc.classList.remove('on');
    state.realRPM = 0;
    applyRunningState(false);
    document.getElementById('liveDot').textContent = 'DESCONECTADO';
    logRaw('<span class="err">WS</span> Backend desconectado — reintentando en 3 s...', 'err');
    setTimeout(wsConnect, 3000);
  };
  ws.onerror = () => {
    logRaw('<span class="err">WS</span> Error de conexión', 'err');
  };
  ws.onmessage = (e) => {
    let m;
    try { m = JSON.parse(e.data); } catch { return; }
    switch (m.type) {
      case 'status': {
        const d = m.data;
        const prevPid = state.usePid;
        state.usePid = !!d.use_pid;

        state.targetRPM = d.target_rpm;
        if (d.measured_rpm != null) state.measuredRpm = d.measured_rpm;
        if (d.pi_error     != null) state.piError     = d.pi_error;
        if (d.control_rpm  != null) state.controlRpm  = d.control_rpm;
        state.realRPM  = d.real_rpm;
        state.angleDeg = d.angle_deg;

        const newDir = d.dir === 'FWD' ? 1 : -1;
        if (newDir !== state.dir) {
          state.dir = newDir;
          document.querySelectorAll('#dirSeg button').forEach(x => x.classList.remove('on'));
          const sel = document.querySelector(`#dirSeg button[data-v="${d.dir === 'FWD' ? 'fwd' : 'rev'}"]`);
          if (sel) sel.classList.add('on');
        }
        state.running = d.running;
        state.lastStatusTs = performance.now();
        ledEnc.classList.add('on');
        applyRunningState(d.running);

        if (prevPid !== state.usePid) applyPidMode(state.usePid);

        syncSliderDisplay();
        updateGauges();
        break;
      }
      case 'log': {
        const lvl = m.level === 'error' ? 'err' : m.level === 'warn' ? 'warn' : 'ok';
        logLine(m.msg, lvl);
        break;
      }
      case 'params': {
        const p = m.data;
        state.radiusCm   = p.radius_cm;
        state.stepsRev   = p.steps_per_rev;
        state.microsteps = p.microsteps;
        state.encPpr     = p.enc_ppr;
        state.debounce   = p.debounce_us;
        // Los límites de RPM son propiedad del servidor: se aplican a los inputs.
        if (p.rpm_min  != null) { rpm.min  = p.rpm_min;  rpmNum.min  = p.rpm_min;  }
        if (p.rpm_max  != null) { rpm.max  = p.rpm_max;  rpmNum.max  = p.rpm_max;  }
        if (p.rpm_step != null) { rpm.step = p.rpm_step; rpmNum.step = p.rpm_step; }
        syncParamInputs();
        updateTelemetry();
        break;
      }
      case 'ready':
        ledPower.classList.add('on');
        logRaw(`<span class="ok">FW</span> ${escapeHtml(m.firmware)}`, 'ok');
        break;
      case 'error':
        ledPower.classList.remove('on');
        ledEnc.classList.remove('on');
        logRaw(`<span class="err">ERR</span> ${escapeHtml(m.msg)}`, 'err');
        break;
    }
  };
}

function wsSend(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
}

/* ===== PID mode switch ===== */
function applyPidMode(pid) {
  // Seg buttons
  document.querySelectorAll('#modeSeg button').forEach(x => x.classList.remove('on'));
  const btn = document.querySelector(`#modeSeg button[data-v="${pid ? 'pid' : 'libre'}"]`);
  if (btn) btn.classList.add('on');

  // Show/hide control sections (slider visible in both modes; PI card only in PI mode)
  document.getElementById('libreControls').style.display = '';
  document.getElementById('pidControls').style.display   = pid ? '' : 'none';

  // LED badge
  const ledPidEl = document.getElementById('ledPid');
  const modeTag  = document.getElementById('ledModeTag');
  if (pid) {
    ledPidEl.className = 'led pid';
    modeTag.textContent = 'PID';
    modeTag.style.color = 'var(--pid)';
    modeTag.style.fontWeight = '700';
  } else {
    ledPidEl.className = 'led warn';
    modeTag.textContent = 'LIBRE';
    modeTag.style.color = '';
    modeTag.style.fontWeight = '';
  }

  // Stage title
  const stageTitle = document.getElementById('stageTitle');
  stageTitle.innerHTML = pid
    ? 'El <em class="pid-em">PI</em> controla la velocidad'
    : 'El <em>hámster</em> corre en su rueda';

  // Gauge styles (solo el gauge objetivo cambia de acento; unidades fijas)
  document.getElementById('g1').classList.toggle('pid-mode', pid);

  updateGauges();
}

/* ===== Param sync ===== */
function syncParamInputs() {
  document.getElementById('radius').value     = state.radiusCm;
  document.getElementById('stepsRev').value   = state.stepsRev;
  document.getElementById('microsteps').value = state.microsteps;
  document.getElementById('encPpr').value     = state.encPpr;
  document.getElementById('debounce').value   = state.debounce;
  syncSliderDisplay();
}

function syncSliderDisplay() {
  const min = +rpm.min, max = +rpm.max;
  const clamped = Math.min(max, Math.max(min, state.targetRPM));
  rpm.value = clamped;
  rpmNum.value = clamped;
  rpmUnit.textContent = clamped + ' rpm';
  rpm.style.setProperty('--p', ((clamped - min) / (max - min) * 100) + '%');
}

function sendParams() {
  // rpm_min/rpm_max/rpm_step NO se envían: son propiedad del servidor.
  wsSend({
    type: 'set_params',
    data: {
      radius_cm:     state.radiusCm,
      steps_per_rev: state.stepsRev,
      microsteps:    state.microsteps,
      enc_ppr:       state.encPpr,
      debounce_us:   state.debounce,
    }
  });
}

/* ===== UI bindings ===== */
const rpm     = document.getElementById('rpm');
const rpmNum  = document.getElementById('rpmNum');
const rpmUnit = document.getElementById('rpmUnit');

function sendTarget(value) {
  const min = +rpm.min, max = +rpm.max;
  state.targetRPM = Math.min(max, Math.max(min, value));
  syncSliderDisplay();
  updateGauges();
  wsSend({ type: 'set_target', rpm: state.targetRPM });
  logRaw(`<span class="v">CMD</span> Target → <b>${state.targetRPM} RPM</b>`);
}

rpm.addEventListener('input', () => sendTarget(+rpm.value));
rpmNum.addEventListener('change', () => sendTarget(Math.round(+rpmNum.value || +rpm.min)));
syncSliderDisplay();

/* Mode toggle — comandos absolutos e idempotentes */
document.getElementById('modeSeg').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  const wantPid = b.dataset.v === 'pid';
  if (wantPid !== state.usePid) {
    wsSend({ type: 'cmd', cmd: wantPid ? 'mode_pi' : 'mode_libre' });
    logRaw(`<span class="pid">MODE</span> ${wantPid ? 'Activando PI (lazo cerrado)…' : 'Desactivando PI (lazo abierto)…'}`);
  }
});

document.getElementById('dirSeg').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#dirSeg button').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  const newDir = b.dataset.v === 'fwd' ? 1 : -1;
  if (newDir !== state.dir) {
    state.dir = newDir;
    wsSend({ type: 'cmd', cmd: newDir > 0 ? 'dir_fwd' : 'dir_rev' });
    logRaw(`<span class="v">DIR</span> ${state.dir>0?'FWD ↻':'REV ↺'}`);
  }
});

document.getElementById('radius').addEventListener('input', e => {
  state.radiusCm = Math.max(0.1, +e.target.value || 0.1); sendParams(); updateGauges();
});
document.getElementById('stepsRev').addEventListener('input', e => {
  state.stepsRev = Math.max(1, +e.target.value || 200); sendParams(); updateTelemetry();
});
document.getElementById('microsteps').addEventListener('change', e => {
  state.microsteps = +e.target.value; sendParams(); updateTelemetry();
});
document.getElementById('encPpr').addEventListener('input', e => {
  state.encPpr = Math.max(1, +e.target.value || 600); sendParams(); updateTelemetry();
});
document.getElementById('debounce').addEventListener('input', e => {
  state.debounce = Math.max(0, +e.target.value || 0); sendParams();
});

/* command pills */
document.body.addEventListener('click', e => {
  const b = e.target.closest('[data-cmd]'); if (!b) return;
  const cmd = b.dataset.cmd;
  if (cmd === '+' || cmd === '-') {
    const stepV = +rpm.step || 1;
    sendTarget(+rpm.value + (cmd === '+' ? stepV : -stepV));
  } else if (cmd === 'z') {
    wsSend({ type: 'cmd', cmd: 'zero_encoder' });
    logRaw('<span class="ok">ENC</span> Encoder → 0');
  } else if (cmd === 'estop') {
    wsSend({ type: 'cmd', cmd: 'e_stop' });
    logRaw('<span class="err">⚠ E-STOP</span> paro de emergencia — driver desenergizado', 'err');
  } else if (cmd === 'clr') {
    logEl.innerHTML = '';
  }
});

/* big button */
const startBtn  = document.getElementById('startBtn');
const stageHead = document.getElementById('stageHead');
const liveDot   = document.getElementById('liveDot');
const ledMotor  = document.getElementById('ledMotor');
const ledPower  = document.getElementById('ledPower');
const ledEnc    = document.getElementById('ledEnc');

function applyRunningState(running) {
  if (running) {
    if (!state.startedAt) state.startedAt = performance.now();
    startBtn.classList.add('running');
    startBtn.querySelector('.lbl').textContent    = '■ DETENER';
    startBtn.querySelector('.action').textContent = 'PARAR';
    stageHead.classList.add('live');
    liveDot.textContent = 'CORRIENDO';
    ledMotor.classList.add('on');
  } else {
    state.startedAt = null;
    startBtn.classList.remove('running');
    startBtn.querySelector('.lbl').textContent    = '▶ INICIAR';
    startBtn.querySelector('.action').textContent = 'CORRER';
    stageHead.classList.remove('live');
    liveDot.textContent = state.wsConnected ? 'CONECTADO' : 'EN ESPERA';
    ledMotor.classList.remove('on');
  }
}

startBtn.addEventListener('click', () => {
  wsSend({ type: 'cmd', cmd: state.running ? 'stop' : 'start' });
});

/* ===== Wheel rungs ===== */
(function makeRungs(){
  const rungs = document.getElementById('rungs');
  const N = 28, R = 133;
  for (let i=0;i<N;i++){
    const a = (i/N)*Math.PI*2;
    const ln = document.createElementNS('http://www.w3.org/2000/svg','line');
    ln.setAttribute('x1',(Math.cos(a)*R).toFixed(2));
    ln.setAttribute('y1',(Math.sin(a)*R).toFixed(2));
    ln.setAttribute('x2',(Math.cos(a)*(R-12)).toFixed(2));
    ln.setAttribute('y2',(Math.sin(a)*(R-12)).toFixed(2));
    rungs.appendChild(ln);
  }
})();

/* ===== Gauges & telemetry ===== */
function updateTelemetry() {
  const spr   = state.stepsRev * state.microsteps;
  const fStep = Math.abs(state.realRPM) * spr / 60;
  const tHalf = fStep > 0.01 ? 0.5e6/fStep : 0;
  const perim = 2 * Math.PI * state.radiusCm;
  document.getElementById('tStepF').textContent = fStep.toFixed(0);
  document.getElementById('tHalf').textContent  = tHalf.toFixed(0);
  document.getElementById('tCpr').textContent   = state.encPpr * 4;
  document.getElementById('tPerim').textContent = perim.toFixed(1);
}

/* Los tres gauges tienen significado fijo en ambos modos:
   objetivo (RPM) · real medida por encoder (RPM) · lineal v=ωr (m/s).
   La salida del PI se muestra en la tarjeta "Estado PI". */
function updateGauges() {
  document.getElementById('gTarget').textContent = fmt(state.targetRPM, 1);
  document.getElementById('gReal').textContent   = fmt(state.realRPM, 1);
  const omega = state.realRPM * 2 * Math.PI / 60;
  const v = omega * (state.radiusCm / 100);
  document.getElementById('gLin').textContent = fmt(v, 2);

  if (state.usePid) {
    document.getElementById('piTgtRpm').textContent = fmt(state.targetRPM, 1);
    document.getElementById('piMeas').textContent   = fmt(state.measuredRpm, 1);
    document.getElementById('piErr').textContent    = fmt(state.piError, 2);
    document.getElementById('piCtrl').textContent   = fmt(state.controlRpm, 1);
  }
  document.getElementById('gAng').textContent = fmt(state.angleDeg, 1) + '°';
  updateTelemetry();
}

/* ===== Animation loop ===== */
const wheelEl   = document.getElementById('wheel');
const tailEl    = document.getElementById('mouseTail');
const headEl    = document.getElementById('mouseHead');
const legBL = document.getElementById('legBackL');
const legBR = document.getElementById('legBackR');
const legFL = document.getElementById('legFrontL');
const legFR = document.getElementById('legFrontR');
const speedLines = document.getElementById('speedLines');

const ENC_STALE_MS = 2500;   // >2 frames de 1 Hz sin llegar → dato viciado

let wheelAngle = 0;
let lastT = performance.now();

function tick(now) {
  const dt = Math.min(0.1, (now - lastT)/1000); lastT = now;

  const degPerSec = state.realRPM * 6;  // signo embebido en realRPM (+ FWD, − REV)
  wheelAngle = (wheelAngle + degPerSec * dt) % 360;
  wheelEl.setAttribute('transform', `translate(260 180) rotate(${wheelAngle})`);

  const cyc = (now/1000) * Math.max(2, Math.abs(state.realRPM)/8);
  const sw  = Math.sin(cyc*Math.PI*2);
  const sw2 = Math.sin(cyc*Math.PI*2 + Math.PI);
  legBL.setAttribute('transform', `translate(0 ${sw>0?sw*4:0}) rotate(${sw*18} -12 5)`);
  legBR.setAttribute('transform', `translate(0 ${sw2>0?sw2*4:0}) rotate(${sw2*18} 8 5)`);
  legFL.setAttribute('transform', `translate(0 ${sw2>0?sw2*3:0}) rotate(${sw2*22} 18 5)`);
  legFR.setAttribute('transform', `translate(0 ${sw>0?sw*3:0}) rotate(${sw*22} 26 5)`);

  const bob = Math.sin(cyc*Math.PI*4) * Math.min(2, Math.abs(state.realRPM)/40);
  document.getElementById('mouse').setAttribute('transform', `translate(260 ${295+bob})`);

  const wag = Math.sin(now/180) * Math.min(20, Math.abs(state.realRPM)/3);
  tailEl.setAttribute('d', `M -34 4 q -22 ${-8-wag*0.3} -38 ${6+wag}`);
  headEl.setAttribute('transform', `translate(28 ${-6+bob*0.4}) rotate(${Math.sin(cyc*Math.PI*2)*4})`);

  const speedAlpha = Math.min(1, Math.max(0, (Math.abs(state.realRPM)-25)/95));
  speedLines.setAttribute('opacity', speedAlpha.toFixed(2));
  if (speedAlpha > 0.05 && Math.random() < 0.35) {
    while (speedLines.children.length > 14) speedLines.removeChild(speedLines.firstChild);
    const y  = 250 + Math.random()*70;
    const fwd = state.realRPM >= 0;   // signo embebido en realRPM
    const xs = fwd ? 90+Math.random()*120 : 320+Math.random()*120;
    const xe = xs + (fwd ? -30-Math.random()*40 : 30+Math.random()*40);
    const ln = document.createElementNS('http://www.w3.org/2000/svg','line');
    ln.setAttribute('x1', xs.toFixed(1)); ln.setAttribute('y1', y.toFixed(1));
    ln.setAttribute('x2', xe.toFixed(1)); ln.setAttribute('y2', y.toFixed(1));
    ln.setAttribute('opacity', (0.5+Math.random()*0.4).toFixed(2));
    speedLines.appendChild(ln);
    setTimeout(() => ln.remove(), 350);
  }

  // Frescura del encoder: si no llegan frames de estado, apagar el LED
  if (state.lastStatusTs && (now - state.lastStatusTs) > ENC_STALE_MS) {
    ledEnc.classList.remove('on');
  }

  updateGauges();

  if (state.running && state.startedAt) {
    const s  = Math.floor((now - state.startedAt)/1000);
    const mm = String(Math.floor(s/60)).padStart(2,'0');
    const ss = String(s%60).padStart(2,'0');
    document.getElementById('tElapsed').textContent = `${mm}:${ss}`;
  }

  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

/* boot */
logRaw('===  NEMA17 + TMC2208 + ENCODER + PI  ===','ok');
logRaw(`Conectando a <span class="v">${WS_URL}</span>…`);
logRaw('Modos: <span class="v">LIBRE</span> (velocidad) · <span class="pid">PI</span> (velocidad lazo cerrado)');
wsConnect();
