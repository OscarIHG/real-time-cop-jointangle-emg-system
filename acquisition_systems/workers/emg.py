# EMGWorker (acquisition only)
# -*- coding: utf-8 -*-
"""
EMGWorker: Bluetooth EMG acquisition over RFCOMM (no UI, no file I/O).
Publishes EmgSample(t, value) to a single-item queue (latest only).

Features:
- SDP discovery for RFCOMM channel (fallback to provided channel)
- Resilient framing (\n, \r, or \r\n)
- Robust float parsing (extracts first float on each line)
- Auto-reconnect on common BlueZ/PyBluez errors (incl. errno 77 EBADFD)

NOTE: This worker assumes a Classic BT SPP profile. If your device is BLE-only (GATT),
      this will not work; you'll need a BLE worker (e.g., using 'bleak').
"""

import time
import threading
import queue
import re
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

_FLOAT_RE = re.compile(rb'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')

# ---- helper: best-effort int errno from exception (pybluez doesn't always expose .errno) ----
def _err_code(exc: Exception) -> int | None:
    try:
        # Some BluetoothError expose .errno or args[0] as int/tuple
        if hasattr(exc, "errno") and isinstance(exc.errno, int):
            return exc.errno
        if exc.args:
            if isinstance(exc.args[0], int):
                return exc.args[0]
            if isinstance(exc.args[0], tuple) and exc.args[0]:
                # e.g. (77, 'File descriptor in bad state')
                if isinstance(exc.args[0][0], int):
                    return exc.args[0][0]
    except Exception:
        pass
    return None


class EMGWorker:
    """
    Start/stop lifecycle:
      w = EMGWorker(mac_address="AA:BB:..", rfcomm_channel=1, clamp_min=0.0, clamp_max=5.0)
      w.start(); ... read w.queue ... ; w.stop()
    """
    def __init__(
        self,
        mac_address: str,
        rfcomm_channel: int = 1,
        clamp_min: float = 0.0,
        clamp_max: float = 5.0,
        start_cmd: bytes | None = None,   # e.g. b"1"
        stop_cmd: bytes | None = None,    # e.g. b"2"
        sdp_uuid: str | None = None,      # e.g. "00001101-0000-1000-8000-00805F9B34FB" for SerialPort
        reconnect_backoff_s: float = 1.0,
    ):
        if bluetooth is None:
            raise ImportError(f"pybluez is required for EMGWorker: {_emg_import_error}")

        self.mac = mac_address
        self.chan_cfg = int(rfcomm_channel)
        self.vmin = float(clamp_min)
        self.vmax = float(clamp_max)
        self.start_cmd = start_cmd
        self.stop_cmd = stop_cmd
        # SerialPort UUID by default (SPP)
        self.sdp_uuid = sdp_uuid or "00001101-0000-1000-8000-00805F9B34FB"
        self.reconnect_backoff_s = float(reconnect_backoff_s)

        self.sock: Optional[bluetooth.BluetoothSocket] = None
        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tail = b""  # partial buffer

    # ---------- SDP / connection ----------
    def _discover_channel(self) -> int:
        # Try SDP lookup by UUID first
        try:
            svcs = bluetooth.find_service(uuid=self.sdp_uuid, address=self.mac)
            for s in svcs or []:
                if s.get("protocol") == "RFCOMM" and "port" in s:
                    return int(s["port"])
        except Exception:
            pass
        # Fallback: any RFCOMM service
        try:
            svcs = bluetooth.find_service(address=self.mac)
            for s in svcs or []:
                if s.get("protocol") == "RFCOMM" and "port" in s:
                    return int(s["port"])
        except Exception:
            pass
        # Final fallback: configured channel
        return self.chan_cfg

    def _connect_once(self):
        # Resolve channel
        port = self._discover_channel()
        # Create socket & connect
        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        # Avoid settimeout on some BlueZ versions (it can cause EBADFD in rare cases)
        # sock.settimeout(2.0)
        sock.connect((self.mac, port))
        # Optional start command
        if self.start_cmd:
            try:
                sock.send(self.start_cmd)
            except Exception:
                # Not fatal; some firmwares start streaming automatically
                pass
        self.sock = sock

    def _safe_close(self):
        try:
            if self.sock:
                # Optional stop command
                if self.stop_cmd:
                    try:
                        self.sock.send(self.stop_cmd)
                    except Exception:
                        pass
                try:
                    self.sock.close()
                except Exception:
                    pass
        finally:
            self.sock = None

    # ---------- framing ----------
    def _recv_lines(self) -> list[bytes]:
        """Return a list of complete lines from the stream (handles \\n, \\r, or \\r\\n)."""
        try:
            chunk = self.sock.recv(4096) if self.sock else b""
        except Exception:
            return []
        if not chunk:
            return []

        self._tail += chunk
        lines = []

        while True:
            nl_pos = self._tail.find(b"\n")
            cr_pos = self._tail.find(b"\r")

            if nl_pos == -1 and cr_pos == -1:
                break

            if nl_pos != -1 and (cr_pos == -1 or nl_pos < cr_pos):
                line = self._tail[:nl_pos]
                self._tail = self._tail[nl_pos + 1 :]
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

    # ---------- main loop with auto-reconnect ----------
    def _loop(self):
        try:
            # Initial connect (with backoff retries)
            while not self._stop.is_set():
                try:
                    self._connect_once()
                    break
                except BluetoothError as e:
                    code = _err_code(e)
                    print(f"[EMG] connect error {code}: {e}. Retrying in {self.reconnect_backoff_s}s...")
                    time.sleep(self.reconnect_backoff_s)
                except Exception as e:
                    print(f"[EMG] connect error: {e}. Retrying in {self.reconnect_backoff_s}s...")
                    time.sleep(self.reconnect_backoff_s)

            # Main read loop
            while not self._stop.is_set():
                try:
                    had_any = False
                    for raw in self._recv_lines():
                        had_any = True
                        m = _FLOAT_RE.search(raw) or _FLOAT_RE.search(raw.replace(b",", b"."))
                        if not m:
                            continue
                        try:
                            v = float(m.group(0))
                        except Exception:
                            continue
                        if v < self.vmin: v = self.vmin
                        if v > self.vmax: v = self.vmax
                        put_latest(self.queue, EmgSample(t=time.perf_counter(), value=v))

                    if not had_any:
                        # Slight sleep to avoid busy spin on idle streams
                        time.sleep(0.003)

                except BluetoothError as e:
                    code = _err_code(e)
                    # Common transient: EBADFD (77) or connection reset/timeout -> reconnect
                    print(f"[EMG] recv error {code}: {e}. Reconnecting...")
                    self._safe_close()
                    # Reconnect loop
                    while not self._stop.is_set():
                        try:
                            self._connect_once()
                            break
                        except Exception as e2:
                            print(f"[EMG] reconnect failed: {e2}. Retrying in {self.reconnect_backoff_s}s...")
                            time.sleep(self.reconnect_backoff_s)

                except Exception as e:
                    # Unknown error -> attempt reconnect as well
                    print(f"[EMG] unexpected error: {e}. Reconnecting...")
                    self._safe_close()
                    while not self._stop.is_set():
                        try:
                            self._connect_once()
                            break
                        except Exception as e2:
                            print(f"[EMG] reconnect failed: {e2}. Retrying in {self.reconnect_backoff_s}s...")
                            time.sleep(self.reconnect_backoff_s)

        finally:
            self._safe_close()

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
