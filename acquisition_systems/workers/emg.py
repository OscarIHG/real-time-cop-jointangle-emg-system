# EMGWorker (ESP32-compatible, connect in main thread)
# -*- coding: utf-8 -*-
"""
EMGWorker: Bluetooth EMG acquisition over RFCOMM (no UI, no file I/O).
Uses Python's native socket module (AF_BLUETOOTH), eliminating the need for PyBluez.

Config expectations:
  mac_address: "A4:CF:12:96:8B:9E"
  rfcomm_channel: 1
  clamp_min/max: 0.0..5.0
"""

import os
import sys
import time
import threading
import queue
import socket
from typing import Optional
import numpy as np

try:
    import scipy.signal as signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from acquisition_systems.common.types import EmgSample
from acquisition_systems.common.utils import put_latest

def _dbg(msg: str):
    if os.environ.get("EMG_DEBUG") == "1":
        print(f"[EMG] {msg}")

class EMGWorker:
    """
    Start/stop lifecycle:
        w = EMGWorker(mac_address="A4:CF:12:96:8B:9E", com_port="COM3", rfcomm_channel=1)
        w.start(); ... read w.queue ... ; w.stop()
    """
    ALLOW_LF = False

    def __init__(
        self,
        mac_address: str,
        com_port: str = "COM3",
        rfcomm_channel: int = 1,
        clamp_min: float = 0.0,
        clamp_max: float = 5.0,
        start_token: str = "1",
        stop_token: str = "2",
    ):
        self.mac = mac_address
        self.com_port = com_port
        self.chan = int(rfcomm_channel)
        self.vmin = float(clamp_min)
        self.vmax = float(clamp_max)
        self.start_token = start_token
        self.stop_token = stop_token

        self.sock: Optional[socket.socket] = None
        self.serial_conn = None
        self.queue: queue.Queue = queue.Queue(maxsize=10000)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tail = b""  # partial line buffer across recv() calls

        # Filter initialization
        if HAS_SCIPY:
            self.b_notch, self.a_notch = signal.iirnotch(60.0, 30.0, fs=1000.0)
            self.b_low, self.a_low = signal.butter(6, 10.0, btype='low', fs=1000.0)
            self.zi_notch = signal.lfilter_zi(self.b_notch, self.a_notch) * 0.0
            self.zi_low = signal.lfilter_zi(self.b_low, self.a_low) * 0.0

    # ---------- connection ----------
    def _connect(self):
        if sys.platform == "win32":
            import serial
            _dbg(f"Connecting Serial to {self.com_port} (Windows) ...")
            try:
                self.serial_conn = serial.Serial(self.com_port, 115200, timeout=1.0)
                _dbg("Connected. Sending start token...")
                if self.start_token:
                    self.serial_conn.write(self.start_token.encode('utf-8'))
            except Exception as e:
                _dbg(f"Serial Connection failed: {e}")
                raise
        else:
            _dbg(f"Connecting RFCOMM to {self.mac} ch {self.chan} (Linux) ...")
            # Native Bluetooth socket (Linux only)
            try:
                self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                self.sock.connect((self.mac, self.chan))
                _dbg("Connected. Sending start token...")
                if self.start_token:
                    self.sock.send(self.start_token.encode('utf-8'))
            except AttributeError:
                _dbg("AF_BLUETOOTH missing in Conda Python. Using system Python bridge...")
                import subprocess
                bridge_script = f"""
import sys, socket, threading
try:
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.connect(('{self.mac}', {self.chan}))
    if '{self.start_token}':
        s.send('{self.start_token}'.encode('utf-8'))
    
    def read_stdin():
        while True:
            cmd = sys.stdin.buffer.read(1)
            if not cmd: break
            s.send(cmd)
            
    threading.Thread(target=read_stdin, daemon=True).start()
    
    while True:
        data = s.recv(4096)
        if not data: break
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
"""
                self._bridge_proc = subprocess.Popen(
                    ["/usr/bin/python3", "-c", bridge_script],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            except Exception as e:
                _dbg(f"Connection or start token send failed: {e}")
                raise

    def _read_bytes(self, size: int) -> bytes:
        if self.serial_conn:
            try:
                return self.serial_conn.read(size)
            except Exception as e:
                _dbg(f"Serial read Error: {e}")
                raise
        elif self.sock:
            try:
                return self.sock.recv(size)
            except Exception as e:
                _dbg(f"Socket recv Error: {e}")
                raise
        elif hasattr(self, '_bridge_proc') and self._bridge_proc:
            try:
                return self._bridge_proc.stdout.read1(size)
            except Exception as e:
                _dbg(f"Bridge read Error: {e}")
                raise
        return b""

    # ---------- framing & parsing ----------
    def _recv_floats_crlf(self) -> list[float]:
        """Read a chunk and parse CRLF-separated floats."""
        chunk = self._read_bytes(4096)
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
        chunk = self._read_bytes(4096)
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
            self._connect()
        except Exception as e:
            _dbg(f"Background connect failed: {e}")
            return

        try:
            while not self._stop.is_set():
                vals = self._recv_floats_crlf()
                if self.ALLOW_LF and not vals:
                    vals = self._recv_floats_lf()

                if not vals:
                    time.sleep(0.001)  # gentle idle
                    continue

                t = time.perf_counter()
                
                if HAS_SCIPY:
                    chunk = np.array(vals)
                    filt_1, self.zi_notch = signal.lfilter(self.b_notch, self.a_notch, chunk, zi=self.zi_notch)
                    filt_2, self.zi_low = signal.lfilter(self.b_low, self.a_low, filt_1, zi=self.zi_low)
                    env = np.abs(signal.hilbert(filt_2))
                    filtered_vals = env.tolist()
                else:
                    filtered_vals = vals

                for v, f in zip(vals, filtered_vals):
                    try:
                        self.queue.put_nowait(EmgSample(t=t, value=v, filtered=f))
                    except queue.Full:
                        pass # if we fall behind, drop oldest or ignore. Ignoring is safer here.
        finally:
            self._safe_close()

    def _safe_close(self):
        try:
            if self.start_token and self.stop_token:
                _dbg("Sending stop token...")
                try:
                    if self.serial_conn:
                        self.serial_conn.write(self.stop_token.encode('utf-8'))
                    elif self.sock:
                        self.sock.send(self.stop_token.encode('utf-8'))
                    elif hasattr(self, '_bridge_proc') and self._bridge_proc:
                        self._bridge_proc.stdin.write(self.stop_token.encode('utf-8'))
                        self._bridge_proc.stdin.flush()
                    time.sleep(0.2)
                except Exception as e:
                    _dbg(f"Stop token send failed (ignored): {e}")
        finally:
            try:
                if self.serial_conn:
                    _dbg("Closing serial port.")
                    self.serial_conn.close()
                if self.sock:
                    _dbg("Closing socket.")
                    self.sock.close()
                if hasattr(self, '_bridge_proc') and self._bridge_proc:
                    _dbg("Terminating system bridge.")
                    self._bridge_proc.terminate()
            except Exception as e:
                _dbg(f"Close failed (ignored): {e}")
            self.sock = None
            self.serial_conn = None
            self._bridge_proc = None

    # ---------- public API ----------
    def start(self):
        """Start background reader which connects asynchronously."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        _dbg("Reader thread started.")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        _dbg("Stopped.")