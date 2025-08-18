# -*- coding: utf-8 -*-
"""
Runtime helpers to start/stop acquisition workers gracefully when some devices are missing.

Usage:
    from acquisition_systems.common.runtime import start_workers_forgiving, stop_workers

    cfg = load_config()
    started = start_workers_forgiving(cfg, want_emg=True, want_cop=True, want_pose=True)
    # started.emg / started.cop / started.pose can be None if failed
    # started.errors holds reason strings per device key
    ...
    stop_workers(started)
"""

from dataclasses import dataclass
from typing import Optional, Dict

from .config import load_config
from acquisition_systems.workers.emg import EMGWorker
from acquisition_systems.workers.cop import CoPWorker
from acquisition_systems.workers.pose import PoseWorker


@dataclass
class StartResult:
    emg: Optional[EMGWorker]
    cop: Optional[CoPWorker]
    pose: Optional[PoseWorker]
    errors: Dict[str, str]  # e.g., {"emg": "RuntimeError: ...", "cop": "No device", "pose": "Camera not available"}


def start_workers_forgiving(
    cfg=None,
    want_emg: bool = True,
    want_cop: bool = True,
    want_pose: bool = True,
) -> StartResult:
    """
    Try to start each worker; keep running with whichever succeed.
    Returns StartResult with workers (or None) and an errors dict.
    """
    if cfg is None:
        cfg = load_config()

    emg = cop = pose = None
    errors: Dict[str, str] = {}

    if want_emg:
        try:
            w = EMGWorker(cfg.emg_mac, cfg.emg_rfcomm_channel, cfg.emg_vmin, cfg.emg_vmax)
            w.start()
            emg = w
        except Exception as e:
            errors["emg"] = f"{type(e).__name__}: {e}"

    if want_cop:
        try:
            w = CoPWorker(cfg.cop_gain, cfg.cop_x_dist_cm, cfg.cop_y_dist_cm, cfg.cop_interval_ms)
            w.start()
            cop = w
        except Exception as e:
            errors["cop"] = f"{type(e).__name__}: {e}"

    if want_pose:
        try:
            w = PoseWorker(cfg.cam_index, cfg.cam_width, cfg.cam_height, cfg.cam_fps)
            w.start()
            pose = w
        except Exception as e:
            errors["pose"] = f"{type(e).__name__}: {e}"

    return StartResult(emg=emg, cop=cop, pose=pose, errors=errors)


def stop_workers(result: StartResult):
    """Stop any worker that actually started."""
    for w in (result.emg, result.cop, result.pose):
        try:
            if w:
                w.stop()
        except Exception:
            pass
