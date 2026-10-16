# Data types: EmgSample, CopSample, PoseSample
# -*- coding: utf-8 -*-
"""
Typed sample payloads passed from workers to the coordinator/recorder.
Keep these small and immutable-like (dataclasses). All timestamps come from
time.perf_counter() (a monotonic clock shared by every thread and process).
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np


@dataclass
class EmgSample:
    t: float       # timestamp in seconds (perf_counter)
    value: float   # voltage between 0 and 3.3 V


@dataclass
class CopSample:
    t: float       # timestamp in seconds
    x: float       # CoP along the long plate axis (cm); NaN when the plate is unloaded
    y: float       # CoP along the short plate axis (cm); NaN when the plate is unloaded
    kg: float      # total mass estimate in kilograms
    cell_kg: Tuple[float, float, float, float] = (float("nan"),) * 4  # CH0..CH3 (F1..F4)


@dataclass
class PoseSample:
    t: float                         # capture time of the frame
    landmarks: np.ndarray            # shape (33,2) float32 array of pixels (NaN when not detected)
    angle_deg: float = float("nan")  # pelvic obliquity (hip 23 -> 24)
    detected: bool = True
    visibility: Optional[np.ndarray] = field(default=None, repr=False)  # shape (33,)
    frame_size: Tuple[int, int] = (640, 480)                            # (width, height)


@dataclass
class AngleSample:
    """Kept for backwards compatibility; new code reads PoseSample.angle_deg."""
    t: float
    deg: float              # pelvic obliquity angle (hip 23–24) in degrees
