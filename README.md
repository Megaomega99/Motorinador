# Motorinador 🐹

Control en tiempo real de una rueda de hámster motorizada desde el navegador.

---

## ¿Qué es esto?

Motorinador es una aplicación web que te permite **controlar y monitorear un motor eléctrico** conectado a tu computador a través de un cable USB. Desde cualquier navegador puedes arrancar el motor, cambiar su velocidad y dirección, ver cuántas vueltas da por minuto, y más — sin necesidad de tocar código.

El control es de **tres cosas**: activado, velocidad y dirección. No hay lazo de
realimentación: un motor paso a paso con el TMC2208 sigue el tren de pasos con
exactitud, así que la velocidad **es** la que se le pide mientras no pierda paso.
El encoder no cierra ningún lazo — es el **instrumento** que verifica si el motor
siguió la consigna y delata pasos perdidos o atascos.

> **La transmisión es por engranajes.** El encoder no está en el eje del motor:
> da ≈**1.99 vueltas por cada vuelta del motor** (medido sobre datos reales; el
> nominal supuesto era 2.1). Por eso la interfaz distingue *velocidad del
> encoder* de *velocidad del motor* = encoder ÷ relación, y solo la segunda es
> comparable con la consigna.

> Hubo un controlador PI (diseño IMC) sobre la velocidad del encoder. **Se
> retiró** al montar los engranajes: la consigna pasaba a significar dos cosas
> distintas según el modo y, ante un atasco, el integrador saturaba y el firmware
> acababa comandando el máximo a un motor bloqueado. El razonamiento completo, con
> las medidas, está en
> [docs/superpowers/specs/2026-07-29-motor-signal-y-retirada-del-PI-design.md](docs/superpowers/specs/2026-07-29-motor-signal-y-retirada-del-PI-design.md).

El **análisis offline** de las grabaciones (electrodos + encoder + señal del motor)
está en la **misma interfaz**, en la pestaña «Análisis de grabaciones»: abre un
`.rhs` o una carpeta de sesión completa, navega con zoom y arrastre, y exporta —
ver [analysis/README.md](analysis/README.md).

---

## Lo que necesitas

| Componente | Descripción |
|---|---|
| **Arduino Nano 33 BLE** | La tarjeta electrónica que habla con el motor (nRF52840, 3.3 V). El mismo firmware también sigue compilando para el **Arduino Nano Every** |
| **Driver TMC2208** | El controlador del motor (modo STEP/DIR) |
| **Motor NEMA17 17HS4401** | El motor paso a paso |
| **Encoder E38S6G5-600B-G24N** | El sensor que verifica la velocidad real (va tras los engranajes) |
| **Cable USB** | Para conectar el Arduino a la computadora |
| **Fuente de poder para el motor** | El driver TMC2208 necesita su propia alimentación |

---

## Conexiones del circuito

> **Antes de conectar cualquier cosa, asegúrate de que todo esté apagado.**

> **⚠️ Nota sobre la placa (Nano 33 BLE vs Nano Every).** Las conexiones usan los
> **mismos números de pin (D2–D11)** en ambas placas, así que a nivel de esquema
> **no cambia ningún cable**. La diferencia crítica es que el **Nano 33 BLE es de
> 3.3 V y NO tolera 5 V** (el Nano Every es de 5 V y sí tolera). En el 33 BLE:
>
> **REGLA DE ORO: ningún pin puede superar 3.3 V, nunca.** Un solo roce del rail
> de 14–24 V (Vcc del encoder o VM del motor) contra un pin de 3.3 V **fríe la
> placa al instante**. Enruta esos cables lejos de la fila D2–D11 y de 3.3 V, y
> fíjalos para que no puedan tocarlos.
>
> - **STEP/DIR/EN** del TMC2208: salidas del Arduino a 3.3 V. Asegúrate de que la
>   alimentación lógica `VIO` del driver sea 3.3 V (o compatible con 3.3 V).
> - **Encoder (open-collector NPN):** su salida **solo tira a masa**; el nivel
>   alto lo pone el **pull-up interno** del Arduino (a 3.3 V), así que aunque
>   alimentes el encoder a 5–24 V, **A/B nunca superan 3.3 V** y se conectan
>   **directo a D2/D3** (sin conversor de nivel). **NUNCA** pongas un pull-up
>   externo a 5/14/24 V — eso sí metería sobretensión en un pin de 3.3 V.
>   - **Antes de fiarte, verifícalo** (los "NPN" de bazar varían entre lotes):
>     alimenta el encoder, pon 10 kΩ de A a 3.3 V (sin el Arduino) y gira el eje.
>     Debe alternar **0 V ↔ ~3.3 V**. Si ves más de 3.3 V, la salida "empuja" a
>     Vcc → necesitas un **conversor de nivel** y NO conectar directo.
>   - **Protección recomendada:** **1 kΩ en serie** en A y B (encoder→D2/D3). No
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
  D9    ────────→  Canal A del encoder  (espejo de D2)
  D10   ────────→  Canal B del encoder  (espejo de D3)
  D11   ────────→  STEP al driver       (espejo de D4)
```

La actualización de D9 y D10 ocurre dentro de las ISRs del encoder (post-debounce), y la de D11 ocurre en el mismo instante que el pulso STEP real.

**D11 es además la fuente de la velocidad del motor en las grabaciones.** En la
toma con el Intan va a la entrada `ANALOG-IN-2`, donde queda registrado como una
onda cuadrada de 3.3 V al 50 % de ciclo. Su frecuencia es el número de micropasos
por segundo, así que de ella sale la velocidad **comandada** del motor, exacta y
sin pasar por el encoder:

```
RPM_motor = f_STEP · 60 / 1600          (1600 micropasos por vuelta)
```

Tener las dos señales grabadas (consigna por D11, movimiento real por el encoder)
es lo que permite medir la relación de engranajes y detectar pasos perdidos. Lo
explota [analysis/](analysis/README.md).

### Motor NEMA17 → Driver TMC2208

Conecta las dos bobinas del motor a los terminales `A1/A2` y `B1/B2` del driver siguiendo el esquema de colores del fabricante (normalmente están marcados en el motor o en su hoja de datos).

### Encoder → Arduino

> **⚠️ Los pines del encoder cambiaron (2026-07-30): antes D7/D8, ahora D2/D3.**
> D7 y D8 se dañaron. Si tienes el montaje antiguo cableado a D7/D8, mueve los dos
> cables **y recarga el firmware** — los números de pin están compilados dentro, no
> se configuran desde la interfaz. Ambas placas admiten interrupción en cualquier
> pin digital, así que el cambio no tiene más consecuencias.

El encoder tiene 5 cables. Conéctalos así:

```
Encoder (color)      Arduino / Circuito
───────────────      ──────────────────
  Rojo               Fuente externa +   (5–24 V; en la práctica ≥ ~7 V)  ②
  Negro              GND  (tierra común, en estrella, con el Arduino)
  Blanco  (canal A)  D2   [+ 1 kΩ en serie recomendado]  ①
  Verde   (canal B)  D3   [+ 1 kΩ en serie recomendado]  ①
```

> ① **Salida open-collector (NPN):** el firmware activa el **pull-up interno** de
> D2/D3, así que **no hacen falta resistencias de pull-up externas**. El nivel
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
 │  D2 ←─[1kΩ]── Canal A (blanco)  [pull-up int.] ←──┤
 │  D3 ←─[1kΩ]── Canal B (verde)   [pull-up int.] ←──┤  Encoder
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

## Cómo se usa (doble clic)

**No hay que instalar nada a mano ni abrir una terminal.**

| Sistema | Qué hacer |
|---|---|
| **Windows** | Doble clic en **`Motorinador.bat`** |
| **Linux / macOS** | Doble clic en **`motorinador.sh`** (o `./motorinador.sh` en una terminal) |

El lanzador busca Python, instala las dependencias **la primera vez** (tarda un par
de minutos y necesita internet), arranca el programa y abre el navegador en
`http://127.0.0.1:8000`.

Deja esa ventana abierta mientras uses el programa: **cerrarla lo detiene**.

> Lo único que necesitas tener instalado es **Python 3.10 o superior**. Si no lo
> tienes, el lanzador te lo dirá con el enlace de descarga; al instalarlo marca la
> casilla *«Add python.exe to PATH»*.

> **Sin Arduino conectado el programa funciona igual** para analizar grabaciones:
> la pestaña «Análisis de grabaciones» no necesita hardware.

---

## Instalación del firmware (solo si vas a mover el motor)

### Carga el firmware en el Arduino

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

### Configura el puerto serial (opcional)

**No necesitas configurar nada.** El sistema **detecta automáticamente** el puerto del Arduino en Linux, Windows y macOS — busca dispositivos USB con los identificadores de Arduino y de los conversores USB‑Serial comunes (CH340, FTDI, CP210x, etc.).

Si tienes varios dispositivos USB conectados y quieres forzar uno específico, puedes hacerlo con una variable de entorno antes de lanzar:

| Sistema | Ejemplo |
|---|---|
| **Linux** | `export MOTORINADOR_PORT=/dev/ttyACM1` |
| **macOS** | `export MOTORINADOR_PORT=/dev/cu.usbmodem14101` |
| **Windows (CMD)** | `set MOTORINADOR_PORT=COM3` |
| **Windows (PowerShell)** | `$env:MOTORINADOR_PORT="COM3"` |

Para volver a la detección automática: `export MOTORINADOR_PORT=auto` (o simplemente no definir la variable).

Y para **trabajar sin Arduino** (solo la pestaña de análisis), `off` desactiva el
serial por completo, así no se reintenta ni se avisa:
`export MOTORINADOR_PORT=off` (también valen `none`, `no`, `disabled`).

> Puedes ver qué puertos detecta el sistema visitando `http://localhost:8000/api/ports` mientras el servidor está corriendo.

---

## Arranque manual (para desarrollo)

El doble clic cubre el uso normal. Si prefieres la terminal:

```bash
python backend/main.py          # → http://127.0.0.1:8000
```

Variables de entorno útiles:

| Variable | Para qué | Por defecto |
|---|---|---|
| `MOTORINADOR_PORT` | Puerto del Arduino, o `off` para no usarlo | `auto` |
| `MOTORINADOR_ANALYSIS_ROOT` | Carpeta desde la que se pueden abrir grabaciones | la del proyecto |
| `MOTORINADOR_HOST` | Interfaz de escucha | `127.0.0.1` (solo local) |
| `MOTORINADOR_HTTP_PORT` | Puerto del servidor | `8000` |
| `MOTORINADOR_RELOAD` | `1` para recargar al editar código | desactivado |

> El servidor escucha **solo en local** por defecto. La API no tiene autenticación
> y puede leer grabaciones del disco, así que no la expongas a la red del
> laboratorio (`MOTORINADOR_HOST=0.0.0.0`) sin saber lo que haces.

> Para detenerlo: `Ctrl + C`.

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

Muestra una animación en tiempo real de la rueda girando. La velocidad de la animación
refleja las RPM **del motor medidas** (encoder ÷ relación de engranajes), no las pedidas:
si el motor se atasca, la rueda de la pantalla se frena con él.

### Panel derecho — Monitoreo

| Indicador | Significado |
|---|---|
| 🟢 **POWER** | Verde = Arduino conectado y comunicándose |
| 🟢 **ENCODER** | Verde = llegan datos frescos del encoder (se apaga si pasan >2.5 s sin datos). La velocidad medida sigue viva incluso con el motor en pausa |
| 🟢 **SIGUE / PIERDE PASOS** | Verde = el motor sigue la consigna; ámbar = deslizamiento > 10 %, está perdiendo pasos o atascado |
| **Consigna · motor** | La velocidad que le pediste al motor |
| **Motor medido** | Velocidad real del motor = encoder ÷ relación de engranajes |
| **Encoder** | Velocidad del encoder en bruto (gira ≈2× más rápido que el motor) |
| **Deslizamiento** | `1 − medido/consigna` en %. 0 % = sigue el tren de pasos |
| **Ángulo** | La posición angular acumulada del eje del encoder |
| **Velocidad lineal** | Calculada con las RPM **del motor** y el radio configurado (la rueda va en el eje del motor) |

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
| `z` | un carácter | Encoder a cero |
| `s` / `r` | un carácter | Toggles legados (solo uso manual por terminal) |

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

## La pestaña «Análisis de grabaciones»

La misma aplicación analiza las grabaciones del Intan sin tocar el Arduino, con el
paquete [analysis/](analysis/README.md) como motor de cálculo.

1. **Elige la grabación** en el navegador de archivos de la izquierda. Si una
   carpeta contiene varios `.rhs` (Intan parte las tomas largas en archivos de un
   minuto), aparece arriba **«Abrir esta sesión completa»**: los une en una sola
   grabación continua.
2. **Espera la barra de progreso.** La toma de referencia (8 archivos, 1.3 GB,
   437 s) tarda unos **3 s** en procesarse.
3. **Navega**: la tira superior muestra toda la sesión — clic o arrastre para
   saltar. En las gráficas, **arrastra** para desplazar, **rueda** para zoom y
   **doble clic** para volver a verlo todo. El cursor lee los valores de las
   cuatro gráficas a la vez.
4. **Cuatro gráficas** con el mismo eje de tiempo: electrodos, ángulo, velocidad
   del encoder y **motor** (consigna del espejo STEP frente a la medida referida
   al eje del motor). El hueco entre esas dos curvas es el deslizamiento.
5. **Exporta** solo la ventana visible o la sesión completa, con las columnas
   derivadas añadidas (ver [analysis/README.md](analysis/README.md#columnas-del-export)).

### Dónde puede leer y escribir

Por seguridad el servidor solo abre y escribe **dentro de una carpeta raíz**, que
por defecto es la del proyecto. Ni `..` ni un enlace simbólico sacan de ahí. Si
guardas las tomas en otro sitio:

```bash
MOTORINADOR_ANALYSIS_ROOT=/ruta/a/mis/grabaciones python backend/main.py
```

> Solo hay **una sesión abierta a la vez**: son ~230 MB en RAM y una caché
> temporal de ~1.4 GB en disco, que se borra al cerrar la sesión o el servidor.

---

## Solución de problemas

**La consola repite avisos del puerto serial**

→ Ya no debería: el aviso se emite **una vez por causa** y los reintentos van
espaciándose (2 s → 30 s). Si solo quieres analizar grabaciones y no tienes el
Arduino conectado, arranca sin serial y no se intentará nada:

```bash
MOTORINADOR_PORT=off python backend/main.py
```

La pestaña de análisis funciona igual; los comandos del motor responden 503.

**La luz POWER está roja o apagada**
→ El Arduino no está conectado. Verifica el cable USB. El sistema busca el puerto automáticamente, así que normalmente basta con conectar la placa y esperar un par de segundos. Si sigue sin conectar, visita `http://localhost:8000/api/ports` para ver qué puertos detecta el sistema y, si es necesario, fuerza uno con `MOTORINADOR_PORT`.

**Tengo varios dispositivos USB y elige el equivocado**
→ Define manualmente el puerto con `MOTORINADOR_PORT` (ver sección "Configura el puerto serial").

**El motor no se mueve aunque POWER esté verde**
→ Verifica que la fuente de alimentación del driver TMC2208 esté encendida.

**Motor medido siempre muestra 0**
→ Revisa las conexiones del encoder: canal A a **D2** y canal B a **D3** (¡cambiaron
desde D7/D8!), y la tierra común. La consigna puede ir bien y el encoder no leer
nada: son señales independientes. Si acabas de mover los cables, **recarga el
firmware**: los pines están compilados dentro.

**El indicador dice PIERDE PASOS constantemente**
→ O el motor se está atascando de verdad (par insuficiente, algo roza), o la relación de
engranajes configurada no es la real. Comprueba la relación con la herramienta de análisis
(`Abrir carpeta de sesión` → *Medir en los datos*) y ponla en el campo «Vueltas de encoder
por vuelta de motor».

**La página no carga**
→ Verifica que el servidor esté corriendo (`python backend/main.py`) y que la dirección sea exactamente `http://localhost:8000`.

---

## Crédito

Desarrollado por **Megaomega · Engineering for Well-Being**.

> *Psst:* hay un huevo de pascua escondido en la interfaz. 🐾
