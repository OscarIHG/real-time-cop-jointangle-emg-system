# EMGWorker (acquisition only)
# -*- coding: utf-8 -*-
"""
EMGWorker: Bluetooth EMG acquisition (no UI, no file I/O).
Publishes EmgSample(t, value) to a single-item queue (latest only).
- Robust line framing: handles \n, \r, or \r\n
- Resilient parsing: extracts first float in line (ignores labels)
"""

import time
import threading
import queue
import re
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


_FLOAT_RE = re.compile(rb'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')


class EMGWorker:
    """
    Start/stop lifecycle:
      w = EMGWorker(mac_address="AA:BB:..", rfcomm_channel=1, clamp_min=0.0, clamp_max=5.0)
      w.start(); ... read w.queue ... ; w.stop()
    """
    def __init__(self, mac_address: str, rfcomm_channel: int = 1, clamp_min: float = 0.0, clamp_max: float = 5.0):
        if bluetooth is None:
            raise ImportError(f"pybluez is required for EMGWorker: {_emg_import_error}")

        self.mac = mac_address
        self.chan = int(rfcomm_channel)
        self.vmin = float(clamp_min)
        self.vmax = float(clamp_max)

        self.sock: Optional[bluetooth.BluetoothSocket] = None
        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tail = b""  # partial buffer

    # ---------- connection ----------
    def _connect(self):
        self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        # Optional: short timeout to avoid blocking forever
        try:
            self.sock.settimeout(2.0)
        except Exception:
            pass
        self.sock.connect((self.mac, self.chan))
        # If your device expects a start command, send it (as bytes)
        try:
            self.sock.send(b"1")
        except Exception:
            pass

    # ---------- framing ----------
    def _recv_lines(self) -> list[bytes]:
        """Return a list of complete lines from the stream (handles \\n, \\r, or \\r\\n)."""
        try:
            chunk = self.sock.recv(4096)
        except Exception:
            return []
        if not chunk:
            return []

        self._tail += chunk
        lines = []

        # Prefer splitting by '\n' but also handle '\r' if no '\n'
        while True:
            nl_pos = self._tail.find(b"\n")
            cr_pos = self._tail.find(b"\r")

            # choose earliest separator present
            if nl_pos == -1 and cr_pos == -1:
                break

            if nl_pos != -1 and (cr_pos == -1 or nl_pos < cr_pos):
                line = self._tail[:nl_pos]
                self._tail = self._tail[nl_pos + 1 :]
                # strip trailing '\r' if present
                if line.endswith(b"\r"):
                    line = line[:-1]
                if line:
                    lines.append(line)
            else:
                line = self._tail[:cr_pos]
                self._tail = self._tail[cr_pos + 1 :]
                if line:
                    lines.append(line)

        return lines

    # ---------- main loop ----------
    def _loop(self):
        try:
            last_push = 0.0
            while not self._stop.is_set():
                for raw in self._recv_lines():
                    # Try to extract first float from the line (robust to labels like "EMG: 2.34")
                    m = _FLOAT_RE.search(raw)
                    if not m:
                        # also try replacing comma decimal if present
                        if b"," in raw:
                            raw = raw.replace(b",", b".")
                            m = _FLOAT_RE.search(raw)
                        if not m:
                            continue
                    try:
                        v = float(m.group(0))
                    except Exception:
                        continue

                    # Clamp to configured range (still allows auto-ylim upstream)
                    if v < self.vmin: v = self.vmin
                    if v > self.vmax: v = self.vmax

                    put_latest(self.queue, EmgSample(t=time.perf_counter(), value=v))
                    last_push = time.perf_counter()

                # small pause to reduce CPU if stream is slow or idle
                time.sleep(0.001)
        finally:
            # Optional: stop command to device
            try:
                self.sock.send(b"2")
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass

    # ---------- public API ----------
    def start(self):
        self._stop.clear()
        self._connect()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
