# -*- coding: utf-8 -*-
"""
Recorder for multi-rate acquisition (sEMG ~100 Hz, CoP >= 80 Hz, pose ~camera fps).

- Collects native-rate samples per stream inside the recording window [t0, t_end].
- Native per-stream CSVs keep every sample (lossless).
- The merged CSV uses a deterministic reference timeline: EMG if recorded,
  otherwise CoP, otherwise pose. Other streams are matched "as of" each
  reference time (last sample <= t). Values older than a per-stream tolerance
  become NaN instead of being forward-filled indefinitely. ``pose_t_s`` shows
  which camera frame each row uses.
- All files share one time origin: t0 = start of the recording.

Usage:
  rec.set_window(t0, t_end)
  rec.push_emg(s); rec.push_cop(s); rec.push_pose(s)
  paths = rec.export(out_dir, base_name, metadata={...})
"""
import json
import os
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

import numpy as np

from acquisition_systems.common.types import AngleSample, CopSample, EmgSample, PoseSample
from acquisition_systems.common.dsp import fft_notch

LM_COUNT = 33  # MediaPipe Pose uses 33 landmarks


@dataclass
class RecordingSnapshot:
    emg: List[EmgSample]
    cop: List[CopSample]
    pose: List[PoseSample]
    t0: Optional[float]
    dropped_counts: Dict[str, int] = field(default_factory=dict)


class Recorder:
    def __init__(
        self,
        max_samples_per_stream: int = 1_000_000,
        emg_fs: Optional[float] = None,
        powerline_hz: float = 60.0,
        notch_bandwidth_hz: float = 2.0,
        notch_harmonics: int = 1,
    ):
        if int(max_samples_per_stream) <= 0:
            raise ValueError("max_samples_per_stream must be greater than zero")
        self.max_samples_per_stream = int(max_samples_per_stream)
        self.emg_fs = emg_fs
        self.powerline_hz = powerline_hz
        self.notch_bandwidth_hz = notch_bandwidth_hz
        self.notch_harmonics = notch_harmonics
        self.t0: Optional[float] = None
        self.t_end: Optional[float] = None
        self.clear()

    def clear(self):
        """Start a new recording without retaining samples from prior sessions."""
        self._emg = deque(maxlen=self.max_samples_per_stream)
        self._cop = deque(maxlen=self.max_samples_per_stream)
        self._pose = deque(maxlen=self.max_samples_per_stream)
        self.dropped_counts = {"emg": 0, "cop": 0, "pose": 0}

    def set_window(self, t0: Optional[float], t_end: Optional[float] = None) -> None:
        """Only samples with t0 <= t <= t_end are recorded (perf_counter seconds)."""
        self.t0, self.t_end = t0, t_end

    def _append(self, name: str, buffer, sample) -> None:
        if sample is None:
            return
        if self.t0 is not None and sample.t < self.t0:
            return
        if self.t_end is not None and sample.t > self.t_end:
            return
        if len(buffer) == buffer.maxlen:
            self.dropped_counts[name] += 1
        buffer.append(sample)

    # -------- push APIs --------
    def push_emg(self, s: Optional[EmgSample]):
        self._append("emg", self._emg, s)

    def push_cop(self, s: Optional[CopSample]):
        self._append("cop", self._cop, s)

    def push_pose(self, s: Optional[PoseSample]):
        self._append("pose", self._pose, s)

    def push_angle(self, s: Optional[AngleSample]):
        """Backwards compatibility: angles now travel inside PoseSample."""
        if s is not None:
            self.push_pose(PoseSample(t=s.t, landmarks=np.full((LM_COUNT, 2), np.nan), angle_deg=s.deg))

    def counts(self) -> Dict[str, int]:
        return {"emg": len(self._emg), "cop": len(self._cop), "pose": len(self._pose)}

    def snapshot(self) -> RecordingSnapshot:
        """Copy the buffers (cheap list copies) so export can run in another thread."""
        return RecordingSnapshot(list(self._emg), list(self._cop), list(self._pose), self.t0, dict(self.dropped_counts))

    # -------- export --------
    def export(self, out_dir: str, base_name: str, metadata: Optional[dict] = None,
               snapshot: Optional[RecordingSnapshot] = None) -> Dict[str, str]:
        """Write merged + per-stream CSVs and metadata JSON. Returns {kind: path}."""
        snap = snapshot or self.snapshot()
        base = _safe_base_name(base_name).removesuffix(".csv")
        os.makedirs(out_dir, exist_ok=True)
        paths = {"merged": self._write_merged(snap, os.path.join(out_dir, base + ".csv"))}
        paths.update(self._write_per_stream(snap, out_dir, base))
        meta = dict(metadata or {})
        meta.update(_summary(snap))
        meta_path = os.path.join(out_dir, base + "_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, default=_json_default)
        paths["meta"] = meta_path
        return paths

    def to_csv_merged(
        self,
        out_dir: str,
        base_name: str,
        reference: Literal["auto", "emg", "cop", "pose"] = "auto",
        allow_nan_landmarks: bool = True,
    ) -> str:
        base_name = _safe_base_name(base_name)
        if not base_name.lower().endswith(".csv"):
            base_name += ".csv"
        os.makedirs(out_dir, exist_ok=True)
        return self._write_merged(self.snapshot(), os.path.join(out_dir, base_name), reference)

    def to_csv_per_stream(self, out_dir: str, base_name: str) -> List[str]:
        os.makedirs(out_dir, exist_ok=True)
        base = _safe_base_name(base_name).removesuffix(".csv")
        return list(self._write_per_stream(self.snapshot(), out_dir, base).values())

    # -------- internals --------
    def _origin(self, snap: RecordingSnapshot) -> float:
        if snap.t0 is not None:
            return float(snap.t0)
        firsts = [s[0].t for s in (snap.emg, snap.cop, snap.pose) if s]
        return float(min(firsts)) if firsts else 0.0

    def _emg_arrays(self, emg: List[EmgSample]):
        t = np.array([s.t for s in emg], dtype=float)
        v = np.array([s.value for s in emg], dtype=float)
        notch = _notch_values(t, v, self.emg_fs, self.powerline_hz, self.notch_bandwidth_hz, self.notch_harmonics)
        return t, v, notch

    def _write_merged(self, snap: RecordingSnapshot, path: str, reference: str = "auto") -> str:
        origin = self._origin(snap)
        emg_t, emg_v, emg_n = self._emg_arrays(snap.emg)
        cop_t = np.array([s.t for s in snap.cop], dtype=float)
        pose_t = np.array([s.t for s in snap.pose], dtype=float)

        streams = {"emg": emg_t, "cop": cop_t, "pose": pose_t}
        if reference == "auto":
            reference = next((k for k in ("emg", "cop", "pose") if streams[k].size), "emg")
        ref_t = streams[reference]

        emg_tol = 1.5 * _median_dt(emg_t, 1.0 / (self.emg_fs or 100.0))
        cop_tol = 3.0 * _median_dt(cop_t, 0.0125)
        pose_tol = max(1.0, 3.0 * _median_dt(pose_t, 0.5))
        ei = _asof(emg_t, ref_t, emg_tol)
        ci = _asof(cop_t, ref_t, cop_tol)
        pi = _asof(pose_t, ref_t, pose_tol)

        n = ref_t.size
        cols = {
            "time_s": ref_t - origin,
            "emg_V": _take(emg_v, ei),
            "emg_notch_V": _take(emg_n, ei),
            "cop_x_cm": _take(np.array([s.x for s in snap.cop], float), ci),
            "cop_y_cm": _take(np.array([s.y for s in snap.cop], float), ci),
            "weight_kg": _take(np.array([s.kg for s in snap.cop], float), ci),
            "angle_deg": _take(np.array([s.angle_deg for s in snap.pose], float), pi),
            "pose_t_s": _take(pose_t - origin, pi),
            "pose_detected": _take(np.array([float(s.detected) for s in snap.pose], float), pi),
        }
        cells = np.array([s.cell_kg for s in snap.cop], float).reshape(-1, 4)
        for k in range(4):
            cols[f"cell{k}_kg"] = _take(cells[:, k], ci)
        lms = _landmark_matrix(snap.pose).reshape(len(snap.pose), LM_COUNT * 2)
        lm_cols = np.full((n, LM_COUNT * 2), np.nan)
        valid = pi >= 0
        if lms.size and valid.any():
            lm_cols[valid] = lms[pi[valid]]
        header = list(cols) + [f"lm{i}_{c}" for i in range(LM_COUNT) for c in ("x", "y")]
        table = np.column_stack([cols[k] for k in cols] + [lm_cols]) if n else np.empty((0, len(header)))
        _write_table(path, header, table)
        return path

    def _write_per_stream(self, snap: RecordingSnapshot, out_dir: str, base: str) -> Dict[str, str]:
        origin = self._origin(snap)
        paths = {}
        emg_t, emg_v, emg_n = self._emg_arrays(snap.emg)
        paths["emg"] = os.path.join(out_dir, f"{base}_emg.csv")
        _write_table(paths["emg"], ["time_s", "emg_V", "emg_notch_V"],
                     np.column_stack([emg_t - origin, emg_v, emg_n]) if emg_t.size else np.empty((0, 3)))

        paths["cop"] = os.path.join(out_dir, f"{base}_cop.csv")
        cop_header = ["time_s", "cop_x_cm", "cop_y_cm", "weight_kg", "cell0_kg", "cell1_kg", "cell2_kg", "cell3_kg"]
        cop_rows = np.array([[s.t - origin, s.x, s.y, s.kg, *s.cell_kg] for s in snap.cop], float).reshape(-1, 8)
        _write_table(paths["cop"], cop_header, cop_rows)

        paths["pose"] = os.path.join(out_dir, f"{base}_pose.csv")
        pose_header = (["time_s", "detected", "angle_deg"]
                       + [f"lm{i}_{c}" for i in range(LM_COUNT) for c in ("x", "y")]
                       + [f"lm{i}_vis" for i in range(LM_COUNT)])
        lms = _landmark_matrix(snap.pose).reshape(len(snap.pose), LM_COUNT * 2)
        vis = np.array([_visibility(s) for s in snap.pose], float).reshape(-1, LM_COUNT)
        head = np.array([[s.t - origin, float(s.detected), s.angle_deg] for s in snap.pose], float).reshape(-1, 3)
        _write_table(paths["pose"], pose_header, np.column_stack([head, lms, vis]) if len(snap.pose) else np.empty((0, len(pose_header))))
        return paths


def _write_table(path: str, header: List[str], table: np.ndarray) -> None:
    table = np.asarray(table, dtype=float).reshape(-1, len(header))
    with open(path, "w", newline="") as f:
        f.write(",".join(header) + "\n")
        if table.size:
            np.savetxt(f, table, delimiter=",", fmt="%.7g")


def _median_dt(t: np.ndarray, default: float) -> float:
    if t.size < 2:
        return default
    d = np.diff(t)
    d = d[np.isfinite(d) & (d > 0)]
    return float(np.median(d)) if d.size else default


def _asof(src_t: np.ndarray, ref_t: np.ndarray, tolerance: float) -> np.ndarray:
    """Index of the last source sample <= each reference time, or -1 if none / too old."""
    if src_t.size == 0 or ref_t.size == 0:
        return np.full(ref_t.size, -1, dtype=int)
    idx = np.searchsorted(src_t, ref_t, side="right") - 1
    stale = (idx < 0) | (ref_t - src_t[np.clip(idx, 0, None)] > tolerance)
    idx[stale] = -1
    return idx


def _take(values: np.ndarray, idx: np.ndarray) -> np.ndarray:
    out = np.full(idx.size, np.nan)
    valid = idx >= 0
    if values.size and valid.any():
        out[valid] = values[idx[valid]]
    return out


def _landmark_matrix(pose: List[PoseSample]) -> np.ndarray:
    out = np.full((len(pose), LM_COUNT, 2), np.nan)
    for k, s in enumerate(pose):
        lm = getattr(s, "landmarks", None)
        if lm is not None and getattr(lm, "ndim", 0) == 2 and lm.shape[1] >= 2:
            n = min(LM_COUNT, lm.shape[0])
            out[k, :n] = lm[:n, :2]
    return out


def _visibility(s: PoseSample) -> np.ndarray:
    vis = getattr(s, "visibility", None)
    if vis is None:
        return np.full(LM_COUNT, np.nan)
    out = np.full(LM_COUNT, np.nan)
    v = np.asarray(vis, float).ravel()[:LM_COUNT]
    out[:v.size] = v
    return out


def _summary(snap: RecordingSnapshot) -> dict:
    def rate(ts):
        if len(ts) < 2:
            return 0.0
        return (len(ts) - 1) / max(ts[-1].t - ts[0].t, 1e-9)
    return {
        "samples": {"emg": len(snap.emg), "cop": len(snap.cop), "pose": len(snap.pose)},
        "effective_rate_hz": {"emg": rate(snap.emg), "cop": rate(snap.cop), "pose": rate(snap.pose)},
        "pose_detected_fraction": (sum(s.detected for s in snap.pose) / len(snap.pose)) if snap.pose else 0.0,
        "recorder_dropped": snap.dropped_counts,
    }


def _json_default(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    return str(obj)


def _safe_base_name(base_name: str) -> str:
    """Return a filename component that cannot escape the output directory."""
    name = os.path.basename(str(base_name).strip())
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    if not name or name in {".", ".."}:
        raise ValueError("base_name must contain a valid filename")
    return name


def _notch_values(t: np.ndarray, raw: np.ndarray, fs: Optional[float], powerline_hz: float,
                  bandwidth_hz: float, harmonics: int) -> np.ndarray:
    """Alias-aware FFT notch over the whole native-rate record (no fs threshold)."""
    if raw.size < 8:
        return raw.copy()
    if not fs:
        dt = _median_dt(t, 0.0)
        if dt <= 0:
            return raw.copy()
        fs = 1.0 / dt
    try:
        return fft_notch(raw, fs, powerline_hz, bandwidth_hz, harmonics)
    except (ValueError, RuntimeError):
        return raw.copy()
