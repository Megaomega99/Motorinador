# Motorinador 🐹

Control en tiempo real de una rueda de hámster motorizada desde el navegador.

---

## ¿Qué es esto?

Motorinador es una aplicación web que te permite **controlar y monitorear un motor eléctrico** conectado a tu computador a través de un cable USB. Desde cualquier navegador puedes arrancar el motor, cambiar su velocidad y dirección, ver cuántas vueltas da por minuto, y más — sin necesidad de tocar código.

---

## Lo que necesitas

| Componente | Descripción |
|---|---|
| **Arduino Nano 33 BLE** | La tarjeta electrónica que habla con el motor (nRF52840, 3.3 V). El mismo firmware también sigue compilando para el **Arduino Nano Every** |
| **Driver TMC2208** | El controlador del motor (modo STEP/DIR) |
| **Motor NEMA17 17HS4401** | El motor paso a paso |
| **Encoder E38S6G5-600B-G24N** | El sensor que mide la velocidad real |
| **Cable USB** | Para conectar el Arduino a la computadora |
| **Fuente de poder para el motor** | El driver TMC2208 necesita su propia alimentación |

---

## Conexiones del circuito

> **Antes de conectar cualquier cosa, asegúrate de que todo esté apagado.**

> **⚠️ Nota sobre la placa (Nano 33 BLE vs Nano Every).** Las conexiones usan los
> **mismos números de pin (D4–D11)** en ambas placas, así que a nivel de esquema
> **no cambia ningún cable**. La diferencia crítica es que el **Nano 33 BLE es de
> 3.3 V y NO tolera 5 V** (el Nano Every es de 5 V y sí tolera). En el 33 BLE:
>
> **REGLA DE ORO: ningún pin puede superar 3.3 V, nunca.** Un solo roce del rail
> de 14–24 V (Vcc del encoder o VM del motor) contra un pin de 3.3 V **fríe la
> placa al instante**. Enruta esos cables lejos de la fila D4–D11 y de 3.3 V, y
> fíjalos para que no puedan tocarlos.
>
> - **STEP/DIR/EN** del TMC2208: salidas del Arduino a 3.3 V. Asegúrate de que la
>   alimentación lógica `VIO` del driver sea 3.3 V (o compatible con 3.3 V).
> - **Encoder (open-collector NPN):** su salida **solo tira a masa**; el nivel
>   alto lo pone el **pull-up interno** del Arduino (a 3.3 V), así que aunque
>   alimentes el encoder a 5–24 V, **A/B nunca superan 3.3 V** y se conectan
>   **directo a D7/D8** (sin conversor de nivel). **NUNCA** pongas un pull-up
>   externo a 5/14/24 V — eso sí metería sobretensión en un pin de 3.3 V.
>   - **Antes de fiarte, verifícalo** (los "NPN" de bazar varían entre lotes):
>     alimenta el encoder, pon 10 kΩ de A a 3.3 V (sin el Arduino) y gira el eje.
>     Debe alternar **0 V ↔ ~3.3 V**. Si ves más de 3.3 V, la salida "empuja" a
>     Vcc → necesitas un **conversor de nivel** y NO conectar directo.
>   - **Protección recomendada:** **1 kΩ en serie** en A y B (encoder→D7/D8). No
>     cambia el funcionamiento y protege el GPIO de picos/rebote de masa del motor
>     y de un roce accidental.
> - **Masa en estrella:** une Arduino GND, encoder GND y GND de la fuente del
>   motor en **un solo punto**, no en cadena, para minimizar el rebote de tierra
>   del motor.

### Driver TMC2208 → Arduino

El driver recibe las órdenes del Arduino a través de tres cables:

```
Arduino           Driver TMC2208
───────           ───────────────
  D4     ────────→   STEP   (cada pulso = un micro-paso del motor)
  D5     ────────→   DIR    (HIGH = adelante, LOW = atrás)
  D6     ────────→   EN     (LOW = motor activo, HIGH = motor libre)
```

Los pines `MS1` y `MS2` del driver van conectados a `GND` para activar el modo **1/8 de micro-paso**.

### Salidas espejo para osciloscopio / analizador lógico

Tres pines replican en tiempo real las señales internas para que puedas conectar un osciloscopio o analizador lógico sin interferir con el circuito principal:

```
Arduino           Señal replicada
───────           ───────────────
  D9    ────────→  Canal A del encoder  (espejo de D7)
  D10   ────────→  Canal B del encoder  (espejo de D8)
  D11   ────────→  STEP al driver       (espejo de D4)
```

La actualización de D9 y D10 ocurre dentro de las ISRs del encoder (post-debounce), y la de D11 ocurre en el mismo instante que el pulso STEP real.

### Motor NEMA17 → Driver TMC2208

Conecta las dos bobinas del motor a los terminales `A1/A2` y `B1/B2` del driver siguiendo el esquema de colores del fabricante (normalmente están marcados en el motor o en su hoja de datos).

### Encoder → Arduino

El encoder tiene 5 cables. Conéctalos así:

```
Encoder (color)      Arduino / Circuito
───────────────      ──────────────────
  Rojo               Fuente externa +   (5–24 V; en la práctica ≥ ~7 V)  ②
  Negro              GND  (tierra común, en estrella, con el Arduino)
  Blanco  (canal A)  D7   [+ 1 kΩ en serie recomendado]  ①
  Verde   (canal B)  D8   [+ 1 kΩ en serie recomendado]  ①
```

> ① **Salida open-collector (NPN):** el firmware activa el **pull-up interno** de
> D7/D8, así que **no hacen falta resistencias de pull-up externas**. El nivel
> alto lo fija el pull-up interno (3.3 V en el Nano 33 BLE, 5 V en el Nano Every),
> por lo que en el 33 BLE la señal nunca supera 3.3 V. Se recomienda **1 kΩ en
> serie** en cada canal como protección del GPIO (opcional pero barato). La tierra
> (Negro) debe ser **común** con la del Arduino.
>
> ② El encoder E38S6G5-600B-G24N admite 5–24 V, pero lleva un regulador interno
> (78M05) con ~2 V de dropout: a 5 V va justo/inestable, así que **aliméntalo con
> ≥ ~7 V** (p. ej. 12 V). Esa tensión **solo** alimenta el encoder; **jamás debe
> tocar A, B ni ningún pin del Arduino** (ver la REGLA DE ORO arriba).

### Diagrama simplificado

```
 ┌──────────────────────────────────────────────┐
 │       Arduino Nano 33 BLE / Nano Every        │
 │                                              │
 │  D4 ──────── STEP ──┐                        │
 │  D5 ──────── DIR  ──┤  Driver TMC2208 ──── Motor NEMA17
 │  D6 ──────── EN   ──┘                        │
 │                                              │
 │  D7 ←─[1kΩ]── Canal A (blanco)  [pull-up int.] ←──┤
 │  D8 ←─[1kΩ]── Canal B (verde)   [pull-up int.] ←──┤  Encoder
 │  GND ─────────────── Negro (tierra común)      ←──┤  (Rojo → fuente ext. ≥7 V)
 │                                              │
 │  D9  ───────────────────────────────────────→  Osciloscopio (canal A)
 │  D10 ───────────────────────────────────────→  Osciloscopio (canal B)
 │  D11 ───────────────────────────────────────→  Osciloscopio (STEP)
 └──────────────────────────────────────────────┘
          │
        USB
          │
      Computador
```

---

## Instalación (solo la primera vez)

### 1. Instala las dependencias de Python

Abre una terminal y ejecuta:

```bash
pip install -r backend/requirements.txt
```

> Si usas Conda (ambiente `base`):
> ```bash
> conda install -n base pyserial-asyncio pydantic-settings -c conda-forge
> pip install fastapi "uvicorn[standard]"
> ```

### 2. Carga el firmware en el Arduino

Con **PlatformIO** el proyecto define dos entornos en `platformio.ini`:

| Placa | Entorno | Comando de carga |
|---|---|---|
| **Arduino Nano 33 BLE** | `nano33ble` | `pio run -e nano33ble -t upload` |
| **Arduino Nano Every** | `nano_every` | `pio run -e nano_every -t upload` |

1. Conecta el Arduino por USB.
2. Ejecuta el comando de carga correspondiente a tu placa (o usa el botón *Upload*
   de la extensión de PlatformIO seleccionando el entorno adecuado).

> En el Nano 33 BLE el `upload` hace automáticamente el "touch" a 1200 bps para
> entrar al bootloader; no necesitas pulsar reset manualmente en condiciones
> normales.

Esto solo se hace una vez. Después el Arduino recuerda el programa aunque se desconecte.

### 3. Configura el puerto serial (opcional)

**No necesitas configurar nada.** El sistema **detecta automáticamente** el puerto del Arduino en Linux, Windows y macOS — busca dispositivos USB con los identificadores de Arduino y de los conversores USB‑Serial comunes (CH340, FTDI, CP210x, etc.).

Si tienes varios dispositivos USB conectados y quieres forzar uno específico, puedes hacerlo con una variable de entorno antes de lanzar:

| Sistema | Ejemplo |
|---|---|
| **Linux** | `export MOTORINADOR_PORT=/dev/ttyACM1` |
| **macOS** | `export MOTORINADOR_PORT=/dev/cu.usbmodem14101` |
| **Windows (CMD)** | `set MOTORINADOR_PORT=COM3` |
| **Windows (PowerShell)** | `$env:MOTORINADOR_PORT="COM3"` |

Para volver a la detección automática: `export MOTORINADOR_PORT=auto` (o simplemente no definir la variable).

> Puedes ver qué puertos detecta el sistema visitando `http://localhost:8000/api/ports` mientras el servidor está corriendo.

---

## Cómo lanzar el sistema

1. **Conecta el Arduino** por USB a la computadora.
2. **Abre una terminal** en la carpeta `Motorinador/`.
3. Ejecuta:

```bash
python backend/main.py
```

4. Abre tu navegador y ve a:

```
http://localhost:8000
```

¡Listo! La interfaz aparecerá automáticamente. No necesitas nada más.

> Para detener el sistema presiona `Ctrl + C` en la terminal.

---

## La interfaz: qué hace cada cosa

### Panel izquierdo — Parámetros

| Control | Para qué sirve |
|---|---|
| **Target RPM** | Arrastra el deslizador o escribe el valor exacto (1 a 120 RPM, en pasos de 1 RPM) |
| **Sentido de giro** | Elige si el motor gira hacia adelante o hacia atrás |
| **Radio de la rueda** | Ingresa el radio en centímetros para calcular la velocidad lineal |
| **Pasos/rev, Microsteps, PPR, Debounce** | Parámetros avanzados del hardware — déjalos en sus valores por defecto a menos que cambies los componentes |

### Panel central — La rueda

Muestra una animación en tiempo real de la rueda girando. La velocidad de la animación refleja las RPM reales medidas por el encoder, no las deseadas.

### Panel derecho — Monitoreo

| Indicador | Significado |
|---|---|
| 🟢 **POWER** | Verde = Arduino conectado y comunicándose |
| 🟢 **ENCODER** | Verde = llegan datos frescos del encoder (se apaga si pasan >2.5 s sin datos). La velocidad medida sigue viva incluso con el motor en pausa |
| **Target RPM** | La velocidad que le pediste al motor |
| **Real RPM** | La velocidad que el encoder está midiendo realmente |
| **Ángulo** | La posición angular acumulada del eje |
| **Velocidad lineal** | Calculada a partir de las RPM reales y el radio configurado |

### Botones de control

| Botón | Acción |
|---|---|
| **START** | Arranca el motor a la velocidad configurada |
| **STOP** | Detiene el motor y desenergiza el driver (el eje queda libre) |
| **E-STOP** | Parada de emergencia real: comando dedicado `e` que detiene y desenergiza el driver incondicionalmente |
| **Zero encoder** | Pone el conteo de ángulo a cero |

### Protocolo serial (firmware ↔ backend, 115200 baud)

| Comando | Formato | Acción |
|---|---|---|
| `v` | `v<rpm>\n` (ej. `v37.5`) | Fijar RPM objetivo absoluto, recorte a [1, 120] |
| `+` / `-` | un carácter | Ajuste relativo ±1 RPM |
| `1` / `0` | un carácter | Marcha / paro (idempotentes; `0` desenergiza el driver) |
| `e` | un carácter | E-STOP incondicional (desenergiza e imprime `E-STOP`) |
| `f` / `b` | un carácter | Dirección adelante / reversa (absoluta) |
| `p` / `l` | un carácter | Modo PI / LIBRE (absoluto) |
| `z` | un carácter | Encoder a cero |
| `s` / `r` / `c` | un carácter | Toggles legados (solo uso manual por terminal) |

> Los límites de velocidad (`rpm_min`, `rpm_max`, `rpm_step`) los fija el servidor
> como espejo de las constantes del firmware; los valores enviados por los clientes
> en `set_params` / `PUT /api/params` se ignoran.

> ⚠️ **Seguridad:** el servidor no tiene autenticación y acepta peticiones de
> cualquier origen (CORS abierto). Está pensado para uso local (`localhost`) o en
> una red de laboratorio de confianza — no lo expongas a redes compartidas o a
> internet sin añadir autenticación.

### Consola de log

La parte inferior muestra en tiempo real todos los mensajes que llegan del Arduino — útil para diagnosticar problemas.

---

## Solución de problemas

**La luz POWER está roja o apagada**
→ El Arduino no está conectado. Verifica el cable USB. El sistema busca el puerto automáticamente, así que normalmente basta con conectar la placa y esperar un par de segundos. Si sigue sin conectar, visita `http://localhost:8000/api/ports` para ver qué puertos detecta el sistema y, si es necesario, fuerza uno con `MOTORINADOR_PORT`.

**Tengo varios dispositivos USB y elige el equivocado**
→ Define manualmente el puerto con `MOTORINADOR_PORT` (ver sección "Configura el puerto serial").

**El motor no se mueve aunque POWER esté verde**
→ Verifica que la fuente de alimentación del driver TMC2208 esté encendida.

**Real RPM siempre muestra 0**
→ Revisa las conexiones del encoder, especialmente las resistencias de pull-up de 4.7 kΩ.

**La página no carga**
→ Verifica que el servidor esté corriendo (`python backend/main.py`) y que la dirección sea exactamente `http://localhost:8000`.

---

## Crédito

Desarrollado por **Megaomega · Engineering for Well-Being**.

> *Psst:* hay un huevo de pascua escondido en la interfaz. 🐾
