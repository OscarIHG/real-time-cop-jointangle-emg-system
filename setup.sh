#!/bin/bash

# =============================================================================
# AUTOMATED SETUP - REAL-TIME COP-JOINTANGLE-EMG SYSTEM
# Optimized for Raspberry Pi 4 (Uses Micromamba for Python 3.11 compatibility)
# =============================================================================

set -euo pipefail

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
    PHIDGETS_INSTALLER_URL="https://www.phidgets.com/downloads/setup_linux"
    PHIDGETS_INSTALLER_SHA256="${PHIDGETS_INSTALLER_SHA256:-}"
    if [ -z "$PHIDGETS_INSTALLER_SHA256" ]; then
        print_error "Set PHIDGETS_INSTALLER_SHA256 to the vendor-published SHA-256 before running setup."
        exit 1
    fi
    installer="$(mktemp)"
    trap 'rm -f "$installer"' EXIT
    curl --fail --location --proto '=https' --tlsv1.2 \
        --output "$installer" "$PHIDGETS_INSTALLER_URL"
    echo "$PHIDGETS_INSTALLER_SHA256  $installer" | sha256sum --check --status
    sudo bash "$installer"
    sudo apt-get install -y libphidget22
else
    print_status "SKIPPING: libphidget22 already installed."
fi

# Configure USB permissions for Phidget Force Plate
# Restrict access to the plugdev group instead of making the device
# world-writable. The setup user is added to the group below.
print_status "CONFIGURING: USB udev rules for Phidgets..."
sudo groupadd --force plugdev
sudo usermod -aG plugdev "$USER"
echo 'SUBSYSTEMS=="usb", ACTION=="add", ATTRS{idVendor}=="06c2", ATTRS{idProduct}=="00[3-a][0-f]", GROUP="plugdev", MODE="0660"' \
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
MICROMAMBA_URL="${MICROMAMBA_URL:-https://micro.mamba.pm/api/micromamba/linux-aarch64/latest}"
MICROMAMBA_SHA256="${MICROMAMBA_SHA256:-}"
if [ -z "$MICROMAMBA_SHA256" ]; then
    print_error "Set MICROMAMBA_SHA256 to the vendor-published SHA-256 before running setup."
    exit 1
fi
micromamba_archive="$(mktemp)"
curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$micromamba_archive" "$MICROMAMBA_URL"
echo "$MICROMAMBA_SHA256  $micromamba_archive" | sha256sum --check --status
mkdir -p bin
tar -xvjf "$micromamba_archive" -C . bin/micromamba
rm -f "$micromamba_archive"

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