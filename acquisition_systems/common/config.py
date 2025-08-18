# Configuration loader (YAML/env)
# -*- coding: utf-8 -*-
"""
Minimal configuration with sane defaults.
Environment variables can override defaults when needed.
(Kept dependency-free: no YAML required.)
"""
import os
from dataclasses import dataclass
from typing import List

@dataclass
class Config:
    # EMG
    emg_mac: str = os.getenv("EMG_MAC", "A4:CF:12:96:8B:9E")
    emg_rfcomm_channel: int = int(os.getenv("EMG_RFCOMM_CH", "1"))
    emg_vmin: float = 0.0
    emg_vmax: float = 5.0

    # Force plate (CoP)
    cop_gain: List[float] = None
    cop_x_dist_cm: float = 48.38
    cop_y_dist_cm: float = 33.14
    cop_interval_ms: int = 10

    # Pose
    cam_index: int = int(os.getenv("POSE_CAM_INDEX", "0"))
    cam_width: int = int(os.getenv("POSE_CAM_WIDTH", "640"))
    cam_height: int = int(os.getenv("POSE_CAM_HEIGHT", "480"))
    cam_fps: int = int(os.getenv("POSE_CAM_FPS", "30"))

def load_config() -> Config:
    cfg = Config()
    # Default gains if not provided by env or caller
    if cfg.cop_gain is None:
        cfg.cop_gain = [
            173385.348938015,
            179629.962277708,
            176102.844060932,
            179195.530109193,
        ]
    return cfg