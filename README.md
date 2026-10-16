# Real-Time CoP-JointAngle-EMG System

[![CI](https://github.com/OscarIHG/real-time-cop-jointangle-emg-system/actions/workflows/ci.yml/badge.svg)](https://github.com/OscarIHG/real-time-cop-jointangle-emg-system/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.1007%2F978--3--032--13729--6__38-blue)](https://doi.org/10.1007/978-3-032-13729-6_38)

Integrated system for real-time measurement of Center of Pressure, Joint Angles, and Abdominal EMG.

Based on the paper: *"Design of a System for the Real-Time Acquisition of Center of Pressure, Joint Angle, and Abdominal EMG"* — published in **IFMBE Proceedings, vol. 137**, Springer, 2026. [→ Read the paper](https://link.springer.com/chapter/10.1007/978-3-032-13729-6_38)

---

## Hardware Documentation

For complete hardware specifications, assembly instructions, schematics, and the Bill of Materials (BOM), please visit the project's [GitHub Wiki](https://github.com/OscarIHG/real-time-cop-jointangle-emg-system/wiki).

---

## Features

This repository provides a software implementation designed for Raspberry Pi 4 (Raspberry Pi OS 64-bit) and Windows systems.

* **Central coordinator:** `acquisition_systems/session.py` synchronises the three modules, routes every sample to the recorder, measures real rates and stores the dataset. It runs behind either GUI or headless over SSH.
* **Data Visualization:** two interchangeable GUIs with the paper's 2x2 layout (Abdominal EMG, Center of Pressure, Body-Tracking, Joint Angle): PyQtGraph (`gui_backend: qt`, default, fastest on the Raspberry Pi) and Tkinter + Matplotlib with blitting (`gui_backend: tk`, the toolkit used in the paper).
* **EMG Sampling:** ESP32 firmware (`esp32_firmware/`) samples at 100 Hz (as in the paper) with a hardware timer and transmits 0-3.3 V readings over Bluetooth Classic (SPP). With `EMG_SIMULATED 1` it generates a synthetic sEMG (tonic activity, periodic bursts and a deliberate 60 Hz component) while the AD8832 is not connected.
* **Simulator fallback:** with `emg_source: auto` the receiver falls back to the same synthetic signal (identical model and PRNG as the firmware) when the ESP32 is off.
* **Force plate:** PhidgetBridge 1046_1 at 125 Hz, CoP from Eqs. (1)-(2) of the paper using the distances between load-cell centres (48.38 x 33.04 cm), event-driven tare after the bridge self-calibration, NaN when the plate is unloaded.
* **Pose Estimation:** MediaPipe Pose (33 landmarks, `model_complexity: 0`) on the newest frame from a dedicated capture thread; USB/V4L2 cameras through OpenCV and CSI cameras (Rpi P5V04A V1.3) through `rpicam-vid`.
* **Data Recording:** native-rate CSVs per stream, a merged CSV on the EMG timeline (other streams matched "as of" with staleness limits) and a metadata JSON (config, emg source, effective rates, tare, drops).
* **Signal Processing:** real-time 60 Hz notch by FFT -> remove -> inverse FFT. It is alias-aware: sampled at 100 Hz, 60 Hz interference appears at 40 Hz. A streaming IIR alternative is available (`emg_notch_method: iir`). Post-processing applies a 6th-order Butterworth low-pass (10 Hz) and the Hilbert envelope.

---

## Installation

One command per platform installs everything into an isolated Python 3.11 environment inside the repository folder (`venv/`). The system Python is never modified, and the scripts are safe to run again (anything already installed is skipped).

Every download is pinned to a fixed version and verified automatically, so there are no checksums to compute by hand:

* Phidgets apt repository: verified by its GPG key fingerprint.
* Micromamba, `uv` and the Windows Phidget22 installer: verified by SHA-256.

### 1. Clone the repository
```bash
git clone https://github.com/OscarIHG/real-time-cop-jointangle-emg-system.git
cd real-time-cop-jointangle-emg-system
```

### 2. Run the setup script

**Raspberry Pi OS / Debian (64-bit)**

```bash
./setup.sh
```

It asks for your `sudo` password once, then:

1. Installs system packages: camera tools, Bluetooth and the OpenCV runtime libraries.
2. Installs the Phidget22 driver from the vendor's signed apt repository.
3. Sets USB permissions for the PhidgetBridge (udev rule and the `plugdev`, `dialout` and `video` groups).
4. Enables Bluetooth Classic SPP (`bluetoothd --compat`) for the ESP32.
5. Creates `venv/` with Micromamba and installs `requirements.txt`.
6. Runs the diagnostic (see below).

If the script added you to a group, **log out and back in (or reboot)** before using the force plate.

**Windows 10/11**

```powershell
.\setup.ps1
```

If PowerShell refuses to run scripts, use `powershell -ExecutionPolicy Bypass -File .\setup.ps1` once. The script:

1. Installs a pinned `uv` in `uv_bin\`.
2. Opens the Phidget22 driver installer: accept the administrator prompt and click through it.
3. Creates `venv\` with an isolated Python 3.11 and installs `requirements.txt`.
4. Runs the diagnostic.

**Options**

| Linux | Windows | Effect |
|-------|---------|--------|
| `./setup.sh --clean` | `.\setup.ps1 -Clean` | Delete `venv` and rebuild it from scratch |
| `./setup.sh --yes` | — | Do not ask for confirmation (unattended runs) |
| — | `.\setup.ps1 -SkipDriver` | Do not install the Phidget22 driver |

### 3. Check the installation and hardware

The setup ends with a diagnostic, which you can run again at any time:

```bash
./venv/bin/python -m acquisition_systems.doctor           # Linux / Raspberry Pi
.\venv\Scripts\python.exe -m acquisition_systems.doctor   # Windows
```

It prints `OK` / `WARN` / `FAIL` for:

* Python and every library.
* `config.yaml`.
* The PhidgetBridge.
* The camera.
* The ESP32 pairing (Linux) or COM port (Windows).
* The graphical display.

Every problem comes with a hint on how to fix it. Missing hardware is only a warning: each module runs on its own, and the EMG falls back to the built-in simulator. Use `--quick` to skip opening the force plate and the camera.

### 4. Pair the ESP32 (one time, manual on both platforms)

Pairing needs a confirmation from the operating system, so it is not automated.

**Raspberry Pi:** the desktop Bluetooth applet often fails to list the ESP32, so pair it from the terminal with the ESP32 powered on:

```bash
bluetoothctl
[bluetoothctl] scan on
# Wait for "[NEW] Device XX:XX:XX:XX:XX:XX <YOUR_ESP32_NAME>"
[bluetoothctl] pair XX:XX:XX:XX:XX:XX
[bluetoothctl] trust XX:XX:XX:XX:XX:XX
[bluetoothctl] quit
```

Then set `emg_mac: "XX:XX:XX:XX:XX:XX"` in `config.yaml`.

**Windows:** pair the ESP32 in *Settings → Bluetooth & devices*. In *Device Manager → Ports (COM & LPT)*, find the **Outgoing** port of the ESP32 and set `emg_com_port: "COMx"` in `config.yaml`. The diagnostic lists the Bluetooth COM ports it finds.

Run the diagnostic again. Both checks should report `OK`.

---

## Usage

Ensure the hardware components (ESP32, Camera, Force Plate) are connected. Verify the configuration parameters in `config.yaml` match the current setup.

**On Linux / Raspberry Pi:**
```bash
./venv/bin/python -m acquisition_systems.app_gui            # GUI from gui_backend (qt by default)
./venv/bin/python -m acquisition_systems.app_gui --gui tk   # Tkinter + Matplotlib (paper Fig. 3)
```

**On Windows:**
```powershell
.\venv\Scripts\python.exe -m acquisition_systems.app_gui
```

Over SSH, run the GUI on the Pi's screen with `DISPLAY=:0 ./venv/bin/python -m acquisition_systems.app_gui`, or acquire without any GUI:

```bash
./venv/bin/python -m acquisition_systems.session --duration 20 [--emg-source simulated]
```

### Data Acquisition Procedure
1. Open the application. The hardware connects and the force plate is tared, so **keep the plate unloaded** until the status bar shows the live rates. Use **Tare** to re-zero at any time.
2. Set the recording length in seconds.
3. Provide an optional **Filename**.
4. Select **Start** to record (**Stop** ends it early).
5. Select **Save** to write the dataset to `sessions/<date>/`:
   * `<name>.csv`: merged
   * `<name>_emg.csv`, `<name>_cop.csv`, `<name>_pose.csv`: native rate
   * `<name>_meta.json`
   * `<name>_emg_processed.csv/.png`: post-processing

### Post-Processing
The GUI runs it automatically on Save. To re-run it (6th-order Butterworth low-pass at 10 Hz, then Hilbert envelope):

```bash
./venv/bin/python scripts/post_process_emg.py [path/to/<name>_emg.csv] [--no-show] [--png out.png]
```

### Hardware checks and benchmarks
```bash
./venv/bin/python scripts/hw_benchmark.py cop      # PhidgetBridge rate, jitter, tare
./venv/bin/python scripts/hw_benchmark.py camera --snapshot frame.jpg
./venv/bin/python scripts/hw_benchmark.py pose [--file person.jpg]
./venv/bin/python scripts/hw_benchmark.py emg --source simulated
./venv/bin/python scripts/hw_benchmark.py dsp      # notch cost per tick
./venv/bin/python scripts/hw_benchmark.py render   # matplotlib naive vs blitting vs PyQtGraph
```

### Running the tests
```bash
./venv/bin/python -m unittest discover -s tests -v
```
The same tests, plus syntax checks of the installer scripts, run automatically on GitHub Actions for every push and pull request (see `.github/workflows/ci.yml`).

---

## Configuration (`config.yaml`)

All hardware parameters live in `config.yaml`. The most common ones to adjust:

| Key | Purpose |
|-----|---------|
| `gui_backend` | `qt` (PyQtGraph) or `tk` (Tkinter + Matplotlib) |
| `emg_source` | `auto` (Bluetooth, falling back to the simulator), `bluetooth` or `simulated` |
| `emg_mac` | Bluetooth MAC address of the ESP32 (Linux) |
| `emg_com_port` | Outgoing COM port of the paired ESP32 (Windows only) |
| `emg_sample_rate_hz` | Must match `SAMPLE_RATE_HZ` in the firmware (100) |
| `emg_notch_method` | `fft` (paper) or `iir` (streaming, lowest CPU) |
| `cop_gain` | Manufacturer factor in kg per V/V (200 kg / 1.0 mV/V = 200000), one value or four |
| `cop_x_dist_cm` / `cop_y_dist_cm` | Distances between load-cell **centres** (48.38 / 33.04 cm), not the plate size |
| `cop_interval_ms` | PhidgetBridge data interval (8 ms = 125 Hz) |
| `cam_backend` / `cam_rotation` | `auto`, `opencv` (USB), `rpicam` (CSI) or `file`; physical rotation of the camera |
| `recording_max_samples_per_stream` | Upper bound on buffered samples per stream during a recording |

Boolean values must be written as `true` or `false`; the loader reports an error for malformed values instead of silently falling back to defaults.

---

## Repository Structure

```text
real-time-cop-jointangle-emg-system/
├── .github/workflows/ci.yml  # Automated tests on every push
├── CITATION.cff              # Academic citation metadata
├── LICENSE                   # MIT License
├── README.md                 # Setup, usage and troubleshooting guide
├── config.yaml               # Hardware configuration parameters
├── requirements.txt          # Pinned Python dependencies
├── setup.sh                  # One-command installer (Linux / Raspberry Pi)
├── setup.ps1                 # One-command installer (Windows)
├── esp32_firmware/           # ESP32 Arduino sketches
│   ├── README.md             # Firmware docs & Core version warning
│   ├── esp32_firmware.ino    # Production firmware (100 Hz; EMG_SIMULATED switch)
│   └── emg_simulator/        # Same firmware, always simulated ("ESP32_EMG_Sim")
├── hardware/
│   └── 3d_prints/
│       └── camera_enclosure/ # 3D printable STL files for camera mount
├── scripts/
│   ├── post_process_emg.py   # Offline Butterworth + Hilbert processing
│   └── hw_benchmark.py       # Console checks: rates, fps, jitter, render cost
├── tests/
│   └── test_*.py             # Unit tests (DSP, CoP, EMG/simulator, recorder, core)
└── acquisition_systems/
    ├── app_gui.py            # GUI launcher (qt | tk)
    ├── app_qt.py             # PyQtGraph GUI
    ├── app_tk.py             # Tkinter + Matplotlib GUI (blitting)
    ├── session.py            # Central coordinator + headless runner
    ├── doctor.py             # Installation and hardware diagnostic
    ├── postprocess.py        # Butterworth + Hilbert pipeline
    ├── recorder.py           # Bounded buffers and CSV export
    ├── common/
    │   ├── config.py         # Strict YAML config loader
    │   ├── dsp.py            # Alias-aware FFT/IIR notch, Butterworth, Hilbert
    │   ├── types.py          # Sample dataclasses
    │   └── utils.py          # Joint angle helpers
    └── workers/
        ├── emg.py            # Bluetooth socket/serial module
        ├── emg_sim.py        # Synthetic sEMG model + simulated ESP32 link
        ├── cop.py            # Phidget force plate module
        ├── camera.py         # OpenCV / rpicam / file frame sources
        └── pose.py           # MediaPipe joint angle module
```

---

## Troubleshooting

Start with the diagnostic: `python -m acquisition_systems.doctor`. It prints a fix for every problem it detects.

* **ESP32 Arduino Core Version (Critical):** You **must** compile the ESP32 firmware using **Arduino Core version 2.0.17** (or any 2.x release). Core 3.x introduced breaking changes to the Bluetooth Classic (SPP) stack that cause COM port hangs and connection failures on Windows 10/11. The device may appear paired but the serial link will never establish. For full firmware installation instructions, see [Module 2: ESP32 EMG in the Hardware Wiki](https://github.com/OscarIHG/real-time-cop-jointangle-emg-system/wiki/Module-2-ESP32-EMG).
* **Windows Bluetooth Connections:** If the Bluetooth port becomes unresponsive, remove the device from Windows Bluetooth Settings, restart the ESP32, and pair it again. Update the `emg_com_port` parameter in `config.yaml` to the newly assigned **Outgoing** COM port (not the Incoming one). You can identify the correct port in Device Manager under Bluetooth → look for the port whose Hardware ID contains your ESP32's MAC address.
* **Linux Bluetooth Connections:** Verify that the ESP32 is trusted and paired using the `bluetoothctl` utility prior to execution.
* **Force Plate (Phidget) Access Denied (Linux):** If you see `Phidgets were detected, but access is denied`, the `udev` rule has not been applied to the connected device yet. Unplug the Phidget's USB cable, wait 2 seconds and plug it back in. If you just ran `setup.sh`, also log out and back in.
* **Force Plate on Windows:** the PhidgetBridge needs the Phidget22 driver (`setup.ps1` opens its installer). Re-run `.\setup.ps1` or install it from [phidgets.com/docs/OS_-_Windows](https://www.phidgets.com/docs/OS_-_Windows). Only one program can use the bridge at a time: close the Phidget Control Panel before starting the application.
* **PowerShell blocks `setup.ps1`:** run it once with `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.
* **Camera Initialization:** USB cameras use `cam_index` (0 is usually the first camera). CSI cameras (Rpi P5V04A V1.3) are only reachable through libcamera on Raspberry Pi OS Bookworm/Trixie: check `rpicam-hello --list-cameras`, then use `cam_backend: rpicam` (or `auto`). If the image is upside down, set `cam_rotation: 180` rather than flipping the frame.
* **Power-line notch at 100 Hz:** at 100 Hz the Nyquist frequency is 50 Hz, so 60 Hz interference is aliased to 40 Hz. The notch targets the aliased frequency automatically.
* **EMG Simulator:** without the AD8832, flash `esp32_firmware.ino` with `EMG_SIMULATED 1` (default) or `emg_simulator/`. With the ESP32 off, `emg_source: auto` uses the identical built-in simulator. See [`esp32_firmware/README.md`](esp32_firmware/README.md).