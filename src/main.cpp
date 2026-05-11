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
//   Blanco → D7 (A)    Verde      → D8 (B)
//   Pull-up interno activado por software (~40 kΩ)
//
// ── Control por Monitor Serial  115200 baud ────────────────
//   '+'  → +5 RPM          '-'  → -5 RPM
//   'r'  → invertir dir    's'  → parar / reanudar
//   'z'  → poner encoder a cero
// =============================================================

// ── Pines driver ─────────────────────────────────────────────
const uint8_t PIN_STEP  = 4;
const uint8_t PIN_DIR   = 5;
const uint8_t PIN_EN    = 6;

// ── Pines encoder ────────────────────────────────────────────
const uint8_t PIN_ENC_A = 7;   // Canal A — interrupción CHANGE
const uint8_t PIN_ENC_B = 8;   // Canal B — interrupción CHANGE

// ── Parámetros mecánicos ─────────────────────────────────────
// 200 pasos/rev × 8 micropasos = 1600 pulsos/vuelta
const uint16_t STEPS_PER_REV = 1600;

// ── Parámetros encoder ───────────────────────────────────────
// ENC_PPR: líneas por vuelta impresas en el encoder.
// Con decodificación X4 (flancos en A y B): COUNTS_PER_REV = PPR × 4.
const int32_t ENC_PPR        = 600;
const int32_t COUNTS_PER_REV = ENC_PPR * 4;   // 2400 conteos/vuelta

// ── Límites y paso de velocidad ──────────────────────────────
const float RPM_MIN  =   5.0f;
const float RPM_MAX  = 120.0f;
const float RPM_STEP =   5.0f;

// ── Período de reporte automático ────────────────────────────
const unsigned long STATUS_INTERVAL_MS = 1000UL;   // cada 1 segundo

// ── Debounce de señal encoder ────────────────────────────────
// Filtra rebotes eléctricos ignorando flancos más rápidos que
// DEBOUNCE_US µs.  A 120 RPM el intervalo mínimo entre flancos
// es ≈ 208 µs, por lo que 50 µs no descarta pulsos reales.
static const uint16_t DEBOUNCE_US = 50;

// ─────────────────────────────────────────────────────────────
// Variables de estado del sistema
// ─────────────────────────────────────────────────────────────
float   targetRPM    = 30.0f;
bool    motorEnabled = true;
bool    dirForward   = true;

// Temporización no bloqueante del generador de pasos
unsigned long lastStepTime   = 0;
bool          stepPinHigh    = false;
unsigned long lastStatusTime = 0;

// Encoder — volatile porque se modifican dentro de las ISRs
volatile int32_t encoderCount = 0;

// Variables auxiliares del encoder (acceso solo en contexto normal)
static volatile unsigned long lastA_us = 0;
static volatile unsigned long lastB_us = 0;
int32_t lastEncCount = 0;
float   measuredRPM  = 0.0f;

// =============================================================
// ISRs de cuadratura X4
// Se disparan en cada flanco (CHANGE) de los canales A y B.
// Decodificación: si el pin que cambió tiene el mismo nivel que
// el otro canal → sentido horario (+1); distinto → antihorario (−1).
// =============================================================
static void ISR_encA() {
  const unsigned long now = micros();
  if ((now - lastA_us) < DEBOUNCE_US) return;
  lastA_us = now;
  if (digitalRead(PIN_ENC_A) == digitalRead(PIN_ENC_B)) encoderCount++;
  else                                                   encoderCount--;
}

static void ISR_encB() {
  const unsigned long now = micros();
  if ((now - lastB_us) < DEBOUNCE_US) return;
  lastB_us = now;
  if (digitalRead(PIN_ENC_A) == digitalRead(PIN_ENC_B)) encoderCount--;
  else                                                   encoderCount++;
}

// =============================================================
// encoderRead — lectura atómica de encoderCount
// En AVR (8-bit) un int32_t no se lee en un solo ciclo, así que
// se deshabilitan interrupciones momentáneamente para evitar
// leer un valor parcialmente actualizado por una ISR.
// =============================================================
int32_t encoderRead() {
  noInterrupts();
  int32_t val = encoderCount;
  interrupts();
  return val;
}

// =============================================================
// encoderReset — pone el conteo y los acumuladores a cero
// =============================================================
void encoderReset() {
  noInterrupts();
  encoderCount = 0;
  interrupts();
  lastEncCount = 0;
  measuredRPM  = 0.0f;
}

// =============================================================
// halfPeriodUs — semiperíodo del pulso STEP en microsegundos
//   f_STEP  = RPM × STEPS_PER_REV / 60
//   T_half  = 500 000 / f_STEP  =  30 000 000 / (RPM × SPR)
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
// updateMeasuredRPM — calcula la velocidad real a partir del
// delta de conteos del encoder en el último intervalo de 1 s.
// Solo debe llamarse desde el temporizador periódico para que
// la ventana de integración sea siempre STATUS_INTERVAL_MS.
// =============================================================
void updateMeasuredRPM() {
  const int32_t cnt   = encoderRead();
  const int32_t delta = cnt - lastEncCount;
  lastEncCount = cnt;
  measuredRPM  = (float)delta / (float)COUNTS_PER_REV
                 * (60000.0f / (float)STATUS_INTERVAL_MS);
}

// =============================================================
// printStatus — imprime en una sola línea:
//   velocidad objetivo | velocidad real medida | ángulo | estado
// No modifica lastEncCount, puede llamarse en cualquier momento.
// =============================================================
void printStatus() {
  const int32_t cnt = encoderRead();
  int32_t mod = cnt % COUNTS_PER_REV;
  if (mod < 0) mod += COUNTS_PER_REV;
  const float angleDeg = mod * (360.0f / (float)COUNTS_PER_REV);

  Serial.print(F("Target: "));    Serial.print(targetRPM, 1);   Serial.print(F(" RPM"));
  Serial.print(F("  |  Real: ")); Serial.print(measuredRPM, 1); Serial.print(F(" RPM"));
  Serial.print(F("  |  Ang: "));  Serial.print(angleDeg, 1);    Serial.print(F(" deg"));
  Serial.print(F("  |  Dir: "));  Serial.print(dirForward ? F("FWD") : F("REV"));
  Serial.print(F("  |  "));
  Serial.println(motorEnabled ? F("CORRIENDO") : F("PARADO"));
}

// =============================================================
void setup() {
  Serial.begin(115200);

  // Driver
  pinMode(PIN_STEP, OUTPUT);
  pinMode(PIN_DIR,  OUTPUT);
  pinMode(PIN_EN,   OUTPUT);

  // Mantener EN=HIGH durante la estabilización interna del TMC2208
  // (datasheet recomienda ≥ 130 µs; se usa 200 ms para mayor margen)
  digitalWrite(PIN_EN,   HIGH);
  digitalWrite(PIN_STEP, LOW);
  setDirection(dirForward);
  delay(200);
  digitalWrite(PIN_EN, LOW);

  // Encoder — pull-up interno activa el canal idle en HIGH
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), ISR_encA, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), ISR_encB, CHANGE);

  lastStepTime   = micros();
  lastStatusTime = millis();

  Serial.println(F("===  NEMA17 + TMC2208 + ENCODER  ==="));
  Serial.println(F("Comandos: '+' subir  '-' bajar  'r' girar  's' parar  'z' zero"));
  printStatus();
}

// =============================================================
void loop() {
  const unsigned long now_us = micros();
  const unsigned long now_ms = millis();

  // ── Comandos por Serial ──────────────────────────────────
  if (Serial.available()) {
    char cmd = (char)Serial.read();
    switch (cmd) {
      case '+':
        targetRPM = min(targetRPM + RPM_STEP, RPM_MAX);
        printStatus();
        break;

      case '-':
        targetRPM = max(targetRPM - RPM_STEP, RPM_MIN);
        printStatus();
        break;

      case 'r':
        dirForward = !dirForward;
        setDirection(dirForward);
        printStatus();
        break;

      case 's':
        motorEnabled = !motorEnabled;
        // EN=HIGH libera la corriente de holding y reduce calor
        digitalWrite(PIN_EN, motorEnabled ? LOW : HIGH);
        if (!motorEnabled) {
          digitalWrite(PIN_STEP, LOW);
          stepPinHigh = false;
        }
        printStatus();
        break;

      case 'z':
        encoderReset();
        Serial.println(F("Encoder -> 0"));
        break;
    }
  }

  // ── Generación de pasos no bloqueante ───────────────────
  // El pin STEP alterna cada halfPeriod µs usando micros() en
  // lugar de delayMicroseconds, dejando libre el loop para
  // atender Serial y el reporte periódico.
  if (motorEnabled) {
    const unsigned long half = halfPeriodUs(targetRPM);
    if ((now_us - lastStepTime) >= half) {
      stepPinHigh  = !stepPinHigh;
      digitalWrite(PIN_STEP, stepPinHigh ? HIGH : LOW);
      lastStepTime += half;   // += en lugar de = para absorber la latencia del loop
    }
  }

  // ── Reporte automático cada segundo ─────────────────────
  // updateMeasuredRPM se llama aquí (y solo aquí) para que la
  // ventana de integración sea siempre exactamente 1 segundo.
  if ((now_ms - lastStatusTime) >= STATUS_INTERVAL_MS) {
    lastStatusTime = now_ms;
    updateMeasuredRPM();
    printStatus();
  }
}
