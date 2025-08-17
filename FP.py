import time
import queue
import numpy             as np
import matplotlib.pyplot as plt
from   Phidget22.Devices.VoltageRatioInput import *
from   matplotlib.animation import FuncAnimation
from   collections  import deque

# Gain value from the Phidget Control Panel
# List of 4 gain values, one for each channel
gain = [173385.348938015, 179629.962277708, 176102.844060932, 179195.530109193]

# Offset calculated in tareScale
# List of 4 offset values, one for each channel
offset = [0, 0, 0, 0]

# 4 calibrated flags, one for each channel
calibrated = [False, False, False, False]

# Save channels, one for data in Kilograms and one for data in Newtons
ch_kg = [[], [], [], []]
ch_nw = [[], [], [], []]

# Plate distances (between each load cell)
x = 48.38
y = 33.14

# Lists that store the center of pressure data in X and Y
copap = [0]
copml = [0]

# List that store the total weight measured in Kilograms
kg_total = [0]

# Make queue for save new values from the sensor
data_queue_copap = queue.Queue()
data_queue_copml = queue.Queue()

def createCH():
    print('Start CH: Step 1')
    ch0 = VoltageRatioInput()
    ch1 = VoltageRatioInput()
    ch2 = VoltageRatioInput()
    ch3 = VoltageRatioInput()
    print('End CH: Step 1')
    
    # Set addressing parameters to specify which channel to open (if any)
    print('Start CH: Step 2')
    ch0.setChannel(0)
    ch1.setChannel(1)
    ch2.setChannel(2)
    ch3.setChannel(3)
    print('End CH: Step 2')
    
    # Assign any event handlers you need before calling open so that no events are missed.
    print('Start CH: Step 3')
    ch0.setOnVoltageRatioChangeHandler(onVoltageRatioChange)
    ch1.setOnVoltageRatioChangeHandler(onVoltageRatioChange)
    ch2.setOnVoltageRatioChangeHandler(onVoltageRatioChange)
    ch3.setOnVoltageRatioChangeHandler(onVoltageRatioChange)
    print('End CH: Step 3')

    # Open your Phidgets and wait for attachment
    print('Start CH: Step 4')
    ch0.openWaitForAttachment(5000)
    ch1.openWaitForAttachment(5000)
    ch2.openWaitForAttachment(5000)
    ch3.openWaitForAttachment(5000)
    print('End CH: Step 4')
    
    time.sleep(0.750)
    fm = int(1000/350)
    print('Start CH: Step 5')
    ch0.setDataInterval(fm)
    ch1.setDataInterval(fm)
    ch2.setDataInterval(fm)
    ch3.setDataInterval(fm)
    print('End CH: Step 5')
    
    # Taring Plate Force
    print("Start Taring")
    tare_scale(ch0, ch1, ch2, ch3)
    print("Taring Complete")
    
    return ch0, ch1, ch2, ch3   

# Get RAW Data
def onVoltageRatioChange(self, voltageRatio):
    global calibrated, offset, gain
    # Get the channel number from the self object
    channel = self.getChannel()
    if calibrated[channel]:
        kg = (voltageRatio - offset[channel]) * gain[channel]
        newton = kg * 9.81
        ch_kg[channel].append(kg)
        ch_nw[channel].append(newton)
        if channel == 3:
            get_data()
            

# Taring
def tare_scale(ch1, ch2, ch3, ch4):
    global offset, gain, calibrated
    num_samples = 16

    for i in range(num_samples):
        offset[0] += ch1.getVoltageRatio()
        time.sleep(ch1.getDataInterval() / 1000.0)
        offset[1] += ch2.getVoltageRatio()
        time.sleep(ch2.getDataInterval() / 1000.0)
        offset[2] += ch3.getVoltageRatio()
        time.sleep(ch3.getDataInterval() / 1000.0)
        offset[3] += ch4.getVoltageRatio()
        time.sleep(ch4.getDataInterval() / 1000.0)
    
    for i in range(4):
        offset[i] /= num_samples
        calibrated[i] = True
        print('Channel Calibrated: ', calibrated[i])

# Get dato from the sensors
def get_data():
    global x, y, ch_nw, ch_kg, kg_total
    # Sum of all the forces
    try:
        f_total = ch_nw[0][-1] + ch_nw[1][-1] + ch_nw[2][-1] + ch_nw[3][-1]
    except IndexError:
        f_total = 1
    # Sum of all the forces (Kilograms)
    try:
        kg = ch_kg[0][-1] + ch_kg[1][-1] + ch_kg[2][-1] + ch_kg[3][-1]
    except IndexError:
        kg = 0

    # M1 (f1 + f4 -f2 -f3)
    try:
        m1 = - ch_nw[0][-1] - ch_nw[3][-1] + ch_nw[1][-1] + ch_nw[2][-1]
    except IndexError:
        m1 = 1

    # M2 (f3 + f4 -f1 -f2)
    try:
        m2 = ch_nw[2][-1] + ch_nw[3][-1] - ch_nw[0][-1] - ch_nw[1][-1]
    except IndexError:
        m2 = 1

    # If the plate has no weight on it, the Center of Pressure will be at point 0,0
    if f_total < 1:
        cop1 = 0
        cop2 = 0
    else:
        # COP1 as COPx
        cop1 = (x / 2) * (m1 / f_total)
        # COP2 as COPy
        cop2 = (y / 2) * (m2 / f_total)

    kg_total.append(kg)

    # Save data
    copap.append(cop1)
    copml.append(cop2)