// ==============================================================================
// ESP32 EMG Bluetooth Serial Firmware
// Compatible with the Real-Time CoP-JointAngle-EMG project
//
// IMPORTANT: Compile with ESP32 Arduino Core version 2.0.17 or earlier.
//            Core 3.x has known Bluetooth Classic (SPP) compatibility issues
//            with Windows 10/11 that cause COM port hangs and connection failures.
// ==============================================================================

#include "BluetoothSerial.h"

// Check if Bluetooth is enabled in the Arduino IDE
#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled! Please run `make menuconfig` to and enable it
#endif

BluetoothSerial SerialBT;

// --- Configuration ---
const int emgPin = A0;      // Analog pin for EMG monitoring
const int ledPin = 2;       // Status LED pin (Built-in LED on most ESP32 boards)

bool isAcquiring = false;

// Variables for LED blinking
unsigned long previousBlinkMillis = 0;
const long blinkInterval = 500; // Blink interval in milliseconds

// Variables for precise 1000 Hz sampling
unsigned long previousMicros = 0;
const unsigned long sampleIntervalMicros = 1000; // 1000 microseconds = 1ms = 1000 Hz

void setup() {
  Serial.begin(115200);
  pinMode(ledPin, OUTPUT);
  
  // This is the exact name Windows will see when pairing
  SerialBT.begin("ESP32Roquiva"); 
  Serial.println("BLUETOOTH DEVICE STARTED PAIRING MODE");
  
  // ESP32 has a 12-bit ADC by default (range 0 to 4095)
  analogReadResolution(12);
}

void loop() {
  // 1. Listen for commands from Python (start_token and stop_token)
  if (SerialBT.available()) {
    char cmd = SerialBT.read();
    
    if (cmd == '1') {          // start_token configured in config.yaml
      isAcquiring = true;
      digitalWrite(ledPin, HIGH); // Solid LED when acquiring
      Serial.println("Python sent START command (1).");
    } 
    else if (cmd == '2') {     // stop_token configured in config.yaml
      isAcquiring = false;
      digitalWrite(ledPin, LOW); // Turn off LED
      Serial.println("Python sent STOP command (2).");
    }
  }

  // 2. State Machine Handling
  if (isAcquiring) {
    // --- Acquisition Mode ---
    unsigned long currentMicros = micros();
    
    // Ultra-precise timer without blocking the processor (no delay() used!)
    if (currentMicros - previousMicros >= sampleIntervalMicros) {
      previousMicros = currentMicros;
      
      // Read pin value
      float analogValue = analogRead(emgPin);
      
      // Convert to voltage (using 5V multiplier as requested in original code)
      float voltage = 5.0 * analogValue / 4095.0;
      
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
