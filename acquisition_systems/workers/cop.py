# acquisition_systems/workers/cop.py
# -*- coding: utf-8 -*-
"""
CoPWorker: Force-plate acquisition with Phidget22 (4 load cells).
Publishes CopSample(t, x, y, kg) to a single-item queue (latest only).

- Accepts cop_gain as a float (replicated to 4 channels) or a list/tuple of four floats.
- Performs automatic tare on start by averaging several readings.
- Computes CoP in centimeters using x_dist_cm / y_dist_cm as total width/height.
- Orientation flags: flip_x / flip_y / swap_xy.
"""

import time
import threading
import queue
from typing import Optional, Sequence, Union, List

try:
    from Phidget22.Devices.VoltageRatioInput import VoltageRatioInput
except Exception as e:
    VoltageRatioInput = None
    _cop_import_error = e
else:
    _cop_import_error = None

from acquisition_systems.common.types import CopSample
from acquisition_systems.common.utils import put_latest


class CoPWorker:
    """
    Start/stop lifecycle:
      w = CoPWorker(gain=1.0, x_dist_cm=55.84, y_dist_cm=40.64, data_interval_ms=10,
                    flip_x=False, flip_y=False, swap_xy=False)
      w.start(); ... read w.queue ... ; w.stop()
    """
    def __init__(
        self,
        gain: Union[float, Sequence[float]],
        x_dist_cm: float,
        y_dist_cm: float,
        data_interval_ms: int = 10,
        offsets: Optional[Sequence[float]] = None,
        flip_x: bool = False,
        flip_y: bool = False,
        swap_xy: bool = False,
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

        self.dt_ms = int(data_interval_ms)
        self.x_dist_cm = float(x_dist_cm)   # total width
        self.y_dist_cm = float(y_dist_cm)   # total height

        # Orientation flags
        self.flip_x = bool(flip_x)
        self.flip_y = bool(flip_y)
        self.swap_xy = bool(swap_xy)

        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()

        # Four Phidget channels (0..3)
        self._ch = [VoltageRatioInput() for _ in range(4)]
        for i, c in enumerate(self._ch):
            c.setChannel(i)
            c.setOnVoltageRatioChangeHandler(self._on_vr)

        # State
        self._offset = [0.0, 0.0, 0.0, 0.0]
        if offsets is not None:
            if not isinstance(offsets, (list, tuple)) or len(offsets) != 4:
                raise ValueError("offsets must be a list/tuple of 4 floats if provided.")
            self._offset = [float(o) for o in offsets]

        self._kg = [0.0, 0.0, 0.0, 0.0]
        self._n  = [0.0, 0.0, 0.0, 0.0]
        self._cal = [False, False, False, False]  # tare completed

    # ---------- handlers ----------
    def _on_vr(self, ch: "VoltageRatioInput", vr: float):
        idx = ch.getChannel()
        if not self._cal[idx]:
            return

        kg = (vr - self._offset[idx]) * self.gain[idx]
        self._kg[idx] = kg
        self._n[idx]  = kg * 9.81  # Newtons

        # Recalculate CoP with each update
        f_total = sum(self._n)
        kg_total = sum(self._kg)
        if f_total <= 1e-9:
            copx = 0.0
            copy = 0.0
        else:
            # Cell convention:
            #  0 ----- 1
            #  |       |
            #  3 ----- 2
            m_ap = -self._n[0] - self._n[3] + self._n[1] + self._n[2]  # anteroposterior
            m_ml =  self._n[2] + self._n[3] - self._n[0] - self._n[1]  # mediolateral
            copx = (self.x_dist_cm / 2.0) * (m_ap / f_total)
            copy = (self.y_dist_cm / 2.0) * (m_ml / f_total)

        # Apply orientation flags
        if self.swap_xy:
            copx, copy = copy, copx
        if self.flip_x:
            copx = -copx
        if self.flip_y:
            copy = -copy

        put_latest(self.queue, CopSample(t=time.perf_counter(), x=copx, y=copy, kg=kg_total))

    def _tare(self, samples: int = 16):
        """
        Average 'samples' readings per channel to estimate voltage offset.
        If offsets were provided in __init__, simply mark as calibrated.
        """
        if any(self._offset):
            for i in range(4):
                self._cal[i] = True
            return

        dt = max(0.001, self.dt_ms / 1000.0)
        self._offset = [0.0, 0.0, 0.0, 0.0]

        for _ in range(samples):
            for c in self._ch:
                i = c.getChannel()
                try:
                    self._offset[i] += c.getVoltageRatio()
                except Exception:
                    self._offset[i] += 0.0
            time.sleep(dt)

        for i in range(4):
            self._offset[i] /= float(samples)
            self._cal[i] = True

    # ---------- public API ----------
    def start(self):
        self._stop.clear()
        for c in self._ch:
            c.openWaitForAttachment(5000)
            c.setDataInterval(self.dt_ms)
        self._tare()

    def stop(self):
        self._stop.set()
        for c in self._ch:
            try:
                c.close()
            except Exception:
                pass