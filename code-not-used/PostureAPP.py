# MONITOREO EN TIEMPO REAL DEL CENTRO DE PRESION, ÁNGULO ARTICULAR Y EMG
# ABDOMINAL PARA ANÁLISIS DIAGNÓSTICO DE PATOLOGÍAS POSTURALES
# INTEGRANTES:
# ÓSCAR IVAN HERNANDEZ GOMEZ
# JOSÉ RODRIGO QUINTERO VALDEZ
# JOSÉ CARLOS VELASCO LOPEZ

import time
import bluetooth
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
    Thread_FP    = State_FP.get(block=True)
    registro_emg = sendEMG_data(long_muestra, socket, fm)
    
    # Cierra la conexión al finalizar la adquisición
    print('Socket bluetooth close')
    socket.send("2")
    time.sleep(1) 
    socket.close()
    print('Thread EMG end')
    for i in range(10):
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
    #EMG Figure
    plt.ion()  # Activa el modo interactivo de Matplotlib
    fig, ax = plt.subplots()
    linea,  = ax.plot([], [])
    ax.set_ylim(0, 5)  # Ajusta los límites según tus datos
    ax.set_xlabel("Tiempo")
    ax.set_ylabel("Valor del EMG")
    
    #FP Figure
    # Create a figure and an axis for the scatter plot
    fig2, ax2 = plt.subplots(figsize=(8.8, 6.4))
    # Scatter plot
    scatter, = ax2.plot([], [], 'o', markersize=10)
    ax2.set_xlim(-27.94, 27.94)  # Adjust the X-axis limits to a specific range
    ax2.set_ylim(-20.32, 20.32)  # Adjust the Y-axis limits to a specific range
    # Set the title of the plot
    ax2.set_title("Real Time Center of Pressure", loc='center', fontdict={'fontsize': 12})
    # Set labels for the X and Y axes
    ax2.set_xlabel("X Distance (centimeters)", fontdict={'fontsize': 10})
    ax2.set_ylabel("Y Distance (centimeters)", fontdict={'fontsize': 10})
    # Set tick locations for the Y and X axes
    ax2.set_yticks([-20.32, 0, 20.32])
    ax2.set_xticks([-27.94, 0, 27.94])
    # Set the aspect ratio to ensure correct scaling of the plot
    ratio = 16/22  # Ratio of width to height for the plot
    x_left, x_right = ax2.get_xlim()
    y_low, y_high   = ax2.get_ylim()
    ax2.set_aspect(abs((x_right - x_left) / (y_low - y_high)) * ratio)
    # Add a grid to the plot
    ax2.grid()
    
    #BT figure
    fig3, ax3 = plt.subplots()
    
    # State of threads validation
    while True:
        try:
            emg_data = data_queue_EMG.get(block=False)
            linea.set_data(range(len(emg_data)), emg_data)
            ax.relim()  # Actualiza los límites del eje y
            ax.autoscale_view()  # Ajusta automáticamente los límites del eje x
            plt.pause(0.01)  # Actualiza el gráfico cada 10 ms
        except queue.Empty:
            pass
        
        try:
            # FP Plot update
            data_copap = data_queue_copap.get(block=False)
            data_copml = data_queue_copml.get(block=False)
            scatter.set_data([data_copap[-1]],[data_copml[-1]])
            plt.pause(0.01)  # Actualiza el gráfico cada 10 ms
        except queue.Empty:
            pass
        
        try:
            #BT Plot Update
            img = data_queue_IMG.get(block=False)
            plt.imshow(img)
            plt.pause(0.01)  # Actualiza el gráfico cada 10 ms
        except queue.Empty:
            pass
        
        try:
            State_Main = State_EMG.get(block=False)
            if State_Main == False:
                break
        except queue.Empty:
            pass

# Función que representa el temporizador
def temp_func():
    State_Tem    = State_FP.get(block=True)
    inicial_time = time.time()
    while True:
        tiempo_transcurrido = time.time() - inicial_time
        print(f"Tiempo transcurrido: {tiempo_transcurrido:.2f} segundos")
        time.sleep(1)
        try:
            State_Tem = State_EMG.get(block=False)
            if State_Tem == False:
                break
        except queue.Empty:
            pass


# State
State_EMG  = queue.Queue()
State_FP   = queue.Queue()
State_Tem  = queue.Queue()

# Duración total de la adquisición en segundos
adquisicion_time = 20  # Por ejemplo, 60 segundos

# Create threads
EMG_acquisition   = threading.Thread(target=read_emg_data, args=(adquisicion_time,))
FP_acquisition    = threading.Thread(target=read_fp_data, args=())
# BD_acquisition    = threading.Thread(target=read_BT_Cam, args=(State_EMG, State_FP,))
Timer             = threading.Thread(target=temp_func)
    
# Inicializate threads
FP_acquisition.start()
EMG_acquisition.start()
# BD_acquisition.start()
Timer.start()

# Make Plot
update_plot()

# Waiting for the ending of threads
EMG_acquisition.join()
FP_acquisition.join()
# BD_acquisition.join()
Timer.join()
