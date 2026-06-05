// =============================================================================
// ESP32 EMG Simulator Firmware
// =============================================================================
// Generates a synthetic EMG signal over Bluetooth Classic (SPP) for testing
// the acquisition GUI without real EMG hardware.
//
// Protocol:
//   - Waits for start token '1' via Bluetooth to begin transmission
//   - Sends voltage values (0.0 - 5.0 V) as text lines terminated by \r\n
//   - Stops transmission when stop token '2' is received
//
// Signal characteristics:
//   - Baseline:   ~0.5 V with small white noise
//   - Bursts:     Every 3 seconds, a 600 ms contraction burst (peak ~2.5 V)
//   - Sample rate: ~500 Hz (2 ms delay between samples)
//
// LED feedback:
//   - Blinking (500 ms):  Waiting for connection / start token
//   - Solid ON:           Connected and transmitting data
//   - OFF:                Stopped (received stop token '2')
//
// IMPORTANT: Compile with ESP32 Arduino Core version 2.0.17 or earlier.
//            Core 3.x has known Bluetooth Classic (SPP) compatibility issues
//            with Windows 10/11 that cause COM port hangs and connection failures.
//            See: https://github.com/espressif/arduino-esp32/issues
// =============================================================================

// PIN CONFIGURATIONS
#define LED_PIN 2     // Status LED pin
#define ANALOG_PIN A0 // Analog port to monitor

// INCLUDES & GLOBALS
#include "BluetoothSerial.h"
BluetoothSerial SerialBT;

bool isConnected             = false;
unsigned long previousMillis = 0;
const long blinkInterval     = 500; // LED blink interval in milliseconds

// Variables for the mathematical EMG simulator
unsigned long burstStartTime = 0;
bool inBurst = false;
float phase = 0.0;

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  SerialBT.begin("ESP32_EMG_Sim"); // Bluetooth device name
  Serial.println("DEVICE STARTED BLUETOOTH PAIRING MODE");
}

void loop() {
  unsigned long currentMillis = millis();
  int           intValue      = 0;
  char          receivedChar;

  if (isConnected == false) {
    if (SerialBT.available()) {
      receivedChar = SerialBT.read();
      delay(1);
      // If we receive the start token '1'
      if (receivedChar == '1') {
        intValue = 1;
      }
      Serial.println(intValue);
    }

    if (intValue == 1) {
      isConnected = true;
      digitalWrite(LED_PIN, HIGH); // Turn LED solid ON when connected
    } else {
      // Blink LED while waiting for connection
      if (currentMillis - previousMillis >= blinkInterval) {
        previousMillis = currentMillis;
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
      }
    }
  } else {
    // --- MATHEMATICAL EMG SIMULATOR ---
    float volt = 0.5; // Baseline at 0.5V

    // Generate bursts every 3 seconds
    if (!inBurst && (currentMillis - burstStartTime) > 3000) {
      inBurst = true;
      burstStartTime = currentMillis;
    }
    if (inBurst && (currentMillis - burstStartTime) > 600) {
      inBurst = false;
      burstStartTime = currentMillis;
    }

    if (inBurst) {
      // Simulated muscle contraction wave
      volt += 2.0 * abs(sin(phase)) * (1.0 + random(-20, 20) / 100.0);
      phase += 0.5;
    }
    // Add white noise to baseline
    volt += random(-5, 5) / 100.0;

    if (volt < 0.0) volt = 0.0;
    if (volt > 5.0) volt = 5.0;
    // ----------------------------------

    Serial.println(volt);
    SerialBT.println(volt);

    // Check if stop token '2' is received
    if (SerialBT.available()) {
      receivedChar = SerialBT.read();
      if (receivedChar == '2') {
        isConnected = false;
        digitalWrite(LED_PIN, LOW); // Turn OFF LED
      }
    }

    delay(2); // ~500 Hz sampling rate
  }
}
