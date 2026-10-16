// =============================================================================
// ESP32 EMG Simulator Firmware
// =============================================================================
// Synthetic sEMG over Bluetooth Classic (SPP) for testing the acquisition
// system without the AD8832 front-end. Identical to esp32_firmware.ino with
// EMG_SIMULATED = 1, but advertised as "ESP32_EMG_Sim".
//
// Protocol:
//   - Waits for start token '1' via Bluetooth to begin transmission
//   - Sends voltage values (0.0 - 3.3 V) as text lines terminated by \r\n
//   - Stops on stop token '2' or when the client disconnects
//
// Signal (mirrors acquisition_systems/workers/emg_sim.py, same xorshift32 PRNG):
//   - Baseline:   0.30 V DC + rectified, smoothed Gaussian tonic activity
//   - Bursts:     every 5 s (first at 2 s), 1 s raised-cosine, ~1.2 V peak
//   - Mains:      deliberate 60 Hz, 0.10 V (aliases to 40 Hz at 100 Hz)
//   - Sample rate: 100 Hz (hardware timer)
//
// LED feedback:
//   - Blinking (500 ms):  Waiting for connection / start token
//   - Solid ON:           Connected and transmitting data
//   - OFF:                Stopped
//
// IMPORTANT: Compile with ESP32 Arduino Core version 2.0.17 or earlier.
//            Core 3.x has known Bluetooth Classic (SPP) compatibility issues
//            with Windows 10/11 that cause COM port hangs and connection failures.
// =============================================================================

#include "BluetoothSerial.h"
#include <math.h>

// Check if Bluetooth is enabled in the Arduino IDE
#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled! Please run `make menuconfig` to and enable it
#endif

#define EMG_SIMULATED 1            // this sketch always simulates

BluetoothSerial SerialBT;

// --- Configuration ---
const int emgPin = A0;      // Analog pin for EMG monitoring
const int ledPin = 2;       // Status LED pin (Built-in LED on most ESP32 boards)
const uint32_t SAMPLE_RATE_HZ = 100;   // must match emg_sample_rate_hz in config.yaml

bool isAcquiring = false;

// Variables for LED blinking
unsigned long previousBlinkMillis = 0;
const long blinkInterval = 500; // Blink interval in milliseconds

// Hardware timer for precise sampling. The ISR only signals the main loop;
// ADC reads and Bluetooth writes are intentionally kept out of the ISR.
hw_timer_t *sampleTimer = nullptr;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;
volatile uint32_t sampleTicks = 0;

// ------------------------------------------------------------------------------
// Synthetic sEMG model (mirror of emg_sim.py)
// ------------------------------------------------------------------------------
const uint32_t SIM_SEED          = 0x1234ABCDu;
const double DC_OFFSET_V         = 0.30;
const double TONIC_SIGMA_V       = 0.04;
const double TONIC_SMOOTH_HZ     = 5.0;
const double BURST_START_S       = 2.0;
const double BURST_PERIOD_S      = 5.0;
const double BURST_DURATION_S    = 1.0;
const double BURST_AMPLITUDE_V   = 1.2;
const double BURST_MOD_SMOOTH_HZ = 8.0;
const double BURST_MOD_DEPTH     = 0.3;
const double MAINS_HZ            = 60.0;
const double MAINS_AMPLITUDE_V   = 0.10;

uint32_t simState = SIM_SEED;
uint32_t simN = 0;
double simTonic = 0.0;
double simMod = 0.0;

uint32_t xorshift32() {
  uint32_t x = simState;
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  simState = x;
  return x;
}

double uniform01() { return (xorshift32() >> 8) * (1.0 / 16777216.0); }

double gauss01() {  // Irwin-Hall with 4 uniforms, unit variance
  double s = uniform01() + uniform01() + uniform01() + uniform01();
  return (s - 2.0) * sqrt(3.0);
}

void simReset() {
  simState = SIM_SEED;
  simN = 0;
  simTonic = TONIC_SIGMA_V * sqrt(2.0 / M_PI);
  simMod = 0.0;
}

double simNextSample() {
  const double fs = (double)SAMPLE_RATE_HZ;
  const double aTonic = 1.0 - exp(-2.0 * M_PI * TONIC_SMOOTH_HZ / fs);
  const double aMod = 1.0 - exp(-2.0 * M_PI * BURST_MOD_SMOOTH_HZ / fs);
  uint32_t n = simN++;
  double t = n / fs;

  double gTonic = gauss01();
  double gMod = gauss01();
  simTonic += aTonic * (fabs(gTonic) * TONIC_SIGMA_V - simTonic);
  simMod += aMod * (gMod - simMod);

  double burst = 0.0;
  if (t >= BURST_START_S) {
    double phase = fmod(t - BURST_START_S, BURST_PERIOD_S);
    if (phase < BURST_DURATION_S) {
      double envelope = 0.5 * (1.0 - cos(2.0 * M_PI * phase / BURST_DURATION_S));
      double mod = 1.0 + BURST_MOD_DEPTH * simMod;
      burst = BURST_AMPLITUDE_V * envelope * (mod > 0.0 ? mod : 0.0);
    }
  }
  double cycles = fmod(MAINS_HZ * n / fs, 1.0);
  double mains = MAINS_AMPLITUDE_V * sin(2.0 * M_PI * cycles);

  double v = DC_OFFSET_V + simTonic + burst + mains;
  if (v < 0.0) v = 0.0;
  if (v > 3.3) v = 3.3;
  return v;
}

// ------------------------------------------------------------------------------

void IRAM_ATTR onSampleTimer() {
  portENTER_CRITICAL_ISR(&timerMux);
  if (sampleTicks < SAMPLE_RATE_HZ) {
    sampleTicks++;
  }
  portEXIT_CRITICAL_ISR(&timerMux);
}

void startAcquisition() {
  simReset();
  portENTER_CRITICAL(&timerMux);
  sampleTicks = 0;
  portEXIT_CRITICAL(&timerMux);
  isAcquiring = true;
  timerAlarmEnable(sampleTimer);
  digitalWrite(ledPin, HIGH); // Solid LED when acquiring
}

void stopAcquisition() {
  isAcquiring = false;
  timerAlarmDisable(sampleTimer);
  portENTER_CRITICAL(&timerMux);
  sampleTicks = 0;
  portEXIT_CRITICAL(&timerMux);
  digitalWrite(ledPin, LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(ledPin, OUTPUT);

  SerialBT.begin("ESP32_EMG_Sim"); // Bluetooth device name
  Serial.println("BLUETOOTH DEVICE STARTED PAIRING MODE");

  // ESP32 has a 12-bit ADC by default (range 0 to 4095)
  analogReadResolution(12);
  analogSetPinAttenuation(emgPin, ADC_11db);
  sampleTimer = timerBegin(0, 80, true);  // 80 MHz / 80 = 1 MHz
  timerAttachInterrupt(sampleTimer, &onSampleTimer, true);
  timerAlarmWrite(sampleTimer, 1000000UL / SAMPLE_RATE_HZ, true); // 10000 us = 100 Hz
  timerAlarmDisable(sampleTimer);
}

void loop() {
  // 1. Listen for commands from Python (start_token and stop_token)
  while (SerialBT.available()) {
    char cmd = SerialBT.read();
    if (cmd == '1') {          // start_token configured in config.yaml
      startAcquisition();
      Serial.println("Python sent START command (1).");
    } else if (cmd == '2') {   // stop_token configured in config.yaml
      stopAcquisition();
      Serial.println("Python sent STOP command (2).");
    }
  }

  // A client that disappears without sending '2' must not leave the board
  // streaming: the next connection would otherwise start mid-line.
  if (isAcquiring && !SerialBT.hasClient()) {
    stopAcquisition();
    Serial.println("Client disconnected: acquisition stopped.");
  }

  // 2. State Machine Handling
  if (isAcquiring) {
    bool due = false;
    portENTER_CRITICAL(&timerMux);
    due = sampleTicks > 0;
    if (due) {
      sampleTicks--;
    }
    portEXIT_CRITICAL(&timerMux);
    if (due) {
#if EMG_SIMULATED
      float voltage = (float)simNextSample();
#else
      // Calibrated reading (eFuse two-point calibration), 0-3.3 V at 11 dB.
      float voltage = analogReadMilliVolts(emgPin) / 1000.0f;
#endif
      // Send data to Python (prints a CRLF newline which Python reads)
      SerialBT.println(voltage, 4);
    }
  } else {
    // --- Idle Mode (Not connected/acquiring) ---
    // Blink the LED to indicate it is waiting for a connection
    unsigned long currentMillis = millis();
    if (currentMillis - previousBlinkMillis >= blinkInterval) {
      previousBlinkMillis = currentMillis;
      digitalWrite(ledPin, !digitalRead(ledPin));
    }
  }
}
