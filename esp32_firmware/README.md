# ESP32 Firmware

This directory contains Arduino sketches for the ESP32 microcontroller used in this project.

> **Hardware Assembly & Full Instructions:** Please refer to [Module 2: ESP32 EMG in the Hardware Wiki](https://github.com/OscarIHG/real-time-cop-jointangle-emg-system/wiki/Module-2-ESP32-EMG) for complete assembly and flashing instructions.

> **IMPORTANT — Arduino Core Version**
>
> You **must** use **ESP32 Arduino Core version 2.0.17** (or any 2.x release).
>
> **Do NOT use Core 3.x.** Version 3.0+ introduced breaking changes to the Bluetooth Classic (SPP)
> stack that cause connection failures and COM port hangs on Windows 10/11.
> The device may appear paired but the serial link will never establish.
> This is a [known issue](https://github.com/espressif/arduino-esp32/issues) in the community.
>
> To install the correct version:
> 1. Open Arduino IDE → **Tools** → **Board** → **Boards Manager**.
> 2. Search for **"esp32"** and find **"esp32 by Espressif Systems"**.
> 3. Select version **2.0.17** from the dropdown and click **Install**.
> 4. Recompile and upload the firmware.

---

## Production Firmware (`esp32_firmware.ino`)

The main firmware that reads a **real analog EMG signal** from pin `A0` at 1000 Hz and transmits it over Bluetooth Classic (SPP).

Use this when your ESP32 is connected to the physical EMG amplifier circuit.

---

## EMG Simulator (`emg_simulator/`)

A test firmware that generates a **synthetic EMG signal** over Bluetooth Classic (SPP). Use this to verify the acquisition GUI and signal pipeline without needing the physical EMG module or analog circuitry.

### Signal Characteristics

| Parameter       | Value                                    |
|-----------------|------------------------------------------|
| Baseline        | ~0.5 V with white noise                  |
| Burst amplitude | ~2.5 V peak                              |
| Burst interval  | Every 3 seconds (600 ms duration)        |
| Sample rate     | ~500 Hz                                  |
| Output range    | 0.0 – 5.0 V (clamped)                   |

### LED Feedback

| LED State          | Meaning                              |
|--------------------|--------------------------------------|
| Blinking (500 ms)  | Waiting for Bluetooth connection     |
| Solid ON           | Connected and transmitting data      |
| OFF                | Stopped (received stop token `'2'`)  |

### How to Flash

1. Open `emg_simulator/emg_simulator.ino` in the Arduino IDE.
2. Select **Board:** `ESP32 Dev Module`.
3. Select the correct **Port** (USB serial).
4. Click **Upload**.
5. Pair the device (named `ESP32_EMG_Sim`) via your OS Bluetooth settings.
6. Update `config.yaml` with the assigned COM port (Windows) or MAC address (Linux).
