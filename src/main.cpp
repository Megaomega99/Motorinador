#include <Arduino.h>

// =============================================================
// Control de motor NEMA17 17HS4401 con driver TMC2208
// y encoder incremental de cuadratura E38S6G5-600B-G24N
//
// Plataforma : Arduino Nano Every (ATmega4809)
// Modo driver: standalone STEP/DIR  MS1=MS2=GND → 1/8 micropaso
//
// ── Conexiones driver ──────────────────────────────────────
//   D4 → STEP    D5 → DIR    D6 → EN  (LOW = habilitado)
//
// ── Conexiones encoder (NPN open-collector) ────────────────
//   Rojo  → 5 V        Negro → GND
//   Blanco → D7 (A)    Verde → D8 (B)
//   Pull-up interno activado por software (~40 kΩ)
//
// ── Control por Monitor Serial  115200 baud ────────────────
//   ABSOLUTOS (idempotentes, usados por el backend):
//     'v<rpm>\n' → fijar RPM objetivo (ej: "v37.5\n"), recorte a [1,120]
//     '1' → marcha        '0' → paro (desenergiza el driver)
//     'e' → PARO DE EMERGENCIA (incondicional, desenergiza)
//     'f' → dirección FWD 'b' → dirección REV
//     'p' → modo PI       'l' → modo LIBRE (lazo abierto)
//   RELATIVOS / LEGADO (uso manual por terminal):
//     '+' → +1 RPM   '-' → -1 RPM
//     's' → alternar paro/marcha   'r' → invertir dirección
//     'c' → alternar PI ↔ LIBRE
//   COMUNES:
//     'z' → poner encoder a cero
// =============================================================

// ── Pines driver ─────────────────────────────────────────────
const uint8_t PIN_STEP  = 4;
const uint8_t PIN_DIR   = 5;
const uint8_t PIN_EN    = 6;
// ── Pines salida espejo (osciloscopio / analizador lógico) ───
const uint8_t PIN_ENC_OA   = 9;
const uint8_t PIN_ENC_OB   = 10;
const uint8_t PIN_STEP_OUT = 11;
// ── Pines encoder ────────────────────────────────────────────
const uint8_t PIN_ENC_A = 7;   // Canal A — interrupción CHANGE
const uint8_t PIN_ENC_B = 8;   // Canal B — interrupción CHANGE

// ── Parámetros mecánicos ─────────────────────────────────────
// 200 pasos/rev × 8 micropasos = 1600 pulsos/vuelta
const uint16_t STEPS_PER_REV = 1600;

// ── Parámetros encoder ───────────────────────────────────────
// Decodificación X4: COUNTS_PER_REV = PPR × 4
const int32_t ENC_PPR        = 600;
const int32_t COUNTS_PER_REV = ENC_PPR * 4;   // 2400 cuentas/vuelta

// ── Límites y paso de velocidad ──────────────────────────────
const float RPM_MIN  =   1.0f;
const float RPM_MAX  = 120.0f;
const float RPM_STEP =   1.0f;

// ── Períodos de temporización ────────────────────────────────
const unsigned long STATUS_INTERVAL_MS  = 1000UL;   // reporte serial
const unsigned long CONTROL_INTERVAL_US = 10000UL;  // lazo PI = 10 ms

// ── Debounce encoder ─────────────────────────────────────────
// A 120 RPM el intervalo mínimo entre flancos es ≈ 208 µs; 50 µs no descarta pulsos reales.
static const uint16_t DEBOUNCE_US = 50;

// ── Controlador PI de velocidad (diseño IMC) ─────────────────
// Planta:  G(s) = 1 / (tau·s + 1),  tau = 0.0001463 s
// Lambda (suavidad IMC): 0.125 s
// C(s) = Kp + Ki/s,  con Kp = tau/lambda,  Ki = 1/lambda
//
// Discretización integral (Forward Euler, Ts = 10 ms):
//   I[k] = I[k-1] + Ki·Ts·e[k]   ← solo si u[k] no está saturado
//   u[k] = Kp·e[k] + I[k]
const float PI_KP = 0.00117f;
const float PI_KI = 8.0f;
const float PI_TS = 0.01f;           // s

// ── Medición de velocidad: media móvil adaptativa + IIR ──────
// La ventana crece hacia atrás desde la muestra más reciente hasta
// acumular ≥ VEL_MIN_COUNTS cuentas (o llegar a VEL_BUF_N muestras),
// con un mínimo de VEL_WIN_MIN muestras.
//   ≥ ~6 RPM → ventana de 80 ms (comportamiento clásico)
//   a 1 RPM  → crece hasta 500 ms → cuantización ≤ 6 % (vs ±31 % con 80 ms)
// Coste: hasta ~250 ms de retardo extra por debajo de ~6 RPM; el PI
// (λ = 0.125 s) debe verificarse en banco a esas velocidades.
const uint8_t VEL_BUF_N      = 50;   // 500 ms de deltas de 10 ms
const uint8_t VEL_WIN_MIN    = 8;    // ventana mínima = 80 ms
const int32_t VEL_MIN_COUNTS = 16;   // crecer hasta |sum| ≥ 16 cuentas
// Filtro IIR de primer orden sobre la velocidad cruda antes del PI.
// α=0.3 → f_c ≈ 5.7 Hz, retardo ≈ 23 ms — amortigua ruido de cuadratura
// sin afectar la respuesta en el ancho de banda del lazo (λ=0.125 s → ~1.3 Hz).
const float VEL_ALPHA = 0.3f;

// ─────────────────────────────────────────────────────────────
// Variables de estado del sistema
// ─────────────────────────────────────────────────────────────
float   targetRPM    = 1.0f;    // RPM objetivo (ambos modos)
float   controlRPM   = 1.0f;    // RPM enviadas al driver (salida del PI o targetRPM)
float   piIntegral   = 1.0f;    // acumulador integral
float   measuredRPM  = 0.0f;    // velocidad medida (media móvil, actualizada cada 10 ms)
bool    usePID       = false;   // false = lazo abierto, true = lazo cerrado
bool    motorEnabled = true;
bool    dirForward   = true;

// Buffer circular para la media móvil adaptativa de velocidad
// (delta máx. a 120 RPM en 10 ms = 48 cuentas → int16_t sobra)
static int16_t velBuf[VEL_BUF_N] = {0};
static uint8_t velHead           = 0;
static int32_t lastEncCtrl       = 0;   // conteo al final del ciclo anterior

// Temporización no bloqueante
unsigned long lastStepTime    = 0UL;
unsigned long lastStatusTime  = 0UL;
unsigned long lastControlTime = 0UL;
bool          stepPinHigh     = false;

// Encoder — volatile porque se modifican dentro de las ISRs
volatile int32_t encoderCount = 0;
static volatile unsigned long lastA_us = 0;
static volatile unsigned long lastB_us = 0;

// =============================================================
// ISRs de cuadratura X4
// Decodificación: si el pin que cambió tiene el mismo nivel que
// el otro canal → sentido horario (+1); distinto → antihorario (−1).
// =============================================================
static void ISR_encA() {
  const unsigned long now = micros();
  if ((now - lastA_us) < DEBOUNCE_US) return;
  lastA_us = now;
  const uint8_t a = digitalRead(PIN_ENC_A);
  const uint8_t b = digitalRead(PIN_ENC_B);
  if (a == b) encoderCount++;
  else        encoderCount--;
  digitalWrite(PIN_ENC_OA, a);
}

static void ISR_encB() {
  const unsigned long now = micros();
  if ((now - lastB_us) < DEBOUNCE_US) return;
  lastB_us = now;
  const uint8_t a = digitalRead(PIN_ENC_A);
  const uint8_t b = digitalRead(PIN_ENC_B);
  if (a == b) encoderCount--;
  else        encoderCount++;
  digitalWrite(PIN_ENC_OB, b);
}

// =============================================================
// encoderRead — lectura atómica de encoderCount
// En AVR un int32_t no se lee en un solo ciclo; se deshabilitan
// interrupciones momentáneamente para evitar valores parciales.
// =============================================================
int32_t encoderRead() {
  noInterrupts();
  int32_t val = encoderCount;
  interrupts();
  return val;
}

// =============================================================
// encoderReset — pone el conteo y el buffer de velocidad a cero
// =============================================================
void encoderReset() {
  noInterrupts();
  encoderCount = 0;
  interrupts();
  for (uint8_t i = 0; i < VEL_BUF_N; i++) velBuf[i] = 0;
  velHead     = 0;
  lastEncCtrl = 0;
  measuredRPM = 0.0f;
}

// =============================================================
// flushVelBuffer — vacía el buffer de velocidad y re-ancla el
// punto de referencia al conteo actual (usar tras cambio de dir.)
// =============================================================
void flushVelBuffer() {
  for (uint8_t i = 0; i < VEL_BUF_N; i++) velBuf[i] = 0;
  velHead     = 0;
  lastEncCtrl = encoderRead();
  measuredRPM = 0.0f;
}

// =============================================================
// halfPeriodUs — semiperíodo del pulso STEP en microsegundos
//   f_STEP = RPM × STEPS_PER_REV / 60
//   T_half = 30 000 000 / (RPM × SPR)
// =============================================================
unsigned long halfPeriodUs(float rpm) {
  return (unsigned long)(30000000.0f / (rpm * (float)STEPS_PER_REV));
}

// =============================================================
// setDirection — aplica dirección con el setup-time mínimo del
// TMC2208 (≥ 20 ns); se usa un margen conservador de 2 µs.
// =============================================================
void setDirection(bool forward) {
  digitalWrite(PIN_DIR, forward ? HIGH : LOW);
  delayMicroseconds(2);
}

// =============================================================
// updateVelocity — medición de velocidad por media móvil adaptativa
//
// Se llama cada CONTROL_INTERVAL_US (10 ms) SIEMPRE, con el motor
// en marcha o parado: así measuredRPM sigue siendo válida durante
// una pausa (decae a 0 o refleja giro manual del eje).
//
// Ventana adaptativa: se acumulan deltas desde la muestra más
// reciente hacia atrás hasta cumplir n ≥ VEL_WIN_MIN y además
// |sum| ≥ VEL_MIN_COUNTS, o agotar el buffer (VEL_BUF_N).
// =============================================================
void updateVelocity() {
  const int32_t cnt   = encoderRead();
  const int32_t delta = cnt - lastEncCtrl;
  lastEncCtrl = cnt;

  velBuf[velHead] = (int16_t)delta;
  velHead = (uint8_t)((velHead + 1 == VEL_BUF_N) ? 0 : velHead + 1);

  int32_t sum = 0;
  uint8_t n   = 0;
  uint8_t idx = velHead;   // tras el ++, velHead apunta a la muestra más antigua
  while (n < VEL_BUF_N) {
    idx = (idx == 0) ? (uint8_t)(VEL_BUF_N - 1) : (uint8_t)(idx - 1);
    sum += velBuf[idx];
    n++;
    if (n >= VEL_WIN_MIN && (sum >= VEL_MIN_COUNTS || sum <= -VEL_MIN_COUNTS)) break;
  }

  // RPM cruda = cuentas_acum / cuentas_por_rev / ventana_s × 60 s/min
  // fabsf: la magnitud de velocidad es siempre positiva; el signo
  // se gestiona por separado con dirForward.
  const float windowS = (float)n * PI_TS;
  const float rawRPM  = fabsf((float)sum) / (float)COUNTS_PER_REV / windowS * 60.0f;
  // Filtro IIR: suaviza el ruido de cuadratura antes de alimentar el PI.
  // measuredRPM se resetea a 0 en flushVelBuffer/encoderReset → el filtro
  // arranca desde cero tras cambio de dirección o reinicio.
  measuredRPM = VEL_ALPHA * rawRPM + (1.0f - VEL_ALPHA) * measuredRPM;
}

// =============================================================
// updateControl — un paso del lazo de control (solo con motor en marcha)
//
// Modo PI (usePID=true):
//   e[k]    = targetRPM − measuredRPM
//   u_raw   = Kp·e[k] + piIntegral
//   u_sat   = saturar(u_raw, RPM_MIN, RPM_MAX)
//   Anti-windup (clamping): integrar solo si u_raw no está saturado
//   I[k]    = I[k-1] + Ki·Ts·e[k]  (con clamping)
//   controlRPM = u_sat
//
// Modo libre (usePID=false):
//   controlRPM = targetRPM
//   piIntegral = targetRPM  ← precondiciona para transferencia sin choque
// =============================================================
void updateControl() {
  if (!usePID) {
    controlRPM = targetRPM;
    piIntegral = targetRPM;   // precondicionar para transferencia sin choque
    return;
  }

  const float e = targetRPM - measuredRPM;

  // Salida proporcional + integral acumulado
  const float uRaw = PI_KP * e + piIntegral;

  // Saturar
  const float uSat = (uRaw < RPM_MIN) ? RPM_MIN
                   : (uRaw > RPM_MAX) ? RPM_MAX
                   : uRaw;

  // Anti-windup condicional mejorado:
  // No integrar solo si la salida está saturada Y el error agrava esa saturación.
  // Así se permite integrar incluso en saturación cuando e ayuda a salir de ella.
  const bool windingHigh = (uRaw > RPM_MAX) && (e > 0.0f);
  const bool windingLow  = (uRaw < RPM_MIN) && (e < 0.0f);
  if (!windingHigh && !windingLow) {
    piIntegral += PI_KI * PI_TS * e;
  }

  controlRPM = uSat;
}

// =============================================================
// buildStatus + drip-pump — reporte de estado NO bloqueante
//
// La línea completa se formatea en statusBuf y se envía por trozos
// desde loop() según haya sitio en el buffer TX del UART. Así el
// reporte de ~85 caracteres no bloquea la generación de pasos
// (con Serial.print directo bloqueaba ~3 ms cada segundo).
//
// El signo de los RPM medidos codifica la dirección: >0 FWD, <0 REV.
// targetRPM es siempre la MAGNITUD porque la dirección se fija aparte.
//
// [LIBRE] : "[LIBRE]  Tgt:30.0RPM  Real:-28.5RPM  Ang:185.4deg  Dir:REV  CORRIENDO"
// [PI]    : "[PI]  Tgt:30.0RPM  Meas:-28.5RPM  Err:1.5  Ctrl:-30.2RPM  Ang:185.4deg  Dir:REV  CORRIENDO"
// =============================================================
static char    statusBuf[112];   // línea PI ≈ 90 chars + margen
static uint8_t statusLen      = 0;
static uint8_t statusPos      = 0;
static bool    statusPending  = false;

// Formatea la línea con el estado ACTUAL. Solo debe llamarse con el
// buffer ya drenado (statusPos >= statusLen); si no, se rompería una
// línea a medio enviar y el parser del backend leería basura.
static void formatStatusLine() {
  const int32_t cnt = encoderRead();
  int32_t mod = cnt % COUNTS_PER_REV;
  if (mod < 0) mod += COUNTS_PER_REV;
  const float angleDeg = mod * (360.0f / (float)COUNTS_PER_REV);

  const float sign = dirForward ? 1.0f : -1.0f;
  // measuredRPM no está acotada por RPM_MAX (deriva del encoder); se
  // recorta a ±999.9 para garantizar que dtostrf quepa en el buffer.
  const float measSafe = (measuredRPM > 999.9f) ? 999.9f : measuredRPM;

  // dtostrf: snprintf de megaavr no soporta %f. Peor caso "-999.9" = 6+1 chars.
  char sTgt[10], sMeas[10], sErr[10], sCtrl[10], sAng[10];
  dtostrf(targetRPM,       1, 1, sTgt);
  dtostrf(sign * measSafe, 1, 1, sMeas);
  dtostrf(angleDeg,        1, 1, sAng);

  int len;
  if (usePID) {
    dtostrf(targetRPM - measSafe, 1, 1, sErr);
    dtostrf(sign * controlRPM,    1, 1, sCtrl);
    len = snprintf(statusBuf, sizeof(statusBuf),
                   "[PI]  Tgt:%sRPM  Meas:%sRPM  Err:%s  Ctrl:%sRPM  Ang:%sdeg  Dir:%s  %s\r\n",
                   sTgt, sMeas, sErr, sCtrl, sAng,
                   dirForward ? "FWD" : "REV",
                   motorEnabled ? "CORRIENDO" : "PARADO");
  } else {
    len = snprintf(statusBuf, sizeof(statusBuf),
                   "[LIBRE]  Tgt:%sRPM  Real:%sRPM  Ang:%sdeg  Dir:%s  %s\r\n",
                   sTgt, sMeas, sAng,
                   dirForward ? "FWD" : "REV",
                   motorEnabled ? "CORRIENDO" : "PARADO");
  }
  if (len < 0) { statusLen = 0; statusPos = 0; return; }
  if (len > (int)(sizeof(statusBuf) - 1)) len = (int)(sizeof(statusBuf) - 1);
  statusLen = (uint8_t)len;
  statusPos = 0;
}

// Solicita un reporte de estado. Si hay una línea a medio enviar,
// se marca como pendiente y se formatea al terminar de drenarla
// (con el estado vigente en ese momento — siempre el más fresco).
void buildStatus() {
  if (statusPos >= statusLen) formatStatusLine();
  else                        statusPending = true;
}

void pumpStatus() {
  if (statusPos >= statusLen) {
    if (!statusPending) return;
    statusPending = false;
    formatStatusLine();
  }
  const int room = Serial.availableForWrite();
  if (room <= 0) return;
  uint8_t n = (uint8_t)(statusLen - statusPos);
  if ((int)n > room) n = (uint8_t)room;
  Serial.write((const uint8_t*)&statusBuf[statusPos], n);
  statusPos += n;
}

// =============================================================
// Acciones de comando — funciones pequeñas e idempotentes muajaja
// =============================================================

// Fija el RPM objetivo con recorte a [RPM_MIN, RPM_MAX].
// Entrada no numérica en 'v' → atof devuelve 0.0 → se recorta a RPM_MIN.
void applyTargetRPM(float rpm) {
  targetRPM = (rpm < RPM_MIN) ? RPM_MIN
            : (rpm > RPM_MAX) ? RPM_MAX
            : rpm;
  buildStatus();
}

void startMotor() {
  if (motorEnabled) return;
  motorEnabled = true;
  digitalWrite(PIN_EN, LOW);
  // Arranque suave: resetear medición e integrador
  flushVelBuffer();
  piIntegral = targetRPM;
  controlRPM = targetRPM;
  const unsigned long now = micros();
  lastControlTime = now;
  lastStepTime    = now;   // evita ráfaga de pasos por deuda acumulada
}

void stopMotor() {
  if (!motorEnabled) return;
  motorEnabled = false;
  // EN=HIGH libera la corriente de holding y reduce calor
  digitalWrite(PIN_EN,       HIGH);
  digitalWrite(PIN_STEP,     LOW);
  digitalWrite(PIN_STEP_OUT, LOW);
  stepPinHigh = false;
}

void setMode(bool pid) {
  if (pid == usePID) return;
  usePID = pid;
  if (usePID) {
    // Transferencia sin choque: el integrador arranca donde está
    // la salida del lazo abierto → el motor no da salto al activar el PI.
    piIntegral = controlRPM;
    Serial.println(F("Modo PI ON  — lazo cerrado velocidad"));
  } else {
    // Al desactivar, dejar el integrador en targetRPM para la próxima activación.
    piIntegral = targetRPM;
    Serial.println(F("Modo PI OFF — lazo abierto"));
  }
  buildStatus();
}

void setDir(bool forward) {
  if (forward == dirForward) return;
  dirForward = forward;
  setDirection(dirForward);
  // Vaciar el buffer: evita mezclar cuentas de sentidos opuestos.
  flushVelBuffer();
  if (usePID) piIntegral = targetRPM;   // re-iniciar integrador limpio
  buildStatus();
}

// =============================================================
// handleCommand — despacho de comandos de un carácter
// ('v' se gestiona aparte en loop() porque lleva argumento)
// =============================================================
void handleCommand(char cmd) {
  switch (cmd) {
    // Relativos (uso manual)
    case '+': applyTargetRPM(targetRPM + RPM_STEP); break;
    case '-': applyTargetRPM(targetRPM - RPM_STEP); break;

    // Absolutos e idempotentes (backend)
    case '1': startMotor(); buildStatus(); break;
    case '0': stopMotor();  buildStatus(); break;
    case 'e':
      // PARO DE EMERGENCIA: incondicional, desenergiza el driver.
      stopMotor();
      Serial.println(F("E-STOP"));
      buildStatus();
      break;
    case 'f': setDir(true);   break;
    case 'b': setDir(false);  break;
    case 'p': setMode(true);  break;
    case 'l': setMode(false); break;

    // Legado (toggles, solo terminal manual)
    case 's':
      if (motorEnabled) stopMotor(); else startMotor();
      buildStatus();
      break;
    case 'r': setDir(!dirForward); break;
    case 'c': setMode(!usePID);    break;

    case 'z':
      encoderReset();
      Serial.println(F("Encoder -> 0"));
      buildStatus();
      break;
  }
}

// =============================================================
void setup() {
  Serial.begin(115200);

  // Driver — EN=HIGH durante la estabilización interna del TMC2208
  // (datasheet recomienda ≥ 130 µs; se usa 200 ms para mayor margen)
  pinMode(PIN_STEP, OUTPUT);
  pinMode(PIN_DIR,  OUTPUT);
  pinMode(PIN_EN,   OUTPUT);
  digitalWrite(PIN_EN,   HIGH);
  digitalWrite(PIN_STEP, LOW);
  setDirection(dirForward);
  delay(200);
  digitalWrite(PIN_EN, LOW);

  // Salidas espejo para osciloscopio / analizador lógico
  pinMode(PIN_ENC_OA,   OUTPUT); digitalWrite(PIN_ENC_OA,   LOW);
  pinMode(PIN_ENC_OB,   OUTPUT); digitalWrite(PIN_ENC_OB,   LOW);
  pinMode(PIN_STEP_OUT, OUTPUT); digitalWrite(PIN_STEP_OUT, LOW);

  // Encoder — pull-up interno activa el canal idle en HIGH
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), ISR_encA, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), ISR_encB, CHANGE);

  const unsigned long now = micros();
  lastStepTime    = now;
  lastControlTime = now;
  lastStatusTime  = millis();
  lastEncCtrl     = 0;

  Serial.println(F("===  NEMA17 + TMC2208 + ENCODER + PI  ==="));
  Serial.println(F("'v<rpm>\\n':RPM abs  '+'/'-':±1RPM  '1'/'0':marcha/paro  'e':E-STOP"));
  Serial.println(F("'f'/'b':direccion  'p'/'l':modo  'z':zero  (legado: s r c)"));
  buildStatus();
}

// =============================================================
void loop() {
  const unsigned long now_us = micros();
  const unsigned long now_ms = millis();

  // ── Comandos por Serial ──────────────────────────────────
  // 'v' abre un mini-parser de línea ("v<float>\n"); el resto son
  // comandos de un carácter despachados de inmediato.
  // Presupuesto por pasada: procesar como máximo unos pocos bytes para
  // no retrasar la generación de pasos si el buffer RX llega lleno.
  static char    vBuf[12];
  static uint8_t vLen  = 0;
  static bool    vMode = false;

  uint8_t rxBudget = 8;
  while (rxBudget-- > 0 && Serial.available() > 0) {
    const char ch = (char)Serial.read();
    if (vMode) {
      if (ch == '\n' || ch == '\r') {
        vBuf[vLen] = '\0';
        applyTargetRPM((float)atof(vBuf));
        vLen = 0; vMode = false;
      } else if (vLen < sizeof(vBuf) - 1) {
        vBuf[vLen++] = ch;
      } else {
        // Desbordamiento: descartar el comando y avisar
        vLen = 0; vMode = false;
        Serial.println(F("ERR v: argumento demasiado largo"));
      }
      continue;
    }
    if (ch == 'v') { vMode = true; vLen = 0; continue; }
    handleCommand(ch);
  }

  // ── Medición de velocidad + lazo de control (cada 10 ms) ─
  // updateVelocity() corre SIEMPRE: la telemetría de velocidad sigue
  // viva con el motor parado (decae a 0, refleja giro manual del eje).
  // Solo la corrección de control se condiciona a motorEnabled.
  if ((now_us - lastControlTime) >= CONTROL_INTERVAL_US) {
    // Re-anclar si la deuda supera 2 intervalos (p.ej. tras un bloqueo):
    // evita ejecutar ráfagas de ticks con deltas que no son de 10 ms.
    if ((now_us - lastControlTime) >= 2UL * CONTROL_INTERVAL_US) {
      lastControlTime = now_us - CONTROL_INTERVAL_US;
    }
    lastControlTime += CONTROL_INTERVAL_US;   // += evita deriva acumulada
    updateVelocity();
    if (motorEnabled) updateControl();
  }

  // ── Generación de pasos no bloqueante ───────────────────
  // El pin STEP alterna cada halfPeriod µs sin bloquear el loop.
  // controlRPM ≥ RPM_MIN > 0, por lo que halfPeriodUs nunca falla.
  if (motorEnabled) {
    const unsigned long half = halfPeriodUs(controlRPM);
    // Anti-ráfaga: si la deuda acumulada supera 2 semiperíodos (puede ocurrir
    // cuando controlRPM sube repentinamente y half encoge), re-anclar para
    // evitar disparar múltiples pasos en la misma iteración del loop.
    if ((now_us - lastStepTime) > 2UL * half) {
      lastStepTime = now_us - half;
    }
    if ((now_us - lastStepTime) >= half) {
      stepPinHigh = !stepPinHigh;
      digitalWrite(PIN_STEP,     stepPinHigh ? HIGH : LOW);
      digitalWrite(PIN_STEP_OUT, stepPinHigh ? HIGH : LOW);
      lastStepTime += half;
    }
  }

  // ── Reporte automático cada segundo ─────────────────────
  if ((now_ms - lastStatusTime) >= STATUS_INTERVAL_MS) {
    lastStatusTime = now_ms;
    buildStatus();
  }

  // ── Envío no bloqueante del reporte pendiente ───────────
  pumpStatus();
}
