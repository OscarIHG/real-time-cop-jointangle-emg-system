# -*- coding: utf-8 -*-
"""
GUI launcher. ``gui_backend`` in config.yaml (or --gui) selects:
  qt  PyQtGraph (default, fastest renderer on the Raspberry Pi)
  tk  Tkinter + Matplotlib with blitting (the toolkit used in the paper, Fig. 3)

Both are views over the same AcquisitionSession, so acquisition, filtering,
synchronisation and storage are identical.

  python -m acquisition_systems.app_gui [--gui qt|tk] [--emg-source simulated]
         [--autostart --duration 20 --autosave --exit-after]   (unattended runs)
"""

if __package__ is None or __package__ == "":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import sys

from acquisition_systems.common.config import load_config


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Real-Time CoP-JointAngle-EMG GUI")
    p.add_argument("--gui", choices=["qt", "tk"], help="override gui_backend from config.yaml")
    p.add_argument("--emg-source", choices=["auto", "bluetooth", "simulated"])
    p.add_argument("--duration", type=float, default=20.0, help="initial recording length (s)")
    p.add_argument("--autostart", action="store_true", help="start recording once hardware is ready")
    p.add_argument("--autosave", action="store_true", help="save automatically when the recording ends")
    p.add_argument("--exit-after", action="store_true", help="close after the automatic save")
    args = p.parse_args(argv)

    backend = args.gui or load_config().gui_backend
    if backend == "tk":
        from acquisition_systems.app_tk import run
    else:
        from acquisition_systems.app_qt import run
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
