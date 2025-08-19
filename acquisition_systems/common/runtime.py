# -*- coding: utf-8 -*-
"""
Runtime helpers to start/stop acquisition workers gracefully when some devices are missing.
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
    errors: Dict[str, str]


def start_workers_forgiving(
    cfg=None,
    want_emg: bool = True,
    want_cop: bool = True,
    want_pose: bool = True,
) -> StartResult:
    if cfg is None:
        cfg = load_config()

    emg = cop = pose = None
    errors: Dict[str, str] = {}

    if want_emg:
        try:
            w = EMGWorker(
                cfg.emg_mac,
                cfg.emg_rfcomm_channel,
                cfg.emg_vmin,
                cfg.emg_vmax,
                start_token=cfg.emg_start_token,
                stop_token=cfg.emg_stop_token,
            )
            # aplica ALLOW_LF desde config
            try:
                w.ALLOW_LF = bool(cfg.emg_allow_lf)
            except Exception:
                pass
            w.start()
            emg = w
        except Exception as e:
            errors["emg"] = f"{type(e).__name__}: {e}"

    if want_cop:
        try:
            w = CoPWorker(
                cfg.cop_gain, cfg.cop_x_dist_cm, cfg.cop_y_dist_cm, cfg.cop_interval_ms,
                flip_x=cfg.cop_flip_x, flip_y=cfg.cop_flip_y, swap_xy=cfg.cop_swap_xy
            )
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
    for w in (result.emg, result.cop, result.pose):
        try:
            if w:
                w.stop()
        except Exception:
            pass
