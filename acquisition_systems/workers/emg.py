# EMGWorker (ESP32-compatible, connect in a background thread)
# -*- coding: utf-8 -*-
"""
EMGWorker: Bluetooth EMG acquisition over RFCOMM (no UI, no file I/O).

Transports (all expose open/read/write/close; read returns b"" on timeout and
raises ConnectionError when the link is gone):
  * RfcommTransport      native socket.AF_BLUETOOTH (Linux)
  * BridgeTransport      /usr/bin/python3 helper when this Python lacks AF_BLUETOOTH
  * SerialTransport      pyserial COM port (Windows)
  * SimulatedEsp32Transport  synthetic 100 Hz sEMG (see emg_sim.py)

With ``source="auto"`` the worker falls back to the simulator when the ESP32
cannot be reached at connect time (never mid-session, so real and simulated
data are not mixed). ``source`` reports what was actually used.
"""

import os
import re
import select
import socket
import subprocess
import sys
import threading
import time
import queue
from collections import deque
from typing import List, Optional

from acquisition_systems.common.types import EmgSample
from acquisition_systems.common.utils import RateMeter, put_counting
from acquisition_systems.workers.emg_sim import SimulatedEsp32Transport


def _dbg(msg: str):
    if os.environ.get("EMG_DEBUG") == "1":
        print(f"[EMG] {msg}")


_NUMBER = re.compile(rb"^[+-]?\d+(?:\.\d+)?$")


class LineParser:
    """
    Frames the ESP32 text stream ("0.1234\\r\\n" per sample).

    The first fragment after connecting is discarded because the stream may
    start mid-line ("312\\r\\n" out of "0.0312\\r\\n"); clamping such garbage to
    vmax produced the spike at t=0 seen in the paper's Fig. 3. Malformed and
    out-of-range lines are rejected and counted instead of clamped.
    """

    def __init__(self, vmin: float = 0.0, vmax: float = 3.3, tolerance: float = 0.05,
                 allow_lf: bool = True, drop_first_fragment: bool = True):
        self.vmin, self.vmax, self.tolerance = float(vmin), float(vmax), float(tolerance)
        self.allow_lf = allow_lf
        self.drop_first_fragment = drop_first_fragment
        self.reset()

    def reset(self) -> None:
        self._tail = b""
        self._synced = not self.drop_first_fragment
        self.parse_errors = 0
        self.out_of_range = 0

    def feed(self, chunk: bytes) -> List[float]:
        if not chunk:
            return []
        data = self._tail + chunk
        parts = data.split(b"\n") if self.allow_lf else data.split(b"\r\n")
        self._tail = parts[-1]
        if len(self._tail) > 64:  # no delimiter in a long run: garbage
            self._tail = b""
            self.parse_errors += 1
        lines = parts[:-1]
        if not self._synced and lines:
            lines = lines[1:]
            self._synced = True
        values = []
        for raw in lines:
            text = raw.strip()
            if not text:
                continue
            if not _NUMBER.match(text):
                self.parse_errors += 1
                continue
            v = float(text)
            if v < self.vmin - self.tolerance or v > self.vmax + self.tolerance:
                self.out_of_range += 1
                continue
            values.append(min(self.vmax, max(self.vmin, v)))
        return values


class RfcommTransport:
    name = "bluetooth"

    def __init__(self, mac: str, channel: int, connect_timeout: float = 5.0):
        self.mac, self.channel, self.connect_timeout = mac, int(channel), float(connect_timeout)
        self.sock: Optional[socket.socket] = None

    def open(self) -> None:
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(self.connect_timeout)
        try:
            sock.connect((self.mac, self.channel))
        except OSError:
            sock.close()
            raise
        sock.settimeout(0.2)
        self.sock = sock

    def read(self, max_bytes: int = 4096, timeout: float = 0.2) -> bytes:
        if self.sock is None:
            raise ConnectionError("socket closed")
        try:
            data = self.sock.recv(max_bytes)
        except socket.timeout:
            return b""
        except OSError as exc:
            raise ConnectionError(f"RFCOMM recv failed: {exc}") from exc
        if not data:
            raise ConnectionError("RFCOMM peer closed the connection")
        return data

    def write(self, data: bytes) -> None:
        if self.sock is not None:
            self.sock.sendall(data)

    def close(self) -> None:
        sock, self.sock = self.sock, None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()


# Constant program text: user/configuration values are passed as argv, never
# interpolated into Python source.
_BRIDGE_SCRIPT = r"""
import socket, sys, threading
mac, channel, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
sock.settimeout(timeout)
sock.connect((mac, channel))
sock.settimeout(0.2)
sys.stderr.write("CONNECTED\n"); sys.stderr.flush()

def forward_commands():
    while True:
        command = sys.stdin.buffer.read1(4096)
        if not command:
            return
        try:
            sock.sendall(command)
        except OSError:
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


class BridgeTransport:
    """RFCOMM through the system Python (micromamba/conda builds lack AF_BLUETOOTH)."""

    name = "bluetooth"

    def __init__(self, mac: str, channel: int, connect_timeout: float = 5.0, python: str = "/usr/bin/python3"):
        self.mac, self.channel, self.connect_timeout, self.python = mac, int(channel), float(connect_timeout), python
        self.proc: Optional[subprocess.Popen] = None
        self.stderr_tail: deque = deque(maxlen=50)
        self._connected = threading.Event()

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        for line in iter(proc.stderr.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            if text == "CONNECTED":
                self._connected.set()
            else:
                self.stderr_tail.append(text)

    def open(self) -> None:
        self.proc = subprocess.Popen(
            [self.python, "-c", _BRIDGE_SCRIPT, self.mac, str(self.channel), str(self.connect_timeout)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        threading.Thread(target=self._drain_stderr, args=(self.proc,), daemon=True).start()
        deadline = time.monotonic() + self.connect_timeout + 2.0
        while time.monotonic() < deadline:
            if self._connected.wait(0.05):
                return
            if self.proc.poll() is not None:
                break
        detail = self.stderr_tail[-1] if self.stderr_tail else "timeout"
        self.close()
        raise ConnectionError(f"Bluetooth bridge could not connect: {detail}")

    def read(self, max_bytes: int = 4096, timeout: float = 0.2) -> bytes:
        proc = self.proc
        if proc is None:
            raise ConnectionError("bridge closed")
        fd = proc.stdout.fileno()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            if proc.poll() is not None:
                raise ConnectionError("bridge exited")
            return b""
        data = os.read(fd, max_bytes)
        if not data:
            raise ConnectionError("bridge closed the stream: " + (self.stderr_tail[-1] if self.stderr_tail else "EOF"))
        return data

    def write(self, data: bytes) -> None:
        if self.proc is not None and self.proc.stdin:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except Exception:
            proc.kill()


class SerialTransport:
    name = "bluetooth"

    def __init__(self, port: str):
        self.port = port
        self.conn = None

    def open(self) -> None:
        import serial
        self.conn = serial.Serial(self.port, 115200, timeout=0.2, write_timeout=0.2)

    def read(self, max_bytes: int = 4096, timeout: float = 0.2) -> bytes:
        if self.conn is None:
            raise ConnectionError("serial port closed")
        try:
            waiting = self.conn.in_waiting
            return self.conn.read(min(max_bytes, waiting) if waiting else 1)
        except Exception as exc:
            raise ConnectionError(f"serial read failed: {exc}") from exc

    def write(self, data: bytes) -> None:
        if self.conn is not None:
            self.conn.write(data)

    def close(self) -> None:
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.cancel_read()
            except Exception:
                pass
            conn.close()


class EMGWorker:
    """
    Start/stop lifecycle:
        w = EMGWorker(mac_address="A4:CF:12:96:8B:9E", sample_rate_hz=100, source="auto")
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
        sample_rate_hz: float = 100.0,
        queue_size: int = 10000,
        source: str = "bluetooth",
        connect_timeout_s: float = 5.0,
        transport=None,
    ):
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be greater than zero")
        if source not in ("auto", "bluetooth", "simulated"):
            raise ValueError("source must be auto, bluetooth or simulated")
        self.mac = mac_address
        self.com_port = com_port
        self.chan = int(rfcomm_channel)
        self.vmin = float(clamp_min)
        self.vmax = float(clamp_max)
        self.start_token = start_token
        self.stop_token = stop_token
        self.sample_rate_hz = float(sample_rate_hz)
        self.sample_interval = 1.0 / float(sample_rate_hz)
        self.requested_source = source
        self.connect_timeout_s = float(connect_timeout_s)
        self._transport_override = transport

        self.queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self.dropped_samples = 0
        self.source: Optional[str] = None      # what is actually streaming
        self.error: Optional[str] = None
        self.connected = threading.Event()
        self.finished = threading.Event()
        self.rate = RateMeter()
        self.parser = LineParser(self.vmin, self.vmax)
        self._transport = None
        self._io_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sample_clock: Optional[float] = None

    @property
    def parse_errors(self) -> int:
        return self.parser.parse_errors + self.parser.out_of_range

    # ---------- connection ----------
    def _bluetooth_transport(self):
        if sys.platform == "win32":
            return SerialTransport(self.com_port)
        if hasattr(socket, "AF_BLUETOOTH"):
            return RfcommTransport(self.mac, self.chan, self.connect_timeout_s)
        _dbg("AF_BLUETOOTH missing in this Python. Using the system Python bridge.")
        return BridgeTransport(self.mac, self.chan, self.connect_timeout_s)

    def _simulated_transport(self):
        return SimulatedEsp32Transport(self.sample_rate_hz, self.start_token, self.stop_token)

    def _open_transport(self):
        if self._transport_override is not None:
            transport = self._transport_override
            transport.open()
            return transport
        if self.requested_source == "simulated":
            transport = self._simulated_transport()
            transport.open()
            return transport
        transport = self._bluetooth_transport()
        try:
            transport.open()
            return transport
        except Exception as exc:
            if self.requested_source != "auto":
                raise
            print(f"[EMG] WARNING: ESP32 not reachable ({exc}). Falling back to the simulated sEMG source.")
            transport = self._simulated_transport()
            transport.open()
            return transport

    # ---------- main loop (read only) ----------
    def _loop(self):
        try:
            transport = self._open_transport()
        except Exception as exc:
            self.error = f"connect failed: {exc}"
            print(f"[EMG] {self.error}")
            self.finished.set()
            return
        with self._io_lock:
            self._transport = transport
            if self._stop.is_set():
                self._close_transport()
                self.finished.set()
                return
            self.source = getattr(transport, "name", "bluetooth")
            # LF splitting also handles CRLF, so ALLOW_LF no longer changes framing.
            self.parser = LineParser(self.vmin, self.vmax)
            if self.start_token:
                transport.write(self.start_token.encode("utf-8"))
        self.connected.set()
        _dbg(f"Streaming from {self.source}")

        try:
            while not self._stop.is_set():
                vals = self.parser.feed(transport.read(4096, timeout=0.2))
                if not vals:
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
                    if not put_counting(self.queue, EmgSample(t=t, value=v)):
                        self.dropped_samples += 1
                self.rate.tick(len(vals), batch_end)
        except ConnectionError as exc:
            if not self._stop.is_set():
                self.error = str(exc)
                print(f"[EMG] link lost: {exc}")
        finally:
            with self._io_lock:
                self._close_transport()
            self._sample_clock = None
            self.finished.set()

    def _close_transport(self):
        """Send the stop token first, then close (caller holds _io_lock)."""
        transport, self._transport = self._transport, None
        if transport is None:
            return
        if self.stop_token:
            try:
                transport.write(self.stop_token.encode("utf-8"))
                time.sleep(0.05)
            except Exception as exc:
                _dbg(f"Stop token send failed (ignored): {exc}")
        try:
            transport.close()
        except Exception as exc:
            _dbg(f"Close failed (ignored): {exc}")

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
        self.connected.clear()
        self.finished.clear()
        self.dropped_samples = 0
        self.error = None
        self._thread = threading.Thread(target=self._loop, name="emg-reader", daemon=True)
        self._thread.start()
        _dbg("Reader thread started.")

    def wait_ready(self, timeout: float) -> bool:
        """Block until streaming started (True) or the connection failed/timed out (False)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.connected.is_set():
                return True
            if self.finished.is_set():
                return False
            time.sleep(0.02)
        return self.connected.is_set()

    def stop(self):
        self._stop.set()
        # Closing the transport (after the stop token) wakes a blocking read,
        # so stop() has a bounded latency.
        with self._io_lock:
            self._close_transport()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        _dbg("Stopped.")
