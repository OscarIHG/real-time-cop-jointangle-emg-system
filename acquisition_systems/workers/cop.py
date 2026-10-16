# acquisition_systems/workers/cop.py
# -*- coding: utf-8 -*-
"""
CoPWorker: Force-plate acquisition with Phidget22 (PhidgetBridge 1046_1, 4 load cells).
Publishes CopSample(t, x, y, kg, cell_kg) at the bridge data rate into a
bounded queue (every sample is kept for recording; overflow is counted).

- Accepts cop_gain (kg per V/V, manufacturer factor) as a float or four floats.
- One CoP sample per *complete* frame: all four channels must have reported
  since the previous sample, so a CoP never mixes fresh and stale cells.
- Tare: waits for the 1046_1 self-calibration (~3 s after opening) to finish,
  then averages ~1 s of unloaded frames and checks their stability.
- CoP follows the paper's Eqs. (1)-(2) (see utils.cop_from_forces) and is NaN
  when the total load is below ``min_load_kg``.
- Orientation flags: flip_x / flip_y / swap_xy (display mapping only).
"""

import time
import threading
import queue
from collections import deque
from typing import Optional, Sequence, Union, List

import numpy as np

try:
    from Phidget22.Devices.VoltageRatioInput import VoltageRatioInput
except Exception as e:
    VoltageRatioInput = None
    _cop_import_error = e
else:
    _cop_import_error = None

from acquisition_systems.common.types import CopSample
from acquisition_systems.common.utils import RateMeter, cop_from_forces, put_counting

G = 9.81


class CopFrameAssembler:
    """
    Pairs the k-th event of every channel into frame k.

    The bridge samples the four inputs on the same clock, but their Python
    callbacks can arrive late, bunched and out of order when the process is
    busy (GIL contention with the GUI). A per-channel FIFO keeps samples of
    the same period together, giving exactly one frame per data interval.
    If a channel stops reporting, the others are bounded to ``max_lag``
    samples and the overflow is counted as ``incomplete_frames``.
    """

    def __init__(self, channels: int = 4, max_lag: int = 32, interval_s: float = 0.008):
        self.channels = channels
        self.max_lag = max_lag
        self.interval_s = interval_s
        self._fifo = [deque() for _ in range(channels)]
        # Handlers are attached once all channels are open, so FIFOs start
        # aligned (within one period). Time-based re-alignment is only used
        # after a channel stalled, because callback times are unreliable
        # under GIL contention.
        self._synced = True
        self.incomplete_frames = 0

    def _align_heads(self) -> None:
        """Drop leading samples older than the newest head: aligns the first common period."""
        latest = max(f[0][1] for f in self._fifo)
        for f in self._fifo:
            while len(f) > 1 and f[0][1] < latest - 0.5 * self.interval_s:
                f.popleft()
                self.incomplete_frames += 1
        self._synced = True

    def update(self, idx: int, value: float, t: float):
        fifo = self._fifo[idx]
        fifo.append((float(value), t))
        if len(fifo) > self.max_lag:
            fifo.popleft()
            self.incomplete_frames += 1
            self._synced = False   # a channel stalled: re-align when it comes back
        if all(self._fifo):
            if not self._synced:
                self._align_heads()
            items = [f.popleft() for f in self._fifo]
            # The earliest callback is the closest to the true sampling instant.
            return [v for v, _ in items], min(ts for _, ts in items)
        return None


class CoPWorker:
    """
    Start/stop lifecycle:
      w = CoPWorker(gain=200000.0, x_dist_cm=48.38, y_dist_cm=33.04, data_interval_ms=8)
      w.start()        # opens the bridge and tares (plate must be unloaded)
      ... read w.queue ...
      w.tare()         # re-zero at any time with the plate unloaded
      w.stop()
    """
    def __init__(
        self,
        gain: Union[float, Sequence[float]],
        x_dist_cm: float,
        y_dist_cm: float,
        data_interval_ms: int = 8,
        offsets: Optional[Sequence[float]] = None,
        flip_x: bool = False,
        flip_y: bool = False,
        swap_xy: bool = False,
        bridge_gain: int = 128,
        min_load_kg: float = 5.0,
        cell_capacity_kg: float = 200.0,
        queue_size: int = 20000,
    ):
        if VoltageRatioInput is None:
            raise ImportError(f"Phidget22 is required for CoPWorker: {_cop_import_error}")

        # Normalize gain to 4 channels
        if isinstance(gain, (int, float)):
            self.gain: List[float] = [float(gain)] * 4
        elif isinstance(gain, (list, tuple)):
            if len(gain) != 4:
                raise ValueError("cop_gain must be a float or a list/tuple of 4 floats (one per channel).")
            self.gain = [float(g) for g in gain]
        else:
            raise ValueError("cop_gain must be a float or a list/tuple of 4 floats.")

        self.dt_ms = max(1, int(data_interval_ms))
        self.x_dist_cm = float(x_dist_cm)   # distance between load-cell centres (long axis)
        self.y_dist_cm = float(y_dist_cm)   # distance between load-cell centres (short axis)
        self.bridge_gain = int(bridge_gain)
        self.min_load_kg = float(min_load_kg)
        self.cell_capacity_kg = float(cell_capacity_kg)

        # Orientation flags
        self.flip_x = bool(flip_x)
        self.flip_y = bool(flip_y)
        self.swap_xy = bool(swap_xy)

        self.queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self.dropped_samples = 0
        self.rate = RateMeter()
        self.warnings: List[str] = []
        self.actual_interval_ms: Optional[int] = None
        self.tare_info: Optional[dict] = None
        self.overload = False
        self._stop = threading.Event()
        self._state_lock = threading.RLock()
        self._assembler = CopFrameAssembler(4, interval_s=self.dt_ms / 1000.0)
        self._tare_frames: Optional[list] = None

        # Four Phidget channels (0..3). Handlers are attached only after all
        # four are open, so the per-channel event FIFOs start together.
        self._ch = [VoltageRatioInput() for _ in range(4)]
        for i, c in enumerate(self._ch):
            c.setChannel(i)

        self._offset = [0.0, 0.0, 0.0, 0.0]
        self._calibrated = False
        if offsets is not None:
            if not isinstance(offsets, (list, tuple)) or len(offsets) != 4:
                raise ValueError("offsets must be a list/tuple of 4 floats if provided.")
            self._offset = [float(o) for o in offsets]
            self._calibrated = True

    @property
    def offsets(self) -> List[float]:
        with self._state_lock:
            return list(self._offset)

    # ---------- handlers ----------
    def _on_vr(self, ch: "VoltageRatioInput", vr: float):
        if self._stop.is_set():
            return
        t = time.perf_counter()
        idx = ch.getChannel()
        with self._state_lock:
            frame = self._assembler.update(idx, vr, t)
            if frame is None:
                return
            ratios, t_frame = frame
            if self._tare_frames is not None:
                self._tare_frames.append(ratios)
                return
            if not self._calibrated:
                return
            cell_kg = tuple((r - o) * g for r, o, g in zip(ratios, self._offset, self.gain))

        kg_total = float(sum(cell_kg))
        cop1, cop2, _ = cop_from_forces(
            [kg * G for kg in cell_kg], self.x_dist_cm, self.y_dist_cm, min_fz=self.min_load_kg * G
        )
        copx, copy = cop1, cop2
        if self.swap_xy:
            copx, copy = copy, copx
        if self.flip_x:
            copx = -copx
        if self.flip_y:
            copy = -copy
        self.overload = max(cell_kg) > self.cell_capacity_kg

        sample = CopSample(t=t_frame, x=copx, y=copy, kg=kg_total, cell_kg=cell_kg)
        if not put_counting(self.queue, sample):
            self.dropped_samples += 1
        self.rate.tick(1, t_frame)

    # ---------- tare ----------
    def tare(self, duration_s: float = 1.0, timeout_s: float = 8.0, max_std_kg: float = 0.5) -> dict:
        """
        Zero the plate (must be unloaded). Waits for valid frames, discards the
        first one, averages ``duration_s`` of frames and reports their spread.
        """
        with self._state_lock:
            self._tare_frames = []
        started = None
        deadline = time.monotonic() + timeout_s
        try:
            while time.monotonic() < deadline:
                with self._state_lock:
                    n = len(self._tare_frames)
                    if started is None and n > 0:
                        self._tare_frames.clear()   # first valid data: calibration finished
                        started = time.monotonic()
                if started is not None and time.monotonic() - started >= duration_s:
                    break
                time.sleep(0.02)
        finally:
            with self._state_lock:
                frames, self._tare_frames = self._tare_frames, None
        if not frames or len(frames) < 5:
            raise RuntimeError("tare failed: the PhidgetBridge delivered no valid data")

        arr = np.asarray(frames, dtype=float)
        offsets = arr.mean(axis=0)
        std_kg = arr.std(axis=0) * np.abs(np.asarray(self.gain))
        stable = bool(np.all(std_kg <= max_std_kg))
        with self._state_lock:
            self._offset = [float(o) for o in offsets]
            self._calibrated = True
        self.tare_info = {
            "offsets": [float(o) for o in offsets],
            "std_kg": [float(s) for s in std_kg],
            "frames": int(arr.shape[0]),
            "stable": stable,
        }
        if not stable:
            msg = f"tare not stable (std kg per cell = {np.round(std_kg, 3).tolist()}); is the plate unloaded?"
            self.warnings.append(msg)
            print(f"[CoP] WARNING: {msg}")
        return self.tare_info

    # ---------- public API ----------
    def _configure_channel(self, c) -> None:
        try:
            from Phidget22.BridgeGain import BridgeGain
            c.setBridgeGain(getattr(BridgeGain, f"BRIDGE_GAIN_{self.bridge_gain}"))
        except Exception as exc:
            self.warnings.append(f"bridge gain not set: {exc}")
        for setter, value in (("setBridgeEnabled", True), ("setVoltageRatioChangeTrigger", 0.0)):
            try:
                getattr(c, setter)(value)
            except Exception as exc:
                self.warnings.append(f"{setter} failed: {exc}")
        interval = self.dt_ms
        try:
            interval = max(interval, int(c.getMinDataInterval()))
        except Exception:
            pass
        c.setDataInterval(interval)
        try:
            self.actual_interval_ms = int(c.getDataInterval())
        except Exception:
            self.actual_interval_ms = interval

    def start(self, tare: bool = True):
        self._stop.clear()
        try:
            for c in self._ch:
                c.openWaitForAttachment(5000)
                self._configure_channel(c)
            with self._state_lock:
                self._assembler = CopFrameAssembler(4, interval_s=(self.actual_interval_ms or self.dt_ms) / 1000.0)
            for c in self._ch:
                c.setOnVoltageRatioChangeHandler(self._on_vr)
            if tare and not self._calibrated:
                self.tare()
        except Exception:
            self.stop()
            raise

    def stop(self):
        self._stop.set()
        for c in self._ch:
            try:
                c.close()
            except Exception:
                pass
