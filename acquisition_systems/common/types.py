# Data types: EmgSample, CopSample, PoseSample, AngleSample
# -*- coding: utf-8 -*-
"""
Typed sample payloads passed from workers to the GUI/recorder.
Keep these small and immutable-like (dataclasses).
"""
from dataclasses import dataclass
import numpy as np

@dataclass
class EmgSample:
    t: float       # timestamp in seconds (perf_counter)
    value: float   # voltage between 0 and 5 V

@dataclass
class CopSample:
    t: float       # timestamp in seconds
    x: float       # CoP anteroposterior position (cm)
    y: float       # CoP mediolateral position (cm)
    kg: float      # total mass estimate in kilograms

@dataclass
class PoseSample:
    t: float
    landmarks: np.ndarray   # shape (33,2) float32 array of pixels

@dataclass
class AngleSample:
    t: float
    deg: float              # pelvic obliquity angle (hip 23–24) in degrees
