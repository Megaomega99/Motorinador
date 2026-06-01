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
//   MODO LIBRE (usePID=false) y MODO PI (usePID=true):
//     '+'  → +5 RPM objetivo     '-'  → -5 RPM objetivo
//   COMUNES:
//     'c'  → alternar PI ↔ LIBRE
//     'r'  → invertir dirección
//     's'  → parar / reanudar
//     'z'  → poner encoder a cero
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
const float RPM_MIN  =   5.0f;
const float RPM_MAX  = 120.0f;
const float RPM_STEP =   5.0f;

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

// ── Medición de velocidad por media móvil + filtro IIR ───────
// VEL_N muestras de 10 ms cada una = ventana de 80 ms.
// Resolución teórica: 1 cnt / 2400 cnt/rev / 0.08 s · 60 = 0.3125 RPM/cnt
const uint8_t VEL_N    = 8;
// Filtro IIR de primer orden sobre la velocidad cruda antes del PI.
// α=0.3 → f_c ≈ 5.7 Hz, retardo ≈ 23 ms — amortigua ruido de cuadratura
// sin afectar la respuesta en el ancho de banda del lazo (λ=0.125 s → ~1.3 Hz).
const float VEL_ALPHA = 0.3f;

// ─────────────────────────────────────────────────────────────
// Variables de estado del sistema
// ─────────────────────────────────────────────────────────────
float   targetRPM    = 30.0f;   // RPM objetivo (ambos modos)
float   controlRPM   = 30.0f;   // RPM enviadas al driver (salida del PI o targetRPM)
float   piIntegral   = 30.0f;   // acumulador integral
float   measuredRPM  = 0.0f;    // velocidad medida (media móvil, actualizada cada 10 ms)
bool    usePID       = false;   // false = lazo abierto, true = lazo cerrado
bool    motorEnabled = true;
bool    dirForward   = true;

// Buffer circular para la media móvil de velocidad
static int32_t velBuf[VEL_N] = {0};
static uint8_t velHead        = 0;
static int32_t velSum         = 0;
static int32_t lastEncCtrl    = 0;   // conteo al final del ciclo anterior

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
  for (uint8_t i = 0; i < VEL_N; i++) velBuf[i] = 0;
  velHead     = 0;
  velSum      = 0;
  lastEncCtrl = 0;
  measuredRPM = 0.0f;
}

// =============================================================
// flushVelBuffer — vacía el buffer de velocidad y re-ancla el
// punto de referencia al conteo actual (usar tras cambio de dir.)
// =============================================================
void flushVelBuffer() {
  for (uint8_t i = 0; i < VEL_N; i++) velBuf[i] = 0;
  velHead     = 0;
  velSum      = 0;
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
// runPIControl — un paso del controlador PI discretizado
//
// Se llama cada CONTROL_INTERVAL_US (10 ms) con motorEnabled=true.
//
// Paso 1 — Medición de velocidad (siempre, independiente del modo):
//   Actualiza el buffer circular de VEL_N = 8 deltas de encoder.
//   measuredRPM = |velSum| / COUNTS_PER_REV / (VEL_N·Ts) × 60
//
// Paso 2 — Lazo PI (solo si usePID=true):
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
void runPIControl() {
  // ── 1. Medición de velocidad ─────────────────────────────
  const int32_t cnt   = encoderRead();
  const int32_t delta = cnt - lastEncCtrl;
  lastEncCtrl = cnt;

  velSum -= velBuf[velHead];
  velBuf[velHead] = delta;
  velSum += delta;
  velHead = (velHead + 1 == VEL_N) ? 0 : velHead + 1;

  // RPM cruda = cuentas_acum / cuentas_por_rev / ventana_s × 60 s/min
  // fabsf: la magnitud de velocidad es siempre positiva; el signo
  // se gestiona por separado con dirForward.
  const float windowS = (float)VEL_N * PI_TS;   // 0.08 s
  const float rawRPM  = fabsf((float)velSum) / (float)COUNTS_PER_REV / windowS * 60.0f;
  // Filtro IIR: suaviza el ruido de cuadratura antes de alimentar el PI.
  // measuredRPM se resetea a 0 en flushVelBuffer/encoderReset → el filtro
  // arranca desde cero tras cambio de dirección o reinicio.
  measuredRPM = VEL_ALPHA * rawRPM + (1.0f - VEL_ALPHA) * measuredRPM;

  // ── 2. Lazo de control ───────────────────────────────────
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
// printStatus — imprime una línea de estado por segundo
//
// El signo de los RPM medidos codifica la dirección:  > 0 → FWD, < 0 → REV.
// targetRPM es siempre la MAGNITUD (5–120) porque la dirección se fija con 'r'.
//
// [LIBRE] : "[LIBRE]  Tgt:30.0RPM  Real:-28.5RPM  Ang:185.4deg  Dir:REV  CORRIENDO"
// [PI]    : "[PI]  Tgt:30.0RPM  Meas:-28.5RPM  Err:1.5  Ctrl:-30.2RPM  Ang:185.4deg  Dir:REV  CORRIENDO"
// =============================================================
void printStatus() {
  const int32_t cnt = encoderRead();
  int32_t mod = cnt % COUNTS_PER_REV;
  if (mod < 0) mod += COUNTS_PER_REV;
  const float angleDeg = mod * (360.0f / (float)COUNTS_PER_REV);

  // El signo distingue FWD (+) de REV (−) sin necesitar un campo separado.
  const float sign      = dirForward ? 1.0f : -1.0f;
  const float signedMeas = sign * measuredRPM;
  const float signedCtrl = sign * controlRPM;

  if (usePID) {
    Serial.print(F("[PI]  Tgt:"));   Serial.print(targetRPM, 1);
    Serial.print(F("RPM  Meas:"));   Serial.print(signedMeas, 1);
    Serial.print(F("RPM  Err:"));    Serial.print(targetRPM - measuredRPM, 1);
    Serial.print(F("  Ctrl:"));      Serial.print(signedCtrl, 1);
    Serial.print(F("RPM"));
  } else {
    Serial.print(F("[LIBRE]  Tgt:"));  Serial.print(targetRPM, 1);
    Serial.print(F("RPM  Real:"));     Serial.print(signedMeas, 1);
    Serial.print(F("RPM"));
  }
  Serial.print(F("  Ang:"));  Serial.print(angleDeg, 1);  Serial.print(F("deg"));
  Serial.print(F("  Dir:"));  Serial.print(dirForward ? F("FWD") : F("REV"));
  Serial.print(F("  "));
  Serial.println(motorEnabled ? F("CORRIENDO") : F("PARADO"));
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
  Serial.println(F("'+'/'-':RPM  'c':toggle PI  'r':dir  's':parar  'z':zero"));
  printStatus();
}

// =============================================================
void loop() {
  const unsigned long now_us = micros();
  const unsigned long now_ms = millis();

  // ── Comandos por Serial ──────────────────────────────────
  if (Serial.available()) {
    const char cmd = (char)Serial.read();
    switch (cmd) {
      case '+':
        targetRPM = min(targetRPM + RPM_STEP, RPM_MAX);
        printStatus();
        break;

      case '-':
        targetRPM = max(targetRPM - RPM_STEP, RPM_MIN);
        printStatus();
        break;

      case 'c':
        usePID = !usePID;
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
        printStatus();
        break;

      case 'r':
        dirForward = !dirForward;
        setDirection(dirForward);
        // Vaciar el buffer: evita mezclar cuentas de sentidos opuestos.
        flushVelBuffer();
        if (usePID) piIntegral = targetRPM;   // re-iniciar integrador limpio
        printStatus();
        break;

      case 's':
        motorEnabled = !motorEnabled;
        // EN=HIGH libera la corriente de holding y reduce calor
        digitalWrite(PIN_EN, motorEnabled ? LOW : HIGH);
        if (!motorEnabled) {
          digitalWrite(PIN_STEP,     LOW);
          digitalWrite(PIN_STEP_OUT, LOW);
          stepPinHigh = false;
        } else {
          // Al reanudar, resetear la medición y el integrador para arranque suave
          flushVelBuffer();
          piIntegral  = targetRPM;
          controlRPM  = targetRPM;
          lastControlTime = micros();
        }
        printStatus();
        break;

      case 'z':
        encoderReset();
        Serial.println(F("Encoder -> 0"));
        break;
    }
  }

  // ── Lazo de control PI (alta prioridad, cada 10 ms) ─────
  // Se ejecuta con micros() para mayor precisión temporal.
  // runPIControl actualiza measuredRPM y controlRPM en ambos modos.
  if (motorEnabled && (now_us - lastControlTime) >= CONTROL_INTERVAL_US) {
    lastControlTime += CONTROL_INTERVAL_US;   // += evita deriva acumulada
    runPIControl();
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
  // measuredRPM ya se actualiza en runPIControl (cada 10 ms);
  // aquí solo se imprime el estado.
  if ((now_ms - lastStatusTime) >= STATUS_INTERVAL_MS) {
    lastStatusTime = now_ms;
    printStatus();
  }
}
