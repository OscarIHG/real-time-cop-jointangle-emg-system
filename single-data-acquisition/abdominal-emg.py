# emg_realtime_single.py
# -*- coding: utf-8 -*-
"""
Single-file EMG acquisition from ESP32 over Bluetooth RFCOMM
- Opens RFCOMM and sends "1" to start streaming
- Estimates sampling rate (fs) over a short window
- Reads continuously in a background thread
- Optional 60 Hz notch (only if fs >= 120 Hz), low-pass smoothing + Hilbert envelope
- Real-time plot with a Stop button placed below the axes (won't cover the plot)
- On exit, asks whether to save CSV; if yes, uses an automatic filename with date & duration

Dependencies: pybluez, numpy, scipy, matplotlib, pandas
"""

import time
import threading
import queue
import bluetooth
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from collections import deque
from datetime import datetime

# Try SciPy features, but degrade gracefully if unavailable
try:
    from scipy.signal import iirnotch, butter, filtfilt, hilbert
    SCIPY_OK = True
except Exception as e:
    print("Warning: SciPy unavailable or incompatible:", e,
          "\nContinuing without notch / envelope.")
    SCIPY_OK = False

# ---------- User-configurable ----------
ESP32_MAC   = "A4:CF:12:96:8B:9E"  # replace if needed
RFCOMM_CH   = 1
PLOT_WINDOW = 1000                  # samples shown in the rolling plot
# --------------------------------------

class EMGStreamer:
    """Handle Bluetooth connection, streaming, filtering, and buffering."""
    def __init__(self, mac, channel, plot_window):
        self.mac = mac
        self.channel = channel
        self.sock = None
        self.stop_event = threading.Event()

        # Data containers
        self.fs = None
        self._line_buffer = b""        # holds partial line between recv() calls
        self.plot_buffer = deque(maxlen=plot_window)
        self.data_all = []             # full-length raw stream
        self.queue = queue.Queue()     # for GUI thread (sends rolling window)

        # Filters (designed after fs is known)
        self._notch_ba = None
        self._lp_ba = None

    # ---------- Connection / control ----------
    def connect_and_start(self):
        """Open RFCOMM and tell ESP32 to start streaming."""
        self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        self.sock.connect((self.mac, self.channel))
        # Your firmware expects a "1" to begin sending analog samples
        self.sock.send("1")

    def stop_and_close(self):
        """Ask ESP32 to stop and close the socket."""
        try:
            self.sock.send("2")   # your firmware's stop command
            time.sleep(0.5)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    # ---------- Streaming helpers ----------
    def _recv_floats(self):
        """
        Read a chunk from RFCOMM and parse newline-separated floats.
        Robust to partial lines across recv() boundaries.
        Clamps values to [0, 5] V (your previous code did this).
        """
        try:
            chunk = self.sock.recv(4096)
        except bluetooth.BluetoothError as e:
            print("Bluetooth error:", e)
            return []

        if not chunk:
            return []

        data = self._line_buffer + chunk
        parts = data.split(b"\r\n")  # device uses CRLF
        self._line_buffer = parts[-1]  # keep the trailing partial line

        vals = []
        for p in parts[:-1]:
            try:
                v = float(p)
                # Clamp to 0..5 V as in your code
                v = min(5.0, max(0.0, v))
                vals.append(v)
            except Exception:
                # Ignore malformed lines
                continue
        return vals

    def estimate_fs(self, seconds=2.0):
        """Estimate sampling rate by counting samples for a fixed time."""
        start = time.time()
        count = 0
        while (time.time() - start) < seconds and not self.stop_event.is_set():
            vals = self._recv_floats()
            count += len(vals)
        self.fs = int(round(count / max(1e-9, seconds))) if count > 0 else 100
        print(f"Estimated sampling rate: {self.fs} Hz")
        return self.fs

    def design_filters(self):
        """
        Design a 60 Hz notch (only if Nyquist >= 60 Hz)
        and a 6th-order low-pass at 10 Hz for smoothing.
        """
        if SCIPY_OK:
            # Notch: only valid if fs >= 120 Hz (Nyquist > 60 Hz)
            if self.fs and self.fs >= 120:
                b, a = iirnotch(60.0, Q=30.0, fs=self.fs)
                self._notch_ba = (b, a)
                print("60 Hz notch enabled.")
            else:
                self._notch_ba = None
                print("60 Hz notch disabled (insufficient fs).")

            # Smoothing for envelope (Butterworth low-pass, 10 Hz)
            b_lp, a_lp = butter(6, 10.0, btype="low", fs=max(1, self.fs or 100))
            self._lp_ba = (b_lp, a_lp)
        else:
            self._notch_ba = None
            self._lp_ba = None

    def _apply_filters_for_plot(self, arr):
        """
        Apply light filtering for the live plot if needed.
        For stability and speed, we only apply the notch in real-time.
        """
        if SCIPY_OK and self._notch_ba is not None and len(arr) > 9:
            b, a = self._notch_ba
            try:
                arr = filtfilt(b, a, arr)
            except Exception:
                pass
        return arr

    def reader_loop(self):
        """Continuously read, filter (light), buffer, and publish to the GUI queue."""
        try:
            while not self.stop_event.is_set():
                vals = self._recv_floats()
                if not vals:
                    continue

                arr = np.asarray(vals, dtype=float)
                arr = self._apply_filters_for_plot(arr)

                # Append to full recording and rolling buffer
                self.data_all.extend(arr.tolist())
                self.plot_buffer.extend(arr.tolist())

                # Push a copy of the rolling buffer for the plot thread
                self.queue.put(list(self.plot_buffer))
        except Exception as e:
            print("Reader loop error:", e)
        finally:
            self.stop_and_close()

# ---------- UI / main ----------
def main():
    streamer = EMGStreamer(ESP32_MAC, RFCOMM_CH, PLOT_WINDOW)

    print("Connecting to ESP32...")
    streamer.connect_and_start()

    print("Measuring sampling rate...")
    t0 = time.time()  # wall-clock start time
    streamer.estimate_fs(seconds=2.0)
    streamer.design_filters()

    # Start background reader
    t_reader = threading.Thread(target=streamer.reader_loop, daemon=True)
    t_reader.start()

    # ---- Matplotlib UI ----
    plt.ion()
    fig, ax = plt.subplots()
    # Leave space at the bottom for the Stop button so it does NOT cover the plot
    plt.subplots_adjust(bottom=0.22)

    line, = ax.plot([], [], lw=1)
    ax.set_ylim(0, 5)
    ax.set_xlim(0, PLOT_WINDOW)
    ax.set_xlabel(f"Samples (last {PLOT_WINDOW})")
    ax.set_ylabel("EMG (V)")
    ax.set_title(f"Real-time EMG from ESP32 (fs ≈ {streamer.fs} Hz)")

    # Stop button (placed below)
    btn_ax = plt.axes([0.02, 0.06, 0.12, 0.1])  # [left, bottom, width, height]
    btn = Button(btn_ax, "Stop")

    def on_stop(event):
        streamer.stop_event.set()
    btn.on_clicked(on_stop)

    # Also allow 'q' to quit
    def on_key(evt):
        if evt.key == 'q':
            streamer.stop_event.set()
    fig.canvas.mpl_connect('key_press_event', on_key)

    try:
        while not streamer.stop_event.is_set():
            try:
                buf = streamer.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            # Update line
            line.set_data(np.arange(len(buf)), buf)
            # Scroll x-limits with the data
            left = max(0, len(buf) - PLOT_WINDOW)
            ax.set_xlim(left, left + PLOT_WINDOW)
            ax.figure.canvas.draw_idle()
            plt.pause(0.001)
    finally:
        # Clean exit and optional save
        streamer.stop_event.set()
        t_reader.join(timeout=1.0)

        data = np.asarray(streamer.data_all, dtype=float)
        fs = max(1, streamer.fs or 100)
        # Prefer duration based on sample count for accuracy
        duration_s = len(data) / fs if len(data) > 0 else 0.0
        t = np.arange(len(data)) / fs
        df = pd.DataFrame({"t_s": t, "emg_v": data})

        # Post-acquisition smoothing + envelope (needs enough samples)
        if SCIPY_OK and len(data) > fs * 2:
            try:
                b_lp, a_lp = streamer._lp_ba
                smoothed = filtfilt(b_lp, a_lp, data)
                envelope = np.abs(hilbert(smoothed))
                df["emg_smooth"] = smoothed
                df["emg_envelope"] = envelope
            except Exception as e:
                print("Post-processing failed:", e)

        # Ask the user whether to save
        try:
            ans = input(f"\nSave CSV? Duration ≈ {duration_s:.1f}s [y/N]: ").strip().lower()
        except EOFError:
            ans = "n"

        if ans in ("y", "yes", "s", "si"):
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"emg_{stamp}_{duration_s:.1f}s.csv"
            try:
                df.to_csv(fname, index=False)
                print("Saved:", fname)
            except Exception as e:
                print("Could not save CSV:", e)
        else:
            print("Not saved.")

        # Close the plot window cleanly
        plt.close(fig)

if __name__ == "__main__":
    main()
