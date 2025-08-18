import time
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button
from Phidget22.Devices.VoltageRatioInput import VoltageRatioInput

# ----------------------- Global configuration & state -----------------------
# Calibration gains (from Phidget Control Panel) for each of the 4 channels
gain = [173385.348938015, 179629.962277708, 176102.844060932, 179195.530109193]

# Offsets computed during tare
offset = [0, 0, 0, 0]

# Per-channel flags indicating calibration status
calibrated = [False, False, False, False]

# Data buffers per channel (kg and N)
ch_kg = [[], [], [], []]
ch_nw = [[], [], [], []]

# Plate geometry (distance between load cells, in cm)
x = 48.38
y = 33.14

# COP & total weight histories
copap = [0]   # COP in AP axis (x)
copml = [0]   # COP in ML axis (y)
kg_total = [0]

# Runtime state
running = True     # set False to stop animation & close resources
ani = None         # FuncAnimation handle
chs = []           # list of 4 VoltageRatioInput objects

# ----------------------- Figure & layout (button bar) -----------------------
# Create a figure with a thin bottom band dedicated for the Stop button
fig = plt.figure(figsize=(8.8, 6.4), layout='constrained')
gs  = fig.add_gridspec(nrows=2, ncols=1, height_ratios=[30, 2])  # top plot, bottom bar
ax      = fig.add_subplot(gs[0, 0])  # main plot axes
btn_ax  = fig.add_subplot(gs[1, 0])  # bottom band for the button
btn_ax.set_axis_off()                # no axes decoration for the button band

# Plot artist for COP point
scatter, = ax.plot([], [], 'o', markersize=10)

# Try to set the window title (backend-dependent)
try:
    manager = plt.get_current_fig_manager()
    manager.set_window_title("Center of Pressure")
except Exception:
    pass

# ----------------------------- Helper functions -----------------------------
def save_file():
    """Ask the user if they want to save COP data as CSV/TXT and do so."""
    if not copap or not copml:
        print("No data to save.")
        return

    data = {'COPX': copap, 'COPY': copml, 'Weight - KG': kg_total}
    df = pd.DataFrame(data)

    # Ask whether to save
    while True:
        save_option = input("Do you want to save the data? (Yes/No): ").strip().lower()
        if save_option in ('yes', 'y', 'no', 'n'):
            break
        print("Invalid option. Please respond 'Yes' or 'No'.")

    if save_option in ('no', 'n'):
        return

    # Ask which format(s)
    while True:
        fmt = input("In which format? (CSV/TXT/Both): ").strip().lower()
        if fmt in ('csv', 'txt', 'both'):
            break
        print("Invalid option. Please respond 'CSV', 'TXT', or 'Both'.")

    if fmt in ('csv', 'both'):
        name_csv = input("CSV file name (without extension): ").strip() + ".csv"
        df.to_csv(name_csv, index=False)
        print(f"Data saved in '{name_csv}'")

    if fmt in ('txt', 'both'):
        name_txt = input("TXT file name (without extension): ").strip() + ".txt"
        df.to_csv(name_txt, sep=' ', index=False)
        print(f"Data saved in '{name_txt}'")

def init():
    """Initialize axes appearance and return blit artists."""
    ax.set_xlim(-27.94, 27.94)
    ax.set_ylim(-20.32, 20.32)
    ax.set_title("Real Time Center of Pressure", loc='center', fontdict={'fontsize': 12})
    ax.set_xlabel("X Distance (centimeters)", fontdict={'fontsize': 10})
    ax.set_ylabel("Y Distance (centimeters)", fontdict={'fontsize': 10})
    ax.set_yticks([-20.32, 0, 20.32])
    ax.set_xticks([-27.94, 0, 27.94])

    # Keep a stable aspect ratio so COP looks proportionally correct
    ratio = 16 / 22
    x_left, x_right = ax.get_xlim()
    y_low, y_high   = ax.get_ylim()
    ax.set_aspect(abs((x_right - x_left) / (y_low - y_high)) * ratio)

    ax.grid(True)
    return scatter,

def update(_frame):
    """Update the scatter point with the latest COP values."""
    scatter.set_data([copap[-1]], [-copml[-1]])  # note the minus sign for ML if needed
    return scatter,

def get_data():
    """Compute COP & weight from the latest per-channel forces."""
    global x, y, copap, copml, ch_nw, ch_kg, kg_total
    # Total force (N)
    try:
        f_total = ch_nw[0][-1] + ch_nw[1][-1] + ch_nw[2][-1] + ch_nw[3][-1]
    except IndexError:
        f_total = 1

    # Total weight (kg)
    try:
        kg = ch_kg[0][-1] + ch_kg[1][-1] + ch_kg[2][-1] + ch_kg[3][-1]
    except IndexError:
        kg = 0

    # Moments
    try:
        m1 = -ch_nw[0][-1] - ch_nw[3][-1] + ch_nw[1][-1] + ch_nw[2][-1]
    except IndexError:
        m1 = 1
    try:
        m2 =  ch_nw[2][-1] + ch_nw[3][-1] - ch_nw[0][-1] - ch_nw[1][-1]
    except IndexError:
        m2 = 1

    # COP when plate is unloaded -> (0, 0)
    if f_total < 1:
        cop1, cop2 = 0, 0
    else:
        cop1 = (x / 2) * (m1 / f_total)  # AP axis
        cop2 = (y / 2) * (m2 / f_total)  # ML axis

    kg_total.append(kg)
    copap.append(cop1)
    copml.append(cop2)

def onVoltageRatioChange(self, voltageRatio):
    """Phidget callback: push processed kg/N and compute COP when channel 3 updates."""
    channel = self.getChannel()
    if calibrated[channel]:
        kg = (voltageRatio - offset[channel]) * gain[channel]
        newton = kg * 9.81
        ch_kg[channel].append(kg)
        ch_nw[channel].append(newton)
        # Recompute COP once all four channels should have updated (using channel 3 as trigger)
        if channel == 3:
            get_data()

def tare_scale(ch1, ch2, ch3, ch4):
    """
    Compute per-channel offsets by averaging multiple samples.
    Waits for each channel's data interval to ensure fresh readings.
    """
    global offset, calibrated
    num_samples = 16
    for _ in range(num_samples):
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

# ---------------------------- Stop / cleanup logic ---------------------------
def stop_everything(*_args):
    """Stop animation, close Phidget channels, and close the figure window."""
    global running, ani, chs
    if not running:
        return
    running = False

    # Stop animation timer
    try:
        if ani is not None and ani.event_source is not None:
            ani.event_source.stop()
    except Exception:
        pass

    # Close all Phidget channels gracefully
    for ch in chs:
        try:
            ch.close()
        except Exception:
            pass

    # Close the figure if still open
    try:
        plt.close(fig)
    except Exception:
        pass

def on_close(_event):
    """Handle window close button (X)."""
    stop_everything()

def on_key(event):
    """Press 'q' to stop from the plot window."""
    if event.key and event.key.lower() == 'q':
        stop_everything()

# Connect close & key handlers now
fig.canvas.mpl_connect('close_event', on_close)
fig.canvas.mpl_connect('key_press_event', on_key)

# Create the Stop button in the bottom band and wire it to stop_everything
stop_btn = Button(btn_ax, 'Stop')
stop_btn.on_clicked(lambda evt: stop_everything())

# ---------------------------------- Main ------------------------------------
def main():
    global ani, chs

    # Create and configure the 4 channels
    v0 = VoltageRatioInput(); v0.setChannel(0)
    v1 = VoltageRatioInput(); v1.setChannel(1)
    v2 = VoltageRatioInput(); v2.setChannel(2)
    v3 = VoltageRatioInput(); v3.setChannel(3)
    chs = [v0, v1, v2, v3]

    # Attach callbacks before opening to avoid missing events
    for v in chs:
        v.setOnVoltageRatioChangeHandler(onVoltageRatioChange)

    # Open and wait for attachment
    for v in chs:
        v.openWaitForAttachment(5000)

    time.sleep(0.750)

    # Ask for frequency once
    while True:
        try:
            frequency = float(input("Insert frequency (min: 1, max: 1000 Hz): "))
            if 1 <= frequency <= 1000:
                break
            print("Invalid data")
        except Exception:
            print("Invalid data")

    data_interval = int(1000 / frequency)
    for v in chs:
        v.setDataInterval(data_interval)

    # Tare the plate
    print("Taring")
    tare_scale(v0, v1, v2, v3)
    print("Taring Complete")

    # Start animation
    ani = FuncAnimation(
        fig, update, init_func=init,
        blit=True, interval=data_interval,
        cache_frame_data=False
    )

    # Show is blocking; ensure cleanup on exit
    try:
        plt.show()  # Stop options: close window, press 'q', or click 'Stop'
    finally:
        stop_everything()

    # Ask to save data after everything is closed
    save_file()

if __name__ == "__main__":
    main()