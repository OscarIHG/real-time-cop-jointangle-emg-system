# Real-Time CoP-JointAngle-EMG System

**Sistema integrado para medición en tiempo real de Centro de Presión, Ángulos Articulares y EMG Abdominal**

## 🎯 Mejoras Implementadas

Este repositorio ha sido **completamente optimizado** basado en la infraestructura exitosa de `single-acquisition`:

### ✅ **Problemas Resueltos**
- **✅ Dependencias no reproducibles** → Sistema de configuración automática
- **✅ Conflictos de NumPy** → Versiones específicas compatibles
- **✅ TensorFlow Lite limitado** → **Reemplazado con MediaPipe** 🚀
- **✅ PyBluez problemas** → Configuración automática con enlaces simbólicos
- **✅ Setup manual complejo** → **Un solo comando**: `./setup.sh`

### 🚀 **Nuevas Capacidades**
- **MediaPipe**: Seguimiento corporal superior con 33 puntos de referencia
- **GUI Unificada**: Todas las funcionalidades en una sola interfaz
- **Estabilidad**: Sin conflictos de dependencias
- **Reproducíble**: Setup automático garantizado

---

## 🛠️ Instalación Rápida

**Un solo comando y listo:**

```bash
# Clonar el repositorio
git clone https://github.com/OscarIHG/real-time-cop-jointangle-emg-system.git
cd real-time-cop-jointangle-emg-system

# Configuración automática (TODO EN UNO)
chmod +x setup.sh
./setup.sh
```

**¡Eso es todo!** El script:
- Instala dependencias del sistema
- Crea entorno virtual optimizado
- Configura MediaPipe
- Resuelve conflictos automáticamente
- Configura PyBluez

---

## 🖥️ Uso del Sistema

### Iniciar la GUI Principal
```bash
# Activar entorno
source venv-unified/bin/activate

# Ejecutar GUI integrada
python3 -m acquisition_systems.app_gui
```

### Funcionalidades Disponibles
- **📊 EMG Abdominal**: Adquisición vía Bluetooth (ESP32)
- **⚖️ Centro de Presión**: Plataforma de fuerza (Phidget)
- **🦴 Seguimiento Corporal**: MediaPipe pose estimation 
- **📐 Ángulos Articulares**: Cálculo automático de oblicuidad pélvica
- **💾 Grabación**: Export CSV sincronizado

---

## 🔧 Configuración

Editar `config.yaml` para:

```yaml
# MediaPipe (NUEVO - Reemplaza TensorFlow Lite)
mediapipe_model_complexity: 1      # 0=Rápido, 1=Balanceado, 2=Preciso
mediapipe_min_detection_confidence: 0.5
mediapipe_min_tracking_confidence: 0.5

# Hardware
emg_mac: "A4:CF:12:96:8B:9E"       # MAC del ESP32
cam_index: 0                        # Cámara para pose

# Rendimiento
gui_update_interval_ms: 16          # ~60 FPS
```

---

## 📊 Diferencias Clave vs Versión Anterior

| **Aspecto** | **Anterior** | **Mejorado** |
|-------------|--------------|---------------|
| **Setup** | Manual, propenso a errores | `./setup.sh` - Un comando |
| **Dependencias** | requirements.txt conflictivos | Versiones específicas compatibles |
| **Pose Estimation** | TensorFlow Lite limitado | **MediaPipe completo** |
| **PyBluez** | Compilación manual | Enlaces simbólicos automáticos |
| **Reproducibilidad** | ⛔ Problemas frecuentes | ✅ **100% reproducible** |
| **Mantenimiento** | Múltiples archivos | Configuración centralizada |

---

## 🧠 Arquitectura del Sistema

```
real-time-cop-jointangle-emg-system/
├── setup.sh                  # 🚀 Setup automático
├── config.yaml               # ⚙️ Configuración unificada
├── requirements-unified.txt  # 📦 Dependencias controladas
└── acquisition_systems/
    ├── app_gui.py            # 🖥️ GUI principal (MediaPipe)
    ├── recorder.py           # 💾 Grabación sincronizada
    ├── common/
    │   ├── config.py         # 🔧 Carga de configuración
    │   └── runtime.py        # ⚡ Gestión de workers
    └── workers/              # 📱 EMG, CoP, Pose workers
```

---

## 🔥 Ventajas de MediaPipe vs TensorFlow Lite

### **MediaPipe (Nuevo)**
- ✅ **33 puntos de referencia** corporal
- ✅ **Seguimiento temporal** suave
- ✅ **Optimizado para tiempo real**
- ✅ **Sin compilación compleja**
- ✅ **API simple y estable**
- ✅ **Mejor precisión** de ángulos articulares

### **TensorFlow Lite (Anterior)**
- ⛔ Setup complejo
- ⛔ Dependencias conflictivas
- ⛔ Menor precisión
- ⛔ Más propenso a errores

---

## 🛡️ Solución de Problemas

### Si el setup falla:
```bash
# Limpiar y reintentar
rm -rf venv-unified
./setup.sh
```

### Si PyBluez no funciona:
```bash
# Verificar paquetes del sistema
sudo apt install python3-bluez bluetooth bluez
sudo systemctl restart bluetooth
```

### Si la cámara no funciona:
```bash
# Probar diferentes índices en config.yaml
cam_index: 0  # o 1, 2, etc.
```

---

## 🎆 Reconocimientos

Basado en la infraestructura exitosa del proyecto **single-acquisition**, que demostró cómo resolver definitivamente los conflictos de dependencias de Python en sistemas de adquisición de datos.

---

## 📝 Licencia

Este proyecto mantiene la licencia original y está optimizado para uso en investigación biomédica.

---

**⚡ ¡Sistema listo para uso en producción con MediaPipe!** ⚡