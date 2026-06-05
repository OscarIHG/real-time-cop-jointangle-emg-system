// ==============================================================================
// ESP32 EMG Bluetooth Serial Firmware - SIMULATOR MODE
// ==============================================================================
// Misma lógica que el firmware real (esp32_firmware.ino) pero en lugar de leer
// del pin analógico A0, genera una señal EMG sintética con:
//   - Línea base de 1.5V (reposo)
//   - Ruido de 60 Hz (red eléctrica) → para probar el filtro Notch
//   - Ruido blanco de fondo
//   - Bursts de contracción muscular cada 4 segundos
// ==============================================================================

#include "BluetoothSerial.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled! Please run `make menuconfig` to and enable it
#endif

// --- Pin ---
#define LED_PIN 2   // LED incorporado del ESP32

// --- Bluetooth ---
BluetoothSerial SerialBT;

// --- Estado (igual que el firmware real, pero como variables GLOBALES
//     para que sobrevivan entre iteraciones del loop) ---
bool          connected      = false;
unsigned long previousMillis = 0;
const long    interval       = 500; // ms de parpadeo esperando conexión

// --- Temporización de muestreo a 1000 Hz ---
unsigned long previousMicros      = 0;
const unsigned long sampleInterval = 1000; // 1000 µs = 1 ms = 1000 Hz

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  SerialBT.begin("ESP32Roquiva");
  Serial.println("SIMULATOR: BLUETOOTH DEVICE STARTED PAIRING MODE");
}

void loop() {
  unsigned long currentMillis = millis();
  char          receivedChar  = 0;
  int           intValue      = 0;

  // ── Leer comando de Python (si hay algo disponible) ──────────────────────
  if (SerialBT.available()) {
    receivedChar = SerialBT.read();
    intValue     = atoi(&receivedChar);
    Serial.print("CMD recibido: ");
    Serial.println(intValue);
  }

  // ── Máquina de estados (lógica idéntica al firmware real) ─────────────────
  if (!connected) {

    if (intValue == 1) {
      connected = true;
      digitalWrite(LED_PIN, HIGH);  // LED fijo = adquiriendo
      Serial.println("Python -> START (1). Iniciando adquisición...");
    } else {
      // Parpadear mientras espera conexión
      if (currentMillis - previousMillis >= interval) {
        previousMillis = currentMillis;
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
      }
    }

  } else {
    // ── Modo adquisición: generar y enviar muestra cada 1 ms ───────────────
    unsigned long currentMicros = micros();

    if (currentMicros - previousMicros >= sampleInterval) {
      previousMicros = currentMicros;

      float t = currentMicros / 1000000.0; // segundos

      // 1. Línea base (reposo muscular) ≈ 1.5 V
      float baseline = 1.5;

      // 2. Ruido de la red eléctrica a 60 Hz (para probar el filtro Notch)
      float noise60 = 0.2 * sin(2.0 * PI * 60.0 * t);

      // 3. Ruido blanco de fondo
      float white_noise = (random(-50, 50) / 1000.0);

      // 4. Burst de contracción muscular: 1.5 s activo cada 4 s
      float burst = 0.0;
      float cycle = fmod(t, 4.0);
      if (cycle > 1.0 && cycle < 2.5) {
        float shape = sin(PI * ((cycle - 1.0) / 1.5));
        burst = shape * (random(-150, 150) / 100.0);
      }

      float volt = baseline + noise60 + white_noise + burst;

      // Clampear al rango del ADC del ESP32 (0 – 3.3 V)
      if (volt < 0.0) volt = 0.0;
      if (volt > 3.3) volt = 3.3;

      // Enviar a Python
      Serial.println(volt);
      SerialBT.println(volt);
    }

    // ── Revisar si Python mandó STOP ──────────────────────────────────────
    if (intValue == 2) {
      connected = false;
      digitalWrite(LED_PIN, LOW);
      Serial.println("Python -> STOP (2). Deteniendo adquisición.");
    }
  }
}
