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

* **Data Visualization:** Utilizes PyQt5 and PyQtGraph with OpenGL rendering for multi-plot data visualization.
* **EMG Sampling:** Includes an ESP32 firmware sketch (`esp32_firmware/`) that samples at exactly 1000 Hz using a hardware timer and transmits 0–3.3 V readings over Bluetooth Classic (SPP).
* **Bluetooth Connectivity:** Implements `socket.AF_BLUETOOTH` (Linux) and `pyserial` (Windows) executed in a dedicated background thread to manage hardware communication without blocking the main process.
* **Pose Estimation:** Integrates MediaPipe to track skeletal joint angles dynamically.
* **Data Recording:** Aligns data streams from the force plate, ESP32, and camera, exporting the synchronized data into a CSV format. Buffers are bounded and cleared between sessions, so the application can record several sessions without restarting.
* **Signal Processing:** Applies a stable IIR notch filter (50/60 Hz) in real time and provides a post-processing script with a 6th-order Butterworth low-pass filter and Hilbert envelope.

---

## Installation

A single setup script per platform installs everything into an isolated Python 3.11 environment inside the repository folder (`venv/`). The system Python is never modified.

### 1. Clone the repository
```bash
git clone https://github.com/OscarIHG/real-time-cop-jointangle-emg-system.git
cd real-time-cop-jointangle-emg-system
```

### 2. Environment Setup

**For Linux / Raspberry Pi OS (64-bit):**

`setup.sh` installs system dependencies, the Phidget22 library, USB permissions for the force plate, Bluetooth SPP support for the ESP32, and a Python 3.11 environment via Micromamba.

The script verifies the two files it downloads (the Phidgets installer and Micromamba) against a SHA-256 checksum before running them, so it refuses to proceed if the checksums are not provided. Compute them first:

```bash
curl -sL https://www.phidgets.com/downloads/setup_linux | sha256sum
curl -sL https://micro.mamba.pm/api/micromamba/linux-aarch64/latest | sha256sum
```

Then run the setup with both values:

```bash
chmod +x setup.sh
PHIDGETS_INSTALLER_SHA256="<first hash>" MICROMAMBA_SHA256="<second hash>" ./setup.sh
```

After the script finishes, log out and back in (or reboot) so the `plugdev` group membership applies to the force plate.

**For Windows 10/11:**

`setup.ps1` downloads a pinned release of `uv`, verifies its SHA-256, and uses it to create the Python 3.11 environment. Obtain the checksum of `uv-x86_64-pc-windows-msvc.zip` from the [uv release page](https://github.com/astral-sh/uv/releases) for the pinned version (see `$uv_version` in the script) and run:

```powershell
$env:UV_SHA256 = "<sha256>"
.\setup.ps1
```

If `uv_bin\uv.exe` is already present, the download is skipped and `UV_SHA256` is not needed.

### 3. Reinstalling from scratch

To rebuild the environment on an existing installation, remove the generated folders and run the setup script again:

```bash
git pull origin master
rm -rf venv bin .mamba_root      # Linux
# Remove-Item -Recurse venv, uv_bin   # Windows
```

### 4. Hardware Pairing (First-time Linux Setup)
If running on a fresh Raspberry Pi installation, you **must** pair the ESP32 manually via the terminal before running the software. 

> [!NOTE]
> It is highly probable that the Raspberry Pi Desktop Bluetooth GUI will fail to discover the ESP32 or result in a blank list, which is why we do it directly from the CLI.

Ensure the ESP32 is powered on, then run the native CLI tool:

```bash
bluetoothctl
[bluetoothctl] scan on
# Wait for "[NEW] Device XX:XX:XX:XX:XX:XX <YOUR_ESP32_NAME>"
[bluetoothctl] pair XX:XX:XX:XX:XX:XX
[bluetoothctl] trust XX:XX:XX:XX:XX:XX
[bluetoothctl] quit
```

---

## Usage

Ensure the hardware components (ESP32, Camera, Force Plate) are connected. Verify the configuration parameters in `config.yaml` match the current setup.

**On Linux / Raspberry Pi:**
```bash
./venv/bin/python -m acquisition_systems.app_gui
```

**On Windows:**
```powershell
.\venv\Scripts\python.exe -m acquisition_systems.app_gui
```

### Data Acquisition Procedure
1. Open the application.
2. Set the **Duration** parameter (in seconds).
3. Provide an optional **Base Filename**.
4. Select **Start** to begin data acquisition.
5. Select **Save CSV** after the acquisition period to export the synchronized data to the `sessions/` directory.

### Post-Processing
To apply the Digital Signal Processing (DSP) steps (6th-order Butterworth low-pass filter at 10 Hz, followed by a Hilbert transform for amplitude envelope), run the standalone post-processing script:

**On Linux / Raspberry Pi:**
```bash
./venv/bin/python scripts/post_process_emg.py
```

**On Windows:**
```powershell
.\venv\Scripts\python.exe scripts\post_process_emg.py
```

The script automatically finds the latest saved CSV in `sessions/`, writes a `_processed.csv` file with the filtered data and amplitude envelope, and opens a PyQtGraph window so you can compare the raw signal against the applied filters. Use `--no-show` on headless Raspberry Pi sessions, or pass a specific CSV path as the first argument.

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
| `emg_mac` | Bluetooth MAC address of the ESP32 (Linux) |
| `emg_com_port` | Outgoing COM port of the paired ESP32 (Windows only) |
| `emg_vmin` / `emg_vmax` | Expected EMG voltage range (0–3.3 V for the ESP32 ADC) |
| `cop_*` | Force plate dimensions, orientation flips, and sampling interval |
| `cam_index` | Camera index (0 for the built-in webcam, 1/2 for USB cameras) |
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
├── setup.sh                  # Installer script (Linux / Raspberry Pi)
├── setup.ps1                 # Installer script (Windows)
├── esp32_firmware/           # ESP32 Arduino sketches
│   ├── README.md             # Firmware docs & Core version warning
│   ├── esp32_firmware.ino    # Production firmware (real EMG, 1000 Hz)
│   └── emg_simulator/        # Synthetic EMG signal generator for testing
├── hardware/
│   └── 3d_prints/
│       └── camera_enclosure/ # 3D printable STL files for camera mount
├── scripts/
│   └── post_process_emg.py   # Offline Butterworth + Hilbert processing
├── tests/
│   └── test_core.py          # Unit tests (config, DSP, recorder, utils)
└── acquisition_systems/
    ├── app_gui.py            # Main GUI script
    ├── recorder.py           # Bounded buffers and CSV export
    ├── common/
    │   ├── config.py         # Strict YAML config loader
    │   ├── dsp.py            # IIR notch and Butterworth filters
    │   ├── types.py          # Sample dataclasses
    │   └── utils.py          # Joint angle helpers
    └── workers/
        ├── emg.py            # Bluetooth socket/serial module
        ├── cop.py            # Phidget force plate module
        └── pose.py           # MediaPipe joint angle module
```

---

## Troubleshooting

* **ESP32 Arduino Core Version (Critical):** You **must** compile the ESP32 firmware using **Arduino Core version 2.0.17** (or any 2.x release). Core 3.x introduced breaking changes to the Bluetooth Classic (SPP) stack that cause COM port hangs and connection failures on Windows 10/11. The device may appear paired but the serial link will never establish. For full firmware installation instructions, see [Module 2: ESP32 EMG in the Hardware Wiki](https://github.com/OscarIHG/real-time-cop-jointangle-emg-system/wiki/Module-2-ESP32-EMG).
* **Windows Bluetooth Connections:** If the Bluetooth port becomes unresponsive, remove the device from Windows Bluetooth Settings, restart the ESP32, and pair it again. Update the `emg_com_port` parameter in `config.yaml` to the newly assigned **Outgoing** COM port (not the Incoming one). You can identify the correct port in Device Manager under Bluetooth → look for the port whose Hardware ID contains your ESP32's MAC address.
* **Linux Bluetooth Connections:** Verify that the ESP32 is trusted and paired using the `bluetoothctl` utility prior to execution.
* **Force Plate (Phidget) Access Denied (Linux):** If you see `Phidgets were detected, but access is denied`, Linux `udev` rules have not been applied to the connected device yet. Physically unplug the Phidget's USB cable from the Raspberry Pi, wait 2 seconds, and plug it back in.
* **Camera Initialization:** Modify the `cam_index` parameter in `config.yaml` (index 0 typically corresponds to the integrated webcam).
* **EMG Simulator Firmware:** An EMG simulator sketch is provided in `esp32_firmware/emg_simulator/` for testing the GUI without real EMG hardware. See [`esp32_firmware/README.md`](esp32_firmware/README.md) for details.