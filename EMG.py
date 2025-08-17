import bluetooth
import time
import queue
import numpy             as np
from collections  import deque
from scipy.signal import hilbert, butter, filtfilt, lfilter

# MAC address from ESP32
esp32_address  = 'A4:CF:12:96:8B:9E'
# Create queue var for comunicate threads
data_queue_EMG = queue.Queue()

        
def getfm(esp32_address):
    muestra_fm = []
    try:
        # Crea un socket RFCOMM
        socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)

        # Conéctate al ESP32
        socket.connect((esp32_address, 1))
        
        # Envía un comando para solicitar la lectura del pin analógico (EMG)
        socket.send("1")
        
        #Obtener frecuencia de muestreo
        #Inicia el tiempo de inicio de la adquisición
        tiempo_inicio = time.time()
        while True:
            # Comprueba si ha pasado el tiempo de adquisición deseado
            tiempo_actual = time.time()
            if tiempo_actual - tiempo_inicio >= 3:
                break
            # Recibe la lectura analógica
            data = socket.recv(4095)
            # Dividir la cadena en líneas y convertir cada línea a un entero
            data_lines = data.split(b'\r\n')
            data_decimal = [float(line) for line in data_lines if line]
            muestra_fm.extend(data_decimal)
            
        fm = int(len(muestra_fm)/3)
        
    except bluetooth.BluetoothError as e:
        print(f"Error de Bluetooth: {str(e)}")
        # Si ocurre un error, puedes manejarlo aquí               
    
    return socket,fm

def acquisitionEMG(socket, fm):
    try:
        # Recibe la lectura analógica
        data = socket.recv(4095)
        # Dividir la cadena en líneas y convertir cada línea a un entero
        data_lines = data.split(b'\r\n')
        data_decimal = [float(line) for line in data_lines if line]
        data_decimal = [min(5, valor) for valor in data_decimal]
        
        #Aplicar filtro rechaza banda de 60 HZ
        try:
            fft_data = np.fft.fft(data_decimal)
            freq_60hz = 60 / fm  # Frecuencia relativa a la frecuencia de muestreo      
            # Eliminar la componente de frecuencia de 60 Hz
            fft_data[int(freq_60hz)] = 0  # Suponiendo que 60 Hz es un número entero en la FFT
            # Aplicar la inversa de la FFT para volver a la señal en el dominio del tiempo
            filtered_data = abs(np.fft.ifft(fft_data))
        except Exception:
            filtered_data = [0]
     
        # Espera un tiempo antes de la próxima lectura
        time.sleep(1 / fm)  # Tiempo de espera según la frecuencia de muestreo
        
        return filtered_data
    
    except bluetooth.BluetoothError as e:
        print(f"Error de Bluetooth: {str(e)}")
        # Si ocurre un error, puedes manejarlo aquí
        
def sendEMG_data(long_muestra, socket, fm):
    
    # List that saves EMG file
    registro_emg = []
    # Deque to plot EMG on real time
    datos_a_graficar = deque(maxlen=1000)
    #Flag
    i = 0
    
    while (i < long_muestra):    
        emg_data = acquisitionEMG(socket, fm, long_muestra, i)
        datos_a_graficar.extend(emg_data)
        data_queue_EMG.put(datos_a_graficar)
        time.sleep(0.1)
        registro_emg.extend(emg_data)
        i = len(registro_emg)
    return registro_emg
