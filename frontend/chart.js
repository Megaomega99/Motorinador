/* =============================================================
   Graficador de series temporales sobre <canvas>.

   Hecho a mano a propósito: el proyecto no tiene build step ni node_modules, y
   el backend ya entrega las series **decimadas** (~2000 puntos por traza), así
   que dibujar una polilínea por serie es de sobra rápido y evita depender de un
   CDN o de vendorizar una librería.

   Dos piezas:
     · TimeChart  — un panel: ejes, rejilla, N series, cursor y leyenda.
     · ChartStack — varios paneles con el MISMO eje de tiempo, más el arrastre
                    para desplazar, la rueda para hacer zoom y el cursor
                    sincronizado entre todos.
   ============================================================= */

const PALETTE = {
  ink:      '#2a1c10',
  inkSoft:  '#5b4327',
  line:     '#d8c8a8',
  lineSoft: '#efe4cc',
  paper:    '#fffaf0',
  sel:      'rgba(58,110,168,.22)',
  cursor:   'rgba(232,96,31,.75)',
};

const AXIS_W = 58;   // ancho reservado al eje Y (px CSS)
const PAD_T  = 8;
const PAD_B  = 6;

/* Formatea un valor para el eje/leyenda con decimales según su magnitud. */
function fmtVal(v) {
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 100)  return v.toFixed(1);
  if (a >= 1)    return v.toFixed(2);
  return v.toFixed(3);
}

function fmtTime(s) {
  if (!isFinite(s)) return '—';
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return m > 0 ? `${m}:${r.toFixed(2).padStart(5, '0')}` : `${s.toFixed(3)} s`;
}

class TimeChart {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {{ylabel?: string, height?: number, showXAxis?: boolean}} opts
   */
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ylabel = opts.ylabel || '';
    this.showXAxis = !!opts.showXAxis;
    this.series = [];
    this.t0 = 0;
    this.t1 = 1;
    this.cursorT = null;
    this.selection = null;      // [t0, t1] sombreado (para la tira de vista general)
    this.emptyText = '';
    this._yRange = null;        // fijado a mano con setYRange
  }

  setSeries(series) { this.series = series || []; return this; }
  setXRange(t0, t1) { this.t0 = t0; this.t1 = t1; return this; }
  setYRange(lo, hi) { this._yRange = (lo == null ? null : [lo, hi]); return this; }
  setCursor(t)      { this.cursorT = t; return this; }
  setSelection(sel) { this.selection = sel; return this; }
  setEmptyText(txt) { this.emptyText = txt || ''; return this; }

  /* Tamaño real del canvas según el CSS y el devicePixelRatio. */
  _resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (!w || !h) return false;
    const pw = Math.round(w * dpr), ph = Math.round(h * dpr);
    if (this.canvas.width !== pw || this.canvas.height !== ph) {
      this.canvas.width = pw;
      this.canvas.height = ph;
    }
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w; this.h = h;
    return true;
  }

  /* Área de dibujo (sin el eje Y ni la franja del eje X). */
  _plotBox() {
    const bottom = this.showXAxis ? 18 : PAD_B;
    return { x: AXIS_W, y: PAD_T, w: Math.max(1, this.w - AXIS_W - 8),
             h: Math.max(1, this.h - PAD_T - bottom) };
  }

  /* Rango Y: el fijado a mano, o el de los datos visibles con 6 % de margen. */
  _autoY() {
    if (this._yRange) return this._yRange;
    let lo = Infinity, hi = -Infinity;
    for (const s of this.series) {
      const { t, y } = s;
      for (let i = 0; i < y.length; i++) {
        if (t[i] < this.t0 || t[i] > this.t1) continue;
        const v = y[i];
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    if (!isFinite(lo) || !isFinite(hi)) return [-1, 1];
    if (hi - lo < 1e-9) { const c = (hi + lo) / 2 || 0; return [c - 1, c + 1]; }
    const pad = (hi - lo) * 0.06;
    return [lo - pad, hi + pad];
  }

  valueAt(t) {
    /* Valor de cada serie en el instante t (búsqueda binaria). */
    const out = [];
    for (const s of this.series) {
      const arr = s.t;
      if (!arr.length) { out.push(null); continue; }
      let lo = 0, hi = arr.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (arr[mid] < t) lo = mid + 1; else hi = mid;
      }
      out.push({ label: s.label, color: s.color, value: s.y[lo] });
    }
    return out;
  }

  draw() {
    if (!this._resize()) return;
    const { ctx } = this;
    const box = this._plotBox();

    ctx.clearRect(0, 0, this.w, this.h);

    if (!this.series.length || !this.series.some(s => s.y.length)) {
      ctx.fillStyle = PALETTE.inkSoft;
      ctx.font = '12px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.globalAlpha = 0.65;
      ctx.fillText(this.emptyText || 'sin datos', this.w / 2, this.h / 2);
      ctx.globalAlpha = 1;
      this._drawYLabel();
      return;
    }

    const [ylo, yhi] = this._autoY();
    const sx = t => box.x + (t - this.t0) / (this.t1 - this.t0 || 1) * box.w;
    const sy = v => box.y + box.h - (v - ylo) / (yhi - ylo || 1) * box.h;

    // Selección sombreada (tira de vista general)
    if (this.selection) {
      const a = sx(this.selection[0]), b = sx(this.selection[1]);
      ctx.fillStyle = PALETTE.sel;
      ctx.fillRect(Math.min(a, b), box.y, Math.max(2, Math.abs(b - a)), box.h);
    }

    this._drawGrid(box, ylo, yhi, sx, sy);

    // Series
    ctx.save();
    ctx.beginPath();
    ctx.rect(box.x, box.y, box.w, box.h);
    ctx.clip();
    for (const s of this.series) {
      if (!s.y.length) continue;
      ctx.strokeStyle = s.color || PALETTE.ink;
      ctx.lineWidth = s.width || 1;
      ctx.globalAlpha = s.alpha == null ? 1 : s.alpha;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < s.y.length; i++) {
        const px = sx(s.t[i]), py = sy(s.y[i]);
        if (!started) { ctx.moveTo(px, py); started = true; }
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.restore();

    // Cursor
    if (this.cursorT != null && this.cursorT >= this.t0 && this.cursorT <= this.t1) {
      const px = sx(this.cursorT);
      ctx.strokeStyle = PALETTE.cursor;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(px, box.y);
      ctx.lineTo(px, box.y + box.h);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    this._drawYLabel();
    this._drawLegend(box);
  }

  _drawGrid(box, ylo, yhi, sx, sy) {
    const { ctx } = this;
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.strokeStyle = PALETTE.lineSoft;
    ctx.fillStyle = PALETTE.inkSoft;
    ctx.lineWidth = 1;

    // Rejilla horizontal + etiquetas del eje Y
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let k = 0; k <= 4; k++) {
      const v = ylo + (yhi - ylo) * k / 4;
      const py = Math.round(sy(v)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(box.x, py);
      ctx.lineTo(box.x + box.w, py);
      ctx.stroke();
      ctx.fillText(fmtVal(v), box.x - 6, py);
    }

    // Rejilla vertical + etiquetas del eje X (solo en el panel de abajo)
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let k = 0; k <= 5; k++) {
      const t = this.t0 + (this.t1 - this.t0) * k / 5;
      const px = Math.round(sx(t)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(px, box.y);
      ctx.lineTo(px, box.y + box.h);
      ctx.stroke();
      if (this.showXAxis) {
        ctx.fillText(t.toFixed(this.t1 - this.t0 < 2 ? 3 : 1), px, box.y + box.h + 4);
      }
    }

    // Marco
    ctx.strokeStyle = PALETTE.line;
    ctx.strokeRect(box.x + 0.5, box.y + 0.5, box.w, box.h);
  }

  _drawYLabel() {
    if (!this.ylabel) return;
    const { ctx } = this;
    ctx.save();
    ctx.translate(11, this.h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.fillStyle = PALETTE.inkSoft;
    ctx.fillText(this.ylabel, 0, 0);
    ctx.restore();
  }

  _drawLegend(box) {
    const labelled = this.series.filter(s => s.label);
    if (labelled.length < 2) return;
    const { ctx } = this;
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    let x = box.x + 8;
    const y = box.y + 4;
    for (const s of labelled) {
      const text = s.label;
      const wText = ctx.measureText(text).width;
      ctx.fillStyle = PALETTE.paper;
      ctx.globalAlpha = 0.8;
      ctx.fillRect(x - 2, y - 1, wText + 16, 12);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, y + 6);
      ctx.lineTo(x + 10, y + 6);
      ctx.stroke();
      ctx.fillStyle = PALETTE.inkSoft;
      ctx.fillText(text, x + 14, y);
      x += wText + 26;
    }
  }

  /* Instante correspondiente a un evento de ratón (null si cae fuera). */
  timeAtEvent(ev) {
    // Si aún no se ha dibujado, this.w es undefined y todo el cálculo sale NaN.
    // Devolver NaN aquí envenenaría el rango del ChartStack, así que se mide
    // primero y se comprueba que el resultado sea finito.
    if (!this.w) this._resize();
    const box = this._plotBox();
    if (!isFinite(box.w) || box.w <= 0) return null;
    const rect = this.canvas.getBoundingClientRect();
    const px = ev.clientX - rect.left;
    if (!(px >= box.x) || px > box.x + box.w) return null;
    const t = this.t0 + (px - box.x) / box.w * (this.t1 - this.t0);
    return isFinite(t) ? t : null;
  }
}

/* =============================================================
   ChartStack — varios TimeChart con eje X compartido.
   Arrastrar desplaza, la rueda hace zoom sobre el punto del cursor y el cursor
   se dibuja en todos los paneles a la vez.
   ============================================================= */
class ChartStack {
  /**
   * @param {TimeChart[]} charts
   * @param {{onRangeChange?: (t0:number,t1:number)=>void,
   *          onCursor?: (t:number|null, readouts:object[])=>void,
   *          bounds?: [number, number], minSpan?: number}} opts
   */
  constructor(charts, opts = {}) {
    this.charts = charts;
    this.onRangeChange = opts.onRangeChange || (() => {});
    this.onCursor = opts.onCursor || (() => {});
    this.bounds = opts.bounds || [0, 1];
    this.minSpan = opts.minSpan || 0.001;
    this.t0 = this.bounds[0];
    this.t1 = this.bounds[1];
    this._drag = null;
    for (const ch of charts) this._bind(ch);
    window.addEventListener('resize', () => this.draw());
  }

  setBounds(lo, hi) { this.bounds = [lo, hi]; return this; }

  setRange(t0, t1, notify = true) {
    // Un NaN aquí dejaría la vista inservible sin error visible; se ignora.
    if (!isFinite(t0) || !isFinite(t1)) return this;
    const [lo, hi] = this.bounds;
    const span = Math.max(this.minSpan, Math.min(t1 - t0, hi - lo));
    const a = Math.max(lo, Math.min(t0, hi - span));
    this.t0 = a;
    this.t1 = a + span;
    for (const ch of this.charts) ch.setXRange(this.t0, this.t1);
    this.draw();
    if (notify) this.onRangeChange(this.t0, this.t1);
    return this;
  }

  draw() { for (const ch of this.charts) ch.draw(); }

  _setCursor(t) {
    for (const ch of this.charts) ch.setCursor(t);
    this.draw();
    if (t == null) { this.onCursor(null, []); return; }
    const readouts = [];
    for (const ch of this.charts) {
      for (const r of ch.valueAt(t)) if (r) readouts.push(r);
    }
    this.onCursor(t, readouts);
  }

  _bind(chart) {
    const el = chart.canvas;
    el.style.cursor = 'crosshair';

    el.addEventListener('mousemove', ev => {
      if (this._drag) {
        // Arrastre: desplazar el rango en sentido contrario al ratón.
        const box = chart._plotBox();
        const dt = (ev.clientX - this._drag.x) / box.w * (this.t1 - this.t0);
        this.setRange(this._drag.t0 - dt, this._drag.t1 - dt);
        return;
      }
      const t = chart.timeAtEvent(ev);
      this._setCursor(t);
    });

    el.addEventListener('mouseleave', () => { if (!this._drag) this._setCursor(null); });

    el.addEventListener('mousedown', ev => {
      if (ev.button !== 0) return;
      this._drag = { x: ev.clientX, t0: this.t0, t1: this.t1 };
      el.style.cursor = 'grabbing';
      ev.preventDefault();
    });

    const endDrag = () => {
      if (!this._drag) return;
      this._drag = null;
      el.style.cursor = 'crosshair';
    };
    window.addEventListener('mouseup', endDrag);

    el.addEventListener('wheel', ev => {
      const t = chart.timeAtEvent(ev);
      if (t == null) return;
      ev.preventDefault();
      const factor = ev.deltaY > 0 ? 1.25 : 0.8;
      const span = (this.t1 - this.t0) * factor;
      // Zoom anclado al instante bajo el cursor.
      const frac = (t - this.t0) / (this.t1 - this.t0);
      this.setRange(t - span * frac, t - span * frac + span);
    }, { passive: false });

    el.addEventListener('dblclick', () => this.setRange(this.bounds[0], this.bounds[1]));
  }
}

window.TimeChart = TimeChart;
window.ChartStack = ChartStack;
window.chartUtils = { fmtVal, fmtTime, PALETTE };
