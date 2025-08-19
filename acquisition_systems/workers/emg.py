# EMGWorker (ESP32-compatible, acquisition only)
# -*- coding: utf-8 -*-
"""
EMGWorker: Bluetooth EMG acquisition over RFCOMM (no UI, no file I/O) compatible
with the standalone script behavior you confirmed works.

Key points (to match your working single-file script):
- Uses a *fixed* RFCOMM channel (no SDP discovery).
- Sends "1" (string) to start streaming; "2" on stop (optional).
- Blocking recv() (no settimeout), parse *exactly* CRLF-separated floats.
- Clamps values to [clamp_min, clamp_max] like your original code (default 0..5 V).
- Publishes EmgSample(t, value) to a single-item queue (latest only).

If your device ever changes line endings, you can toggle ALLOW_LF as needed.
"""

import time
import threading
import queue
from typing import Optional

try:
    import bluetooth  # pybluez (Classic BT)
    from bluetooth.btcommon import BluetoothError
except Exception as e:
    bluetooth = None
    BluetoothError = Exception
    _emg_import_error = e
else:
    _emg_import_error = None

from acquisition_systems.common.types import EmgSample
from acquisition_systems.common.utils import put_latest


class EMGWorker:
    """
    Start/stop lifecycle:
        w = EMGWorker(mac_address="A4:CF:12:96:8B:9E", rfcomm_channel=1, clamp_min=0.0, clamp_max=5.0)
        w.start(); ... read w.queue ... ; w.stop()
    """
    # If your firmware ever sends '\n' instead of '\r\n', flip this to True.
    ALLOW_LF = False

    def __init__(self, mac_address: str, rfcomm_channel: int = 1,
                 clamp_min: float = 0.0, clamp_max: float = 5.0,
                 start_token: str = "1", stop_token: str = "2"):
        if bluetooth is None:
            raise ImportError(f"pybluez is required for EMGWorker: {_emg_import_error}")

        self.mac = mac_address
        self.chan = int(rfcomm_channel)
        self.vmin = float(clamp_min)
        self.vmax = float(clamp_max)
        self.start_token = start_token
        self.stop_token = stop_token

        self.sock: Optional[bluetooth.BluetoothSocket] = None
        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tail = b""  # partial line buffer across recv() calls

    # ---------- connection ----------
    def _connect(self):
        # Mirror the working script: blocking RFCOMM connect, no timeouts.
        self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        self.sock.connect((self.mac, self.chan))
        # Your firmware expects a "1" to begin streaming (string, not bytes).
        try:
            if self.start_token:
                self.sock.send(self.start_token)
        except Exception:
            # Some firmwares autostart; ignore send failures.
            pass

    # ---------- framing & parsing ----------
    def _recv_floats_crlf(self) -> list[float]:
        """
        Read a chunk from RFCOMM and parse CRLF-separated floats.
        Robust to partial lines across recv() boundaries.
        """
        try:
            chunk = self.sock.recv(4096) if self.sock else b""
        except BluetoothError as e:
            # Propagate to loop so it can stop cleanly; reconnection is intentionally not implemented
            # to match the simpler working script behavior.
            raise
        if not chunk:
            return []

        data = self._tail + chunk
        parts = data.split(b"\r\n")
        self._tail = parts[-1]  # keep the trailing partial line

        vals = []
        for p in parts[:-1]:
            try:
                v = float(p)
            except Exception:
                continue
            # Clamp as in your code
            if v < self.vmin: v = self.vmin
            if v > self.vmax: v = self.vmax
            vals.append(v)
        return vals

    def _recv_floats_lf(self) -> list[float]:
        """
        Optional fallback for pure LF line endings (disabled by default).
        """
        try:
            chunk = self.sock.recv(4096) if self.sock else b""
        except BluetoothError:
            raise
        if not chunk:
            return []

        data = self._tail + chunk
        parts = data.split(b"\n")
        self._tail = parts[-1]
        vals = []
        for p in parts[:-1]:
            p = p.rstrip(b"\r")
            try:
                v = float(p)
            except Exception:
                continue
            if v < self.vmin: v = self.vmin
            if v > self.vmax: v = self.vmax
            vals.append(v)
        return vals

    # ---------- main loop ----------
    def _loop(self):
        try:
            # Connect once (no reconnection logic — mirrors your single-file script)
            self._connect()

            while not self._stop.is_set():
                vals = self._recv_floats_crlf()
                if self.ALLOW_LF and not vals:
                    vals = self._recv_floats_lf()

                if not vals:
                    # Keep CPU sane when idle (rare)
                    time.sleep(0.001)
                    continue

                t = time.perf_counter()
                for v in vals:
                    put_latest(self.queue, EmgSample(t=t, value=v))
        finally:
            # Send stop token and close, as in your single-file script
            try:
                if self.sock and self.stop_token:
                    self.sock.send(self.stop_token)
                    time.sleep(0.2)
            except Exception:
                pass
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass
            self.sock = None

    # ---------- public API ----------
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
