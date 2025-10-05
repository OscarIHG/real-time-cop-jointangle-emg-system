#!/bin/bash

# =============================================================================
# AUTOMATED SETUP - REAL-TIME COP-JOINTANGLE-EMG SYSTEM
# Integrated system with MediaPipe - Uses requirements.txt as source of truth
# =============================================================================

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m' 
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() { echo -e "${BLUE}$1${NC}"; }
print_success() { echo -e "${GREEN}$1${NC}"; }
print_warning() { echo -e "${YELLOW}$1${NC}"; }
print_error() { echo -e "${RED}$1${NC}"; }

check_status() {
    if [ $? -eq 0 ]; then
        print_success "✅ $1"
    else
        print_warning "⚠️ $1 (continuing...)"
    fi
}

print_status "🚀 REAL-TIME COP-JOINTANGLE-EMG SYSTEM - Automated Setup"
print_status "📋 Using requirements.txt as single source of truth"
echo ""

# Ensure correct directory
if [ ! -f "acquisition_systems/app_gui.py" ]; then
    print_error "❌ Error: Run from project root directory"
    print_error "   Script must find acquisition_systems/app_gui.py"
    exit 1
fi

# Check requirements.txt exists
if [ ! -f "requirements.txt" ]; then
    print_error "❌ Error: requirements.txt not found"
    print_error "   Make sure requirements.txt exists in project root"
    exit 1
fi

# Clean previous environment
if [ -d "venv-unified" ]; then
    print_status "🧹 Removing previous environment..."
    rm -rf venv-unified
fi

# System dependencies
print_status "📦 Installing system dependencies..."
sudo apt update -qq
sudo apt install -y \
    python3-pip python3-virtualenv python3-dev build-essential \
    bluetooth bluez libbluetooth-dev python3-bluez \
    libglib2.0-dev libdbus-1-dev \
    portaudio19-dev libasound2-dev \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libgomp1 \
    pkg-config \
    >/dev/null 2>&1

sudo systemctl enable bluetooth && sudo systemctl start bluetooth >/dev/null 2>&1
check_status "System dependencies installed"

# Create unified virtual environment
print_status "🐍 Creating unified virtual environment..."
python3 -m venv venv-unified
source venv-unified/bin/activate
pip install --upgrade pip >/dev/null 2>&1
check_status "Virtual environment created"

# CRITICAL STEP: Install numpy first to prevent conflicts
print_status "🔒 STEP 1: Installing numpy 1.26.4 first (prevents conflicts)..."
pip install "numpy==1.26.4" >/dev/null 2>&1
check_status "NumPy base installed first"

# Install all packages from requirements.txt
print_status "📋 STEP 2: Installing all packages from requirements.txt..."
pip install -r requirements.txt >/dev/null 2>&1
check_status "All requirements.txt packages installed"

# PyBluez automatic configuration
print_status "🔗 STEP 3: Configuring PyBluez automatically..."
VENV_SITE_PACKAGES="$PWD/venv-unified/lib/python3.11/site-packages"

# Verify system availability
dpkg -l | grep python3-bluez >/dev/null 2>&1
check_status "System PyBluez verified"

# Create symbolic links
print_status "   Creating symbolic links for PyBluez..."
ln -sf /usr/lib/python3/dist-packages/bluetooth "$VENV_SITE_PACKAGES/bluetooth" 2>/dev/null || true
find /usr/lib/python3/dist-packages/ -name "_bluetooth*.so" -exec ln -sf {} "$VENV_SITE_PACKAGES/" \; 2>/dev/null || true
check_status "PyBluez symbolic links created"

# Verify PyBluez integration
print_status "   Verifying PyBluez integration..."
python3 -c "import bluetooth; print('PyBluez integrated correctly')" >/dev/null 2>&1
check_status "PyBluez verification complete"

# Verify critical imports
print_status "🎯 STEP 4: Verifying critical package imports..."
python3 -c "
import mediapipe as mp
import cv2
import matplotlib.pyplot
import numpy as np
import scipy
import pandas
import bluetooth
import yaml
print(f'✅ MediaPipe {mp.__version__}')
print(f'✅ NumPy {np.__version__}')
print('✅ All critical imports successful')
" >/dev/null 2>&1
check_status "All critical packages verified"

# Backup conflicting files
print_status "🧹 STEP 5: Managing configuration files..."
if [ -f "requirements-pip-only.txt" ]; then
    mv requirements-pip-only.txt requirements-pip-only.txt.backup
    print_status "   requirements-pip-only.txt backed up"
fi
if [ -f "pyproject.toml" ]; then
    mv pyproject.toml pyproject.toml.backup
    print_status "   pyproject.toml backed up"
fi
check_status "Configuration files managed"

print_success "\n✅ AUTOMATED SETUP COMPLETED!"
print_success "📋 System using requirements.txt as single source of truth"

echo ""
echo "🎯 SETUP SUMMARY:"
echo "✅ System dependencies installed"
echo "✅ Virtual environment venv-unified created" 
echo "✅ NumPy 1.26.4 installed first (prevents conflicts)"
echo "✅ All packages from requirements.txt installed"
echo "✅ PyBluez configured automatically via system links"
echo "✅ All critical imports verified successfully"
echo "✅ MediaPipe-only system (no TensorFlow Lite conflicts)"
echo ""

print_status "💡 QUICK VERIFICATION:"
echo "   source venv-unified/bin/activate"
echo "   python3 -c 'import mediapipe, cv2, matplotlib.pyplot, bluetooth; print(\"✅ All dependencies OK\")'"
echo ""

print_status "🚀 RUN APPLICATION:"
echo "   source venv-unified/bin/activate"
echo "   python3 -m acquisition_systems.app_gui    # ✅ Recommended method"
echo "   python3 acquisition_systems/app_gui.py   # ✅ Alternative method"
echo ""

print_success "🎉 MediaPipe system ready to use!"
print_warning "⚡ ARCHITECTURE: Single source of truth"
print_warning "   - requirements.txt controls ALL package versions"
print_warning "   - setup.sh handles system dependencies + PyBluez only"  
print_warning "   - Easier maintenance and standard Python practices"
