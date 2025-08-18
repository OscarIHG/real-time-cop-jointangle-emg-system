from picamera import PiCamera
from time import sleep
import numpy as np
import matplotlib.pyplot    as plt
from PIL import Image, ImageTk
import queue

# Create queue var for comunicate threads
data_queue_IMG = queue.Queue()

def startcamera(State_EMG, State_FP):
    Thread_FP = State_FP.get(block=True)
    camara    = PiCamera()
    camara.resolution = (320, 240)  # Ajusta la resolución según tus preferencias
    output = np.empty((camara.resolution[1] * camara.resolution[0] * 3,), dtype=np.uint8)
    while True:
        camara.capture(output, 'rgb')
        img = Image.frombytes('RGB', camara.resolution, output)
        data_queue_IMG.put(img)
        try:
            State_Tem = State_EMG.get(block=False)
            if State_Tem == False:
                break
        except queue.Empty:
            pass


