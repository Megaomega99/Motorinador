/* =============================================================
   Motorinador — vista de análisis offline.

   Habla con /api/analysis/*, que envuelve el MISMO motor de cálculo que la app
   de escritorio (paquete `analysis/`). Aquí no se calcula nada: el servidor
   manda las series ya decimadas y esto solo las dibuja y gestiona la interacción.

   Nombres con prefijo AN_ / an* para no chocar con app.js, que comparte el
   ámbito global de la página.
   ============================================================= */

const AN = {
  meta: null,          // metadatos de la sesión abierta
  overview: null,      // serie de toda la sesión (para la tira de navegación)
  stack: null,         // ChartStack de los cuatro paneles
  stripChart: null,    // tira de vista general
  charts: {},          // panel → TimeChart
  gearRatio: 1.986,
  pending: null,       // petición de ventana en vuelo (para no encadenar)
  needsFetch: false,
  timer: null,
  browsePath: null,
};

const AN_FETCH_DEBOUNCE_MS = 130;

/* Colores coherentes con la app de escritorio y con la paleta del sitio. */
const AN_COLORS = {
  angle:    '#3a6ea8',
  velocity: '#d92b1f',
  cmd:      '#4b7a2a',
  meas:     '#8b5cc7',
  elec:     ['#2a1c10', '#e8601f', '#3a6ea8', '#6a8a3e', '#a01a11', '#8b5cc7'],
};

function anEl(id) { return document.getElementById(id); }

function anStatus(text, kind = '') {
  const el = anEl('anStatus');
  el.textContent = text;
  el.className = 'an-status' + (kind ? ' ' + kind : '');
}

function anLog(msg, cls) {
  // Reutiliza la consola de la vista de control si está disponible.
  if (typeof logRaw === 'function') logRaw(`<span class="v">ANÁLISIS</span> ${msg}`, cls);
}

async function anApi(path, opts = {}) {
  const res = await fetch(`/api/analysis${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* sin cuerpo JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ===== Navegador de archivos ===== */

async function anBrowse(path) {
  try {
    const listing = await anApi('/browse' + (path ? `?path=${encodeURIComponent(path)}` : ''));
    AN.browsePath = listing.path;
    anRenderBrowser(listing);
  } catch (err) {
    anStatus(`No se pudo listar: ${err.message}`, 'err');
  }
}

function anRenderBrowser(listing) {
  anEl('anCwd').textContent = listing.path;
  const list = anEl('anFileList');
  list.innerHTML = '';

  const row = (label, sub, onClick, cls = '') => {
    const div = document.createElement('div');
    div.className = 'an-row ' + cls;
    div.innerHTML = `<span class="an-row-name"></span><span class="an-row-sub"></span>`;
    div.querySelector('.an-row-name').textContent = label;
    div.querySelector('.an-row-sub').textContent = sub || '';
    div.addEventListener('click', onClick);
    list.appendChild(div);
  };

  if (listing.parent) row('..', 'subir', () => anBrowse(listing.parent), 'dir');

  // Si la carpeta actual ES una sesión partida en varios archivos, ofrecerla entera.
  if (listing.is_session) {
    row(`▶ Abrir esta sesión completa`,
        `${listing.session_files} archivos como una sola grabación`,
        () => anOpen(listing.path, true), 'session');
  }

  for (const d of listing.dirs) {
    const sub = d.session_files > 1 ? `sesión · ${d.session_files} archivos`
              : d.session_files === 1 ? '1 grabación' : 'carpeta';
    row(d.name + '/', sub, () => anBrowse(d.path), 'dir');
  }
  for (const f of listing.files) {
    row(f.name, `${f.size_mb} MB`, () => anOpen(f.path, false), 'file');
  }
  if (!listing.dirs.length && !listing.files.length && !listing.is_session) {
    row('(vacío)', '', () => {}, 'muted');
  }
}

/* ===== Apertura y progreso ===== */

async function anOpen(path, wholeSession) {
  anEl('anBrowser').classList.add('busy');
  anStatus(wholeSession ? 'Procesando la sesión completa…' : 'Procesando…');
  try {
    await anApi('/open', {
      method: 'POST',
      body: JSON.stringify({ path, whole_session: wholeSession }),
    });
    anLog(`Abriendo ${path}`);
    anPollProgress();
  } catch (err) {
    anEl('anBrowser').classList.remove('busy');
    anStatus(`Error al abrir: ${err.message}`, 'err');
  }
}

async function anPollProgress() {
  try {
    const p = await anApi('/progress');
    anEl('anProgress').value = p.fraction;
    if (p.state === 'building') {
      anStatus(`${p.message} ${(p.fraction * 100).toFixed(0)} %`);
      setTimeout(anPollProgress, 250);
      return;
    }
    anEl('anBrowser').classList.remove('busy');
    anEl('anProgress').value = 0;
    if (p.state === 'error') {
      anStatus(`Error: ${p.message}`, 'err');
      anLog(p.message, 'err');
      return;
    }
    if (p.state === 'ready') {
      anStatus(p.message, 'ok');
      await anLoadSession();
    }
  } catch (err) {
    anEl('anBrowser').classList.remove('busy');
    anStatus(`Error: ${err.message}`, 'err');
  }
}

/* ===== Carga de la sesión ===== */

async function anLoadSession() {
  AN.meta = await anApi('/meta');
  anRenderMeta();
  AN.overview = await anApi(`/overview?points=3000`);
  anBuildCharts();
  // Arrancar mostrando los primeros 10 s (o toda la sesión si es más corta).
  const dur = AN.meta.duration_s;
  AN.stack.setBounds(0, dur).setRange(0, Math.min(10, dur));
  anRenderStrip();
  anEl('anWorkspace').classList.add('ready');
}

function anRenderMeta() {
  const m = AN.meta;
  anEl('anMetaPath').textContent = m.path || '—';
  anEl('anMetaSamples').textContent = m.n_samples.toLocaleString('es');
  anEl('anMetaDur').textContent = `${m.duration_s.toFixed(2)} s`;
  anEl('anMetaFs').textContent = `${(m.sample_rate_hz / 1000).toFixed(0)} kHz`;
  anEl('anMetaParts').textContent = m.n_parts > 1 ? `${m.n_parts} archivos` : '1 archivo';
  anEl('anMetaMotor').textContent = m.has_motor ? (m.motor_channel || 'sí') : 'no grabada';
  anEl('anMetaMotor').className = m.has_motor ? 'ok' : 'warn';

  // Electrodos: lista de selección múltiple, con los tres primeros preseleccionados.
  const sel = anEl('anElectrodes');
  sel.innerHTML = '';
  m.electrodes.forEach((name, i) => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    opt.selected = i < 3;
    sel.appendChild(opt);
  });

  // Relación de engranajes: se mide de los datos y se adopta.
  const g = m.gearing;
  if (g && g.ratio != null) {
    AN.gearRatio = g.ratio;
    anEl('anGearRatio').value = g.ratio.toFixed(4);
    anEl('anGearInfo').textContent =
      `Medido ${g.ratio.toFixed(4)} en ${g.n_steady} ventanas · ` +
      `pérdida de paso en ${g.n_stall} (${g.stall_pct.toFixed(1)} %)`;
    anEl('anGearInfo').className = 'an-note' + (g.stall_pct > 5 ? ' warn' : '');
  } else {
    anEl('anGearInfo').textContent = m.has_motor
      ? 'Sin tramos de consigna estable para medir.'
      : 'Sin ANALOG-IN-2: no se puede medir.';
    anEl('anGearInfo').className = 'an-note';
  }
}

/* ===== Construcción de los paneles ===== */

function anBuildCharts() {
  const specs = [
    ['elec', 'Electrodos (µV)'],
    ['angle', 'Ángulo'],
    ['vel', 'Vel. encoder'],
    ['motor', 'Motor (RPM)'],
  ];
  AN.charts = {};
  const charts = specs.map(([key, label], i) => {
    const ch = new TimeChart(anEl(`anCanvas_${key}`), {
      ylabel: label,
      showXAxis: i === specs.length - 1,
    });
    ch.setEmptyText(key === 'motor' && !AN.meta.has_motor
      ? 'Esta grabación no incluye ANALOG-IN-2 (espejo STEP)'
      : 'sin datos');
    AN.charts[key] = ch;
    return ch;
  });

  AN.stack = new ChartStack(charts, {
    bounds: [0, AN.meta.duration_s],
    minSpan: 0.002,
    onRangeChange: () => { anScheduleFetch(); anRenderStrip(); },
    onCursor: anRenderCursor,
  });

  // Tira de vista general: clic o arrastre para saltar.
  // Etiqueta corta: la tira mide ~76 px de alto y el texto va rotado, así que
  // "RPM motor (consigna)" se cortaría a la mitad.
  AN.stripChart = new TimeChart(anEl('anCanvasStrip'),
                                { ylabel: anStripLabel() });
  AN.stripChart.setXRange(0, AN.meta.duration_s);
  const strip = anEl('anCanvasStrip');
  const seek = ev => {
    const t = AN.stripChart.timeAtEvent(ev);
    if (t == null) return;
    const span = AN.stack.t1 - AN.stack.t0;
    AN.stack.setRange(t - span / 2, t + span / 2);
  };
  strip.style.cursor = 'pointer';
  strip.addEventListener('mousedown', ev => { AN._stripDrag = true; seek(ev); });
  strip.addEventListener('mousemove', ev => { if (AN._stripDrag) seek(ev); });
  window.addEventListener('mouseup', () => { AN._stripDrag = false; });

  // Los paneles miden según su tamaño CSS, que ahora depende del alto de la
  // ventana: al redimensionar hay que volver a dibujar. El ChartStack ya cuida
  // de los suyos; la tira va aparte. Solo se registra una vez.
  if (!AN._resizeBound) {
    AN._resizeBound = true;
    window.addEventListener('resize', () => anRenderStrip());
  }
}

function anStripLabel() {
  return AN.overview.kind === 'motor' ? 'RPM motor' : 'RPM enc.';
}

function anRenderStrip() {
  if (!AN.stripChart || !AN.overview) return;
  AN.stripChart.ylabel = anStripLabel();
  AN.stripChart
    .setSeries([{
      t: AN.overview.t, y: AN.overview.y,
      color: AN.overview.kind === 'motor' ? AN_COLORS.cmd : AN_COLORS.velocity,
      width: 1,
    }])
    .setXRange(0, AN.meta.duration_s)
    .setSelection([AN.stack.t0, AN.stack.t1])
    .draw();
}

/* ===== Petición de la ventana visible ===== */

function anScheduleFetch() {
  AN.needsFetch = true;
  if (AN.timer) return;
  AN.timer = setTimeout(async () => {
    AN.timer = null;
    if (!AN.needsFetch) return;
    AN.needsFetch = false;
    await anFetchWindow();
    // Si llegaron más cambios mientras se pedía, volver a lanzar.
    if (AN.needsFetch) anScheduleFetch();
  }, AN_FETCH_DEBOUNCE_MS);
}

function anSelectedElectrodes() {
  return Array.from(anEl('anElectrodes').selectedOptions).map(o => o.value);
}

async function anFetchWindow() {
  if (!AN.meta) return;
  const body = {
    t0: AN.stack.t0,
    t1: AN.stack.t1,
    electrodes: anSelectedElectrodes(),
    angle_unit: anEl('anAngleUnit').value,
    vel_unit: anEl('anVelUnit').value,
    window_ms: +anEl('anWindowMs').value || 50,
    motor_window_ms: +anEl('anMotorWindowMs').value || 500,
    gear_ratio: AN.gearRatio,
    wrap_angle: anEl('anWrap').checked,
    points: 2000,
  };
  try {
    const w = await anApi('/window', { method: 'POST', body: JSON.stringify(body) });
    anRenderWindow(w);
  } catch (err) {
    anStatus(`Error al leer la ventana: ${err.message}`, 'err');
  }
}

function anRenderWindow(w) {
  AN.lastWindow = w;

  // Electrodos
  const elecSeries = Object.entries(w.electrodes).map(([name, s], i) => ({
    t: s.t, y: s.y, label: name, width: 0.8,
    color: AN_COLORS.elec[i % AN_COLORS.elec.length],
  }));
  AN.charts.elec.setSeries(elecSeries);

  AN.charts.angle.setSeries(
    [{ t: w.angle.t, y: w.angle.y, color: AN_COLORS.angle, width: 1 }]);
  AN.charts.angle.ylabel = `Ángulo (${w.angle_unit})`;

  AN.charts.vel.setSeries(
    [{ t: w.velocity.t, y: w.velocity.y, color: AN_COLORS.velocity, width: 1 }]);
  AN.charts.vel.ylabel = `Vel. encoder (${w.vel_unit})`;

  if (w.motor) {
    AN.charts.motor.setSeries([
      { t: w.motor.commanded.t, y: w.motor.commanded.y, color: AN_COLORS.cmd,
        width: 1.4, label: 'Comandada (STEP)' },
      { t: w.motor.measured.t, y: w.motor.measured.y, color: AN_COLORS.meas,
        width: 0.9, alpha: 0.9, label: `Medida (encoder ÷ ${AN.gearRatio.toFixed(3)})` },
    ]);
    anRenderMotorSummary(w.motor.summary);
  } else {
    AN.charts.motor.setSeries([]);
    anEl('anMotorSummary').textContent = 'sin señal de motor';
    anEl('anMotorSummary').className = 'an-summary muted';
  }

  anRenderStats(w.stats);
  anEl('anRangeInfo').textContent =
    `${w.t0.toFixed(3)} – ${w.t1.toFixed(3)} s  ·  ${w.n_samples.toLocaleString('es')} muestras`;
  AN.stack.draw();
}

function anRenderMotorSummary(s) {
  const el = anEl('anMotorSummary');
  el.textContent = s.text;
  const bad = (s.slip_pct || 0) > 10;
  el.className = 'an-summary' + (bad ? ' bad' : ' ok');
}

function anRenderStats(st) {
  const rows = [
    ['Muestras', st.n.toLocaleString('es')],
    ['Media (con signo)', `${st.mean.toFixed(3)} ${st.unit}`],
    ['Media |·|', `${st.mean_abs.toFixed(3)} ${st.unit}`],
    ['Desv. típica', `${st.std.toFixed(3)} ${st.unit}`],
    ['Mínimo', `${st.vmin.toFixed(3)} ${st.unit}`],
    ['Máximo', `${st.vmax.toFixed(3)} ${st.unit}`],
    ['Mediana', `${st.median.toFixed(3)} ${st.unit}`],
  ];
  // Se construye con textContent (no innerHTML) para no interpretar el contenido.
  const box = anEl('anStats');
  box.innerHTML = '';
  for (const [label, value] of rows) {
    const div = document.createElement('div');
    const k = document.createElement('span');
    const v = document.createElement('b');
    k.textContent = label;
    v.textContent = value;
    div.append(k, v);
    box.appendChild(div);
  }
}

function anRenderCursor(t, readouts) {
  const el = anEl('anCursor');
  if (t == null) { el.textContent = ''; return; }
  const parts = readouts
    .filter(r => r.value != null && isFinite(r.value))
    .map(r => `${r.label || '·'}: ${window.chartUtils.fmtVal(r.value)}`);
  el.textContent = `t = ${t.toFixed(4)} s` + (parts.length ? `   ${parts.join('   ')}` : '');
}

/* ===== Exportación ===== */

async function anExport(wholeSession) {
  if (!AN.meta) return;
  const name = anEl('anExportName').value.trim();
  if (!name) { anStatus('Pon un nombre de archivo para exportar.', 'err'); return; }
  const body = {
    t0: AN.stack.t0, t1: AN.stack.t1,
    electrodes: anSelectedElectrodes(),
    angle_unit: anEl('anAngleUnit').value,
    vel_unit: anEl('anVelUnit').value,
    window_ms: +anEl('anWindowMs').value || 50,
    motor_window_ms: +anEl('anMotorWindowMs').value || 500,
    gear_ratio: AN.gearRatio,
    wrap_angle: anEl('anWrap').checked,
    out_path: name,
    whole_session: wholeSession,
  };
  try {
    const r = await anApi('/export', { method: 'POST', body: JSON.stringify(body) });
    anStatus(`Exportando a ${r.out_path}…`);
    anPollExport();
  } catch (err) {
    anStatus(`Error al exportar: ${err.message}`, 'err');
  }
}

async function anPollExport() {
  try {
    const p = await anApi('/export/progress');
    anEl('anProgress').value = p.fraction;
    if (p.state === 'building') {
      anStatus(`Exportando… ${(p.fraction * 100).toFixed(0)} %`);
      setTimeout(anPollExport, 300);
      return;
    }
    anEl('anProgress').value = 0;
    anStatus(p.message, p.state === 'error' ? 'err' : 'ok');
    anLog(p.message, p.state === 'error' ? 'err' : 'ok');
  } catch (err) {
    anStatus(`Error: ${err.message}`, 'err');
  }
}

/* ===== Cableado de controles ===== */

function anBindControls() {
  for (const id of ['anAngleUnit', 'anVelUnit', 'anWindowMs', 'anMotorWindowMs', 'anWrap']) {
    anEl(id).addEventListener('change', anScheduleFetch);
  }
  anEl('anElectrodes').addEventListener('change', anScheduleFetch);

  anEl('anGearRatio').addEventListener('change', e => {
    const v = +e.target.value;
    // El backend rechaza <= 0: dividiría por cero al referir el encoder al motor.
    AN.gearRatio = v > 0 ? v : AN.gearRatio;
    anEl('anGearRatio').value = AN.gearRatio;
    anScheduleFetch();
  });

  anEl('anZoomAll').addEventListener('click', () => {
    if (AN.stack) AN.stack.setRange(0, AN.meta.duration_s);
  });
  for (const [id, span] of [['anWin1', 1], ['anWin5', 5], ['anWin20', 20]]) {
    anEl(id).addEventListener('click', () => {
      if (!AN.stack) return;
      const c = (AN.stack.t0 + AN.stack.t1) / 2;
      AN.stack.setRange(c - span / 2, c + span / 2);
    });
  }

  anEl('anExportWindow').addEventListener('click', () => anExport(false));
  anEl('anExportAll').addEventListener('click', () => anExport(true));
  anEl('anRefreshBrowse').addEventListener('click', () => anBrowse(AN.browsePath));
  anEl('anCloseSession').addEventListener('click', async () => {
    await anApi('/close', { method: 'POST' });
    AN.meta = null;
    anEl('anWorkspace').classList.remove('ready');
    anStatus('Sesión cerrada.');
  });
}

/* ===== Cambio de pestaña ===== */

function anBindTabs() {
  const tabs = document.querySelectorAll('#viewTabs button');
  tabs.forEach(btn => btn.addEventListener('click', () => {
    tabs.forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    const view = btn.dataset.view;
    anEl('viewControl').style.display = view === 'control' ? '' : 'none';
    anEl('viewAnalysis').style.display = view === 'analysis' ? '' : 'none';
    // Los canvas dimensionan según su tamaño CSS: al hacerse visibles hay que redibujar.
    if (view === 'analysis' && AN.stack) { AN.stack.draw(); anRenderStrip(); }
  }));
}

/* ===== Arranque ===== */

(async function anInit() {
  anBindTabs();
  anBindControls();
  try {
    const cfg = await anApi('/config');
    AN.gearRatio = cfg.gear_ratio_default;
    anEl('anGearRatio').value = AN.gearRatio;
    anEl('anRootInfo').textContent = `Raíz permitida: ${cfg.root}`;
    await anBrowse(null);
    // Si el backend ya tenía una sesión abierta (recarga de página), recuperarla.
    const p = await anApi('/progress');
    if (p.state === 'ready') { anStatus(p.message, 'ok'); await anLoadSession(); }
    else if (p.state === 'building') anPollProgress();
  } catch (err) {
    anStatus(`No se pudo contactar con el backend: ${err.message}`, 'err');
  }
})();
