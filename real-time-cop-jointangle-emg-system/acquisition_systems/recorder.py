# Recorder for CSV/Parquet (no UI)
# -*- coding: utf-8 -*-
"""
Recorder: builds a single wide table combining EMG, CoP, Angle, and Landmarks.
- Append rows with add(now, emg, cop, pose, ang) using last-known (forward-fill)
- Save to CSV with to_csv(path)
"""
import csv
from typing import Optional
import numpy as np

from acquisition_systems.common.types import EmgSample, CopSample, PoseSample, AngleSample

LM_COUNT = 33  # MediaPipe Pose


class Recorder:
    def __init__(self):
        # last-known values
        self._emg: Optional[EmgSample] = None
        self._cop: Optional[CopSample] = None
        self._pose: Optional[PoseSample] = None
        self._ang: Optional[AngleSample] = None

        self._rows: list[list[float]] = []
        self._header = self._build_header()

    def _build_header(self):
        header = ["time_s", "emg_V", "cop_x_cm", "cop_y_cm", "weight_kg", "angle_deg"]
        for i in range(LM_COUNT):
            header += [f"lm{i}_x", f"lm{i}_y"]
        return header

    @staticmethod
    def _f(x):
        try:
            return float(x)
        except Exception:
            return float("nan")

    def add(self, time_s: float,
            emg: Optional[EmgSample],
            cop: Optional[CopSample],
            pose: Optional[PoseSample],
            ang: Optional[AngleSample]):
        """Append one row combining current latest samples with forward-fill."""
        if emg: self._emg = emg
        if cop: self._cop = cop
        if pose: self._pose = pose
        if ang: self._ang = ang

        emg_v = self._f(self._emg.value) if self._emg else float("nan")
        cop_x = self._f(self._cop.x) if self._cop else float("nan")
        cop_y = self._f(self._cop.y) if self._cop else float("nan")
        cop_kg = self._f(self._cop.kg) if self._cop else float("nan")
        ang_d = self._f(self._ang.deg) if self._ang else float("nan")

        # Landmarks padded to LM_COUNT
        lm = np.full((LM_COUNT, 2), np.nan, dtype=float)
        if self._pose is not None and getattr(self._pose.landmarks, "ndim", 0) == 2 and self._pose.landmarks.shape[1] >= 2:
            n = min(LM_COUNT, self._pose.landmarks.shape[0])
            lm[:n, :2] = self._pose.landmarks[:n, :2]

        row = [self._f(time_s), emg_v, cop_x, cop_y, cop_kg, ang_d]
        row.extend(lm.reshape(-1).tolist())
        self._rows.append(row)

    def to_csv(self, path: str):
        if not path.lower().endswith(".csv"):
            path += ".csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(self._header)
            w.writerows(self._rows)
        return path
