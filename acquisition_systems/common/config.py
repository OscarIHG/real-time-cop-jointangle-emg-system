# -*- coding: utf-8 -*-
"""
Config loader for acquisition systems.
Reads config.yaml at repo root; provides sane defaults if keys are missing.
"""

from __future__ import annotations
import os
import math
from dataclasses import dataclass
from typing import Any, Dict

import yaml


@dataclass
class Config:
    # EMG
    emg_mac: str = "00:00:00:00:00:00"
    emg_com_port: str = "COM3"
    emg_rfcomm_channel: int = 1
    emg_vmin: float = 0.0
    emg_vmax: float = 3.3
    emg_allow_lf: bool = False
    emg_start_token: str = "1"
    emg_stop_token: str = "2"
    cop_flip_x: bool = False
    cop_flip_y: bool = False
    cop_swap_xy: bool = False
    # CoP (worker inputs and GUI ranges)
    cop_gain: Any = 1.0            # was float; now Any to accept list[float] or float
    cop_x_dist_cm: float = 55.88
    cop_y_dist_cm: float = 40.54
    cop_x_half_range_cm: float = 27.94
    cop_y_half_range_cm: float = 20.27
    cop_interval_ms: int = 10
    recording_max_samples_per_stream: int = 1_000_000

    # Camera / Pose
    cam_index: int = 0
    cam_width: int = 640
    cam_height: int = 480
    cam_fps: int = 30

    # MediaPipe
    mediapipe_model_complexity: int = 0
    mediapipe_min_detection_confidence: float = 0.7
    mediapipe_min_tracking_confidence: float = 0.5
    mediapipe_smooth_landmarks: bool = True
    mediapipe_enable_segmentation: bool = False
    mediapipe_smooth_segmentation: bool = False
    mediapipe_static_image_mode: bool = False

    # Plot (GUI)
    emg_plot_window: int = 200
    angle_plot_window: int = 50


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


def _positive_int(value: Any, *, field: str, default: int) -> int:
    try:
        result = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be an integer, got {value!r}") from exc
    if result <= 0:
        raise ConfigError(f"{field} must be greater than zero")
    return result


def load_config() -> Config:
    # Look for config.yaml in the repository root
    root = _repo_root()
    ypath = os.path.join(root, "config.yaml")
    data = _load_yaml(ypath)

    cfg = Config()

    # EMG
    cfg.emg_mac           = str(data.get("emg_mac", cfg.emg_mac))
    cfg.emg_com_port      = str(data.get("emg_com_port", cfg.emg_com_port))
    cfg.emg_rfcomm_channel = int(data.get("emg_rfcomm_channel", cfg.emg_rfcomm_channel))
    cfg.emg_vmin          = _finite_float(data.get("emg_vmin"), field="emg_vmin", default=cfg.emg_vmin)
    cfg.emg_vmax          = _finite_float(data.get("emg_vmax"), field="emg_vmax", default=cfg.emg_vmax)
    cfg.emg_allow_lf      = _coerce_bool(data.get("emg_allow_lf"), field="emg_allow_lf", default=cfg.emg_allow_lf)
    cfg.emg_start_token   = str(data.get("emg_start_token", cfg.emg_start_token))
    cfg.emg_stop_token    = str(data.get("emg_stop_token", cfg.emg_stop_token))
    cfg.cop_flip_x = _coerce_bool(data.get("cop_flip_x"), field="cop_flip_x", default=cfg.cop_flip_x)
    cfg.cop_flip_y = _coerce_bool(data.get("cop_flip_y"), field="cop_flip_y", default=cfg.cop_flip_y)
    cfg.cop_swap_xy = _coerce_bool(data.get("cop_swap_xy"), field="cop_swap_xy", default=cfg.cop_swap_xy)

    # CoP (accepts total distances or half ranges; derive missing values if needed)
    raw_gain = data.get("cop_gain", cfg.cop_gain)
    # Normalize: accept a float or a list/tuple of four values
    if isinstance(raw_gain, (int, float)):
        cfg.cop_gain = float(raw_gain)                 # single gain for the four cells
    elif isinstance(raw_gain, (list, tuple)):
        cfg.cop_gain = [float(g) for g in raw_gain]    # list of four gains
    else:
        raise ConfigError("cop_gain must be a number or a list of four numbers")
    if isinstance(cfg.cop_gain, list) and len(cfg.cop_gain) != 4:
        raise ConfigError("cop_gain must contain exactly four values")

    x_half = data.get("cop_x_half_range_cm", cfg.cop_x_half_range_cm)
    y_half = data.get("cop_y_half_range_cm", cfg.cop_y_half_range_cm)
    x_dist = data.get("cop_x_dist_cm", None)
    y_dist = data.get("cop_y_dist_cm", None)
    cfg.cop_x_half_range_cm = _finite_float(x_half, field="cop_x_half_range_cm", default=cfg.cop_x_half_range_cm)
    cfg.cop_y_half_range_cm = _finite_float(y_half, field="cop_y_half_range_cm", default=cfg.cop_y_half_range_cm)
    cfg.cop_x_dist_cm = _finite_float(
        x_dist, field="cop_x_dist_cm", default=2.0 * cfg.cop_x_half_range_cm
    )
    cfg.cop_y_dist_cm = _finite_float(
        y_dist, field="cop_y_dist_cm", default=2.0 * cfg.cop_y_half_range_cm
    )
    cfg.cop_interval_ms = _positive_int(
        data.get("cop_interval_ms"), field="cop_interval_ms", default=cfg.cop_interval_ms
    )
    cfg.recording_max_samples_per_stream = _positive_int(
        data.get("recording_max_samples_per_stream"),
        field="recording_max_samples_per_stream",
        default=cfg.recording_max_samples_per_stream,
    )

    # Camera / Pose
    cfg.cam_index  = int(data.get("cam_index",  cfg.cam_index))
    cfg.cam_width  = _positive_int(data.get("cam_width"), field="cam_width", default=cfg.cam_width)
    cfg.cam_height = _positive_int(data.get("cam_height"), field="cam_height", default=cfg.cam_height)
    cfg.cam_fps    = _positive_int(data.get("cam_fps"), field="cam_fps", default=cfg.cam_fps)

    # MediaPipe
    cfg.mediapipe_model_complexity          = int(data.get("mediapipe_model_complexity",          cfg.mediapipe_model_complexity))
    cfg.mediapipe_min_detection_confidence  = float(data.get("mediapipe_min_detection_confidence", cfg.mediapipe_min_detection_confidence))
    cfg.mediapipe_min_tracking_confidence   = float(data.get("mediapipe_min_tracking_confidence",  cfg.mediapipe_min_tracking_confidence))
    cfg.mediapipe_smooth_landmarks          = _coerce_bool(data.get("mediapipe_smooth_landmarks"), field="mediapipe_smooth_landmarks", default=cfg.mediapipe_smooth_landmarks)
    cfg.mediapipe_enable_segmentation       = _coerce_bool(data.get("mediapipe_enable_segmentation"), field="mediapipe_enable_segmentation", default=cfg.mediapipe_enable_segmentation)
    cfg.mediapipe_smooth_segmentation       = _coerce_bool(data.get("mediapipe_smooth_segmentation"), field="mediapipe_smooth_segmentation", default=cfg.mediapipe_smooth_segmentation)
    cfg.mediapipe_static_image_mode         = _coerce_bool(data.get("mediapipe_static_image_mode"), field="mediapipe_static_image_mode", default=cfg.mediapipe_static_image_mode)

    # Plot
    cfg.emg_plot_window   = int(data.get("emg_plot_window",   cfg.emg_plot_window))
    cfg.angle_plot_window = int(data.get("angle_plot_window", cfg.angle_plot_window))

    return cfg


# =============================================================================
# ADDED TO SOLVE IMPORT ERROR
# =============================================================================

# Type alias for compatibility with existing code
ConfigDict = Dict[str, Any]

# Helper function to convert Config to dictionary
def config_to_dict(config: Config) -> ConfigDict:
    """Converts Config object to dictionary for compatibility."""
    return {
        # EMG
        'emg_mac': config.emg_mac,
        'emg_com_port': config.emg_com_port,
        'emg_rfcomm_channel': config.emg_rfcomm_channel,
        'emg_vmin': config.emg_vmin,
        'emg_vmax': config.emg_vmax,
        'emg_allow_lf': config.emg_allow_lf,
        'emg_start_token': config.emg_start_token,
        'emg_stop_token': config.emg_stop_token,
        'cop_flip_x': config.cop_flip_x,
        'cop_flip_y': config.cop_flip_y,
        'cop_swap_xy': config.cop_swap_xy,
        # CoP
        'cop_gain': config.cop_gain,
        'cop_x_dist_cm': config.cop_x_dist_cm,
        'cop_y_dist_cm': config.cop_y_dist_cm,
        'cop_x_half_range_cm': config.cop_x_half_range_cm,
        'cop_y_half_range_cm': config.cop_y_half_range_cm,
        'cop_interval_ms': config.cop_interval_ms,
        # Camera / Pose
        'cam_index': config.cam_index,
        'cam_width': config.cam_width,
        'cam_height': config.cam_height,
        'cam_fps': config.cam_fps,
        # Plot
        'emg_plot_window': config.emg_plot_window,
        'angle_plot_window': config.angle_plot_window,
        # MediaPipe
        'mediapipe_model_complexity': config.mediapipe_model_complexity,
        'mediapipe_min_detection_confidence': config.mediapipe_min_detection_confidence,
        'mediapipe_min_tracking_confidence': config.mediapipe_min_tracking_confidence,
        'mediapipe_smooth_landmarks': config.mediapipe_smooth_landmarks,
        'mediapipe_enable_segmentation': config.mediapipe_enable_segmentation,
        'mediapipe_smooth_segmentation': config.mediapipe_smooth_segmentation,
        'mediapipe_static_image_mode': config.mediapipe_static_image_mode,
        'recording_max_samples_per_stream': config.recording_max_samples_per_stream,
    }

# Function to load config as dictionary (compatibility)
def load_config_dict() -> ConfigDict:
    """Loads configuration as dictionary for compatibility with existing code."""
    config = load_config()
    return config_to_dict(config)