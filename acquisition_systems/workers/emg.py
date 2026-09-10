# EMGWorker (ESP32-compatible, connect in main thread)
# -*- coding: utf-8 -*-
"""
EMGWorker: Bluetooth EMG acquisition over RFCOMM (no UI, no file I/O).
Uses Python's native socket module (AF_BLUETOOTH), eliminating the need for PyBluez.

Config expectations:
  mac_address: "A4:CF:12:96:8B:9E"
  rfcomm_channel: 1
  clamp_min/max: 0.0..3.3
"""

import os
import sys
import time
import threading
import queue
import socket
from typing import Optional

from acquisition_systems.common.types import EmgSample
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
        clamp_max: float = 3.3,
        start_token: str = "1",
        stop_token: str = "2",
        sample_rate_hz: float = 1000.0,
        queue_size: int = 10000,
    ):
        self.mac = mac_address
        self.com_port = com_port
        self.chan = int(rfcomm_channel)
        self.vmin = float(clamp_min)
        self.vmax = float(clamp_max)
        self.start_token = start_token
        self.stop_token = stop_token
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be greater than zero")
        self.sample_interval = 1.0 / float(sample_rate_hz)

        self.sock: Optional[socket.socket] = None
        self.serial_conn = None
        self._bridge_proc = None
        self.queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self.dropped_samples = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tail = b""  # partial line buffer across recv() calls
        self._sample_clock: Optional[float] = None

    # ---------- connection ----------
    def _connect(self):
        if sys.platform == "win32":
            import serial
            _dbg(f"Connecting Serial to {self.com_port} (Windows) ...")
            try:
                self.serial_conn = serial.Serial(self.com_port, 115200, timeout=0.2, write_timeout=0.2)
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
                self.sock.settimeout(5.0)
                self.sock.connect((self.mac, self.chan))
                self.sock.settimeout(0.2)
                _dbg("Connected. Sending start token...")
                if self.start_token:
                    self.sock.sendall(self.start_token.encode('utf-8'))
            except AttributeError:
                _dbg("AF_BLUETOOTH missing in this Python. Using a parameterized system Python bridge...")
                import subprocess
                # Keep the program text constant. User/configuration values are
                # passed as argv, never interpolated into Python source.
                bridge_script = r"""
import socket
import sys
import threading

mac, channel, start_token = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
sock.settimeout(0.2)
sock.connect((mac, channel))
if start_token:
    sock.sendall(start_token.encode("utf-8"))

def forward_commands():
    while True:
        command = sys.stdin.buffer.read(4096)
        if not command:
            return
        try:
            sock.sendall(command)
        except (OSError, socket.timeout):
            return

threading.Thread(target=forward_commands, daemon=True).start()
while True:
    try:
        data = sock.recv(4096)
    except socket.timeout:
        continue
    if not data:
        break
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
"""
                self._bridge_proc = subprocess.Popen(
                    ["/usr/bin/python3", "-c", bridge_script, self.mac, str(self.chan), self.start_token],
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
            except socket.timeout:
                return b""
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
            self._safe_close()
            return

        try:
            while not self._stop.is_set():
                vals = self._recv_floats_crlf()
                if self.ALLOW_LF and not vals:
                    vals = self._recv_floats_lf()

                if not vals:
                    time.sleep(0.001)  # gentle idle
                    continue

                batch_end = time.perf_counter()
                if self._sample_clock is None:
                    self._sample_clock = batch_end - (len(vals) - 1) * self.sample_interval
                elif batch_end - self._sample_clock > max(1.0, len(vals) * self.sample_interval * 10):
                    # Resynchronise after a transport interruption without
                    # assigning one identical timestamp to an entire batch.
                    self._sample_clock = batch_end - (len(vals) - 1) * self.sample_interval

                for v in vals:
                    t = self._sample_clock
                    self._sample_clock += self.sample_interval
                    try:
                        self.queue.put_nowait(EmgSample(t=t, value=v))
                    except queue.Full:
                        # Preserve the newest measurement and make data loss
                        # observable instead of silently discarding it.
                        try:
                            self.queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self.queue.put_nowait(EmgSample(t=t, value=v))
                        except queue.Full:
                            pass
                        self.dropped_samples += 1
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
                        self.sock.sendall(self.stop_token.encode('utf-8'))
                    elif self._bridge_proc and self._bridge_proc.stdin:
                        self._bridge_proc.stdin.write(self.stop_token.encode('utf-8'))
                        self._bridge_proc.stdin.flush()
                    time.sleep(0.05)
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
                if self._bridge_proc:
                    _dbg("Terminating system bridge.")
                    self._bridge_proc.terminate()
            except Exception as e:
                _dbg(f"Close failed (ignored): {e}")
            self.sock = None
            self.serial_conn = None
            self._bridge_proc = None
            self._sample_clock = None

    # ---------- public API ----------
    def start(self):
        """Start background reader which connects asynchronously."""
        if self._thread and self._thread.is_alive():
            return
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self._stop.clear()
        self.dropped_samples = 0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        _dbg("Reader thread started.")

    def stop(self):
        self._stop.set()
        # Closing the transport is the wake-up mechanism for a blocking
        # recv/read. Do it before join so stop() has a bounded latency.
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):
            pass
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        try:
            if self.serial_conn:
                self.serial_conn.cancel_read()
                self.serial_conn.close()
        except (AttributeError, OSError):
            pass
        if self._bridge_proc:
            try:
                self._bridge_proc.terminate()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        _dbg("Stopped.")