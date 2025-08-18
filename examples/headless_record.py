# Example: record without GUI using Recorder
# -*- coding: utf-8 -*-
"""
Headless recorder: runs EMG, CoP, and Pose without GUI and saves a merged CSV.
Usage (from repo root):
  python examples/headless_record.py --duration 15 --name test1 --reference auto
"""

import os
import time
import argparse
from datetime import datetime

from acquisition_systems.workers.emg import EMGWorker
from acquisition_systems.workers.cop import CoPWorker
from acquisition_systems.workers.pose import PoseWorker
from acquisition_systems.common.utils import get_latest
from acquisition_systems.common.config import load_config
from acquisition_systems.recorder import Recorder


def get_sessions_dir():
    base = os.environ.get("AS_OUTDIR")
    if base:
        return base
    root = os.path.abspath(os.path.dirname(__file__) + "/..")
    return os.path.join(root, "sessions")

def dated_subdir(base: str) -> str:
    day = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(base, day)
    os.makedirs(path, exist_ok=True)
    return path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=20.0, help="Seconds to record")
    parser.add_argument("--name", type=str, default="", help="Base filename (no extension). If empty, auto name.")
    parser.add_argument("--reference", type=str, default="auto", choices=["auto","emg","cop","pose","angle"],
                        help="Reference stream for merged CSV alignment")
    args = parser.parse_args()

    cfg = load_config()

    # Workers
    w_emg = EMGWorker(cfg.emg_mac, cfg.emg_rfcomm_channel, cfg.emg_vmin, cfg.emg_vmax)
    w_cop = CoPWorker(cfg.cop_gain, cfg.cop_x_dist_cm, cfg.cop_y_dist_cm, cfg.cop_interval_ms)
    w_pose = PoseWorker(cfg.cam_index, cfg.cam_width, cfg.cam_height, cfg.cam_fps)

    # Start
    w_emg.start(); w_cop.start(); w_pose.start()

    rec = Recorder()
    t0 = time.time()
    t_end = t0 + max(1.0, args.duration)

    try:
        while time.time() < t_end:
            emg = get_latest(w_emg.queue, default=None)
            cop = get_latest(w_cop.queue, default=None)
            pose = get_latest(w_pose.landmarks_q, default=None)
            ang  = get_latest(w_pose.angle_q, default=None)

            rec.push_emg(emg)
            rec.push_cop(cop)
            rec.push_pose(pose)
            rec.push_angle(ang)

            time.sleep(0.005)  # ~200 Hz polling (no GUI)
    finally:
        try: w_emg.stop()
        except: pass
        try: w_cop.stop()
        except: pass
        try: w_pose.stop()
        except: pass

    # Output path
    base = args.name.strip()
    if not base:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        elapsed = int(max(0, time.time() - t0))
        base = f"session_{stamp}_{elapsed}s"

    out_dir = dated_subdir(get_sessions_dir())
    path = rec.to_csv_merged(out_dir, base, reference=args.reference)
    print(f"[OK] Saved merged CSV: {path}")


if __name__ == "__main__":
    main()
