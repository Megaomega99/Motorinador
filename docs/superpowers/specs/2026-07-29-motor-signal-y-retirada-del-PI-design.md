# Señal del motor (ANALOG-IN-2), engranajes y retirada del PI

Fecha: 2026-07-29
Datos de referencia: `intento serio 2_260729_142804/` (8 × `.rhs`, 1 min cada uno, 30 kHz, ≈7.3 min)

## 1. Qué es la nueva columna analógica

El `.rhs` de esta toma añade un stream que antes no existía:

| Stream | Canal | Unidades | Escala |
|--------|-------|----------|--------|
| `USB board ADC input channel` | `ANALOG-IN-2` | V | `gain=0.0003125`, `offset=-10.24` → ±10.24 V |

**Es el espejo del pulso STEP: `PIN_STEP_OUT` (D11) de [../../../src/main.cpp](../../../src/main.cpp).**

Evidencia (medida sobre la toma real):

1. **Amplitud**: con el motor en marcha oscila 10530 LSB = **3.29 V** con la media en
   la mitad del recorrido → onda cuadrada lógica de 3.3 V (Nano 33 BLE). Con el motor
   parado queda plana en ~2 mV (el firmware pone `PIN_STEP_OUT` a LOW en `stopMotor`).
2. **Ciclo de trabajo = 0.500 exacto** en todas las ventanas medidas. El firmware
   conmuta el pin cada `half` µs, así que por construcción el duty es 50 %. Una señal
   de origen mecánico no daría 0.500 clavado.
3. **La frecuencia da RPM "redondas" del firmware**: `RPM = f · 60/1600` produce
   1.16, 4.18, 5.00, 5.01, 7.01 RPM — los valores de consigna. 
4. **No es el espejo del encoder** (D9/D10): en la misma ventana `f_analog = 187 Hz`
   mientras que el canal A del encoder va a 141 Hz.

Por tanto se recupera la **velocidad del motor comandada**, exacta:

```
f_STEP  = nº de flancos de subida por segundo   (1 flanco = 1 micropaso)
RPM_mot = f_STEP · 60 / STEPS_PER_REV           (STEPS_PER_REV = 1600)
```

La dirección **no** está en esta señal (DIR es otro pin y no se graba): `ANALOG-IN-2`
da magnitud. El signo lo sigue dando el encoder.

## 2. Relación de engranajes medida

Integrando micropasos comandados y cuentas de encoder sobre los tramos en los que la
consigna es constante (125 s útiles, excluyendo arranques y atascos):

```
GEAR_RATIO (vueltas de encoder por vuelta de motor) = 1.979
   mediana por segundo = 1.981     percentiles 5/95 = 1.61 / 2.22
```

El valor asumido de 2.1 está un **6 % alto**; 1.98 es lo que dicen los datos (a 1 %
de 2.0). Se adopta **1.98 como valor por defecto, configurable**, y la herramienta
lo **estima desde los propios datos** (tiene las dos señales, puede medirlo).

## 3. Hallazgo colateral: pérdida de pasos

En 11 de 142 segundos de consigna constante (**7.7 %**) las cuentas del encoder caen
muy por debajo de lo comandado. El peor caso, t = 182 s: **8 cuentas de encoder
mientras se comandaban 187 micropasos** — el motor está atascado y el tren de pasos
sigue corriendo.

Esto convierte al encoder en lo que de verdad aporta ahora: **un instrumento de
verificación** (¿siguió el motor la consigna?), no un sensor para cerrar un lazo.

## 4. Veredicto sobre el PI: se retira

El PI no solo "ya no tiene sentido" — con engranajes es **incorrecto y peligroso**:

1. **La consigna significa dos cosas distintas según el modo.** `targetRPM` alimenta
   `halfPeriodUs()` → en modo LIBRE es RPM *del motor*. Pero `measuredRPM` se calcula
   con `COUNTS_PER_REV = 2400` → es RPM *del encoder* ≈ 1.98 × RPM del motor. El PI
   lleva `measuredRPM → targetRPM`, así que estabiliza en
   `RPM_motor = targetRPM / 1.98`. Pasar de LIBRE a PI **divide por dos la velocidad
   real del motor sin avisar**.
2. **La ganancia del lazo no es la del diseño.** El IMC se diseñó para planta de
   ganancia unidad (`Kp = τ/λ`, `Ki = 1/λ`, λ = 0.125 s). Los engranajes meten un
   factor 1.98 → λ efectiva ≈ 0.063 s. Sigue estable, pero no es el diseño.
3. **Ante un atasco, el PI empeora las cosas.** Con el motor bloqueado `measuredRPM ≈ 0`,
   el error es máximo, el integrador sube hasta que `uRaw > RPM_MAX` y el anti-windup
   lo congela **en el techo**: el firmware comanda **120 RPM** a un motor atascado.
   Es exactamente el escenario de t = 176–183 s. Ni recupera el paso perdido (un PI de
   velocidad no puede) ni es seguro cuando el eje se libera de golpe.
4. **Un stepper no necesita lazo de velocidad.** Con TMC2208 en STEP/DIR el motor sigue
   el tren de pasos *exactamente* mientras no pierda paso. Lo único que un lazo podría
   corregir es la pérdida de paso, y un PI de velocidad no la corrige (punto 3).

**Decisión: eliminar el PI del firmware, del backend y del frontend.** El control
queda: activado/parado, velocidad, dirección — que es justo lo que se usa. El encoder
pasa a ser telemetría de verificación: velocidad real medida y **deslizamiento**
(consigna vs medido) para delatar pasos perdidos.

## 5. Cambios

### 5.1 Firmware (`src/main.cpp`)
- Fuera: `PI_KP/PI_KI`, `piIntegral`, `usePID`, `updateControl()`, comandos `p`/`l`/`c`.
  `controlRPM` desaparece: el tren de pasos usa `targetRPM` directamente.
- `updateVelocity()` **se mantiene** (telemetría) y se añade `GEAR_RATIO = 1.98` para
  reportar la velocidad **referida al motor**.
- Línea de estado única:
  `Tgt:5.0RPM  Mot:5.02RPM  Enc:9.9RPM  Ang:185.4deg  Dir:FWD  CORRIENDO`
  (`Mot` = RPM de motor medida = `Enc / GEAR_RATIO`, con signo por dirección).

### 5.2 Backend
- `StatusFrame`: `target_rpm`, `motor_rpm`, `enc_rpm`, `angle_deg`, `dir`, `running`,
  `omega_rad_s`, `v_m_s`, `slip_pct`. Fuera `use_pid`/`pi_error`/`control_rpm`.
- `Params`: nuevo `gear_ratio` (1.98). `v_m_s` se calcula con la RPM **del motor**
  (la rueda va en el eje del motor; el encoder es solo instrumento).
- Fuera los comandos `mode_pi`/`mode_libre`; un solo regex de estado.

### 5.3 Frontend
- Fuera el selector de modo y la tarjeta "Estado PI".
- Marcadores: consigna, RPM motor medida, RPM encoder, velocidad lineal, ángulo y un
  indicador de **deslizamiento** (delata pasos perdidos).
- `gear_ratio` editable en el bloque de mecánica.

### 5.4 Paquete `analysis/`
- `units.py`: `STEPS_PER_REV = 1600`, `GEAR_RATIO_DEFAULT = 1.98`; las conversiones
  cuentas→velocidad se parametrizan con `counts_per_rev` (2400 encoder / 1600 motor).
- **`motor.py` (nuevo)**: `StepCounter` (binarización con histéresis 0.8/1.5 V y conteo
  acumulado de flancos, con estado entre segmentos, igual que `QuadratureDecoder`) y
  `motor_rpm_from_step_counts()` por **intervalo entre flancos** (exacto para un tren
  comandado, sin la cuantización de una ventana móvil) con caída a 0 por *timeout*.
- **`gearing.py` (nuevo)**: estima `GEAR_RATIO` desde los datos y detecta segundos con
  pérdida de paso / atasco.
- `readers/`: `Chunk.motor` y `Meta.has_motor`; `RhsReader` lee el stream ADC;
  `TxtReader` acepta una columna `ANALOG-IN-*` si existe. Grabaciones antiguas sin la
  señal siguen funcionando (`has_motor = False`).
- **`readers/session.py` (nuevo)**: abre una **carpeta** de `.rhs` como una única
  grabación continua. La toma real son 8 archivos de 1 min: sin esto la herramienta
  solo puede ver un minuto a la vez.
- `processing.py`: la caché guarda `step_counts` y la tensión cruda de `ANALOG-IN-2`;
  nuevos *slices*/*overviews* de RPM de motor.
- `ui/`: cuarta gráfica con **RPM de motor comandada vs RPM de motor medida**
  (encoder/ratio) — el hueco entre ambas *es* el deslizamiento; control de
  `gear_ratio` y su estimación; estadísticos de motor y de deslizamiento.
- `exporter.py`: columnas nuevas `step_count`, `motor_rpm`, `analog_in_2_v`.

## 6. ¿Debe la interfaz web hacer también el análisis?

**Veredicto: sí, merece la pena, pero no era esta entrega.** Razonamiento y plan
concreto para decidirlo con datos en la mano:

### A favor
- El control real ha quedado en tres cosas (activado, velocidad, dirección): sobra
  pantalla en la interfaz web.
- Las gráficas web (zoom/pan/hover nativos) son bastante mejores que matplotlib
  embebido en Tk, que es lo que hoy limita la exploración.
- Una sola aplicación que lanzar en lugar de dos.
- El backend ya corre en local, así que puede leer las rutas de las grabaciones
  directamente: no hace falta subir 1.3 GB por HTTP.
- El motor de cálculo ya está aislado y probado (`readers` / `processing` /
  `encoder` / `motor` / `gearing` / `stats` / `exporter`), así que la vista web
  reutilizaría exactamente el mismo código, sin duplicar lógica.

### En contra / coste real
- El coste no es la UI sino el *pipeline*: 1.3 GB por sesión y una caché de 1.4 GB.
  Medido, construirla son ~2 s en este equipo (memmap + NVMe), así que **el
  problema que se temía no existe**; pero sigue haciendo falta trabajo en segundo
  plano con progreso y un ciclo de vida de la caché por sesión.
- Hay que elegir librería de gráficas. El CSP/offline del proyecto aconseja
  **vendorizar** (uPlot pesa ~40 kB y va sobrado para millones de puntos ya
  decimados) en vez de depender de un CDN.
- Mientras exista la app Tk hay **dos** clientes que mantener. La salida es
  retirar la Tk cuando la web la iguale, no mantener las dos para siempre.

### Plan propuesto (una entrega, ~4 fases)
1. `backend/app/routes/analysis.py`: `POST /api/analysis/open {path}` (job en
   segundo plano) · `GET /api/analysis/progress` · `GET /api/analysis/meta` ·
   `GET /api/analysis/overview?signal=` · `GET /api/analysis/window?t0=&t1=&signals=`
   · `GET /api/analysis/gearing` · `POST /api/analysis/export`. Todo devuelve series
   **ya decimadas** con `decimate_minmax`, así que el JSON es pequeño.
2. Vendorizar uPlot en `frontend/vendor/` y una segunda pestaña "Análisis" con las
   cuatro gráficas sincronizadas + la tira de vista general.
3. Selector de archivo/carpeta servido por el backend (listar rutas del disco
   local; **no** subida).
4. Retirar la app Tk cuando la web cubra lo mismo, dejando `analysis/` como
   librería.

### Mientras tanto (hecho en esta entrega)
En lugar de dejar el análisis como está, se ha atacado directamente lo que hacía
incómoda la herramienta actual: **tira de vista general navegable** (en una sesión
de 437 s el motor está parado 235 s; encontrar los tramos en marcha a ciegas era
el peor punto), **apertura de la carpeta completa** como una grabación, **relación
medida y adoptada automáticamente**, y **resaltado del deslizamiento**. Eso cubre
la parte de "más amigable" sin comprometerse todavía con la migración a web.

## 7. Verificación
- Tests unitarios de `motor.py`, `gearing.py`, `units.py`, `session.py`, caché y export.
- Validación sobre la toma real: la RPM recuperada debe reproducir las consignas del
  firmware y la relación de engranajes debe salir ≈1.98.
- Suite del backend actualizada al protocolo nuevo (sin PI).
