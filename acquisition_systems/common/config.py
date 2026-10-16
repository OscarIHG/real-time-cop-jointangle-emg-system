# -*- coding: utf-8 -*-
"""
Config loader for acquisition systems.
Reads config.yaml at repo root; provides sane defaults if keys are missing.

Defaults follow the published paper (CNIB 2025): sEMG at ~100 Hz with a
real-time 60 Hz FFT notch, CoP at >= 80 Hz from a 55.88 x 40.54 cm plate whose
load-cell centres are 48.38 x 33.04 cm apart, MediaPipe Pose at 640x480.
"""

from __future__ import annotations
import os
import math
from dataclasses import dataclass, asdict
from typing import Any, Dict

import yaml


@dataclass
class Config:
    # GUI
    gui_backend: str = "qt"            # qt (PyQtGraph, fastest) | tk (Tkinter + Matplotlib, as in the paper)
    gui_update_ms: int = 33

    # EMG
    emg_source: str = "auto"           # auto | bluetooth | simulated
    emg_mac: str = "00:00:00:00:00:00"
    emg_com_port: str = "COM3"
    emg_rfcomm_channel: int = 1
    emg_vmin: float = 0.0
    emg_vmax: float = 3.3
    emg_allow_lf: bool = False
    emg_start_token: str = "1"
    emg_stop_token: str = "2"
    emg_sample_rate_hz: float = 100.0
    emg_connect_timeout_s: float = 5.0
    emg_powerline_hz: float = 60.0
    emg_notch_method: str = "fft"      # fft (paper: FFT -> remove -> IFFT) | iir (streaming)
    emg_notch_bandwidth_hz: float = 2.0
    emg_notch_harmonics: int = 1

    # CoP (worker inputs and GUI ranges)
    cop_gain: Any = 200000.0           # kg per V/V; float or list of four (sign allowed)
    cop_x_dist_cm: float = 48.38       # distance between load-cell centres, long axis (x in the paper)
    cop_y_dist_cm: float = 33.04       # distance between load-cell centres, short axis (y in the paper)
    cop_x_half_range_cm: float = 27.94 # GUI limits (paper Fig. 3)
    cop_y_half_range_cm: float = 20.32
    cop_interval_ms: int = 8
    cop_bridge_gain: int = 128
    cop_min_load_kg: float = 5.0
    cop_cell_capacity_kg: float = 200.0
    cop_flip_x: bool = True
    cop_flip_y: bool = True
    cop_swap_xy: bool = False
    recording_max_samples_per_stream: int = 1_000_000

    # Camera / Pose
    cam_backend: str = "auto"          # auto | opencv | rpicam | file
    cam_index: int = 0
    cam_width: int = 640
    cam_height: int = 480
    cam_fps: int = 30
    cam_rotation: int = 0              # 0 | 90 | 180 | 270 (physical mounting)
    cam_hflip: bool = False
    cam_file: str = ""                 # image/video replayed when cam_backend == "file"
    cam_constant_fps: bool = False     # UVC: disable exposure_dynamic_framerate (more fps, darker in dim light)
    pose_min_visibility: float = 0.5

    # MediaPipe
    mediapipe_model_complexity: int = 0
    mediapipe_min_detection_confidence: float = 0.7
    mediapipe_min_tracking_confidence: float = 0.5
    mediapipe_smooth_landmarks: bool = True
    mediapipe_enable_segmentation: bool = False
    mediapipe_smooth_segmentation: bool = False
    mediapipe_static_image_mode: bool = False

    # Plot (GUI)
    emg_plot_window: float = 5.0       # seconds
    angle_plot_window: float = 40.0    # seconds
    angle_plot_limit_deg: float = 40.0


def _repo_root() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir))  # repository root


class ConfigError(ValueError):
    """Raised when the configuration file cannot be loaded or is invalid."""


def _coerce_bool(value: Any, *, field: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "on", "1"}:
            return True
        if normalized in {"false", "no", "n", "off", "0"}:
            return False
    raise ConfigError(
        f"{field} must be a boolean (true/false), got {value!r}"
    )


def _load_yaml(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ConfigError("top-level YAML value must be a mapping")
            return data
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"unable to read configuration {path}: {exc}") from exc


def _finite_float(value: Any, *, field: str, default: float) -> float:
    try:
        result = float(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be numeric, got {value!r}") from exc
    if not math.isfinite(result):
        raise ConfigError(f"{field} must be finite")
    return result


def _positive_float(value: Any, *, field: str, default: float) -> float:
    result = _finite_float(value, field=field, default=default)
    if result <= 0:
        raise ConfigError(f"{field} must be greater than zero")
    return result


def _positive_int(value: Any, *, field: str, default: int) -> int:
    try:
        result = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be an integer, got {value!r}") from exc
    if result <= 0:
        raise ConfigError(f"{field} must be greater than zero")
    return result


def _choice(value: Any, *, field: str, default: str, choices: set) -> str:
    result = str(default if value is None else value).strip().lower()
    if result not in choices:
        raise ConfigError(f"{field} must be one of {sorted(choices)}, got {value!r}")
    return result


def load_config() -> Config:
    # Look for config.yaml in the repository root
    root = _repo_root()
    ypath = os.path.join(root, "config.yaml")
    data = _load_yaml(ypath)

    cfg = Config()

    # GUI
    cfg.gui_backend   = _choice(data.get("gui_backend"), field="gui_backend", default=cfg.gui_backend, choices={"qt", "tk"})
    cfg.gui_update_ms = _positive_int(data.get("gui_update_ms"), field="gui_update_ms", default=cfg.gui_update_ms)

    # EMG
    cfg.emg_source        = _choice(data.get("emg_source"), field="emg_source", default=cfg.emg_source,
                                    choices={"auto", "bluetooth", "simulated"})
    cfg.emg_mac           = str(data.get("emg_mac", cfg.emg_mac))
    cfg.emg_com_port      = str(data.get("emg_com_port", cfg.emg_com_port))
    cfg.emg_rfcomm_channel = _positive_int(data.get("emg_rfcomm_channel"), field="emg_rfcomm_channel", default=cfg.emg_rfcomm_channel)
    cfg.emg_vmin          = _finite_float(data.get("emg_vmin"), field="emg_vmin", default=cfg.emg_vmin)
    cfg.emg_vmax          = _finite_float(data.get("emg_vmax"), field="emg_vmax", default=cfg.emg_vmax)
    if cfg.emg_vmax <= cfg.emg_vmin:
        raise ConfigError("emg_vmax must be greater than emg_vmin")
    cfg.emg_allow_lf      = _coerce_bool(data.get("emg_allow_lf"), field="emg_allow_lf", default=cfg.emg_allow_lf)
    cfg.emg_start_token   = str(data.get("emg_start_token", cfg.emg_start_token))
    cfg.emg_stop_token    = str(data.get("emg_stop_token", cfg.emg_stop_token))
    cfg.emg_sample_rate_hz = _positive_float(data.get("emg_sample_rate_hz"), field="emg_sample_rate_hz", default=cfg.emg_sample_rate_hz)
    cfg.emg_connect_timeout_s = _positive_float(data.get("emg_connect_timeout_s"), field="emg_connect_timeout_s", default=cfg.emg_connect_timeout_s)
    cfg.emg_powerline_hz  = _positive_float(data.get("emg_powerline_hz"), field="emg_powerline_hz", default=cfg.emg_powerline_hz)
    cfg.emg_notch_method  = _choice(data.get("emg_notch_method"), field="emg_notch_method", default=cfg.emg_notch_method,
                                    choices={"fft", "iir"})
    cfg.emg_notch_bandwidth_hz = _positive_float(data.get("emg_notch_bandwidth_hz"), field="emg_notch_bandwidth_hz", default=cfg.emg_notch_bandwidth_hz)
    cfg.emg_notch_harmonics = _positive_int(data.get("emg_notch_harmonics"), field="emg_notch_harmonics", default=cfg.emg_notch_harmonics)

    cfg.cop_flip_x = _coerce_bool(data.get("cop_flip_x"), field="cop_flip_x", default=cfg.cop_flip_x)
    cfg.cop_flip_y = _coerce_bool(data.get("cop_flip_y"), field="cop_flip_y", default=cfg.cop_flip_y)
    cfg.cop_swap_xy = _coerce_bool(data.get("cop_swap_xy"), field="cop_swap_xy", default=cfg.cop_swap_xy)

    # CoP: a single manufacturer gain (kg per V/V) or one per load cell
    raw_gain = data.get("cop_gain", cfg.cop_gain)
    if isinstance(raw_gain, (int, float)) and not isinstance(raw_gain, bool):
        cfg.cop_gain = float(raw_gain)                 # single gain for the four cells
    elif isinstance(raw_gain, (list, tuple)):
        cfg.cop_gain = [float(g) for g in raw_gain]    # list of four gains
    else:
        raise ConfigError("cop_gain must be a number or a list of four numbers")
    if isinstance(cfg.cop_gain, list) and len(cfg.cop_gain) != 4:
        raise ConfigError("cop_gain must contain exactly four values")

    # Distances between load-cell centres (paper: x and y). These are NOT the
    # plate dimensions; the plate size only sets the GUI half ranges.
    cfg.cop_x_dist_cm = _positive_float(data.get("cop_x_dist_cm"), field="cop_x_dist_cm", default=cfg.cop_x_dist_cm)
    cfg.cop_y_dist_cm = _positive_float(data.get("cop_y_dist_cm"), field="cop_y_dist_cm", default=cfg.cop_y_dist_cm)
    cfg.cop_x_half_range_cm = _positive_float(data.get("cop_x_half_range_cm"), field="cop_x_half_range_cm", default=cfg.cop_x_half_range_cm)
    cfg.cop_y_half_range_cm = _positive_float(data.get("cop_y_half_range_cm"), field="cop_y_half_range_cm", default=cfg.cop_y_half_range_cm)
    cfg.cop_interval_ms = _positive_int(
        data.get("cop_interval_ms"), field="cop_interval_ms", default=cfg.cop_interval_ms
    )
    cfg.cop_bridge_gain = _positive_int(data.get("cop_bridge_gain"), field="cop_bridge_gain", default=cfg.cop_bridge_gain)
    if cfg.cop_bridge_gain not in (1, 8, 16, 32, 64, 128):
        raise ConfigError("cop_bridge_gain must be one of 1, 8, 16, 32, 64, 128")
    cfg.cop_min_load_kg = _positive_float(data.get("cop_min_load_kg"), field="cop_min_load_kg", default=cfg.cop_min_load_kg)
    cfg.cop_cell_capacity_kg = _positive_float(data.get("cop_cell_capacity_kg"), field="cop_cell_capacity_kg", default=cfg.cop_cell_capacity_kg)
    cfg.recording_max_samples_per_stream = _positive_int(
        data.get("recording_max_samples_per_stream"),
        field="recording_max_samples_per_stream",
        default=cfg.recording_max_samples_per_stream,
    )

    # Camera / Pose
    cfg.cam_backend = _choice(data.get("cam_backend"), field="cam_backend", default=cfg.cam_backend,
                              choices={"auto", "opencv", "rpicam", "file"})
    cfg.cam_index  = int(data.get("cam_index",  cfg.cam_index))
    cfg.cam_width  = _positive_int(data.get("cam_width"), field="cam_width", default=cfg.cam_width)
    cfg.cam_height = _positive_int(data.get("cam_height"), field="cam_height", default=cfg.cam_height)
    cfg.cam_fps    = _positive_int(data.get("cam_fps"), field="cam_fps", default=cfg.cam_fps)
    cfg.cam_rotation = int(data.get("cam_rotation", cfg.cam_rotation))
    if cfg.cam_rotation not in (0, 90, 180, 270):
        raise ConfigError("cam_rotation must be 0, 90, 180 or 270")
    cfg.cam_hflip  = _coerce_bool(data.get("cam_hflip"), field="cam_hflip", default=cfg.cam_hflip)
    cfg.cam_file   = str(data.get("cam_file", cfg.cam_file) or "")
    cfg.cam_constant_fps = _coerce_bool(data.get("cam_constant_fps"), field="cam_constant_fps", default=cfg.cam_constant_fps)
    cfg.pose_min_visibility = _finite_float(data.get("pose_min_visibility"), field="pose_min_visibility", default=cfg.pose_min_visibility)

    # MediaPipe
    cfg.mediapipe_model_complexity          = int(data.get("mediapipe_model_complexity",          cfg.mediapipe_model_complexity))
    if cfg.mediapipe_model_complexity not in (0, 1, 2):
        raise ConfigError("mediapipe_model_complexity must be 0, 1 or 2")
    cfg.mediapipe_min_detection_confidence  = float(data.get("mediapipe_min_detection_confidence", cfg.mediapipe_min_detection_confidence))
    cfg.mediapipe_min_tracking_confidence   = float(data.get("mediapipe_min_tracking_confidence",  cfg.mediapipe_min_tracking_confidence))
    cfg.mediapipe_smooth_landmarks          = _coerce_bool(data.get("mediapipe_smooth_landmarks"), field="mediapipe_smooth_landmarks", default=cfg.mediapipe_smooth_landmarks)
    cfg.mediapipe_enable_segmentation       = _coerce_bool(data.get("mediapipe_enable_segmentation"), field="mediapipe_enable_segmentation", default=cfg.mediapipe_enable_segmentation)
    cfg.mediapipe_smooth_segmentation       = _coerce_bool(data.get("mediapipe_smooth_segmentation"), field="mediapipe_smooth_segmentation", default=cfg.mediapipe_smooth_segmentation)
    cfg.mediapipe_static_image_mode         = _coerce_bool(data.get("mediapipe_static_image_mode"), field="mediapipe_static_image_mode", default=cfg.mediapipe_static_image_mode)

    # Plot
    cfg.emg_plot_window   = _positive_float(data.get("emg_plot_window"), field="emg_plot_window", default=cfg.emg_plot_window)
    cfg.angle_plot_window = _positive_float(data.get("angle_plot_window"), field="angle_plot_window", default=cfg.angle_plot_window)
    cfg.angle_plot_limit_deg = _positive_float(data.get("angle_plot_limit_deg"), field="angle_plot_limit_deg", default=cfg.angle_plot_limit_deg)

    return cfg


# Type alias for compatibility with existing code
ConfigDict = Dict[str, Any]


def config_to_dict(config: Config) -> ConfigDict:
    """Converts Config object to dictionary (also used for session metadata)."""
    return asdict(config)


def load_config_dict() -> ConfigDict:
    """Loads configuration as dictionary for compatibility with existing code."""
    return config_to_dict(load_config())
