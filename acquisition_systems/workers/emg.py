# EMGWorker (acquisition only)
# -*- coding: utf-8 -*-
"""
EMGWorker: Bluetooth EMG acquisition (no UI, no file I/O).
Publishes EmgSample(t, value) to a single-item queue (latest only).
"""
import time
import threading
import queue
from typing import Optional

try:
    import bluetooth  # pybluez
except Exception as e:
    bluetooth = None
    _emg_import_error = e
else:
    _emg_import_error = None

from acquisition_systems.common.types import EmgSample
from acquisition_systems.common.utils import put_latest


class EMGWorker:
    """
    Start/stop lifecycle:
      w = EMGWorker(mac="AA:BB:..", channel=1)
      w.start(); ... read w.queue ... ; w.stop()
    """
    def __init__(self, mac_address: str, rfcomm_channel: int = 1, clamp_min: float = 0.0, clamp_max: float = 5.0):
        if bluetooth is None:
            raise ImportError(f"pybluez is required for EMGWorker: {_emg_import_error}")

        self.mac = mac_address
        self.chan = rfcomm_channel
        self.vmin = clamp_min
        self.vmax = clamp_max

        self.sock: Optional[bluetooth.BluetoothSocket] = None
        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tail = b""  # partial line buffer

    def _connect(self):
        self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        self.sock.connect((self.mac, self.chan))
        # Ask device to start stream if your firmware expects it:
        try:
            self.sock.send("1")
        except Exception:
            pass

    def _recv_lines(self) -> list[bytes]:
        try:
            chunk = self.sock.recv(4096)
        except Exception:
            return []
        if not chunk:
            return []
        data = self._tail + chunk
        parts = data.split(b"\r\n")
        self._tail = parts[-1]  # keep incomplete for next read
        return parts[:-1]

    def _loop(self):
        try:
            while not self._stop.is_set():
                for raw in self._recv_lines():
                    try:
                        v = float(raw)
                    except Exception:
                        continue
                    v = min(self.vmax, max(self.vmin, v))
                    put_latest(self.queue, EmgSample(t=time.perf_counter(), value=v))
                time.sleep(0.001)  # small pause to reduce CPU if stream is slow
        finally:
            try:
                self.sock.send("2")  # optional stop cmd
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass

    # ------------ public API ------------
    def start(self):
        self._stop.clear()
        self._connect()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
