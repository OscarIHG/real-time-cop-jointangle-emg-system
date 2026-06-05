# -*- coding: utf-8 -*-
"""
Recorder for multi-rate acquisition:
- Collects native-rate samples per stream (EMG, CoP, Pose, Angle).
- Exports a merged CSV aligned to a reference timeline (auto = densest).
  Alignment uses "asof" (last-known <= t) with forward fill.
- Optionally you can also export per-stream CSVs if needed later.

Usage in GUI:
  rec.push_emg(emg)   # only when new EMG sample arrives
  rec.push_cop(cop)   # only when new CoP sample arrives
  rec.push_pose(pose) # only when new Pose landmarks arrive
  rec.push_angle(ang) # only when new Angle sample arrives
  rec.to_csv_merged(out_dir, base_name, reference="auto")
"""
import os
import csv
import math
from typing import Optional, List, Literal
import numpy as np

from acquisition_systems.common.types import EmgSample, CopSample, PoseSample, AngleSample

LM_COUNT = 33  # MediaPipe Pose uses 33 landmarks


class Recorder:
    def __init__(self):
        # Buffers storing samples at their original sampling rate
        self._emg: List[EmgSample] = []
        self._cop: List[CopSample] = []
        self._pose: List[PoseSample] = []
        self._ang: List[AngleSample] = []

    # -------- push APIs (call only when a new sample is available) --------
    def push_emg(self, s: Optional[EmgSample]):  # sample is (timestamp, value)
        if s is not None:
            self._emg.append(s)

    def push_cop(self, s: Optional[CopSample]):  # sample is (timestamp, x, y, kg)
        if s is not None:
            self._cop.append(s)

    def push_pose(self, s: Optional[PoseSample]):  # sample is (timestamp, landmarks(33,2))
        if s is not None:
            self._pose.append(s)

    def push_angle(self, s: Optional[AngleSample]):  # sample is (timestamp, degrees)
        if s is not None:
            self._ang.append(s)

    # -------- export merged streams --------
    def to_csv_merged(
        self,
        out_dir: str,
        base_name: str,
        reference: Literal["auto", "emg", "cop", "pose", "angle"] = "auto",
        allow_nan_landmarks: bool = True,
    ) -> str:
        """
        Build a single wide CSV aligned to a reference stream timeline.
        - reference="auto" -> picks densest (most samples).
        - reference in {"emg","cop","pose","angle"} -> use that stream times.
        - Forward-fills last-known values (asof); if none yet, writes NaN.
        - Landmarks are 33*2 columns (x,y) padded with NaN if missing.

        Returns: full file path saved.
        """
        if not base_name.lower().endswith(".csv"):
            base_name += ".csv"
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, base_name)

        # Pick the reference timeline
        ref_name, ref_times = self._choose_reference(reference)

        # Prepare iterators; assume timestamps never decrease
        emg_i = cop_i = pose_i = ang_i = -1
        emg_last = cop_last = pose_last = ang_last = None

        header = ["time_s", "emg_V", "emg_filtered_V", "cop_x_cm", "cop_y_cm", "weight_kg", "angle_deg"]
        for i in range(LM_COUNT):
            header += [f"lm{i}_x", f"lm{i}_y"]

        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)

            # Pre-extract arrays of timestamps for quick traversal
            emg_t = np.array([s.t for s in self._emg], dtype=float)
            cop_t = np.array([s.t for s in self._cop], dtype=float)
            pose_t = np.array([s.t for s in self._pose], dtype=float)
            ang_t = np.array([s.t for s in self._ang], dtype=float)

            for t in ref_times:
                # Advance each stream up to time <= current t
                if emg_t.size:
                    # Indices increase strictly; advance while next timestamp <= t
                    while emg_i + 1 < emg_t.size and emg_t[emg_i + 1] <= t:
                        emg_i += 1
                        emg_last = self._emg[emg_i]
                if cop_t.size:
                    while cop_i + 1 < cop_t.size and cop_t[cop_i + 1] <= t:
                        cop_i += 1
                        cop_last = self._cop[cop_i]
                if pose_t.size:
                    while pose_i + 1 < pose_t.size and pose_t[pose_i + 1] <= t:
                        pose_i += 1
                        pose_last = self._pose[pose_i]
                if ang_t.size:
                    while ang_i + 1 < ang_t.size and ang_t[ang_i + 1] <= t:
                        ang_i += 1
                        ang_last = self._ang[ang_i]

                # Create a row using the most recent samples
                emg_v = _f(emg_last.value) if emg_last else float("nan")
                emg_f = _f(emg_last.filtered) if emg_last else float("nan")
                cop_x = _f(cop_last.x) if cop_last else float("nan")
                cop_y = _f(cop_last.y) if cop_last else float("nan")
                cop_kg = _f(cop_last.kg) if cop_last else float("nan")
                ang_d = _f(ang_last.deg) if ang_last else float("nan")

                lm = np.full((LM_COUNT, 2), np.nan, dtype=float)
                if pose_last is not None and getattr(pose_last.landmarks, "ndim", 0) == 2 and pose_last.landmarks.shape[1] >= 2:
                    n = min(LM_COUNT, pose_last.landmarks.shape[0])
                    lm[:n, :2] = pose_last.landmarks[:n, :2]

                row = [float(t), emg_v, emg_f, cop_x, cop_y, cop_kg, ang_d]
                row.extend(lm.reshape(-1).tolist())
                w.writerow(row)

        return path

    # -------- export helpers for individual streams --------
    def to_csv_per_stream(self, out_dir: str, base_name: str) -> List[str]:
        """
        Save one CSV per stream at their native rates.
        Returns: list of file paths.
        """
        os.makedirs(out_dir, exist_ok=True)
        files = []

        def save(path, header, rows):
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
            files.append(path)

        # EMG stream
        emg_rows = [[_f(s.t), _f(s.value), _f(s.filtered)] for s in self._emg]
        save(os.path.join(out_dir, f"{base_name}_emg.csv"), ["time_s", "emg_V", "emg_filtered_V"], emg_rows)

        # CoP stream
        cop_rows = [[_f(s.t), _f(s.x), _f(s.y), _f(s.kg)] for s in self._cop]
        save(os.path.join(out_dir, f"{base_name}_cop.csv"), ["time_s", "cop_x_cm", "cop_y_cm", "weight_kg"], cop_rows)

        # Angle stream
        ang_rows = [[_f(s.t), _f(s.deg)] for s in self._ang]
        save(os.path.join(out_dir, f"{base_name}_angle.csv"), ["time_s", "angle_deg"], ang_rows)

        # Pose landmarks
        lm_header = ["time_s"] + [f"lm{i}_{c}" for i in range(LM_COUNT) for c in ("x", "y")]
        lm_rows = []
        for s in self._pose:
            lm = np.full((LM_COUNT, 2), np.nan, dtype=float)
            if s.landmarks is not None and getattr(s.landmarks, "ndim", 0) == 2 and s.landmarks.shape[1] >= 2:
                n = min(LM_COUNT, s.landmarks.shape[0])
                lm[:n, :2] = s.landmarks[:n, :2]
            lm_rows.append([_f(s.t)] + lm.reshape(-1).tolist())
        save(os.path.join(out_dir, f"{base_name}_landmarks.csv"), lm_header, lm_rows)

        return files

    # -------- internals --------
    def _choose_reference(self, reference: str):
        if reference == "emg":
            ref = self._emg
        elif reference == "cop":
            ref = self._cop
        elif reference == "pose":
            ref = self._pose
        elif reference == "angle":
            ref = self._ang
        else:
            # Automatically pick the stream with the most samples
            candidates = [("emg", self._emg), ("cop", self._cop), ("pose", self._pose), ("angle", self._ang)]
            ref_name, ref = max(candidates, key=lambda kv: len(kv[1]))
            return ref_name, np.array([s.t for s in ref], dtype=float)

        return reference, np.array([s.t for s in ref], dtype=float)


def _f(x):
    try:
        return float(x)
    except Exception:
        return float("nan")
