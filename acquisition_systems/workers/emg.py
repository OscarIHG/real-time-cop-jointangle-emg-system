# EMGWorker (ESP32-compatible, connect in main thread)
# -*- coding: utf-8 -*-
"""
EMGWorker: Bluetooth EMG acquisition over RFCOMM (no UI, no file I/O) compatible
with the standalone script behavior you confirmed works.

Key changes vs previous version:
- Connects in start() (main thread) and only reads in the background thread.
- Exact CRLF parsing, optional LF fallback.
- Optional debug logs via env var EMG_DEBUG=1.

Config expectations (match your working script):
  mac_address: "A4:CF:12:96:8B:9E"
  rfcomm_channel: 1
  clamp_min/max: 0.0..5.0
"""

import os
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
# put_latest keeps only the latest item in a single-slot queue
from acquisition_systems.common.utils import put_latest


def _dbg(msg: str):
    if os.environ.get("EMG_DEBUG") == "1":
        print(f"[EMG] {msg}")


class EMGWorker:
    """
    Start/stop lifecycle:
        w = EMGWorker(mac_address="A4:CF:12:96:8B:9E", rfcomm_channel=1, clamp_min=0.0, clamp_max=5.0)
        w.start(); ... read w.queue ... ; w.stop()
    """
    # If your firmware ever sends '\n' instead of '\r\n', flip this to True.
    ALLOW_LF = False

    def __init__(
        self,
        mac_address: str,
        rfcomm_channel: int = 1,
        clamp_min: float = 0.0,
        clamp_max: float = 5.0,
        start_token: str = "1",
        stop_token: str = "2",
    ):
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
        _dbg(f"Connecting RFCOMM to {self.mac} ch {self.chan} ...")
        self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        # We avoid settimeout to match the working script exactly
        self.sock.connect((self.mac, self.chan))
        _dbg("Connected. Sending start token...")
        try:
            if self.start_token:
                # Your standalone script sends a string, not bytes; keep the same
                self.sock.send(self.start_token)
        except Exception as e:
            _dbg(f"Start token send failed (ignored): {e}")

    # ---------- framing & parsing ----------
    def _recv_floats_crlf(self) -> list[float]:
        """Read a chunk and parse CRLF-separated floats (exactly like your working script)."""
        try:
            chunk = self.sock.recv(4096) if self.sock else b""
        except BluetoothError as e:
            _dbg(f"recv BluetoothError: {e}")
            raise
        if not chunk:
            return []

        data = self._tail + chunk
        parts = data.split(b"\r\n")
        self._tail = parts[-1]

        vals = []
        for p in parts[:-1]:
            try:
                v = float(p)
            except Exception:
                continue
            if v < self.vmin: v = self.vmin
            if v > self.vmax: v = self.vmax
            vals.append(v)
        return vals

    def _recv_floats_lf(self) -> list[float]:
        """Optional LF-only fallback (disabled by default)."""
        try:
            chunk = self.sock.recv(4096) if self.sock else b""
        except BluetoothError as e:
            _dbg(f"recv BluetoothError(LF): {e}")
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

    # ---------- main loop (read only) ----------
    def _loop(self):
        try:
            while not self._stop.is_set():
                vals = self._recv_floats_crlf()
                if self.ALLOW_LF and not vals:
                    vals = self._recv_floats_lf()

                if not vals:
                    time.sleep(0.001)  # gentle idle
                    continue

                t = time.perf_counter()
                for v in vals:
                    put_latest(self.queue, EmgSample(t=t, value=v))
        finally:
            self._safe_close()

    def _safe_close(self):
        try:
            if self.sock and self.stop_token:
                _dbg("Sending stop token...")
                try:
                    self.sock.send(self.stop_token)
                    time.sleep(0.2)
                except Exception as e:
                    _dbg(f"Stop token send failed (ignored): {e}")
        finally:
            try:
                if self.sock:
                    _dbg("Closing socket.")
                    self.sock.close()
            except Exception as e:
                _dbg(f"Close failed (ignored): {e}")
            self.sock = None

    # ---------- public API ----------
    def start(self):
        """Connect in main thread, then start background reader."""
        self._stop.clear()
        # Connecting here mirrors the standalone script and avoids BlueZ issues on some systems
        self._connect()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        _dbg("Reader thread started.")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        _dbg("Stopped.")