// ==============================================================================
// ESP32 EMG Bluetooth Serial Firmware - SIMULATOR MODE
// ==============================================================================
// This firmware simulates a human EMG signal + 60Hz electrical noise.
// Flash this to your ESP32 to test the Python GUI without the physical EMG module.
// ==============================================================================

#include "BluetoothSerial.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled! Please run `make menuconfig` to and enable it
#endif

BluetoothSerial SerialBT;

const int ledPin = 2;       // Status LED pin (Built-in LED)
bool isAcquiring = false;
unsigned long previousBlinkMillis = 0;
const long blinkInterval = 500;

unsigned long previousMicros = 0;
const unsigned long sampleIntervalMicros = 1000; // 1000 Hz

void setup() {
  Serial.begin(115200);
  pinMode(ledPin, OUTPUT);
  
  // Same Bluetooth name so your Python code connects automatically
  SerialBT.begin("ESP32Roquiva"); 
  Serial.println("SIMULATOR: BLUETOOTH DEVICE STARTED PAIRING MODE");
}

void loop() {
  // Listen for commands from Python
  if (SerialBT.available()) {
    char cmd = SerialBT.read();
    if (cmd == '1') {          // start_token
      isAcquiring = true;
      digitalWrite(ledPin, HIGH); 
      Serial.println("Python sent START command (1).");
    } 
    else if (cmd == '2') {     // stop_token
      isAcquiring = false;
      digitalWrite(ledPin, LOW); 
      Serial.println("Python sent STOP command (2).");
    }
  }

  // Acquisition State
  if (isAcquiring) {
    unsigned long currentMicros = micros();
    
    if (currentMicros - previousMicros >= sampleIntervalMicros) {
      previousMicros = currentMicros;
      
      float t = currentMicros / 1000000.0; // Time in seconds
      
      // 1. Base voltage of the ADC (typically 1.5V at rest)
      float baseline = 1.5;
      
      // 2. Add 60 Hz electrical grid noise (to test our new Notch filter!)
      float noise60 = 0.2 * sin(2 * PI * 60 * t);
      
      // 3. Add background white noise
      float white_noise = (random(-50, 50) / 1000.0);
      
      // 4. Simulate a muscle contraction for 1.5 seconds every 4 seconds
      float burst = 0.0;
      float cycle = fmod(t, 4.0);
      if (cycle > 1.0 && cycle < 2.5) {
         // High frequency "muscle" noise (approx 100Hz-200Hz broadband) multiplied by a window curve
         float envelope_shape = sin(PI * ((cycle - 1.0) / 1.5)); 
         burst = envelope_shape * (random(-150, 150) / 100.0); 
      }
      
      // Calculate final simulated voltage
      float voltage = baseline + noise60 + white_noise + burst;
      
      // Clamp to realistic ESP32 ADC limits
      if (voltage < 0.0) voltage = 0.0;
      if (voltage > 3.3) voltage = 3.3;
      
      // Send data to Python via Bluetooth
      SerialBT.println(voltage, 4);
    }
  } else {
    // Waiting for connection (blink LED)
    unsigned long currentMillis = millis();
    if (currentMillis - previousBlinkMillis >= blinkInterval) {
      previousBlinkMillis = currentMillis;
      digitalWrite(ledPin, !digitalRead(ledPin));
    }
  }
}
