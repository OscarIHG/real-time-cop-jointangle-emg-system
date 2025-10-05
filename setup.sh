#!/bin/bash

# =============================================================================
# AUTOMATIC CONFIGURATION - REAL-TIME COP-JOINTANGLE-EMG SYSTEM
# Integrated system with MediaPipe ONLY - Optimized and conflict-free
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

print_status "🚀 REAL-TIME COP-JOINTANGLE-EMG SYSTEM - Automatic Configuration"
print_status "🎯 Optimized system with MediaPipe ONLY - No TensorFlow Lite"
echo ""

# Ensure correct directory
if [ ! -f "acquisition_systems/app_gui.py" ]; then
    print_error "❌ Error: Run from project root directory"
    print_error "   Script must find acquisition_systems/app_gui.py"
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
sudo apt install -y \\
    python3-pip python3-virtualenv python3-dev build-essential \\
    bluetooth bluez libbluetooth-dev python3-bluez \\
    libglib2.0-dev libdbus-1-dev \\
    portaudio19-dev libasound2-dev \\
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \\
    libgomp1 \\
    pkg-config \\
    >/dev/null 2>&1

sudo systemctl enable bluetooth && sudo systemctl start bluetooth >/dev/null 2>&1
check_status "System dependencies"

# Create unified virtual environment
print_status "🐍 Creating unified virtual environment..."
python3 -m venv venv-unified
source venv-unified/bin/activate
pip install --upgrade pip >/dev/null 2>&1
check_status "Virtual environment created"

# STEP 1: Stable base with pinned numpy
print_status "🔒 STEP 1: Stable base with numpy 1.26.4..."
pip install "numpy==1.26.4" >/dev/null 2>&1
check_status "NumPy base fixed"

# STEP 2: Compatible scientific stack
print_status "📊 STEP 2: Base scientific packages..."
pip install \\
    "scipy==1.11.4" \\
    "pandas==2.0.3" \\
    "python-dateutil>=2.7" \\
    "pytz" \\
    >/dev/null 2>&1
check_status "Scientific stack"

# STEP 3: Complete matplotlib and visualization
print_status "🎨 STEP 3: Matplotlib and all its dependencies..."
pip install \\
    "contourpy==1.1.1" \\
    "cycler>=0.10" \\
    "fonttools>=4.22.0" \\
    "kiwisolver>=1.0.1" \\
    "pyparsing>=2.3.1" \\
    "pillow" \\
    >/dev/null 2>&1

pip install "matplotlib==3.7.3" >/dev/null 2>&1
check_status "Matplotlib and complete dependencies"

# STEP 4: Compatible OpenCV
print_status "🔧 STEP 4: OpenCV compatible with numpy<2..."
pip install "opencv-contrib-python==4.8.1.78" >/dev/null 2>&1
check_status "OpenCV installed"

# STEP 5: Protobuf for MediaPipe
print_status "📋 STEP 5: MediaPipe-compatible Protobuf..."
pip install "protobuf>=3.11,<4" >/dev/null 2>&1
check_status "Protobuf configured"

# STEP 6: MediaPipe dependencies
print_status "🧩 STEP 6: MediaPipe base dependencies..."
pip install \\
    "attrs>=19.1.0" \\
    "flatbuffers>=2.0" \\
    "absl-py" \\
    "sounddevice" \\
    >/dev/null 2>&1
check_status "MediaPipe dependencies"

# STEP 7: Main MediaPipe
print_status "🎥 STEP 7: MediaPipe 0.10.9 - Main functionality..."
pip install "mediapipe==0.10.9" >/dev/null 2>&1
check_status "MediaPipe installed successfully"

# STEP 8: Hardware interfaces
print_status "🔌 STEP 8: Hardware interfaces..."
pip install \\
    "Phidget22>=1.20.0" \\
    "CFFI>=1.16.0" \\
    "pyserial>=3.0" \\
    >/dev/null 2>&1
check_status "Hardware interfaces"

# STEP 9: GUI and configuration
print_status "🖥️ STEP 9: GUI and configuration components..."
pip install \\
    "PyYAML>=5.0" \\
    >/dev/null 2>&1
# tkinter comes with Python by default
check_status "GUI and configuration"

# STEP 10: Automatic PyBluez
print_status "🔗 STEP 10: Configuring PyBluez automatically..."
VENV_SITE_PACKAGES="$PWD/venv-unified/lib/python3.11/site-packages"

# Verify system availability
dpkg -l | grep python3-bluez >/dev/null 2>&1
check_status "System PyBluez verified"

# Create symbolic links
print_status "   Creating symbolic links for PyBluez..."
ln -sf /usr/lib/python3/dist-packages/bluetooth "$VENV_SITE_PACKAGES/bluetooth" 2>/dev/null || true
find /usr/lib/python3/dist-packages/ -name "_bluetooth*.so" -exec ln -sf {} "$VENV_SITE_PACKAGES/" \; 2>/dev/null || true
check_status "PyBluez symbolic links"

# Verify PyBluez integration
print_status "   Verifying PyBluez integration..."
python3 -c "import bluetooth; print('PyBluez integrated correctly')" >/dev/null 2>&1
check_status "PyBluez verification"

# STEP 11: MediaPipe verification
print_status "🎯 STEP 11: Verifying MediaPipe installation..."
python3 -c "import mediapipe as mp; print(f'MediaPipe {mp.__version__} working correctly')" >/dev/null 2>&1
check_status "Complete MediaPipe verification"

# STEP 12: Clean obsolete requirements files
print_status "🧹 STEP 12: Managing requirements files..."
if [ -f "requirements.txt" ]; then
    if grep -q "tflite-runtime" requirements.txt; then
        print_status "   Backing up requirements.txt with TensorFlow Lite..."
        mv requirements.txt requirements-with-tflite.txt.backup
        print_status "   requirements.txt with TFLite backed up as requirements-with-tflite.txt.backup"
    fi
fi
if [ -f "requirements-pip-only.txt" ]; then
    mv requirements-pip-only.txt requirements-pip-only.txt.backup
    print_status "   requirements-pip-only.txt backed up"
fi
if [ -f "pyproject.toml" ]; then
    mv pyproject.toml pyproject.toml.backup
    print_status "   pyproject.toml backed up"
fi
check_status "Obsolete files managed"

# STEP 13: Create optimized requirements.txt for MediaPipe
print_status "📝 STEP 13: Creating optimized requirements.txt..."
cat > requirements.txt << 'EOF'
# =============================================================================
# REAL-TIME COP-JOINTANGLE-EMG SYSTEM - MediaPipe ONLY
# Generated automatically by setup.sh - Do not edit manually
# =============================================================================

# CORE NUMERICAL STACK (STABLE BASE)
numpy==1.26.4
scipy==1.11.4
pandas==2.0.3
python-dateutil>=2.7
pytz

# VISUALIZATION STACK
matplotlib==3.7.3
contourpy==1.1.1
cycler>=0.10
fonttools>=4.22.0
kiwisolver>=1.0.1
pyparsing>=2.3.1
pillow

# COMPUTER VISION - MediaPipe Stack
opencv-contrib-python==4.8.1.78
mediapipe==0.10.9
attrs>=19.1.0
flatbuffers>=2.0
protobuf>=3.11,<4
absl-py
sounddevice

# HARDWARE INTERFACES
Phidget22>=1.20.0
CFFI>=1.16.0
pyserial>=3.0

# GUI AND CONFIGURATION
PyYAML>=5.0

# NOTE: PyBluez installed via system symbolic links
# NOTE: tkinter included with Python
EOF
check_status "Optimized requirements.txt created"

print_success "\n✅ AUTOMATIC CONFIGURATION COMPLETED!"
print_success "🎯 System with MediaPipe ONLY - Conflict-free"

echo ""
echo "🎯 INSTALLATION SUMMARY:"
echo "✅ NumPy 1.26.4 stable base (eliminates version conflicts)"
echo "✅ MediaPipe 0.10.9 - Complete body tracking"
echo "✅ OpenCV 4.8.1.78 compatible with numpy<2"
echo "✅ PyBluez configured automatically via system"
echo "✅ All hardware dependencies functional"
echo "✅ GUI Tkinter + Matplotlib fully functional"
echo "✅ Optimized requirements.txt generated"
echo "❌ TensorFlow Lite REMOVED - MediaPipe only"
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
print_warning "⚡ IMPORTANT: Now uses MediaPipe ONLY"
print_warning "   - No TensorFlow Lite to avoid conflicts"
print_warning "   - Better body tracking capabilities"
print_warning "   - All GUI functions available"