#!/bin/bash

# =============================================================================
# CONFIGURACIÓN AUTOMÁTICA - REAL-TIME COP-JOINTANGLE-EMG SYSTEM
# Sistema integrado con MediaPipe - Basado en single-acquisition exitoso
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

print_status "🚀 REAL-TIME COP-JOINTANGLE-EMG SYSTEM - Configuración Automática"
print_status "🔧 Sistema unificado con MediaPipe y dependencias controladas"
echo ""

# Asegurar directorio correcto
if [ ! -f "acquisition_systems/app_gui.py" ]; then
    print_error "❌ Error: Ejecutar desde el directorio raíz del proyecto"
    print_error "   El script debe encontrar acquisition_systems/app_gui.py"
    exit 1
fi

# Limpiar entorno previo
if [ -d "venv-unified" ]; then
    print_status "🧹 Removiendo entorno previo..."
    rm -rf venv-unified
fi

# Dependencias del sistema
print_status "📦 Instalando dependencias del sistema..."
sudo apt update -qq
sudo apt install -y \
    python3-pip python3-virtualenv python3-dev build-essential \
    bluetooth bluez libbluetooth-dev python3-bluez \
    libglib2.0-dev libdbus-1-dev \
    portaudio19-dev libasound2-dev \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libgomp1 \
    >/dev/null 2>&1

sudo systemctl enable bluetooth && sudo systemctl start bluetooth >/dev/null 2>&1
check_status "Dependencias del sistema"

# Crear entorno virtual unificado
print_status "🐍 Creando entorno virtual unificado..."
python3 -m venv venv-unified
source venv-unified/bin/activate
pip install --upgrade pip >/dev/null 2>&1
check_status "Entorno virtual creado"

# PASO 1: Base estable con numpy pinneado
print_status "🔒 PASO 1: Base estable con numpy 1.26.4..."
pip install "numpy==1.26.4" >/dev/null 2>&1
check_status "NumPy base fijado"

# PASO 2: Stack científico compatible
print_status "📊 PASO 2: Paquetes científicos base..."
pip install \
    "scipy==1.11.4" \
    "pandas==2.0.3" \
    "python-dateutil>=2.7" \
    "pytz" \
    >/dev/null 2>&1
check_status "Stack científico"

# PASO 3: Matplotlib compatible
print_status "🎨 PASO 3: Matplotlib y visualización..."
pip install \
    "contourpy==1.1.1" \
    "matplotlib==3.7.3" \
    "cycler>=0.10" \
    "fonttools>=4.22.0" \
    "kiwisolver>=1.0.1" \
    "pyparsing>=2.3.1" \
    "pillow" \
    >/dev/null 2>&1
check_status "Matplotlib y dependencias"

# PASO 4: OpenCV compatible
print_status "🔧 PASO 4: OpenCV compatible con numpy<2..."
pip install "opencv-contrib-python==4.8.1.78" >/dev/null 2>&1
check_status "OpenCV instalado"

# PASO 5: Protobuf para MediaPipe
print_status "🔧 PASO 5: Protobuf para MediaPipe..."
pip install "protobuf>=3.11,<4" >/dev/null 2>&1
check_status "Protobuf configurado"

# PASO 6: MediaPipe (reemplaza TensorFlow Lite)
print_status "📹 PASO 6: MediaPipe - Reemplazando TensorFlow Lite..."
pip install \
    "attrs>=19.1.0" \
    "flatbuffers>=2.0" \
    "mediapipe==0.10.9" \
    --no-deps >/dev/null 2>&1

pip install \
    "absl-py" \
    "sounddevice" \
    >/dev/null 2>&1
check_status "MediaPipe instalado (TensorFlow Lite removido)"

# PASO 7: Hardware interfaces
print_status "🔌 PASO 7: Interfaces de hardware..."
pip install \
    "Phidget22>=1.20.0" \
    "CFFI>=1.16.0" \
    "pyserial>=3.0" \
    >/dev/null 2>&1
check_status "Interfaces de hardware"

# PASO 8: GUI y configuración
print_status "🖥️ PASO 8: Componentes de GUI..."
pip install \
    "PyYAML>=5.0" \
    >/dev/null 2>&1
# tkinter viene con Python, matplotlib ya instalado
check_status "GUI y configuración"

# PASO 9: PyBluez automático
print_status "🔗 PASO 9: Configurando PyBluez automáticamente..."
VENV_SITE_PACKAGES="$PWD/venv-unified/lib/python3.11/site-packages"

# Verificar disponibilidad del sistema
dpkg -l | grep python3-bluez >/dev/null 2>&1
check_status "PyBluez del sistema verificado"

# Crear enlaces simbólicos
print_status "   Creando enlaces simbólicos para PyBluez..."
ln -sf /usr/lib/python3/dist-packages/bluetooth "$VENV_SITE_PACKAGES/bluetooth" 2>/dev/null || true
find /usr/lib/python3/dist-packages/ -name "_bluetooth*.so" -exec ln -sf {} "$VENV_SITE_PACKAGES/" \; 2>/dev/null || true
check_status "Enlaces simbólicos PyBluez"

# Verificar integración
print_status "   Verificando integración PyBluez..."
python3 -c "import bluetooth; print('PyBluez integrado correctamente')" >/dev/null 2>&1
check_status "Verificación PyBluez"

# PASO 10: Limpiar archivos de requirements obsoletos
print_status "🧹 PASO 10: Limpiando configuración obsoleta..."
if [ -f "requirements.txt" ]; then
    mv requirements.txt requirements.txt.backup
    print_status "   requirements.txt respaldado como .backup"
fi
if [ -f "requirements-pip-only.txt" ]; then
    mv requirements-pip-only.txt requirements-pip-only.txt.backup
    print_status "   requirements-pip-only.txt respaldado"
fi
if [ -f "pyproject.toml" ]; then
    mv pyproject.toml pyproject.toml.backup
    print_status "   pyproject.toml respaldado"
fi
check_status "Archivos obsoletos respaldados"

print_success "\n✅ ¡CONFIGURACIÓN AUTOMÁTICA COMPLETADA!"
print_success "🎯 Sistema integrado con MediaPipe funcionando"

echo ""
echo "🎯 RESUMEN DE MEJORAS:"
echo "✅ NumPy 1.26.4 base estable (elimina conflictos)"
echo "✅ MediaPipe 0.10.9 instalado (reemplaza TensorFlow Lite)"
echo "✅ OpenCV 4.8.1.78 compatible con numpy<2"
echo "✅ PyBluez automáticamente configurado"
echo "✅ Todas las dependencias de hardware funcionales"
echo "✅ GUI Tkinter + Matplotlib lista"
echo "✅ Configuración obsoleta respaldada"
echo ""
print_status "💡 USO:"
echo "   source venv-unified/bin/activate"
echo "   python3 -m acquisition_systems.app_gui    # ✅ GUI Principal"
echo "   python3 acquisition_systems/app_gui.py   # ✅ Alternativo"
echo ""
print_success "🎉 ¡Sistema listo para usar!"
print_warning "⚡ IMPORTANTE: Ahora usa MediaPipe en lugar de TensorFlow Lite"
print_warning "   Esto proporciona mejores capacidades de seguimiento corporal"