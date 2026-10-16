# -*- coding: utf-8 -*-
"""
Synthetic sEMG source used while the AD8232 front-end is not connected.

``EmgSignalModel`` is mirrored line by line in the ESP32 firmware
(esp32_firmware/esp32_firmware.ino with EMG_SIMULATED=1 and
esp32_firmware/emg_simulator/emg_simulator.ino), including the xorshift32
generator, so the fallback below produces the same sequence as the board
(up to float32 rounding). Keep the constants of both in sync.

Signal = DC offset
       + tonic activity: rectified, smoothed Gaussian noise (standing at rest)
       + periodic bursts: raised-cosine envelope with stochastic modulation
       + deliberate 60 Hz power-line interference (aliases to 40 Hz at 100 Hz)
"""

import math
import time
from typing import Callable, List

FS_HZ = 100.0
SEED = 0x1234ABCD
DC_OFFSET_V = 0.30
TONIC_SIGMA_V = 0.04
TONIC_SMOOTH_HZ = 5.0
BURST_START_S = 2.0
BURST_PERIOD_S = 5.0
BURST_DURATION_S = 1.0
BURST_AMPLITUDE_V = 1.2
BURST_MOD_SMOOTH_HZ = 8.0
BURST_MOD_DEPTH = 0.3
MAINS_HZ = 60.0
MAINS_AMPLITUDE_V = 0.10
VMIN_V = 0.0
VMAX_V = 3.3


class Xorshift32:
    """32-bit xorshift PRNG (Marsaglia 2003), identical to the firmware version."""

    def __init__(self, seed: int = SEED):
        self.state = (seed & 0xFFFFFFFF) or 1

    def next_u32(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x

    def uniform(self) -> float:
        """Uniform in [0, 1) with 24-bit resolution."""
        return (self.next_u32() >> 8) * (1.0 / 16777216.0)

    def gauss(self) -> float:
        """Unit-variance Gaussian approximation (Irwin-Hall, 4 uniforms)."""
        s = self.uniform() + self.uniform() + self.uniform() + self.uniform()
        return (s - 2.0) * math.sqrt(3.0)


class EmgSignalModel:
    """Deterministic synthetic sEMG envelope sampled at ``fs`` Hz (volts, 0..3.3)."""

    def __init__(self, fs: float = FS_HZ, seed: int = SEED):
        self.fs = float(fs)
        self.seed = seed
        self._a_tonic = 1.0 - math.exp(-2.0 * math.pi * TONIC_SMOOTH_HZ / self.fs)
        self._a_mod = 1.0 - math.exp(-2.0 * math.pi * BURST_MOD_SMOOTH_HZ / self.fs)
        self.reset()

    def reset(self) -> None:
        self.n = 0
        self._rng = Xorshift32(self.seed)
        self._tonic = TONIC_SIGMA_V * math.sqrt(2.0 / math.pi)  # start at the rectified mean
        self._mod = 0.0

    def next_sample(self) -> float:
        n = self.n
        self.n += 1
        t = n / self.fs

        g_tonic = self._rng.gauss()
        g_mod = self._rng.gauss()
        self._tonic += self._a_tonic * (abs(g_tonic) * TONIC_SIGMA_V - self._tonic)
        self._mod += self._a_mod * (g_mod - self._mod)

        burst = 0.0
        if t >= BURST_START_S:
            phase = math.fmod(t - BURST_START_S, BURST_PERIOD_S)
            if phase < BURST_DURATION_S:
                envelope = 0.5 * (1.0 - math.cos(2.0 * math.pi * phase / BURST_DURATION_S))
                burst = BURST_AMPLITUDE_V * envelope * max(0.0, 1.0 + BURST_MOD_DEPTH * self._mod)

        cycles = math.fmod(MAINS_HZ * n / self.fs, 1.0)
        mains = MAINS_AMPLITUDE_V * math.sin(2.0 * math.pi * cycles)

        v = DC_OFFSET_V + self._tonic + burst + mains
        return min(VMAX_V, max(VMIN_V, v))

    def generate(self, count: int) -> List[float]:
        return [self.next_sample() for _ in range(int(count))]


class SimulatedEsp32Transport:
    """
    Emulates the ESP32 Bluetooth SPP byte stream: waits for the start token,
    then emits ``"%.4f\\r\\n"`` lines paced by the wall clock at ``fs`` Hz
    (n_due = floor((t - t0) * fs) + 1, so the average rate never drifts) and
    stops on the stop token, exactly like the firmware.
    """

    name = "simulated"

    def __init__(
        self,
        fs: float = FS_HZ,
        start_token: str = "1",
        stop_token: str = "2",
        seed: int = SEED,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
        decimals: int = 4,
    ):
        self.fs = float(fs)
        self.model = EmgSignalModel(fs, seed)
        self.start_token = start_token
        self.stop_token = stop_token
        self._clock = clock
        self._sleep = sleep
        self._fmt = f"%.{int(decimals)}f\r\n"
        self._open = False
        self._streaming = False
        self._t0 = 0.0
        self._sent = 0

    def open(self) -> None:
        self._open = True

    def write(self, data: bytes) -> None:
        if not self._open:
            raise ConnectionError("simulated transport is closed")
        for ch in data.decode("utf-8", errors="ignore"):
            if self.start_token and ch == self.start_token:
                self.model.reset()
                self._t0 = self._clock()
                self._sent = 0
                self._streaming = True
            elif self.stop_token and ch == self.stop_token:
                self._streaming = False

    def read(self, max_bytes: int = 4096, timeout: float = 0.2) -> bytes:
        if not self._open:
            raise ConnectionError("simulated transport is closed")
        if not self._streaming:
            self._sleep(min(timeout, 0.01))
            return b""
        deadline = self._clock() + timeout
        while True:
            now = self._clock()
            due = int((now - self._t0) * self.fs) + 1
            if due > self._sent:
                break
            next_time = self._t0 + self._sent / self.fs
            if next_time >= deadline:
                self._sleep(max(0.0, deadline - now))
                return b""
            self._sleep(max(0.0, next_time - now))
        max_lines = max(1, int(max_bytes) // 8)
        count = min(due - self._sent, max_lines)
        lines = "".join(self._fmt % self.model.next_sample() for _ in range(count))
        self._sent += count
        return lines.encode("ascii")

    def close(self) -> None:
        self._open = False
        self._streaming = False
