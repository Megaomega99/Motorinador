# Motorinador — Guía de implementación del backend (FastAPI)

> Documento para **Claude Code** (o cualquier agente/dev) que vaya a construir el backend que sirve al frontend `index.html`. Léelo de arriba a abajo antes de tocar código.

---

## 1. Contexto del proyecto

**Motorinador** es una rueda de hámster motorizada controlada por:

- **Microcontrolador:** Arduino Nano Every (ATmega4809)
- **Motor:** NEMA17 17HS4401 (200 pasos/rev)
- **Driver:** TMC2208 en modo standalone STEP/DIR (MS1=MS2=GND → 1/8 microstep → **1600 pulsos/vuelta**)
- **Encoder:** incremental de cuadratura E38S6G5-600B-G24N (600 PPR · decodificación X4 = **2400 conteos/vuelta**)
- **Pines:**
  - `D4 STEP`, `D5 DIR`, `D6 EN` (LOW = habilitado)
  - `D7 ENC_A`, `D8 ENC_B` (INPUT_PULLUP, ISR CHANGE)

El firmware del Nano ya está escrito (ver `firmware/motorinador.ino` o el bloque pegado en el thread del proyecto). Habla por **Serial USB a 115200 baud** y entiende los comandos de un solo caracter:

| char | acción                          |
|------|---------------------------------|
| `+`  | +5 RPM (clamp a `RPM_MAX=120`)  |
| `-`  | −5 RPM (clamp a `RPM_MIN=5`)    |
| `r`  | invertir dirección              |
| `s`  | toggle motor (pone EN=HIGH/LOW) |
| `z`  | encoder → 0                     |

Cada **1 s** el firmware imprime una línea de estado con el formato:

```
Target: 30.0 RPM  |  Real: 29.8 RPM  |  Ang: 142.3 deg  |  Dir: FWD  |  CORRIENDO
```

---

## 2. Rol del backend

El frontend (`index.html` en este repo) es **estático** y ya funciona. Hoy simula el estado del motor en JavaScript. El backend FastAPI debe:

1. **Hablar con el Arduino por puerto serial** (usando `pyserial`).
2. **Exponer el estado en tiempo real al frontend** vía **WebSocket** (`ws://host:port/ws`).
3. **Aceptar comandos del frontend** (cambio de RPM objetivo, dirección, start/stop, reset encoder, ajuste de parámetros) y traducirlos al protocolo del firmware.
4. **Calcular la velocidad lineal** `v = ω · r` cuando el cliente envíe el radio de la rueda (también puede calcularlo el front; mantén ambos consistentes).
5. **Persistir parámetros** (radio actual, microsteps configurados, PPR del encoder) en un archivo JSON o SQLite simple, para sobrevivir reinicios del backend.

---

## 3. Stack recomendado

```
fastapi          >= 0.110
uvicorn[standard]>= 0.27
pyserial         >= 3.5
pyserial-asyncio >= 0.6     # I/O serial no bloqueante en asyncio
pydantic         >= 2.5
```

Estructura de carpetas sugerida:

```
backend/
  app/
    __init__.py
    main.py              # FastAPI app + lifespan
    config.py            # pydantic-settings (puerto, baud, defaults)
    serial_link.py       # wrapper asíncrono del puerto serial
    state.py             # estado global + broadcaster
    models.py            # Pydantic schemas (mensajes ws)
    routes/
      __init__.py
      control.py         # endpoints REST de respaldo
      ws.py              # endpoint /ws
  tests/
    test_parser.py
    test_state.py
  pyproject.toml
  README.md
```

---

## 4. Capa serial — el corazón del backend

### 4.1 Conexión

- El puerto suele ser `/dev/ttyACM0` en Linux, `COM3+` en Windows, `/dev/cu.usbmodem*` en macOS. Hazlo configurable por env var `MOTORINADOR_PORT`.
- Baud **fijo a 115200**.
- Tras abrir el puerto, **espera 2 s antes de mandar comandos** — el Nano Every se resetea al abrir la conexión USB y el firmware tiene un `delay(200)` de estabilización del driver.

### 4.2 Parser de la línea de estado

Cada segundo llega una línea como:

```
Target: 30.0 RPM  |  Real: 29.8 RPM  |  Ang: 142.3 deg  |  Dir: FWD  |  CORRIENDO
```

Parseala con un regex robusto (tolera espacios extra y signos):

```python
import re

_STATUS_RE = re.compile(
    r"Target:\s*([-+]?\d+\.?\d*)\s*RPM\s*\|\s*"
    r"Real:\s*([-+]?\d+\.?\d*)\s*RPM\s*\|\s*"
    r"Ang:\s*([-+]?\d+\.?\d*)\s*deg\s*\|\s*"
    r"Dir:\s*(FWD|REV)\s*\|\s*"
    r"(CORRIENDO|PARADO)"
)
```

Devuelve un `StatusFrame` Pydantic:

```python
class StatusFrame(BaseModel):
    target_rpm: float
    real_rpm:   float
    angle_deg:  float
    dir:        Literal["FWD", "REV"]
    running:    bool
    ts:         float          # time.time() del backend al recibir la línea
```

**Importante:** las líneas que NO matcheen el regex (banners, ecos de comando, `Encoder -> 0`) deben loguearse y reemitirse como **eventos de log** al WS, no descartarse silenciosamente.

### 4.3 Envío de comandos

El firmware acepta UN caracter a la vez. Envía sin newline (`Serial.read()` en el firmware lee `char`):

```python
async def send(self, cmd: str) -> None:
    assert cmd in {"+","-","r","s","z"}
    self.writer.write(cmd.encode("ascii"))
    await self.writer.drain()
```

Para "subir a 70 RPM desde 30" hay que enviar `+` 8 veces — no hay comando absoluto. **El backend debe traducir un setpoint absoluto a una secuencia de `+`/`-`** comparando contra el último Target conocido (de la última `StatusFrame`).

```python
async def set_target_rpm(self, target: float):
    steps = round((target - self.last_target) / 5)   # paso fijo en firmware
    cmd = "+" if steps > 0 else "-"
    for _ in range(abs(steps)):
        await self.send(cmd)
        await asyncio.sleep(0.02)   # pequeño respiro para no perder chars
```

---

## 5. Protocolo WebSocket `/ws`

### 5.1 Backend → cliente

Todos los mensajes son JSON con campo `type`:

```json
{ "type": "status", "data": {
    "target_rpm": 30.0, "real_rpm": 29.8, "angle_deg": 142.3,
    "dir": "FWD", "running": true, "ts": 1715459123.41
}}

{ "type": "log", "level": "info", "msg": "Encoder -> 0", "ts": 1715459124.11 }

{ "type": "params", "data": {
    "radius_cm": 12.0, "steps_per_rev": 200, "microsteps": 8,
    "enc_ppr": 600, "debounce_us": 50, "rpm_min": 5, "rpm_max": 120,
    "rpm_step": 5
}}

{ "type": "ready", "firmware": "NEMA17 + TMC2208 + ENCODER" }
{ "type": "error", "msg": "Serial port disconnected" }
```

Envía `status` a **20 Hz como máximo**. Si el firmware sólo manda 1 Hz, interpola en el cliente — no en el backend.

### 5.2 Cliente → backend

```json
{ "type": "cmd", "cmd": "start" }      // == toggle si está parado
{ "type": "cmd", "cmd": "stop" }       // == toggle si está corriendo
{ "type": "cmd", "cmd": "reverse" }
{ "type": "cmd", "cmd": "zero_encoder" }
{ "type": "cmd", "cmd": "e_stop" }     // fuerza stop + EN=HIGH

{ "type": "set_target", "rpm": 75 }
{ "type": "set_params", "data": { "radius_cm": 8.5 } }
```

El backend valida con Pydantic, traduce y responde con un nuevo `status` cuando el firmware confirme el cambio.

---

## 6. Endpoints REST (respaldo / health-check)

| método | path                | descripción                              |
|--------|---------------------|------------------------------------------|
| GET    | `/healthz`          | `{"ok": true, "serial": "open"}`         |
| GET    | `/api/state`        | Último `StatusFrame` conocido            |
| GET    | `/api/params`       | Parámetros persistidos                   |
| PUT    | `/api/params`       | Actualiza parámetros (radius, etc.)      |
| POST   | `/api/cmd/{cmd}`    | Misma semántica que `cmd` por WS         |
| POST   | `/api/target`       | Body: `{"rpm": 75}` → setpoint absoluto  |

CORS: permite el origin del frontend (probablemente `http://localhost:5173` en dev, `null` si abren el HTML directo desde el filesystem — usa `allow_origins=["*"]` sólo en dev).

---

## 7. Cálculos en el backend

```python
import math

def angular_velocity_rad_s(rpm: float) -> float:
    return rpm * 2 * math.pi / 60

def linear_velocity_m_s(rpm: float, radius_cm: float) -> float:
    return angular_velocity_rad_s(rpm) * (radius_cm / 100.0)

def perimeter_cm(radius_cm: float) -> float:
    return 2 * math.pi * radius_cm

def step_frequency_hz(rpm: float, steps_per_rev: int, microsteps: int) -> float:
    return rpm * steps_per_rev * microsteps / 60.0
```

Adjúntalos al payload `status` como **campos derivados** (`omega_rad_s`, `v_m_s`) si el cliente envió un radio — así el frontend sólo formatea.

---

## 8. Robustez · cosas que NO se te pueden olvidar

1. **Reconexión automática del puerto serial.** Si el cable se desenchufa, no mueras: emite `{"type":"error"}` por WS, intenta reabrir cada 2 s en backoff.
2. **Una sola conexión serial, varios clientes WS.** Usa un `asyncio.Queue` y un task `broadcaster` que reparte a todos los `WebSocket` activos.
3. **Buffer de log circular** (últimas 200 líneas) para que un cliente que se conecta tarde reciba el contexto previo.
4. **Rate-limit de comandos**: si un usuario arrastra el slider de RPM, no mandes 50 `+` por segundo. Debounce a 100 ms y manda sólo el delta acumulado.
5. **E-STOP es sagrado.** Cualquier `e_stop` ignora cola y envía `s` inmediatamente si el motor está corriendo.
6. **Logs estructurados** (`structlog` o `logging` con JSON formatter) — útiles cuando algo falla con el hardware.
7. **No bloquees el event loop.** Toda I/O serial pasa por `pyserial-asyncio` o un `ThreadPoolExecutor`.

---

## 9. Cómo correr todo

```bash
# 1. Instalar deps
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Conectar Arduino, identificar puerto
ls /dev/cu.usbmodem*           # macOS
ls /dev/ttyACM*                # Linux

# 3. Configurar
export MOTORINADOR_PORT=/dev/ttyACM0
export MOTORINADOR_BAUD=115200

# 4. Lanzar
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 5. Servir el frontend (en otra terminal)
cd ..
python -m http.server 5173
# → abrir http://localhost:5173/index.html
```

En `index.html` reemplaza la sección de estado simulado (`state`, `toggleRun`, etc.) por un cliente WS:

```js
const ws = new WebSocket("ws://localhost:8000/ws");
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.type === "status") {
    state.targetRPM = m.data.target_rpm;
    state.realRPM   = m.data.real_rpm;
    state.angleDeg  = m.data.angle_deg;
    state.dir       = m.data.dir === "FWD" ? 1 : -1;
    state.running   = m.data.running;
    updateGauges();
  } else if (m.type === "log") {
    logLine(m.msg, m.level);
  }
};
function send(payload) { ws.send(JSON.stringify(payload)); }

// Reemplazar handlers locales:
rpm.addEventListener("change", () => send({type:"set_target", rpm: +rpm.value}));
startBtn.addEventListener("click", () =>
  send({type:"cmd", cmd: state.running ? "stop" : "start"}));
```

---

## 10. Tests mínimos

- `test_parser.py` — parsea 20 líneas reales del firmware y casos malformados.
- `test_command_translator.py` — `set_target_rpm(75)` desde 30 produce `["+","+","+","+","+","+","+","+","+"]`.
- `test_ws_protocol.py` — usa `TestClient` para abrir el WS, enviar `cmd`, verificar respuesta.
- Mock del puerto serial con un `asyncio.StreamReader/Writer` falso que emite líneas a 1 Hz.

---

## 11. Notas para Claude Code

- **No reescribas el firmware.** Asume que está fijo y respeta el protocolo de un caracter.
- **No inventes comandos nuevos** sin antes proponerlos al usuario (el firmware tendría que cambiar).
- **No uses `requests` ni librerías sincrónicas** dentro de handlers async.
- Cuando dudes del puerto/baud/timing, **pregunta** antes de hard-codear.
- El frontend ya tiene un easter egg en `easteregg-hamster.js`. **No lo toques.**
- El monitor serial del frontend (`<div class="log">`) espera **HTML** dentro de `innerHTML` con clases `.ok .warn .err .v .ts`. Si vas a re-renderizarlo desde mensajes WS, escapa el texto del firmware antes de inyectarlo.
- Mantén el estilo del proyecto: español en mensajes de usuario, inglés en código y logs técnicos.

Buena suerte. 🐹
