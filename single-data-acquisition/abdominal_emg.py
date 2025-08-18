# -*- coding: utf-8 -*-
"""
EMG worker for GUI integration
- Opens Bluetooth RFCOMM to ESP32 and streams EMG floats (0..5 V)
- Pushes a rolling window to a thread-safe Queue for real-time plotting
- Optionally applies a 60 Hz notch if SciPy is available and fs >= 120 Hz
- Clean start()/stop() API for Tk GUI

Dependencies (Raspberry Pi):
  pybluez, numpy, matplotlib (for types), optional: scipy, pandas
"""

import time
import threading
import queue
import bluetooth
import numpy as np
from collections import deque

# Try SciPy, degrade gracefully if unavailable
try:
    from scipy.signal import iirnotch, filtfilt
    SCIPY_OK = True
except Exception:
    SCIPY_OK = False


class EMGWorker:
    def __init__(self,
                 mac_address: str = "A4:CF:12:96:8B:9E",
                 rfcomm_channel: int = 1,
                 plot_window: int = 1000):
        """Prepare the worker but do not connect yet."""
        self.mac = mac_address
        self.chan = rfcomm_channel
        self.plot_window = plot_window

        self.sock = None
        self.stop_event = threading.Event()
        self.thread = None

        # Buffers / outputs
        self.roll = deque(maxlen=plot_window)
        self.full = []  # full raw log (optional, can grow)
        self.queue = queue.Queue()  # GUI picks last rolling vector
        self.fs = 100  # default; estimated at runtime

        # Filters (filled after fs known)
        self._notch = None

    # ------------------ private helpers ------------------
    def _connect(self):
        """Open RFCOMM and ask the ESP32 to start ('1')."""
        self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        self.sock.connect((self.mac, self.chan))
        self.sock.send("1")

    def _estimate_fs(self, seconds: float = 2.0):
        """Estimate sampling rate counting samples for a short window."""
        start = time.time()
        count = 0
        buf_tail = b""
        while (time.time() - start) < seconds and not self.stop_event.is_set():
            chunk = self.sock.recv(4096)
            if not chunk:
                continue
            data = buf_tail + chunk
            parts = data.split(b"\r\n")
            buf_tail = parts[-1]
            for p in parts[:-1]:
                try:
                    float(p)
                    count += 1
                except Exception:
                    pass
        self.fs = max(1, int(round(count / max(1e-6, seconds))))

    def _design_filters(self):
        """Design only a 60 Hz notch if feasible."""
        if SCIPY_OK and self.fs >= 120:
            b, a = iirnotch(60.0, Q=30.0, fs=self.fs)
            self._notch = (b, a)
        else:
            self._notch = None

    def _recv_block(self):
        """Receive a chunk and parse newline-separated floats (clamped 0..5 V)."""
        try:
            chunk = self.sock.recv(4096)
        except bluetooth.BluetoothError:
            return []
        if not chunk:
            return []
        vals = []
        for part in chunk.split(b"\r\n"):
            if not part:
                continue
            try:
                v = float(part)
                v = min(5.0, max(0.0, v))
                vals.append(v)
            except Exception:
                # ignore malformed line
                pass
        return vals

    def _filter_realtime(self, arr: np.ndarray) -> np.ndarray:
        """Light filtering for live plot (only notch, zero-phase)."""
        if self._notch is None or arr.size < 9:
            return arr
        try:
            b, a = self._notch
            return filtfilt(b, a, arr)
        except Exception:
            return arr

    def _reader_loop(self):
        """Main streaming loop: receive -> (optional)filter -> push to queue."""
        # Estimate fs with a quick pass that discards values
        self._estimate_fs(seconds=1.5)
        self._design_filters()

        # Main loop
        try:
            while not self.stop_event.is_set():
                vals = self._recv_block()
                if not vals:
                    continue
                arr = np.asarray(vals, dtype=float)
                arr = self._filter_realtime(arr)

                self.full.extend(arr.tolist())
                self.roll.extend(arr.tolist())

                # Push a snapshot of the rolling window
                try:
                    self.queue.put_nowait(list(self.roll))
                except queue.Full:
                    pass
        finally:
            # Best-effort stop command '2'
            try:
                self.sock.send("2")
                time.sleep(0.2)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass

    # ------------------ public API ------------------
    def start(self):
        """Connect and start streaming in a background thread."""
        self.stop_event.clear()
        self._connect()
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Signal the loop to stop and wait for thread to finish."""
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.5)
