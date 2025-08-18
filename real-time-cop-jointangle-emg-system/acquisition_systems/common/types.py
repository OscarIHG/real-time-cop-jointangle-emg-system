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
    t: float       # seconds (perf_counter)
    value: float   # volts 0..5

@dataclass
class CopSample:
    t: float       # seconds
    x: float       # CoP AP (cm)
    y: float       # CoP ML (cm)
    kg: float      # total mass estimate (kg)

@dataclass
class PoseSample:
    t: float
    landmarks: np.ndarray   # shape (33,2), float32 pixels

@dataclass
class AngleSample:
    t: float
    deg: float              # pelvic obliquity (hip 23–24) in degrees