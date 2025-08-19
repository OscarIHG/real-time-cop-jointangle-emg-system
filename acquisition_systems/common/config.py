# -*- coding: utf-8 -*-
"""
Config loader for acquisition systems.
Reads config.yaml at repo root; provides sane defaults if keys are missing.
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Dict

import yaml


@dataclass
class Config:
    # EMG
    emg_mac: str = "00:00:00:00:00:00"
    emg_rfcomm_channel: int = 1
    emg_vmin: float = 0.0
    emg_vmax: float = 5.0
    emg_allow_lf: bool = False
    emg_start_token: str = "1"
    emg_stop_token: str = "2"
    cop_flip_x: bool = False
    cop_flip_y: bool = False
    cop_swap_xy: bool = False
    # CoP (worker inputs and GUI ranges)
    cop_gain: Any = 1.0            # was float; now Any to accept list[float] or float
    cop_x_dist_cm: float = 55.84
    cop_y_dist_cm: float = 40.64
    cop_x_half_range_cm: float = 27.92
    cop_y_half_range_cm: float = 20.32
    cop_interval_ms: int = 10

    # Camera / Pose
    cam_index: int = 0
    cam_width: int = 640
    cam_height: int = 480
    cam_fps: int = 30

    # Plot (GUI)
    emg_plot_window: int = 200
    angle_plot_window: int = 50


def _repo_root() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir))  # repository root


def _load_yaml(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                return {}
            return data
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def load_config() -> Config:
    # Look for config.yaml in the repository root
    root = _repo_root()
    ypath = os.path.join(root, "config.yaml")
    data = _load_yaml(ypath)

    cfg = Config()

    # EMG
    cfg.emg_mac           = str(data.get("emg_mac", cfg.emg_mac))
    cfg.emg_rfcomm_channel = int(data.get("emg_rfcomm_channel", cfg.emg_rfcomm_channel))
    cfg.emg_vmin          = float(data.get("emg_vmin", cfg.emg_vmin))
    cfg.emg_vmax          = float(data.get("emg_vmax", cfg.emg_vmax))
    cfg.emg_allow_lf      = bool(data.get("emg_allow_lf", cfg.emg_allow_lf))
    cfg.emg_start_token   = str(data.get("emg_start_token", cfg.emg_start_token))
    cfg.emg_stop_token    = str(data.get("emg_stop_token", cfg.emg_stop_token))
    cfg.cop_flip_x = bool(data.get("cop_flip_x", cfg.cop_flip_x))
    cfg.cop_flip_y = bool(data.get("cop_flip_y", cfg.cop_flip_y))
    cfg.cop_swap_xy = bool(data.get("cop_swap_xy", cfg.cop_swap_xy))

    # CoP (accepts total distances or half ranges; derive missing values if needed)
    raw_gain = data.get("cop_gain", cfg.cop_gain)
    # Normalize: accept a float or a list/tuple of four values
    if isinstance(raw_gain, (int, float)):
        cfg.cop_gain = float(raw_gain)                 # single gain for the four cells
    elif isinstance(raw_gain, (list, tuple)):
        cfg.cop_gain = [float(g) for g in raw_gain]    # list of four gains
    else:
        cfg.cop_gain = 1.0                             # safe fallback

    x_half = data.get("cop_x_half_range_cm", cfg.cop_x_half_range_cm)
    y_half = data.get("cop_y_half_range_cm", cfg.cop_y_half_range_cm)
    x_dist = data.get("cop_x_dist_cm", None)
    y_dist = data.get("cop_y_dist_cm", None)
    cfg.cop_x_half_range_cm = float(x_half)
    cfg.cop_y_half_range_cm = float(y_half)
    cfg.cop_x_dist_cm = float(x_dist) if x_dist is not None else 2.0 * float(x_half)
    cfg.cop_y_dist_cm = float(y_dist) if y_dist is not None else 2.0 * float(y_half)
    cfg.cop_interval_ms = int(data.get("cop_interval_ms", cfg.cop_interval_ms))


    # Camera / Pose
    cfg.cam_index = int(data.get("cam_index", cfg.cam_index))
    cfg.cam_width = int(data.get("cam_width", cfg.cam_width))
    cfg.cam_height = int(data.get("cam_height", cfg.cam_height))
    cfg.cam_fps = int(data.get("cam_fps", cfg.cam_fps))

    # Plot
    cfg.emg_plot_window = int(data.get("emg_plot_window", cfg.emg_plot_window))
    cfg.angle_plot_window = int(data.get("angle_plot_window", cfg.angle_plot_window))

    return cfg
