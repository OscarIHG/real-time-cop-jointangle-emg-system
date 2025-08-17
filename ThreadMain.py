# MONITOREO EN TIEMPO REAL DEL CENTRO DE PRESION, ÁNGULO ARTICULAR Y EMG
# ABDOMINAL PARA ANÁLISIS DIAGNÓSTICO DE PATOLOGÍAS POSTURALES
# INTEGRANTES:
# ÓSCAR IVAN HERNANDEZ GOMEZ
# JOSÉ RODRIGO QUINTERO VALDEZ
# JOSÉ CARLOS VELASCO LOPEZ

import time
import threading
import queue
import matplotlib.pyplot    as plt

from EMG       import *                     
from FP        import *
from BTracking import *

def read_emg_data(adquisicion_time):
    print('Thread EMG started')
        
    # Call fm, for gettin frequency of EMG
    socket, fm   = getfm(esp32_address)
    print('EMG Frequency: ', fm)
    
    # Time for the adquisicion
    long_muestra = fm*adquisicion_time
    print('EMG long vector data: ', long_muestra)
    
    # Adquisicion of EMG signal
#     Thread_FP    = State_FP.get(block=True)
    registro_emg = sendEMG_data(long_muestra, socket, fm)
    
    # Cierra la conexión al finalizar la adquisición
    print('Socket bluetooth close')
    socket.send("2")
    time.sleep(1) 
    socket.close()
    print('Thread EMG end')
    for i in range(50):
        State_EMG.put(False)
    
def read_fp_data():
    print('Thread FM started')
    ch0, ch1, ch2, ch3 = createCH()
    for i in range(10):
        State_FP.put(True)
    State_EMG.get(block=True)
    ch0.close()
    ch1.close()
    ch2.close()
    ch3.close()
    print('Thread FP end')
    
def read_BT_Cam(State_EMG, State_FP):
    startcamera(State_EMG, State_FP)
    
# Función para actualizar el gráfico en tiempo real
def update_plot():
    global emg_data
    # State of threads validation
    try:
        emg_data = data_queue_EMG.get(block=False)
        time.sleep(0.1)
    except queue.Empty:
        emg_data = [0]
        pass
    print(emg_data)
#     try:
#         # FP Plot update
#         data_copap = data_queue_copap.get(block=False)
#         data_copml = data_queue_copml.get(block=False)
#         fopax.plot([data_copap[-1]],[data_copml[-1]])
#         plt.pause(0.01)  # Actualiza el gráfico cada 10 ms
#     except queue.Empty:
#         pass
    
#     try:
#         State_Main = State_EMG.get(block=False)
#         if State_Main == False:
#             State_MainLay = False
#     except queue.Empty:
#         pass
     
    return emg_data

# Función que representa el temporizador
def temp_func():
    print('Timer start')
    time.sleep(20)  # Duración de la animación: 3 segundos
    print('Timer ends')

# State
State_EMG  = queue.Queue()
State_FP   = queue.Queue()
State_Tem  = queue.Queue()

# Var globals
emg_data   = [0]

# Duración total de la adquisición en segundos
adquisicion_time = 20  # Por ejemplo, 60 segundos

# Create threads
EMG_acquisition   = threading.Thread(target=read_emg_data, args=(adquisicion_time,))
FP_acquisition    = threading.Thread(target=read_fp_data, args=())
BD_acquisition    = threading.Thread(target=read_BT_Cam, args=(State_EMG, State_FP,))
Timer             = threading.Thread(target=temp_func)
