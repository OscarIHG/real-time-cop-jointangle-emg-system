# CoPWorker (acquisition only)
# -*- coding: utf-8 -*-
"""
CoPWorker: Force-plate acquisition with Phidget22 (4 load cells).
Publishes CopSample(t, x, y, kg) to a single-item queue (latest only).
"""
import time
import threading
import queue
from typing import Optional, List

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
      w = CoPWorker(gain=[...], x_dist_cm=..., y_dist_cm=...)
      w.start(); ... read w.queue ... ; w.stop()
    """
    def __init__(self, gain: List[float], x_dist_cm: float, y_dist_cm: float, data_interval_ms: int = 10):
        if VoltageRatioInput is None:
            raise ImportError(f"Phidget22 is required for CoPWorker: {_cop_import_error}")

        assert len(gain) == 4, "gain must be length-4 list for channels 0..3"
        self.gain = gain
        self.dt_ms = data_interval_ms
        self.x_dist_cm = x_dist_cm
        self.y_dist_cm = y_dist_cm

        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()

        self._ch = [VoltageRatioInput() for _ in range(4)]
        for i, c in enumerate(self._ch):
            c.setChannel(i)
            c.setOnVoltageRatioChangeHandler(self._on_vr)

        # state
        self._offset = [0.0, 0.0, 0.0, 0.0]
        self._kg = [0.0, 0.0, 0.0, 0.0]
        self._n = [0.0, 0.0, 0.0, 0.0]
        self._cal = [False, False, False, False]

    def _on_vr(self, ch: "VoltageRatioInput", vr: float):
        idx = ch.getChannel()
        if not self._cal[idx]:
            return
        kg = (vr - self._offset[idx]) * self.gain[idx]
        self._kg[idx] = kg
        self._n[idx] = kg * 9.81

        # Recompute CoP when any channel updates (all update often)
        f_total = sum(self._n)
        kg_total = sum(self._kg)
        if f_total <= 1e-9:
            copx = 0.0
            copy = 0.0
        else:
            m1 = -self._n[0] - self._n[3] + self._n[1] + self._n[2]  # AP
            m2 =  self._n[2] + self._n[3] - self._n[0] - self._n[1]  # ML
            copx = (self.x_dist_cm / 2.0) * (m1 / f_total)
            copy = (self.y_dist_cm / 2.0) * (m2 / f_total)

        put_latest(self.queue, CopSample(t=time.perf_counter(), x=copx, y=copy, kg=kg_total))

    def _tare(self, samples: int = 16):
        # Average several samples per channel to get offsets
        for _ in range(samples):
            for c in self._ch:
                i = c.getChannel()
                self._offset[i] += c.getVoltageRatio()
                time.sleep(c.getDataInterval() / 1000.0)
        for i in range(4):
            self._offset[i] /= samples
            self._cal[i] = True

    # ------------ public API ------------
    def start(self):
        self._stop.clear()
        for c in self._ch:
            c.openWaitForAttachment(5000)
        for c in self._ch:
            c.setDataInterval(self.dt_ms)
        self._tare()

    def stop(self):
        self._stop.set()
        for c in self._ch:
            try:
                c.close()
            except Exception:
                pass
