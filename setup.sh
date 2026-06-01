#!/bin/bash

# =============================================================================
# AUTOMATED SETUP - REAL-TIME COP-JOINTANGLE-EMG SYSTEM
# Optimized for Raspberry Pi 4 (Uses Micromamba for Python 3.11 compatibility)
# =============================================================================

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m' 
BLUE='\033[0;34m'
NC='\033[0m'

print_status() { echo -e "${BLUE}$1${NC}"; }
print_success() { echo -e "${GREEN}$1${NC}"; }
print_error() { echo -e "${RED}$1${NC}"; }

print_status "STARTING REAL-TIME COP-JOINTANGLE-EMG SYSTEM SETUP"

# System dependencies for OpenCV and hardware
print_status "INSTALLING: System dependencies (sudo required)..."
sudo apt update -qq
sudo apt install -y \
    build-essential curl bzip2 \
    libbluetooth-dev \
    libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1

# Install Phidget22 system library (required for the Python package to communicate with hardware)
print_status "INSTALLING: Phidget22 system library..."
if ! dpkg -l | grep -q libphidget22; then
    curl -fsSL https://www.phidgets.com/downloads/setup_linux | sudo -E bash -
    sudo apt-get install -y libphidget22
else
    print_status "SKIPPING: libphidget22 already installed."
fi

# Configure USB permissions for Phidget Force Plate
# Rule grants read/write access to all Phidgets USB devices for all users (MODE=666)
print_status "CONFIGURING: USB udev rules for Phidgets..."
echo 'SUBSYSTEMS=="usb", ACTION=="add", ATTRS{idVendor}=="06c2", ATTRS{idProduct}=="00[3-a][0-f]", MODE="666"' \
    | sudo tee /etc/udev/rules.d/99-libphidget22.rules > /dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger

# Enable Bluetooth Classic Serial Port Profile (SPP/RFCOMM) required by ESP32
# Uses a systemd drop-in override to safely add --compat without modifying the
# original bluetooth.service file.
print_status "CONFIGURING: Enabling Bluetooth Classic SPP profile for ESP32..."
OVERRIDE_DIR="/etc/systemd/system/bluetooth.service.d"
OVERRIDE_FILE="$OVERRIDE_DIR/compat.conf"
if [ ! -f "$OVERRIDE_FILE" ]; then
    sudo mkdir -p "$OVERRIDE_DIR"
    printf '[Service]\nExecStart=\nExecStart=/usr/libexec/bluetooth/bluetoothd --compat\n' \
        | sudo tee "$OVERRIDE_FILE" > /dev/null
    sudo systemctl daemon-reload
    sudo systemctl restart bluetooth
    print_status "Bluetooth SPP profile enabled."
else
    print_status "SKIPPING: Bluetooth SPP profile already configured."
fi

# Clean previous environment
if [ -d "venv" ]; then
    print_status "CLEANING: Removing previous venv..."
    rm -rf venv
fi

if [ -d "bin" ]; then
    rm -rf bin
fi

# Download Micromamba (standalone package manager to get Python 3.11 without compiling)
print_status "DOWNLOADING: Micromamba (to get precompiled Python 3.11)..."
curl -Ls https://micro.mamba.pm/api/micromamba/linux-aarch64/latest | tar -xvj bin/micromamba

# Create local environment
print_status "PYTHON: Creating self-contained Python 3.11 environment..."
export MAMBA_ROOT_PREFIX=$(pwd)/.mamba_root
./bin/micromamba create -p ./venv -c conda-forge python=3.11 tk pyqt pyqtgraph -y

print_status "PYTHON: Upgrading pip and installing requirements..."
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.txt

print_success "\nSUCCESS: AUTOMATED SETUP COMPLETED!"
print_status "To run the application:"
echo "   ./venv/bin/python -m acquisition_systems.app_gui"
echo ""