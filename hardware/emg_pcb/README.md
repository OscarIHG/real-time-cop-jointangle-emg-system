# PCB del módulo sEMG (ESP32 + AD8232)

Especificación de diseño de la PCB que reemplaza el módulo sEMG del prototipo descrito en el paper (Sec. 3.2, *Electromyography System*). Este documento define **qué debe hacer el circuito y con qué valores**. El esquemático y el ruteo se hacen en la herramienta EDA que prefieras (KiCad recomendado) siguiendo estas secciones.

> **Aviso de seguridad.** Este dispositivo se conecta a una persona mediante electrodos. Debe funcionar **solo con batería** y **nunca** estar conectado a la red eléctrica ni a una computadora conectada a la red mientras los electrodos están puestos. Durante la carga por USB-C los electrodos deben estar desconectados. No es un dispositivo médico.

---

## 1. Contexto y requisitos

### 1.1 Lo que dice el paper

> "The surface electromyography (sEMG) system is based on an AD8832 module. This module provides the necessary signal conditioning, including preamplification, rectification, smoothing, and amplification. Surface electrodes were connected to the module via a 3.5 mm connector. The resulting analog signal was digitized by an ESP32 microprocessor and transmitted wirelessly to the Raspberry Pi via Bluetooth. The entire portable unit was powered by two 9V batteries, providing a ±9V DC supply."

### 1.2 Sobre el número de parte "AD8832"

**No existe un circuito integrado AD8832.** Los distribuidores no lo listan. El chip que corresponde a la descripción (front-end de biopotencial de Analog Devices, alimentación sencilla, conector de electrodos de 3.5 mm en los módulos comerciales) es el **AD8232**. Esta PCB usa el **AD8232ACPZ** (LFCSP-20, 4 × 4 mm).

El AD8232 hace la **preamplificación** (amplificador de instrumentación) y el **filtrado**, pero **no rectifica ni suaviza**: su salida es la señal bipolar centrada en la referencia. Para obtener la envolvente que describe el paper, esta PCB agrega una **etapa de envolvente** (rectificador de onda completa + pasa-bajas de suavizado) después del AD8232. La alimentación de ±9 V del prototipo se sustituye por una **batería LiPo de una celda**, porque toda la cadena funciona con una sola fuente de 3.3 V.

### 1.3 Requisitos del sistema

Estos valores vienen del software del repositorio y no deben cambiar sin actualizarlo:

| Parámetro | Valor | Dónde se usa |
|---|---|---|
| Salida al ADC | Envolvente unipolar, **0 – 3.3 V** | `emg_vmin`/`emg_vmax` en `config.yaml` |
| Frecuencia de muestreo | **100 Hz** (timer de hardware) | `SAMPLE_RATE_HZ` del firmware, `emg_sample_rate_hz` |
| Pin del ADC | **GPIO36 (VP / ADC1_CH0)** = `A0` en el firmware | `emgPin` en `esp32_firmware.ino` |
| Enlace | Bluetooth Classic SPP, una línea `0.1234\r\n` por muestra | `workers/emg.py` |
| Notch de 60 Hz | En software (FFT, alias de 40 Hz a 100 Hz) | `common/dsp.py` |

> **Por qué importa el anti-aliasing (pendiente #12).** A 100 Hz la frecuencia de Nyquist es 50 Hz: **cualquier** componente arriba de 50 Hz que llegue al ADC se pliega sobre la banda útil. El notch por software solo elimina el alias de 60 Hz (en 40 Hz), no el resto del ruido. Por eso el pasa-bajas de suavizado (§3.4) **es también el filtro anti-aliasing**: debe atenuar al menos 40 dB en 50 Hz.

---

## 2. Diagrama de bloques

```text
 Electrodos ─ Jack 3.5 mm ─► Protección ─► AD8232 ─────────────► Rectificador ─► Pasa-bajas ─► ESP32
 (RA, LA, RL)               de entrada    in-amp G=100         de onda          4.º orden     GPIO36 (ADC)
                            (R + ESD)     HPF 20 Hz            completa         Butterworth       │
                                          op-amp G=10          (op-amp)         fc = 10 Hz        │
                                          LPF 450 Hz                            (anti-aliasing)   │
                                          RLD → electrodo RL                                       │
                                          LO+/LO- ───────────────────────────────────────────────► GPIO34/35
                                                                                                   │
 LiPo 1S ─► Cargador USB-C ─► Interruptor ─► LDO 3.3 V ───────► AD8232, op-amps, ESP32          Bluetooth
 3.7 V      (TP4056 o MCP73831)             (bajo ruido)                                       SPP ─► RPi
```

---

## 3. Bloques del circuito

### 3.1 Entrada de electrodos y protección

- **Conector:** jack de audio **TRS de 3.5 mm** de montaje en PCB (por ejemplo, CUI SJ1-3523N), compatible con los cables de 3 derivaciones de los módulos AD8232 comerciales:
  - **Punta** = RA (electrodo activo 1)
  - **Anillo** = LA (electrodo activo 2)
  - **Manga** = RL (referencia / pierna derecha)
- **Resistencias de protección:** **10 kΩ** en serie en cada entrada (IN+, IN−), lo más cerca posible del jack. Limitan la corriente hacia el sujeto ante una falla y protegen el chip.
- **ESD:** un arreglo de diodos TVS de baja capacitancia (por ejemplo, TPD3E001 o ESD9B3.3) en las tres líneas, referido a GND.
- **Polarización de entrada (DC leads-off):** dos resistencias de **10 MΩ**, de IN+ y de IN− hacia la referencia, como en el modo de detección DC de la hoja de datos.

### 3.2 AD8232: preamplificación y filtrado

La configuración de la hoja de datos para ECG se ajusta a la banda del sEMG abdominal: **20 – 450 Hz**. El corte de 20 Hz elimina artefactos de movimiento y de respiración.

| Etapa interna del AD8232 | Configuración | Valor |
|---|---|---|
| Amplificador de instrumentación | Ganancia fija | **G = 100** |
| Filtro pasa-altas (HPF) | 2 polos con R/C externos | **fc ≈ 20 Hz** (por ejemplo, R = 100 kΩ, C = 82 nF → 19.4 Hz) |
| Amplificador operacional integrado | Ganancia + pasa-bajas Sallen-Key | **G = 10**, **fc ≈ 450 Hz** |
| Ganancia total | 100 × 10 | **1000** (2 mV pico → 2 V pico) |
| Referencia (REFIN / REFOUT) | Divisor + buffer interno | **VREF = 1.65 V** (mitad de 3.3 V) |
| Right-Leg Drive (RLD) | Hacia el electrodo RL por **360 kΩ** | Reduce el ruido de modo común (60 Hz) |
| Detección de electrodo suelto | Modo DC: salidas LO+ / LO− | A GPIO34 / GPIO35 del ESP32 |
| SDN | Controlado por GPIO del ESP32 | Apaga el AD8232 cuando no se transmite |
| FR / AC/DC | Según la tabla de la hoja de datos | Recuperación rápida activada; DC leads-off |

> Antes de cerrar los valores, usa la herramienta de diseño de filtros de Analog Devices para el AD8232 (*AD8232 Filter Design Tool*). Los valores de esta tabla son el punto de partida y deben ajustarse con ella.

La amplitud del sEMG abdominal en superficie va de decenas de µV a unos pocos mV. Con G = 1000, una contracción de 2 mV pico da 2 V pico alrededor de 1.65 V. Si en las pruebas la señal satura, baja la ganancia del op-amp interno a **G = 5** (ganancia total 500).

### 3.3 Rectificador de onda completa (precisión)

Convierte la señal bipolar (centrada en VREF = 1.65 V) en su valor absoluto respecto a VREF. Usa un **rectificador de precisión con op-amp** (no diodos solos, porque su caída de ~0.6 V borraría la señal pequeña).

- **Op-amp:** rail-to-rail de entrada y salida, a 3.3 V, de bajo ruido. Por ejemplo, **MCP6002** (doble) o **OPA2333** (doble, cero deriva).
- **Topología:** rectificador de onda completa de precisión de dos op-amps, referido a VREF, con diodos Schottky de señal (BAT54S).
- **Salida:** |señal − VREF|, entre **0 V** y **~1.65 V**. Si se requiere usar todo el rango del ADC, agrega una ganancia de ×1.8 en la etapa siguiente.

### 3.4 Pasa-bajas de suavizado = filtro anti-aliasing

Obtiene la envolvente (nivel de activación) y además cumple la función anti-aliasing del #12.

- **Filtro:** Butterworth de **4.º orden**, como dos etapas Sallen-Key de ganancia unitaria en cascada.
- **Corte:** **fc = 10 Hz**, igual al Butterworth de 10 Hz del post-proceso del paper.
- **Atenuación calculada:** **−56 dB en 50 Hz** (Nyquist) y **−62 dB en 60 Hz**. Con eso no queda nada que pueda plegarse.
- **Valores por etapa** (Q = 0.707): R1 = R2 = **100 kΩ**, C1 (realimentación) = **220 nF**, C2 (a tierra) = **110 nF** (en la práctica, 100 nF + 10 nF en paralelo). Con esos valores fc ≈ 10.2 Hz.
- **Capacitores:** C0G/NP0 o de película (no X7R, cuya capacitancia cambia con el voltaje y la temperatura).
- **Salida al ADC:** a **GPIO36** a través de **1 kΩ**, con **100 nF** a GND junto al pin del ESP32 (amortigua la carga de muestreo del ADC).

> Si en el futuro se quiere filtrar en software en lugar de hacerlo en la placa, se puede subir el muestreo a 1 kHz en el ESP32 y diezmar a 100 Hz antes de transmitir. En ese caso este filtro puede relajarse, pero entonces hay que cambiar el firmware. La PCB, tal como se especifica aquí, funciona **con el firmware actual sin cambios**.

### 3.5 Alimentación

| Bloque | Componente sugerido | Notas |
|---|---|---|
| Batería | LiPo **1S, 3.7 V, ≥ 1000 mAh**, con circuito de protección | Conector JST-PH de 2 pines |
| Cargador | **MCP73831** o **TP4056** (500 mA) + USB-C solo para alimentación | LED de carga. **Carga solo con los electrodos desconectados** |
| Interruptor | Deslizable en serie con la batería | Corta toda la placa |
| Regulador | LDO de **bajo ruido** de 3.3 V y ≥ 500 mA: **AP2112K-3.3** o **TLV75533** | El ESP32 tiene picos de ~350 mA al transmitir por radio |
| Desacoplo | 10 µF + 100 nF en la salida del LDO; 100 nF en cada pin de alimentación de los chips | |
| Medición de batería | Divisor 100 kΩ / 100 kΩ a **GPIO39** (ADC1) | Opcional; permite reportar la carga |

Consumo estimado: ESP32 con Bluetooth activo, ~80-130 mA en promedio; AD8232, ~170 µA; op-amps, ~1 mA. Con 1000 mAh la autonomía es de **unas 8-10 horas**.

**Separación analógica / digital:**
- Plano de tierra continuo.
- La parte analógica (jack, AD8232, op-amps) va lejos de la antena del ESP32 y del regulador.
- Alimenta la parte analógica a través de una **ferrita** (por ejemplo, BLM18PG) con su propio desacoplo, desde la misma salida de 3.3 V.

### 3.6 ESP32-WROOM-32E

- **Módulo:** **ESP32-WROOM-32E** (4 MB de flash), con antena de PCB. Bajo la antena no debe haber cobre en ninguna capa, y el área debe quedar sobre el borde de la placa.
- **Programación por USB:**
  - Convertidor USB-serial **CH340C** o **CP2102N** en el mismo conector USB-C del cargador.
  - **Circuito de auto-reset**: dos transistores NPN (MMBT3904) que controlan EN y GPIO0 desde DTR/RTS, como en las placas DevKit.
  - Así se flashea con `arduino-cli upload` sin presionar botones.
- **Botones:** **EN (reset)** y **BOOT (GPIO0)**, para flashear manualmente si el auto-reset falla.
- **Pines de arranque (strapping):** no uses GPIO0, 2, 12 ni 15 para señales que puedan estar en un nivel fijo al encender. **GPIO12 debe estar en bajo al arrancar** (si no, el módulo arranca con el voltaje de flash incorrecto).
- **ADC:** usa solo pines del **ADC1** (GPIO32-39). El ADC2 no funciona mientras el radio está activo.

**Asignación de pines:**

| GPIO | Función | Notas |
|---|---|---|
| 36 (VP) | Envolvente sEMG (ADC1_CH0) | `emgPin = A0` en el firmware actual |
| 39 (VN) | Voltaje de la batería (ADC1_CH3) | Opcional |
| 34 | LO+ del AD8232 | Solo entrada |
| 35 | LO− del AD8232 | Solo entrada |
| 25 | SDN del AD8232 | Salida; en alto = activo |
| 2 | LED de estado | Mismo LED que usa el firmware (`ledPin = 2`) |
| 1 / 3 | TX0 / RX0 al USB-serial | Programación y consola |
| EN / 0 | Auto-reset y BOOT | Vía DTR/RTS |

---

## 4. Consideraciones de ruteo

- **Placa de 2 capas** como mínimo, con el plano de tierra completo en la capa inferior. 4 capas si el presupuesto lo permite.
- **Entradas diferenciales (IN+ / IN−):** pistas cortas, paralelas y de la misma longitud, del jack al AD8232, para no convertir el ruido de modo común en diferencial.
- **Lejos de la antena del ESP32:** el AD8232 y el filtro van en el extremo opuesto de la placa.
- **Nodos de alta impedancia** (entradas de 10 MΩ y filtros de 100 kΩ): sin pistas digitales cerca y, de preferencia, con un anillo de guarda a VREF.
- **Puntos de prueba** en VREF, la salida del AD8232, la salida del rectificador, la salida del filtro (entrada del ADC), 3.3 V y VBAT.
- **Orificios de montaje** M3 en las esquinas, para una carcasa impresa en 3D.

---

## 5. Firmware

`esp32_firmware/esp32_firmware.ino` ya está listo para esta placa:

1. Cambia `#define EMG_SIMULATED 1` a **`0`**. El firmware lee GPIO36 con `analogReadMilliVolts`, la lectura calibrada de fábrica del ESP32.
2. Compila con el **ESP32 Arduino Core 2.0.17**: con el core 3.x falla el Bluetooth SPP.
3. Con la PCB conectada por USB-C a la Raspberry Pi:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 esp32_firmware
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/ttyUSB0 esp32_firmware   # CH340/CP2102 usually appear as ttyUSB0
```

**Pendientes de firmware para cuando la placa exista** (no son necesarios para el primer encendido):
- Leer LO+ / LO− y reportar "electrodo suelto" (por ejemplo, enviando `NaN`, que el receptor ya rechaza).
- Usar SDN para apagar el AD8232 cuando no se está transmitiendo.
- Reportar el voltaje de la batería.

---

## 6. Plan de pruebas de la PCB

Realiza las pruebas en orden. **Sin electrodos en una persona hasta pasar las pruebas 1-5.**

| # | Prueba | Cómo | Criterio de aceptación |
|---|---|---|---|
| 1 | Alimentación | Batería conectada, interruptor encendido, sin ESP32 programado | 3.3 V ± 3 % en el LDO; VREF = 1.65 V ± 2 % |
| 2 | Programación | Flashear por USB-C con `arduino-cli upload` | Flasheo sin presionar botones; el LED parpadea |
| 3 | Respuesta en frecuencia | Generador de funciones a la entrada (con un divisor a ~1 mV): barrido de 5 a 500 Hz | Banda de paso de 20-450 Hz en la salida del AD8232; ganancia ≈ 1000 |
| 4 | Envolvente y anti-aliasing | Seno de 1 mV a 80 Hz con modulación AM lenta; luego un tono de 50 Hz | La salida sigue la modulación; el tono de 50 Hz queda atenuado ≥ 40 dB en el ADC |
| 5 | Ruido en reposo | Entradas en corto con la referencia | Ruido en el ADC < 10 mV pico a pico |
| 6 | Enlace con la RPi | `scripts/hw_benchmark.py emg --source bluetooth` | ≈ 100 Hz, 0 errores de parseo, `source=bluetooth` |
| 7 | Señal real | Electrodos en el recto abdominal, a ~3 cm de la línea media del ombligo (protocolo del paper, Sec. 3.5): reposo y luego contracción | Tono basal bajo; ráfagas claras al contraer; el electrodo suelto se detecta |
| 8 | Sistema completo | GUI + plataforma + cámara, grabación de 20 s | La señal sEMG aparece en la GUI y en `_emg.csv`; post-proceso sin errores |

Al pasar todas: en `config.yaml` deja `emg_source: bluetooth` (o `auto`) y la `emg_mac` de la PCB.

---

## 7. Lista de materiales (BOM) preliminar

| Cant. | Referencia | Componente | Ejemplo |
|---|---|---|---|
| 1 | U1 | Front-end de biopotencial | **AD8232ACPZ** (LFCSP-20) |
| 1 | U2 | Op-amp doble rail-to-rail (rectificador) | MCP6002 / OPA2333 |
| 1 | U3 | Op-amp doble rail-to-rail (filtro de 4.º orden) | MCP6002 / OPA2333 |
| 1 | U4 | Módulo Wi-Fi/BT | **ESP32-WROOM-32E** (4 MB) |
| 1 | U5 | Regulador LDO 3.3 V, ≥ 500 mA, bajo ruido | AP2112K-3.3 / TLV75533 |
| 1 | U6 | Cargador LiPo | MCP73831 / TP4056 |
| 1 | U7 | USB-serial | CH340C / CP2102N |
| 1 | U8 | Protección ESD (3 líneas) | TPD3E001 |
| 2 | Q1, Q2 | NPN para auto-reset | MMBT3904 |
| 2 | D1, D2 | Schottky de señal (rectificador) | BAT54S |
| 1 | J1 | Jack TRS 3.5 mm para PCB | CUI SJ1-3523N |
| 1 | J2 | USB-C (solo alimentación y datos USB 2.0) | Receptáculo de 16 pines |
| 1 | J3 | Conector de batería | JST-PH 2 pines |
| 1 | SW1 | Interruptor deslizable | — |
| 2 | SW2, SW3 | Pulsadores EN / BOOT | — |
| 1 | FB1 | Ferrita para la alimentación analógica | BLM18PG221 |
| 1 | BT1 | Batería LiPo 1S ≥ 1000 mAh con protección | — |
| — | — | Resistencias 1 %, capacitores C0G en el filtro, desacoplos X7R | Según §3 |
| 1 juego | — | Cable de 3 derivaciones con plug de 3.5 mm + electrodos Ag/AgCl desechables | — |

---

## 8. Entregables del diseño

- [ ] Esquemático (KiCad) con todos los bloques de §3.
- [ ] Simulación de los filtros (LTspice o la herramienta de Analog Devices), con respuesta 20-450 Hz y −40 dB o más en 50 Hz en la entrada del ADC.
- [ ] Ruteo de la PCB siguiendo §4, con revisión DRC.
- [ ] BOM final con números de parte de un distribuidor.
- [ ] Archivos Gerber + archivo de posiciones (si se va a ensamblar).
- [ ] Pruebas 1-8 de §6 documentadas.
- [ ] Actualizar este documento con los valores finales y fotos de la placa.
