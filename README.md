# Real-Time CoP-JointAngle-EMG System

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
* **EMG Sampling:** Includes an ESP32 firmware sketch (`esp32_firmware/`) configured for a 1000 Hz sampling rate using hardware timers.
* **Bluetooth Connectivity:** Implements `socket.AF_BLUETOOTH` (Linux) and `pyserial` (Windows) executed in a dedicated background thread to manage hardware communication without blocking the main process.
* **Pose Estimation:** Integrates MediaPipe to track skeletal joint angles dynamically.
* **Data Recording:** Aligns data streams from the force plate, ESP32, and camera, exporting the synchronized data into a CSV format.

---

## Installation

The installation scripts configure isolated virtual environments.

### 1. Clone the repository
```bash
git clone https://github.com/OscarIHG/real-time-cop-jointangle-emg-system.git
cd real-time-cop-jointangle-emg-system
```

### 2. Environment Setup

**For Linux / Raspberry Pi OS:**
The setup script installs required system dependencies, downloads Micromamba, and configures a Python 3.11 environment.
```bash
chmod +x setup.sh
./setup.sh
```

**For Windows 10/11:**
The PowerShell script uses `uv` to download Python 3.11 and install dependencies. Execute from a PowerShell terminal:
```powershell
.\setup.ps1
```

### 3. Hardware Pairing (First-time Linux Setup)
If running on a fresh Raspberry Pi installation, you **must** pair the ESP32 manually before running the software. The OS will block the connection otherwise. Ensure the ESP32 is powered on, then run:

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

### Post-Processing (Paper Methodology)
To apply the exact Digital Signal Processing (DSP) steps described in the published paper (6th-order Butterworth low-pass filter at 10 Hz, followed by a Hilbert transform for amplitude envelope), run the standalone post-processing script:

**On Linux / Raspberry Pi:**
```bash
./venv/bin/python scripts/post_process_emg.py
```

**On Windows:**
```powershell
.\venv\Scripts\python.exe scripts\post_process_emg.py
```

The script will automatically find the latest saved CSV in `sessions/`, generate a `_processed.csv` file with the mathematically filtered data, and open a PyQtGraph window so you can visually compare the raw hardware signal against the published filters.

---

## Configuration (`config.yaml`)

Hardware specifications are defined in the `config.yaml` file.

---

## Repository Structure

```text
real-time-cop-jointangle-emg-system/
├── CITATION.cff              # Academic citation metadata
├── LICENSE                   # MIT License
├── README.md                 # Setup, usage and troubleshooting guide
├── config.yaml               # Hardware configuration parameters
├── setup.sh                  # Micromamba installer script (Linux)
├── setup.ps1                 # uv installer script (Windows)
├── esp32_firmware/           # ESP32 Arduino sketches
│   ├── README.md             # Firmware docs & Core version warning
│   └── emg_simulator/        # Synthetic EMG signal generator for testing
├── hardware/
│   └── 3d_prints/
│       └── camera_enclosure/ # 3D printable STL files for camera mount
└── acquisition_systems/
    ├── app_gui.py            # Main GUI script
    ├── recorder.py           # CSV export module
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
* **Camera Initialization:** Modify the `cam_index` parameter in `config.yaml` (index 0 typically corresponds to the integrated webcam).
* **EMG Simulator Firmware:** An EMG simulator sketch is provided in `esp32_firmware/emg_simulator/` for testing the GUI without real EMG hardware. See [`esp32_firmware/README.md`](esp32_firmware/README.md) for details.