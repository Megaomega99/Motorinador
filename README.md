# Motorinador 🐹

Control en tiempo real de una rueda de hámster motorizada desde el navegador.

---

## ¿Qué es esto?

Motorinador es una aplicación web que te permite **controlar y monitorear un motor eléctrico** conectado a tu computador a través de un cable USB. Desde cualquier navegador puedes arrancar el motor, cambiar su velocidad y dirección, ver cuántas vueltas da por minuto, y más — sin necesidad de tocar código.

---

## Lo que necesitas

| Componente | Descripción |
|---|---|
| **Arduino Nano Every** | La tarjeta electrónica que habla con el motor |
| **Driver TMC2208** | El controlador del motor (modo STEP/DIR) |
| **Motor NEMA17 17HS4401** | El motor paso a paso |
| **Encoder E38S6G5-600B-G24N** | El sensor que mide la velocidad real |
| **Cable USB** | Para conectar el Arduino a la computadora |
| **Fuente de poder para el motor** | El driver TMC2208 necesita su propia alimentación |

---

## Conexiones del circuito

> **Antes de conectar cualquier cosa, asegúrate de que todo esté apagado.**

### Driver TMC2208 → Arduino Nano Every

El driver recibe las órdenes del Arduino a través de tres cables:

```
Arduino           Driver TMC2208
───────           ───────────────
  D4     ────────→   STEP   (cada pulso = un micro-paso del motor)
  D5     ────────→   DIR    (HIGH = adelante, LOW = atrás)
  D6     ────────→   EN     (LOW = motor activo, HIGH = motor libre)
```

Los pines `MS1` y `MS2` del driver van conectados a `GND` para activar el modo **1/8 de micro-paso**.

### Motor NEMA17 → Driver TMC2208

Conecta las dos bobinas del motor a los terminales `A1/A2` y `B1/B2` del driver siguiendo el esquema de colores del fabricante (normalmente están marcados en el motor o en su hoja de datos).

### Encoder → Arduino Nano Every

El encoder tiene 5 cables. Conéctalos así:

```
Encoder (color)      Arduino / Circuito
───────────────      ──────────────────
  Rojo               5 V  (alimentación)
  Negro              GND  (tierra)
  Blanco  (canal A)  D7   + resistencia 4.7 kΩ a 5 V  ①
  Verde   (canal B)  D8   + resistencia 4.7 kΩ a 5 V  ①
```

> ① **Resistencia de pull-up:** Conecta una resistencia de 4.7 kΩ entre el cable de señal (blanco o verde) y el pin de 5 V del Arduino. Esto es necesario porque el encoder tiene salida de tipo "colector abierto" — sin la resistencia la señal no funciona correctamente.

### Diagrama simplificado

```
 ┌──────────────────────────────────────────────┐
 │              Arduino Nano Every               │
 │                                              │
 │  D4 ──────── STEP ──┐                        │
 │  D5 ──────── DIR  ──┤  Driver TMC2208 ──── Motor NEMA17
 │  D6 ──────── EN   ──┘                        │
 │                                              │
 │  D7 ──[4.7kΩ]──5V   ← Canal A (blanco)  ←──┤
 │  D8 ──[4.7kΩ]──5V   ← Canal B (verde)   ←──┤  Encoder
 │  5V ──────────────── Rojo                ←──┤
 │  GND ─────────────── Negro               ←──┘
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

1. Abre el archivo `src/main.cpp` en **PlatformIO** (o Arduino IDE).
2. Conecta el Arduino por USB.
3. Sube el programa al Arduino.

Esto solo se hace una vez. Después el Arduino recuerda el programa aunque se desconecte.

### 3. Configura el puerto serial (si es necesario)

Por defecto el sistema busca el Arduino en `/dev/ttyACM0`. Si tu sistema usa otro puerto (por ejemplo `/dev/ttyACM1` o `/dev/ttyUSB0`), puedes indicárselo con una variable de entorno antes de lanzar:

```bash
export MOTORINADOR_PORT=/dev/ttyACM1
```

En Windows el puerto se llama diferente, por ejemplo `COM3`:

```bash
set MOTORINADOR_PORT=COM3
```

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
| **Target RPM** | Arrastra el deslizador para elegir la velocidad deseada (5 a 120 RPM) |
| **Sentido de giro** | Elige si el motor gira hacia adelante o hacia atrás |
| **Radio de la rueda** | Ingresa el radio en centímetros para calcular la velocidad lineal |
| **Pasos/rev, Microsteps, PPR, Debounce** | Parámetros avanzados del hardware — déjalos en sus valores por defecto a menos que cambies los componentes |

### Panel central — La rueda

Muestra una animación en tiempo real de la rueda girando. La velocidad de la animación refleja las RPM reales medidas por el encoder, no las deseadas.

### Panel derecho — Monitoreo

| Indicador | Significado |
|---|---|
| 🟢 **POWER** | Verde = Arduino conectado y comunicándose |
| 🟢 **ENCODER** | Verde = el encoder está enviando datos de velocidad real |
| **Target RPM** | La velocidad que le pediste al motor |
| **Real RPM** | La velocidad que el encoder está midiendo realmente |
| **Ángulo** | La posición angular acumulada del eje |
| **Velocidad lineal** | Calculada a partir de las RPM reales y el radio configurado |

### Botones de control

| Botón | Acción |
|---|---|
| **START** | Arranca el motor a la velocidad configurada |
| **STOP** | Detiene el motor suavemente |
| **E-STOP** | Parada de emergencia inmediata |
| **Zero encoder** | Pone el conteo de ángulo a cero |

### Consola de log

La parte inferior muestra en tiempo real todos los mensajes que llegan del Arduino — útil para diagnosticar problemas.

---

## Solución de problemas

**La luz POWER está roja o apagada**
→ El Arduino no está conectado o está en el puerto equivocado. Verifica el cable USB y el puerto (`MOTORINADOR_PORT`).

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
