# -*- coding: utf-8 -*-
"""
Center of Pressure worker for GUI integration (PhidgetBridge 4-ch)
- Opens 4 VoltageRatioInput channels, tares, and streams forces
- Computes CoP (AP=x, ML=y) and total weight
- Pushes latest values to thread-safe Queues for real-time plotting

Dependency: Phidget22
"""

import time
import threading
import queue
from Phidget22.Devices.VoltageRatioInput import VoltageRatioInput

# Plate geometry (cm) and calibration (example values)
X_DIST = 48.38
Y_DIST = 33.14
GAIN = [173385.348938015, 179629.962277708, 176102.844060932, 179195.530109193]


class CoPWorker:
    def __init__(self, data_interval_ms: int = 10):
        """Prepare but do not open yet."""
        self.dt_ms = data_interval_ms
        self.offset = [0.0, 0.0, 0.0, 0.0]
        self.calibrated = [False, False, False, False]
        self.ch = [VoltageRatioInput() for _ in range(4)]
        for i, c in enumerate(self.ch):
            c.setChannel(i)
            c.setOnVoltageRatioChangeHandler(self._on_vr)

        # Outputs (thread-safe)
        self.copx_q = queue.Queue()
        self.copy_q = queue.Queue()
        self.kg_q = queue.Queue()

        self._stop = threading.Event()

    def _on_vr(self, self_ch, voltage_ratio):
        """Phidget callback: compute CoP when channel 3 updates."""
        idx = self_ch.getChannel()
        if not self.calibrated[idx]:
            return

        kg = (voltage_ratio - self.offset[idx]) * GAIN[idx]
        # Keep a tiny buffer per channel in attributes to compute CoP
        if not hasattr(self, "_kg"):
            self._kg = [0.0, 0.0, 0.0, 0.0]
            self._n = [0.0, 0.0, 0.0, 0.0]
        self._kg[idx] = kg
        self._n[idx] = kg * 9.81

        # Recompute CoP once ch3 ticks (all channels update similarly)
        if idx == 3:
            f_total = sum(self._n)
            kg_total = sum(self._kg)

            # Moments (signs per standard 4-cell plate)
            m1 = -self._n[0] - self._n[3] + self._n[1] + self._n[2]
            m2 =  self._n[2] + self._n[3] - self._n[0] - self._n[1]

            if f_total < 1e-9:
                copx = 0.0
                copy = 0.0
            else:
                copx = (X_DIST / 2.0) * (m1 / f_total)  # AP
                copy = (Y_DIST / 2.0) * (m2 / f_total)  # ML

            # Non-blocking publish (drop if queue is full)
            for q, v in ((self.copx_q, copx), (self.copy_q, copy), (self.kg_q, kg_total)):
                try:
                    q.put_nowait(v)
                except queue.Full:
                    pass

    def _tare(self, samples: int = 16):
        """Average several samples per channel to get offsets."""
        for _ in range(samples):
            for c in self.ch:
                i = c.getChannel()
                self.offset[i] += c.getVoltageRatio()
                time.sleep(c.getDataInterval() / 1000.0)
        for i in range(4):
            self.offset[i] /= samples
            self.calibrated[i] = True

    def start(self):
        """Open channels, set data interval, tare."""
        self._stop.clear()
        for c in self.ch:
            c.openWaitForAttachment(5000)
        # Set a uniform interval
        for c in self.ch:
            c.setDataInterval(self.dt_ms)
        # Tare once
        self._tare()

    def stop(self):
        """Close channels cleanly."""
        self._stop.set()
        for c in self.ch:
            try:
                c.close()
            except Exception:
                pass
