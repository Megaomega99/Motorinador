/* Tests del graficador de canvas (chart.js) — se ejecutan con Node:
 *
 *     node --test frontend/tests/
 *
 * chart.js está escrito a mano, así que lo que se prueba aquí es su parte
 * delicada: el mapeo tiempo↔píxel, el recorte del rango, el zoom anclado al
 * cursor y la búsqueda del valor bajo el ratón. Nada de esto se ve en una
 * captura de pantalla y todo se rompe en silencio.
 *
 * No hay DOM: se sustituye el canvas y su contexto 2D por dobles mínimos.
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* ===== Dobles del entorno de navegador ===== */

function fakeCtx() {
  const calls = [];
  const rec = name => (...args) => calls.push([name, ...args]);
  return {
    calls,
    setTransform: rec('setTransform'), clearRect: rec('clearRect'),
    beginPath: rec('beginPath'), moveTo: rec('moveTo'), lineTo: rec('lineTo'),
    stroke: rec('stroke'), fill: rec('fill'), fillRect: rec('fillRect'),
    strokeRect: rec('strokeRect'), fillText: rec('fillText'),
    save: rec('save'), restore: rec('restore'), translate: rec('translate'),
    rotate: rec('rotate'), rect: rec('rect'), clip: rec('clip'),
    setLineDash: rec('setLineDash'),
    measureText: () => ({ width: 30 }),
  };
}

function fakeCanvas(w = 600, h = 200) {
  const ctx = fakeCtx();
  const listeners = {};
  return {
    clientWidth: w, clientHeight: h, width: 0, height: 0, style: {},
    getContext: () => ctx,
    _ctx: ctx,
    _listeners: listeners,
    addEventListener: (name, fn) => { (listeners[name] ||= []).push(fn); },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: w, height: h }),
    emit(name, ev) { for (const fn of listeners[name] || []) fn(ev); },
  };
}

/* Carga chart.js en un contexto con los globales que espera. */
function loadChart() {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'chart.js'), 'utf8');
  const sandbox = {
    window: { devicePixelRatio: 1, addEventListener() {} },
    console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  return sandbox.window;
}

const { TimeChart, ChartStack, chartUtils } = loadChart();

/* Área de dibujo: AXIS_W=58 a la izquierda, 8 a la derecha. */
const AXIS_W = 58;
const plotW = (w, showX) => w - AXIS_W - 8;

/* ===== TimeChart ===== */

test('dibuja una polilínea con un punto por muestra', () => {
  const cv = fakeCanvas();
  const ch = new TimeChart(cv, { ylabel: 'y' });
  ch.setSeries([{ t: [0, 1, 2, 3], y: [0, 1, 2, 3], color: '#000' }]);
  ch.setXRange(0, 3);
  ch.draw();
  const lineTos = cv._ctx.calls.filter(c => c[0] === 'lineTo');
  const moveTos = cv._ctx.calls.filter(c => c[0] === 'moveTo');
  // 1 moveTo + 3 lineTo de la serie (más los de la rejilla, que usan moveTo/lineTo).
  assert.ok(moveTos.length >= 1);
  assert.ok(lineTos.length >= 3);
});

test('ajusta el canvas al devicePixelRatio', () => {
  const cv = fakeCanvas(400, 100);
  const w = loadChart();
  w.devicePixelRatio = 2;
  // Se usa el TimeChart ya cargado (comparte el window del sandbox original,
  // con dpr=1) → se comprueba el caso base.
  const ch = new TimeChart(cv, {});
  ch.setSeries([{ t: [0, 1], y: [0, 1] }]).setXRange(0, 1).draw();
  assert.strictEqual(cv.width, 400);
  assert.strictEqual(cv.height, 100);
});

test('no revienta sin series y muestra el texto de vacío', () => {
  const cv = fakeCanvas();
  const ch = new TimeChart(cv, {});
  ch.setEmptyText('sin señal de motor').draw();
  const texts = cv._ctx.calls.filter(c => c[0] === 'fillText').map(c => c[1]);
  assert.ok(texts.includes('sin señal de motor'));
});

test('timeAtEvent mapea píxel → tiempo dentro del área de dibujo', () => {
  const cv = fakeCanvas(600, 200);
  const ch = new TimeChart(cv, {});
  ch.setSeries([{ t: [0, 10], y: [0, 1] }]).setXRange(0, 10).draw();
  const box = plotW(600, false);
  // Borde izquierdo → t0; borde derecho → t1; centro → mitad.
  assert.ok(Math.abs(ch.timeAtEvent({ clientX: AXIS_W }) - 0) < 1e-9);
  assert.ok(Math.abs(ch.timeAtEvent({ clientX: AXIS_W + box }) - 10) < 1e-9);
  assert.ok(Math.abs(ch.timeAtEvent({ clientX: AXIS_W + box / 2 }) - 5) < 1e-9);
});

test('timeAtEvent devuelve null fuera del área (sobre el eje Y)', () => {
  const cv = fakeCanvas(600, 200);
  const ch = new TimeChart(cv, {});
  ch.setXRange(0, 10);
  assert.strictEqual(ch.timeAtEvent({ clientX: 10 }), null);
  assert.strictEqual(ch.timeAtEvent({ clientX: 5000 }), null);
});

test('valueAt encuentra el valor de cada serie en un instante', () => {
  const cv = fakeCanvas();
  const ch = new TimeChart(cv, {});
  ch.setSeries([
    { t: [0, 1, 2, 3], y: [10, 20, 30, 40], label: 'a', color: '#1' },
    { t: [0, 1, 2, 3], y: [-1, -2, -3, -4], label: 'b', color: '#2' },
  ]);
  const out = ch.valueAt(2);
  assert.strictEqual(out.length, 2);
  assert.strictEqual(out[0].value, 30);
  assert.strictEqual(out[1].value, -3);
  assert.strictEqual(out[0].label, 'a');
});

test('valueAt con serie vacía no falla', () => {
  const ch = new TimeChart(fakeCanvas(), {});
  ch.setSeries([{ t: [], y: [], label: 'vacía' }]);
  const out = ch.valueAt(1);
  assert.strictEqual(out.length, 1);
  assert.strictEqual(out[0], null);
});

test('el rango Y se calcula solo con los puntos visibles', () => {
  const cv = fakeCanvas();
  const ch = new TimeChart(cv, {});
  // Un pico enorme FUERA de la ventana no debe aplastar la escala.
  ch.setSeries([{ t: [0, 1, 2, 10], y: [0, 1, 2, 1000] }]);
  ch.setXRange(0, 2);
  const [lo, hi] = ch._autoY();
  assert.ok(hi < 10, `hi=${hi} — el pico de fuera se colo en la escala`);
  assert.ok(lo < 0.1 && hi > 1.9);
});

test('el rango Y de una serie plana no degenera', () => {
  const ch = new TimeChart(fakeCanvas(), {});
  ch.setSeries([{ t: [0, 1, 2], y: [5, 5, 5] }]).setXRange(0, 2);
  const [lo, hi] = ch._autoY();
  assert.ok(hi > lo, 'rango degenerado');
  assert.ok(lo <= 5 && hi >= 5);
});

/* ===== ChartStack ===== */

function makeStack(bounds = [0, 100]) {
  const canvases = [fakeCanvas(), fakeCanvas()];
  const charts = canvases.map(cv => {
    const ch = new TimeChart(cv, {});
    ch.setSeries([{ t: [0, 50, 100], y: [0, 1, 0] }]);
    return ch;
  });
  const events = { ranges: [], cursors: [] };
  const stack = new ChartStack(charts, {
    bounds,
    onRangeChange: (a, b) => events.ranges.push([a, b]),
    onCursor: (t, r) => events.cursors.push([t, r]),
  });
  return { stack, charts, canvases, events };
}

test('setRange propaga el mismo rango a todos los paneles', () => {
  const { stack, charts } = makeStack();
  stack.setRange(10, 20);
  for (const ch of charts) {
    assert.strictEqual(ch.t0, 10);
    assert.strictEqual(ch.t1, 20);
  }
});

test('setRange recorta a los límites de la sesión', () => {
  const { stack } = makeStack([0, 100]);
  stack.setRange(-50, -10);
  assert.strictEqual(stack.t0, 0);
  stack.setRange(95, 200);
  assert.ok(stack.t1 <= 100, `t1=${stack.t1}`);
  assert.ok(stack.t0 >= 0);
});

test('setRange no permite una ventana mayor que la sesión', () => {
  const { stack } = makeStack([0, 100]);
  stack.setRange(-1000, 1000);
  assert.strictEqual(stack.t0, 0);
  assert.strictEqual(stack.t1, 100);
});

test('setRange respeta el ancho mínimo', () => {
  const canvases = [fakeCanvas()];
  const ch = new TimeChart(canvases[0], {});
  const stack = new ChartStack([ch], { bounds: [0, 10], minSpan: 0.5 });
  stack.setRange(5, 5.0001);
  assert.ok(stack.t1 - stack.t0 >= 0.5 - 1e-9, `span=${stack.t1 - stack.t0}`);
});

test('la rueda hace zoom anclado al instante bajo el cursor', () => {
  const { stack, canvases, charts } = makeStack([0, 100]);
  stack.setRange(0, 100);
  const box = plotW(600, false);
  // Cursor en el centro → t=50; al hacer zoom, 50 debe seguir en el centro.
  const ev = {
    clientX: AXIS_W + box / 2, deltaY: -1,
    preventDefault() {},
  };
  canvases[0].emit('wheel', ev);
  const mid = (stack.t0 + stack.t1) / 2;
  assert.ok(Math.abs(mid - 50) < 1e-6, `centro=${mid}`);
  assert.ok(stack.t1 - stack.t0 < 100, 'no se redujo la ventana');
});

test('la rueda hacia abajo amplía la ventana', () => {
  const { stack, canvases } = makeStack([0, 100]);
  stack.setRange(40, 60);
  const before = stack.t1 - stack.t0;
  canvases[0].emit('wheel', {
    clientX: AXIS_W + plotW(600, false) / 2, deltaY: 1, preventDefault() {},
  });
  assert.ok(stack.t1 - stack.t0 > before, 'no se amplió');
});

test('arrastrar desplaza la ventana en sentido contrario al ratón', () => {
  const { stack, canvases } = makeStack([0, 100]);
  stack.setRange(40, 60);
  const box = plotW(600, false);
  canvases[0].emit('mousedown', { button: 0, clientX: 300, preventDefault() {} });
  // Arrastrar 1/4 del ancho hacia la derecha → la ventana retrocede 1/4 del span.
  canvases[0].emit('mousemove', { clientX: 300 + box / 4 });
  assert.ok(Math.abs(stack.t0 - 35) < 0.01, `t0=${stack.t0}`);
  assert.ok(Math.abs(stack.t1 - 55) < 0.01, `t1=${stack.t1}`);
});

test('el arrastre con el botón derecho se ignora', () => {
  const { stack, canvases } = makeStack([0, 100]);
  stack.setRange(40, 60);
  canvases[0].emit('mousedown', { button: 2, clientX: 300, preventDefault() {} });
  canvases[0].emit('mousemove', { clientX: 500 });
  // Sin arrastre activo, mousemove solo mueve el cursor.
  assert.strictEqual(stack.t0, 40);
});

test('doble clic vuelve a mostrar toda la sesión', () => {
  const { stack, canvases } = makeStack([0, 100]);
  stack.setRange(10, 12);
  canvases[0].emit('dblclick', {});
  assert.strictEqual(stack.t0, 0);
  assert.strictEqual(stack.t1, 100);
});

test('el cursor se sincroniza en todos los paneles', () => {
  const { stack, charts, canvases, events } = makeStack([0, 100]);
  stack.setRange(0, 100);
  canvases[0].emit('mousemove', { clientX: AXIS_W + plotW(600, false) / 2 });
  for (const ch of charts) {
    assert.ok(ch.cursorT != null, 'un panel se quedó sin cursor');
    assert.ok(Math.abs(ch.cursorT - 50) < 1e-6);
  }
  assert.ok(events.cursors.length > 0);
  const [t, readouts] = events.cursors.at(-1);
  assert.ok(Math.abs(t - 50) < 1e-6);
  assert.ok(readouts.length >= 2, 'faltan lecturas de los paneles');
});

test('salir del panel borra el cursor', () => {
  const { stack, charts, canvases, events } = makeStack([0, 100]);
  stack.setRange(0, 100);
  canvases[0].emit('mousemove', { clientX: AXIS_W + 50 });
  canvases[0].emit('mouseleave', {});
  for (const ch of charts) assert.strictEqual(ch.cursorT, null);
  assert.strictEqual(events.cursors.at(-1)[0], null);
});

test('onRangeChange avisa al cambiar el rango', () => {
  const { stack, events } = makeStack([0, 100]);
  stack.setRange(10, 20);
  assert.deepStrictEqual(events.ranges.at(-1), [10, 20]);
  // Con notify=false no debe avisar (se usa al inicializar).
  const n = events.ranges.length;
  stack.setRange(30, 40, false);
  assert.strictEqual(events.ranges.length, n);
});

/* ===== utilidades ===== */

test('fmtVal ajusta decimales a la magnitud', () => {
  const { fmtVal } = chartUtils;
  assert.strictEqual(fmtVal(1234.5), '1235');
  assert.strictEqual(fmtVal(123.45), '123.5');
  assert.strictEqual(fmtVal(1.2345), '1.23');
  assert.strictEqual(fmtVal(0.012345), '0.012');
});


test('setRange ignora rangos no finitos', () => {
  const { stack } = makeStack([0, 100]);
  stack.setRange(10, 20);
  stack.setRange(NaN, 30);
  assert.strictEqual(stack.t0, 10, 'un NaN corrompió el rango');
  stack.setRange(5, Infinity);
  assert.strictEqual(stack.t0, 10);
});

test('timeAtEvent no devuelve NaN antes del primer dibujado', () => {
  const cv = fakeCanvas(600, 200);
  const ch = new TimeChart(cv, {});
  ch.setXRange(0, 10);            // sin draw()
  const t = ch.timeAtEvent({ clientX: AXIS_W + 100 });
  assert.ok(t === null || isFinite(t), `devolvió ${t}`);
});
