# -*- coding: utf-8 -*-
"""
Headless recorder (EMG/CoP/Pose) with graceful degradation if devices are offline.

Interactive mode:
  - Run without CLI args (e.g., VS Code "Run") and it will prompt for:
    * Duration
    * Base filename + optional auto suffix
    * Reference stream (auto/emg/cop/pose/angle)
    * Which devices to start (EMG/CoP/Pose)
    * Confirm start and whether to save at the end

Non-interactive (CLI examples, from repo root):
  python -m examples.headless_record --duration 12 --name test --append-suffix --reference cop --save
  python -m examples.headless_record --duration 10 --no-emg --save
"""

import os
import sys
import time
import argparse
from datetime import datetime

# Allow running this file directly: add project root to sys.path
if __package__ is None or __package__ == "":
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from acquisition_systems.common.config import load_config
from acquisition_systems.common.runtime import start_workers_forgiving, stop_workers, StartResult
from acquisition_systems.common.utils import get_latest
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

def auto_suffix(t_start: float) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    elapsed = int(max(0, time.time() - (t_start or time.time())))
    return f"{stamp}_{elapsed}s"


# ------------------ interactive helpers ------------------
def _input_with_default(prompt: str, default: str) -> str:
    try:
        s = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        return default
    return s if s else default

def _input_yes_no(prompt: str, default_yes: bool = True) -> bool:
    tag = "Y/n" if default_yes else "y/N"
    try:
        s = input(f"{prompt} [{tag}]: ").strip().lower()
    except EOFError:
        return default_yes
    if s == "":
        return default_yes
    return s in ("y", "yes")

def _choose_reference(default: str = "auto") -> str:
    choices = ("auto", "emg", "cop", "pose", "angle")
    while True:
        s = _input_with_default("Reference stream (auto/emg/cop/pose/angle)", default).lower()
        if s in choices:
            return s
        print("Invalid choice. Please enter one of:", ", ".join(choices))


# ------------------ main ------------------
def main():
    parser = argparse.ArgumentParser(description="Headless multi-rate recorder with forgiving device start.")
    parser.add_argument("--duration", type=float, help="Seconds to record.")
    parser.add_argument("--name", type=str, help="Base filename (no extension). If empty/omitted, auto name.")
    parser.add_argument("--reference", type=str, choices=["auto","emg","cop","pose","angle"],
                        help="Reference stream for merged CSV alignment.")
    parser.add_argument("--append-suffix", action="store_true",
                        help="If a base name is provided, append auto suffix (-YYYYmmdd-HHMMSS_XXs).")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--save", action="store_true", help="Save without prompting.")
    g.add_argument("--no-save", action="store_true", help="Do not save (skip) without prompting.")
    # device toggles (optional)
    parser.add_argument("--no-emg", action="store_true", help="Skip EMG device.")
    parser.add_argument("--no-cop", action="store_true", help="Skip CoP device.")
    parser.add_argument("--no-pose", action="store_true", help="Skip Pose device.")
    parser.add_argument("--no-prompt", action="store_true",
                        help="Disable interactive prompts even if no CLI args are provided.")
    args = parser.parse_args()

    cfg = load_config()

    # Decide interactive vs non-interactive
    interactive = (len(sys.argv) == 1 and sys.stdin.isatty()) and not args.no_prompt

    if interactive:
        print("=== Headless Recorder (interactive) ===")

        # Optionally override EMG MAC
        emg_mac = _input_with_default("EMG MAC address", cfg.emg_mac)
        cfg.emg_mac = emg_mac

        # Duration
        while True:
            d_str = _input_with_default("Duration (seconds)", "20")
            try:
                duration = max(1.0, float(d_str))
                break
            except ValueError:
                print("Invalid number. Try again.")

        # Enable/disable devices
        want_emg = _input_yes_no("Start EMG device?", default_yes=True)
        want_cop = _input_yes_no("Start CoP device?", default_yes=True)
        want_pose = _input_yes_no("Start Pose device (camera)?", default_yes=True)

        # Base name and suffix
        base = _input_with_default("Base filename (leave blank for auto)", "").strip()
        append_suffix = False
        if base:
            append_suffix = _input_yes_no("Append auto suffix to filename?", default_yes=False)

        # Reference
        reference = _choose_reference(default="auto")

        # Summary + confirm
        print("\nSummary:")
        print(f"  EMG MAC      : {cfg.emg_mac}")
        print(f"  Duration     : {duration:.2f} s")
        print(f"  Devices      : EMG={'ON' if want_emg else 'OFF'}, CoP={'ON' if want_cop else 'OFF'}, Pose={'ON' if want_pose else 'OFF'}")
        print(f"  Base name    : {base or '(auto)'}")
        print(f"  Append suffix: {append_suffix}")
        print(f"  Reference    : {reference}")
        if not _input_yes_no("Start recording now?", default_yes=True):
            print("Aborted by user before starting.")
            return
    else:
        # Non-interactive
        duration = max(1.0, float(args.duration if args.duration is not None else 20.0))
        base = (args.name or "").strip() if args.name is not None else ""
        append_suffix = bool(args.append_suffix)
        reference = args.reference or "auto"
        want_emg = not args.no_emg
        want_cop = not args.no_cop
        want_pose = not args.no_pose

    # Start forgiving (works even if 1-2 devices are offline)
    started: StartResult = start_workers_forgiving(cfg, want_emg=want_emg, want_cop=want_cop, want_pose=want_pose)

    # Log statuses
    print("[INFO] Device status:")
    print("  EMG :", "ONLINE" if started.emg else f"OFFLINE ({started.errors.get('emg','')})")
    print("  CoP :", "ONLINE" if started.cop else f"OFFLINE ({started.errors.get('cop','')})")
    print("  Pose:", "ONLINE" if started.pose else f"OFFLINE ({started.errors.get('pose','')})")

    if not any((started.emg, started.cop, started.pose)):
        print("[ERROR] No devices online. Exiting.")
        return

    rec = Recorder()
    t0 = time.time()
    t_end = t0 + duration

    print(f"[INFO] Recording for {duration:.2f} s. Press Ctrl+C to stop early.")
    try:
        while time.time() < t_end:
            emg  = get_latest(started.emg.queue,  default=None) if started.emg else None
            cop  = get_latest(started.cop.queue,  default=None) if started.cop else None
            pose = get_latest(started.pose.landmarks_q, default=None) if started.pose else None
            ang  = get_latest(started.pose.angle_q,     default=None) if started.pose else None

            rec.push_emg(emg)
            rec.push_cop(cop)
            rec.push_pose(pose)
            rec.push_angle(ang)

            time.sleep(0.005)  # ~200 Hz polling
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
    finally:
        stop_workers(started)

    # Decide filename
    if not base:
        base = f"session_{auto_suffix(t0)}"
    else:
        if append_suffix:
            base = f"{base}-{auto_suffix(t0)}"

    # Decide save
    if args.no_save:
        print("[OK] Skipped saving (no CSV written).")
        return
    if args.save:
        do_save = True
    else:
        do_save = _input_yes_no("Save merged CSV?", default_yes=True) if interactive else True

    if not do_save:
        print("[OK] Skipped saving (no CSV written).")
        return

    out_dir = dated_subdir(get_sessions_dir())
    path = rec.to_csv_merged(out_dir, base, reference=reference)
    print(f"[OK] Saved merged CSV: {path}")


if __name__ == "__main__":
    main()
