# Example: record without GUI using Recorder
# -*- coding: utf-8 -*-
"""
Headless recorder: runs EMG, CoP, and Pose without GUI and optionally saves a merged CSV.

Interactive mode:
  - If you run this file with no CLI args (e.g., from VS Code "Run"), it prompts for params.

Non-interactive mode (from repo root):
  python -m examples.headless_record --duration 15 --name test1 --reference auto --append-suffix --save
"""

import os
import sys
import time
import argparse
from datetime import datetime

# Allow running this file directly: add project root to sys.path
if __package__ is None or __package__ == "":
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from acquisition_systems.workers.emg import EMGWorker
from acquisition_systems.workers.cop import CoPWorker
from acquisition_systems.workers.pose import PoseWorker
from acquisition_systems.common.utils import get_latest
from acquisition_systems.common.config import load_config
from acquisition_systems.recorder import Recorder


# ------------------ paths ------------------
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


# ------------------ interactive helpers ------------------
def _input_with_default(prompt: str, default: str) -> str:
    try:
        s = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        return default
    return s if s else default

def _input_yes_no(prompt: str, default_yes: bool = True) -> bool:
    default_tag = "Y/n" if default_yes else "y/N"
    try:
        s = input(f"{prompt} [{default_tag}]: ").strip().lower()
    except EOFError:
        return default_yes
    if s == "" and default_yes: return True
    if s == "" and not default_yes: return False
    return s in ("y", "yes")

def _choose_reference(default: str = "auto") -> str:
    choices = ("auto", "emg", "cop", "pose", "angle")
    while True:
        s = _input_with_default("Reference stream (auto/emg/cop/pose/angle)", default).lower()
        if s in choices:
            return s
        print("Invalid choice. Please enter one of:", ", ".join(choices))


def auto_suffix(t_start: float) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    elapsed = int(max(0, time.time() - (t_start or time.time())))
    return f"{stamp}_{elapsed}s"


# ------------------ main ------------------
def main():
    parser = argparse.ArgumentParser(description="Headless multi-rate recorder (EMG/CoP/Pose).")
    parser.add_argument("--duration", type=float, help="Seconds to record.")
    parser.add_argument("--name", type=str, help="Base filename (no extension). If empty/omitted, auto name.")
    parser.add_argument("--reference", type=str, choices=["auto","emg","cop","pose","angle"],
                        help="Reference stream for merged CSV alignment.")
    parser.add_argument("--append-suffix", action="store_true",
                        help="If a base name is provided, append auto suffix (-YYYYmmdd-HHMMSS_XXs).")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--save", action="store_true", help="Save without prompting.")
    g.add_argument("--no-save", action="store_true", help="Do not save (skip) without prompting.")
    parser.add_argument("--no-prompt", action="store_true",
                        help="Disable interactive prompts even if no CLI args are provided.")
    args = parser.parse_args()

    # Decide interactive vs non-interactive
    interactive = (len(sys.argv) == 1 and sys.stdin.isatty()) or (not args.no_prompt and args.duration is None and args.name is None and args.reference is None)

    cfg = load_config()

    # -------- Interactive parameter collection --------
    if interactive:
        print("=== Headless Recorder (interactive) ===")
        # EMG MAC (optional override)
        emg_mac = _input_with_default("EMG MAC address", cfg.emg_mac)

        # Duration
        while True:
            d_str = _input_with_default("Duration (seconds)", "20")
            try:
                duration = max(1.0, float(d_str))
                break
            except ValueError:
                print("Invalid number. Try again.")

        # Name
        base = _input_with_default("Base filename (leave blank for auto)", "").strip()

        # Append suffix?
        append_suffix = False
        if base:
            append_suffix = _input_yes_no("Append auto suffix to filename?", default_yes=False)

        # Reference
        reference = _choose_reference(default="auto")

        # Confirm before starting
        print("\nSummary:")
        print(f"  EMG MAC      : {emg_mac}")
        print(f"  Duration     : {duration:.2f} s")
        print(f"  Base name    : {base or '(auto)'}")
        print(f"  Append suffix: {append_suffix}")
        print(f"  Reference    : {reference}")
        if not _input_yes_no("Start recording now?", default_yes=True):
            print("Aborted by user before starting.")
            return

    else:
        # Non-interactive: read from args/env/config
        emg_mac = cfg.emg_mac
        duration = max(1.0, float(args.duration if args.duration is not None else 20.0))
        base = (args.name or "").strip() if args.name is not None else ""
        append_suffix = bool(args.append_suffix)
        reference = args.reference or "auto"

    # -------- Start workers --------
    w_emg = EMGWorker(emg_mac, cfg.emg_rfcomm_channel, cfg.emg_vmin, cfg.emg_vmax)
    w_cop = CoPWorker(cfg.cop_gain, cfg.cop_x_dist_cm, cfg.cop_y_dist_cm, cfg.cop_interval_ms)
    w_pose = PoseWorker(cfg.cam_index, cfg.cam_width, cfg.cam_height, cfg.cam_fps)

    w_emg.start(); w_cop.start(); w_pose.start()

    rec = Recorder()
    t0 = time.time()
    t_end = t0 + duration

    print(f"[INFO] Recording for {duration:.2f} s. Press Ctrl+C to stop early.")
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

            time.sleep(0.005)  # ~200 Hz polling
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
    finally:
        for w in (w_emg, w_cop, w_pose):
            try: w.stop()
            except: pass

    # -------- Decide filename --------
    if not base:
        base = f"session_{auto_suffix(t0)}"
    else:
        if append_suffix:
            base = f"{base}-{auto_suffix(t0)}"

    # -------- Decide save or not --------
    if args.save:
        do_save = True
    elif args.no_save:
        do_save = False
    else:
        # Interactive prompt if in interactive mode, otherwise default yes
        do_save = _input_yes_no("Save merged CSV?", default_yes=True) if interactive else True

    if not do_save:
        print("[OK] Skipped saving (no CSV written).")
        return

    out_dir = dated_subdir(get_sessions_dir())
    path = rec.to_csv_merged(out_dir, base, reference=reference)
    print(f"[OK] Saved merged CSV: {path}")


if __name__ == "__main__":
    main()
