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

Streams one voltage sample per line (`0.1234\r\n`) over Bluetooth Classic (SPP) at **100 Hz** (hardware timer, `SAMPLE_RATE_HZ`). This matches the paper and `emg_sample_rate_hz` in `config.yaml`. Streaming starts on `'1'` and stops on `'2'` or when the client disconnects.

| `EMG_SIMULATED` | Source |
|-----------------|--------|
| `1` (default)   | Synthetic sEMG, while the AD8232 module is not connected (avoids streaming the noise of a floating ADC pin) |
| `0`             | AD8232 output on `A0`, read with `analogReadMilliVolts` (calibrated, 0-3.3 V) |

---

## EMG Simulator (`emg_simulator/`)

The same firmware with `EMG_SIMULATED 1` fixed, advertised as `ESP32_EMG_Sim`. Use it to verify the acquisition GUI and signal pipeline without the physical EMG module.

### Signal Characteristics

The model and its xorshift32 PRNG are mirrored in `acquisition_systems/workers/emg_sim.py`, so the Python fallback (`emg_source: auto`/`simulated`) produces the same sequence. Keep the two in sync.

| Parameter       | Value                                                    |
|-----------------|----------------------------------------------------------|
| Baseline        | 0.30 V DC + rectified, smoothed Gaussian tonic activity  |
| Bursts          | every 5 s (first at 2 s), 1 s raised cosine, ~1.2 V peak |
| Interference    | deliberate 60 Hz sinusoid, 0.10 V (appears at 40 Hz when sampled at 100 Hz) |
| Sample rate     | 100 Hz                                                   |
| Output range    | 0.0 - 3.3 V (never clips at 0 V)                         |

### LED Feedback

| LED State          | Meaning                              |
|--------------------|--------------------------------------|
| Blinking (500 ms)  | Waiting for Bluetooth connection     |
| Solid ON           | Connected and transmitting data      |
| OFF                | Stopped (stop token or disconnect)   |

### How to Flash

1. Open `esp32_firmware.ino` (or `emg_simulator/emg_simulator.ino`) in the Arduino IDE.
2. Select **Board:** `ESP32 Dev Module`.
3. Select the correct **Port** (USB serial).
4. Click **Upload**.
5. Pair the device via your OS Bluetooth settings.
6. Update `config.yaml` with the assigned COM port (Windows) or MAC address (Linux).

From the command line (e.g. on the Raspberry Pi):

```bash
arduino-cli core install esp32:esp32@2.0.17
arduino-cli compile --fqbn esp32:esp32:esp32 esp32_firmware
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/ttyACM0 esp32_firmware
```
