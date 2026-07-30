# Análisis de encoder, motor y electrodos

Este paquete es el **motor de cálculo** del análisis offline de las grabaciones de
banco. No tiene interfaz propia: se usa desde la pestaña **«Análisis de
grabaciones»** de la aplicación, que habla con `/api/analysis/*`. Esa API solo
envuelve este paquete —no recalcula nada— y sirve las series ya decimadas; hay un
test que comprueba que el resultado por API y el cálculo directo coinciden.

También se puede usar como librería desde Python, que es lo que hacen los tests:

```python
from analysis.readers.factory import open_reader
from analysis.processing import SessionCache, build_cache

build_cache(open_reader("mi_carpeta_de_sesion"), "cache.h5")
with SessionCache("cache.h5") as c:
    print(c.gear_estimate().ratio)          # relación medida de los datos
    print(c.motor_summary(0, c.n_samples, 1.986, 15000).as_text())
```

Lo que hace, sin cargar la sesión entera en RAM:

- el **ángulo** y la **velocidad angular** del encoder, desde las dos señales
  digitales de cuadratura, y
- la **velocidad comandada del motor**, desde el espejo del pulso STEP grabado en
  la entrada analógica `ANALOG-IN-2`,

y las compara para medir la **relación de engranajes** y delatar **pasos
perdidos**. Todo junto a la actividad de los electrodos, en el mismo eje de tiempo.

Reutiliza la geometría del firmware ([../src/main.cpp](../src/main.cpp)):
`ENC_PPR = 600` → `COUNTS_PER_REV = 2400` (X4) y `STEPS_PER_REV = 1600`.

## Instalación

Requiere **Python 3.10 o superior** (probado en 3.13). Solo `neo` suele faltar:

```bash
pip install -r analysis/requirements.txt
```

## Uso

Doble clic en `Motorinador.bat` (Windows) o `./motorinador.sh` (Linux/macOS) →
pestaña **«Análisis de grabaciones»**.

1. **Abrir archivo** `.txt` (export tabular de Intan) o `.rhs` (binario Intan), o
   **Abrir esta sesión completa** para tratar los varios `.rhs` de una toma como
   una **única grabación continua** — Intan parte las sesiones largas en archivos
   de un minuto (la toma de referencia son 8 archivos = 7.3 min).
   Se procesa por segmentos a un caché HDF5 temporal (barra de progreso).
2. **Navegar con la tira de vista general** (arriba): muestra toda la sesión y la
   ventana visible sombreada; un clic salta a ese instante. En una sesión con
   arranques y paradas es la forma rápida de encontrar los tramos en marcha.
   En las gráficas: arrastrar desplaza, la rueda hace zoom y el doble clic vuelve
   a mostrarlo todo.
3. **Elegir unidades**: ángulo (rad / grados), velocidad (rad/s, grad/s, RPM) y
   las dos ventanas de suavizado (ver abajo).
4. **Relación de engranajes**: se **mide sobre los propios datos** al cargar y se
   adopta como valor de trabajo; el campo `Vueltas enc/motor` permite fijarla a mano.
5. **Seleccionar electrodos** (Ctrl/Shift en la lista).
6. **Resultados** (panel derecho): resumen del motor (consigna → medido y
   deslizamiento) y estadísticos de la ventana visible.
7. **Exportar** la ventana visible o la sesión completa, a CSV/TXT o HDF5.

### Las dos ventanas de suavizado

| Control | Por defecto | Para qué |
|---|---|---|
| `Ventana vel. (ms)` | 50 ms | Velocidad del encoder (gráfica 3 y estadísticos). |
| `Ventana motor (ms)` | 500 ms | Comparación con la consigna (gráfica 4, resumen y columna `slip`). |

Son distintas por una razón física: **el tren de engranajes resuena**. A 5 RPM de
consigna la velocidad del encoder oscila ±20 RPM alrededor de su media a ~10 Hz
(stick-slip / juego entre dientes). Con 50 ms esa oscilación es real pero tapa por
completo la curva de la consigna; con 500 ms se promedia sin ocultar un atasco,
que dura segundos.

## Las cuatro gráficas

1. **Electrodos** elegidos (µV).
2. **Ángulo** del encoder (acumulado u envuelto).
3. **Velocidad del encoder**.
4. **Motor**: consigna (del espejo STEP) frente a medida referida al eje del motor
   (encoder ÷ relación). *El hueco entre las dos curvas es el deslizamiento*: si el
   motor pierde pasos o se atasca, la medida cae por debajo de la consigna.

## Formatos de entrada

| Formato | Soporte | Notas |
|---------|---------|-------|
| `.rhs`  | ✅ | Binario Intan monolítico, leído con `neo.rawio.IntanRawIO` (memmap, RAM plana). |
| carpeta de `.rhs` | ✅ | Todos los archivos en orden temporal como una sola grabación. |
| `.txt`  | ✅ | Export tabular de Intan. Las columnas `DIGITAL-IN` son **pulsos de flanco**; el lector reconstruye el nivel por paridad (ver abajo). |
| `.smrx` / `.s2rx` | ❌ | Spike2. `sonpy` no tiene wheel para Python 3.13 en Linux. Convertir a `.txt`/`.rhs`. |

La señal del motor es **opcional**: las grabaciones anteriores a
`intento serio 2_260729_142804` no la traen. En ese caso la cuarta gráfica lo dice,
la relación no se puede medir y el export omite las columnas del motor.

### Canales que se leen del `.rhs`

| Stream | Canal | Uso |
|---|---|---|
| `RHS2000 amplifier channel` | `A-0xx` (µV) | electrodos |
| `USB board digital input channel` | `DIGITAL-IN-01/02` | encoder A/B |
| `USB board ADC input channel` | `ANALOG-IN-2` (V) | espejo STEP → velocidad del motor |

### Detalle importante: codificación de las señales digitales en `.txt`

En el `textform.txt` de este proyecto, `DIGITAL-IN-01`/`02` **no** son el nivel del
canal sino un pulso de una muestra en cada flanco. El nivel real es la paridad
acumulada (`nivel[i] = Σ pulsos[0..i] mod 2`). El `.rhs` sí da niveles directos.
Verificado: ambas vías dan el **mismo** conteo del encoder (X4). El lector `.txt`
normaliza esto por defecto (`digital_mode="toggle"`).

## Columnas del export

Siempre: `Time`, `DIGITAL-IN-01/02`, los electrodos (µV), `angle_<unidad>`,
`omega_<unidad>`.

Si la grabación trae el espejo STEP, además:

| Columna | Unidad | Qué es |
|---|---|---|
| `analog_in_2_V` | V | la onda cuadrada cruda del espejo STEP |
| `step_count` | pasos | micropasos acumulados |
| `motor_rpm` | RPM | velocidad **comandada** del motor (exacta) |
| `slip` | frac. [0,1] | deslizamiento: 0 sigue la consigna, 1 eje bloqueado |

### Metadatos del HDF5

El `.h5` guarda todo lo necesario para **reproducir sus propias columnas** sin
volver a la grabación original:

| Atributo | Para qué |
|---|---|
| `window_samples` / `window_ms` | suavizado usado en `omega_*` |
| `motor_window_samples` / `motor_window_ms` | suavizado usado en `slip` |
| `gear_ratio`, `motor_channel` | relación aplicada y canal del espejo STEP |
| `t_start_s`, `t_stop_s` | tramo exportado dentro de la sesión |
| `source_path`, `n_parts` | de qué grabación salió y si era multiarchivo |
| `counts_per_rev`, `steps_per_rev` | geometría, para reinterpretar sin el firmware |
| `angle_unit`, `velocity_unit`, `sample_rate_hz`, `has_motor` | unidades y muestreo |

Las ventanas están porque hicieron falta: sin ellas, dos exportaciones del mismo
tramo con distinto suavizado son indistinguibles, y recuperarlas obliga a
compararlas por fuerza bruta contra la grabación original. Hay un test que
comprueba que `omega_*` se puede recalcular leyendo la ventana del propio archivo.

> El export **tabular** (CSV/TXT) no tiene dónde guardar esto: su formato es la
> cabecera de Intan (nombres + unidades) y añadir líneas rompería a quien lo lea.
> Si necesitas la trazabilidad, exporta a `.h5`.

## Diseño (RAM plana)

Una única pasada por segmentos vuelca a un HDF5 chunked: conteo del encoder,
conteo de micropasos, tensión del espejo STEP y electrodos. Después,
`SessionCache` sirve tramos (ventana visible), la vista general decimada
(envolvente min/max) y los estadísticos leyendo del HDF5. Los dos conteos
(~8 MB/millón de muestras cada uno) se mantienen en RAM porque son baratos y de
ellos derivan ángulo, velocidad, velocidad de motor y deslizamiento al vuelo. Los
electrodos nunca se cargan enteros a la vez.

Coste medido en la toma de referencia (8 archivos, 1.3 GB, 13.1 M muestras,
21 electrodos): **caché de 1.4 GB construida en ~2 s** (NVMe + memmap).

## Módulos

| Archivo | Responsabilidad |
|---------|-----------------|
| `units.py` | Unidades y geometría (encoder 2400, motor 1600, relación por defecto). |
| `encoder.py` | Decodificación X4 vectorizada (stateful) + ángulo + velocidad. |
| `motor.py` | Espejo STEP → conteo de micropasos (stateful) → RPM del motor. |
| `gearing.py` | Estimación de la relación de engranajes y deslizamiento. |
| `readers/` | `base` (Protocol), `txt_reader`, `rhs_reader`, `session`, `factory`. |
| `processing.py` | Construcción del caché HDF5 + `SessionCache` + decimación. |
| `stats.py` | Estadísticos de velocidad y resumen del motor. |
| `exporter.py` | Exportación por segmentos a CSV/TXT/HDF5 con columnas nuevas. |

Este paquete no contiene interfaz. El cliente vive fuera y lo consume por HTTP:

| Archivo | Responsabilidad |
|---------|-----------------|
| `backend/app/analysis_service.py` | Sesión abierta, trabajos en segundo plano, confinamiento de rutas. |
| `backend/app/routes/analysis.py` | Endpoints `/api/analysis/*`. |
| `frontend/chart.js` | Graficador de canvas (sin dependencias). |
| `frontend/analysis.js` | Vista: navegador de archivos, paneles, export. |

## Resultados sobre la toma de referencia

`intento serio 2_260729_142804` (8 × `.rhs`, 30 kHz, 437 s, 21 electrodos):

- Relación medida: **1.9861** enc/motor (mediana por ventana 1.9822) sobre 141
  ventanas de consigna estable. El nominal supuesto era 2.1 → **6 % alto**.
- Pérdida de paso en **12 de 141** ventanas (**8.5 %**), con un bloqueo casi total
  hacia t ≈ 180–183 s (el ángulo se queda plano mientras siguen llegando pasos).
- Consignas recuperadas del espejo STEP: 3.02, 4.02, 5.00, 5.02, 6.99 RPM — valores
  limpios, como los fija el firmware.

## Rendimiento

La velocidad se suaviza con **sumas acumuladas**, no con `np.convolve`: el coste es
O(n) en lugar de O(n·w). Con la ventana de motor de 500 ms sobre un tramo de 20 s a
30 kHz la diferencia es de **~5 s a ~20 ms**, que es lo que hace viable navegar con
zoom y arrastre. Una petición de ventana completa (cuatro gráficas + estadísticos)
tarda **22–52 ms** sobre la sesión de 437 s.

## Tests

```bash
pytest analysis/tests/ --cov=analysis     # motor de cálculo
cd backend && pytest tests                # API + contratos entre capas
node --test frontend/tests/chart.test.js  # graficador de canvas
```

No hacen falta las grabaciones reales: los tests generan trenes STEP y cuadratura
sintéticos con la misma geometría. Entre ellos hay dos que importan especialmente:
uno comprueba que **la API y el cálculo directo dan el mismo resultado**, y otro
que un `.h5` exportado permite **recalcular sus propias columnas** leyendo las
ventanas de sus metadatos.
