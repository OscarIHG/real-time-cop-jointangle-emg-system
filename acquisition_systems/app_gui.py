# -*- coding: utf-8 -*-
"""
Tkinter + Matplotlib GUI orchestrating three acquisition workers:
- EMG (Bluetooth)
- Center of Pressure (Phidgets)
- Pose (MediaPipe)

Multi-rate recording: samples are stored at their native rates and merged on save.

Run from project root (recommended):
  python -m acquisition_systems.app_gui

You can also run directly:
  python acquisition_systems/app_gui.py
"""

# Make this runnable both as a module (-m) and as a script
if __package__ is None or __package__ == "":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import os
import tkinter as tk
from tkinter import ttk
import time
from datetime import datetime

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from acquisition_systems.workers.emg import EMGWorker
from acquisition_systems.workers.cop import CoPWorker
from acquisition_systems.workers.pose import PoseWorker
from acquisition_systems.common.utils import get_latest
from acquisition_systems.recorder import Recorder
from acquisition_systems.common.config import load_config


# ---------- output directory helpers ----------
def get_sessions_dir() -> str:
    """
    Base directory to store CSVs. Defaults to <project_root>/sessions.
    Override with env var AS_OUTDIR.
    """
    base = os.environ.get("AS_OUTDIR")
    if base:
        return base
    # project root = parent of this file's directory
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    return os.path.join(root, "sessions")


def dated_subdir(base: str) -> str:
    day = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(base, day)
    os.makedirs(path, exist_ok=True)
    return path


# ---------- simple UI builders ----------
def create_control_bar(master: tk.Widget, default_mac: str):
    frame = tk.Frame(master)

    # Duration
    tk.Label(frame, text="Duration (s):").pack(side=tk.LEFT, padx=5)
    e_len = tk.Entry(frame, width=6)
    e_len.insert(0, "20")
    e_len.pack(side=tk.LEFT)

    # EMG MAC
    tk.Label(frame, text="EMG MAC:").pack(side=tk.LEFT, padx=(20, 5))
    e_mac = tk.Entry(frame, width=17)
    e_mac.insert(0, default_mac)
    e_mac.pack(side=tk.LEFT)

    # Filename
    tk.Label(frame, text="Filename:").pack(side=tk.LEFT, padx=(20, 5))
    e_name = tk.Entry(frame, width=22)
    e_name.insert(0, "")
    e_name.pack(side=tk.LEFT)

    # Append suffix checkbox
    append_var = tk.BooleanVar(value=False)
    cb_append = tk.Checkbutton(frame, text="Append auto suffix", variable=append_var)
    cb_append.pack(side=tk.LEFT, padx=8)

    # Reference selector
    tk.Label(frame, text="Reference:").pack(side=tk.LEFT, padx=(20, 5))
    ref_var = tk.StringVar(value="auto")
    ref_combo = ttk.Combobox(
        frame,
        textvariable=ref_var,
        values=("auto", "emg", "cop", "pose", "angle"),
        width=7,
        state="readonly",
    )
    ref_combo.pack(side=tk.LEFT)

    # Buttons
    b_start = tk.Button(frame, text="Start")
    b_start.pack(side=tk.LEFT, padx=8)

    b_save = tk.Button(frame, text="Save CSV")
    b_save.pack(side=tk.LEFT, padx=8)

    b_quit = tk.Button(frame, text="Quit")
    b_quit.pack(side=tk.LEFT, padx=8)

    frame.pack(fill="x", padx=10, pady=6)
    return e_len, e_mac, e_name, append_var, ref_var, b_start, b_save, b_quit


def create_subplots(master: tk.Widget, cam_w: int, cam_h: int):
    fig, ax = plt.subplots(2, 2, figsize=(10, 6))
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    canvas = FigureCanvasTkAgg(fig, master=master)
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    # EMG
    (emg_line,) = ax[0, 0].plot([], [], lw=1.3)
    ax[0, 0].set_title("Abdominal EMG (V)")
    ax[0, 0].set_ylim(0, 5)
    ax[0, 0].set_xlim(0, 1000)
    ax[0, 0].grid(True, alpha=0.25)

    # CoP
    (cop_point,) = ax[0, 1].plot([], [], "o", ms=8)
    ax[0, 1].set_title("Center of Pressure (cm)")
    ax[0, 1].set_xlim(-30, 30)
    ax[0, 1].set_ylim(-22, 22)
    ax[0, 1].set_aspect("equal", adjustable="box")
    ax[0, 1].grid(True, alpha=0.3)

    # Landmarks
    bt_scat = ax[1, 0].scatter([], [], s=12)
    ax[1, 0].set_title("Body-Tracking Landmarks (px)")
    ax[1, 0].set_xlim(0, cam_w)
    ax[1, 0].set_ylim(0, cam_h)
    ax[1, 0].invert_yaxis()
    ax[1, 0].set_aspect("equal", adjustable="box")
    ax[1, 0].grid(True, alpha=0.25)

    # Angle
    (ang_line,) = ax[1, 1].plot([], [], lw=2)
    ax[1, 1].set_title("Joint Angle (Pelvic Obliquity 23–24) [deg]")
    ax[1, 1].set_ylim(-90, 90)
    ax[1, 1].set_xlim(0, 900)
    ax[1, 1].grid(True, alpha=0.3)

    return fig, ax, canvas, emg_line, cop_point, bt_scat, ang_line


# ---------- application ----------
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.root.title("Acquisition Systems GUI")

        # controls (now includes append_var and ref_var)
        (self.e_len, self.e_mac, self.e_name, self.append_var, self.ref_var,
         self.b_start, self.b_save, self.b_quit) = create_control_bar(root, self.cfg.emg_mac)

        self.b_start.config(command=self.toggle_start)
        self.b_save.config(command=self.save_csv)
        self.b_quit.config(command=self.on_close)

        # plots
        (self.fig, self.ax, self.canvas,
         self.emg_line, self.cop_point, self.bt_scat, self.ang_line) = create_subplots(root, self.cfg.cam_width, self.cfg.cam_height)
        self._emg_buf = []  # rolling only for plot
        self._ang_x, self._ang_y = [], []

        # workers
        self.w_emg = None
        self.w_cop = None
        self.w_pose = None

        # recorder
        self.rec = Recorder()

        # runtime
        self.running = False
        self.t_start = None
        self.t_stop = 0.0

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----- helpers -----
    def _auto_suffix(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        elapsed = 0 if not self.t_start else int(max(0, time.time() - self.t_start))
        return f"{stamp}_{elapsed}s"

    # ----- UI actions -----
    def toggle_start(self):
        if not self.running:
            try:
                dur = float(self.e_len.get() or "20")
            except Exception:
                dur = 20.0
            dur = max(1.0, dur)

            mac = (self.e_mac.get() or "").strip() or self.cfg.emg_mac

            # start workers
            self.w_emg = EMGWorker(
                mac_address=mac,
                rfcomm_channel=self.cfg.emg_rfcomm_channel,
                clamp_min=self.cfg.emg_vmin,
                clamp_max=self.cfg.emg_vmax,
            )
            self.w_emg.start()

            self.w_cop = CoPWorker(
                gain=self.cfg.cop_gain,
                x_dist_cm=self.cfg.cop_x_dist_cm,
                y_dist_cm=self.cfg.cop_y_dist_cm,
                data_interval_ms=self.cfg.cop_interval_ms,
            )
            self.w_cop.start()

            self.w_pose = PoseWorker(
                cam_index=self.cfg.cam_index,
                width=self.cfg.cam_width,
                height=self.cfg.cam_height,
                fps=self.cfg.cam_fps,
            )
            self.w_pose.start()

            # reset plot buffers and timer
            self._emg_buf.clear()
            self._ang_x.clear(); self._ang_y.clear()
            self.t_start = time.time()
            self.t_stop = self.t_start + dur
            self.running = True
            self.b_start.config(text="Stop")
            self._tick()
        else:
            self._stop_all()
            self.b_start.config(text="Start")

    def save_csv(self):
        # Base name typed by user (could be empty)
        base = (self.e_name.get() or "").strip()
        append = bool(self.append_var.get())
        ref = (self.ref_var.get() or "auto").lower()

        if not base:
            # No name typed -> always auto name
            base = f"session_{self._auto_suffix()}"
        else:
            # Name typed -> append suffix only if checkbox is ON
            if append:
                base = f"{base}-{self._auto_suffix()}"

        out_dir = dated_subdir(get_sessions_dir())
        path = self.rec.to_csv_merged(out_dir, base, reference=ref)
        print(f"[OK] Saved merged CSV: {path}")

    # ----- main loop -----
    def _tick(self):
        if not self.running:
            return
        now = time.time()
        if now >= self.t_stop:
            # Auto-stop; user can Save CSV or Quit.
            self.toggle_start()
            return

        # Get latest samples (or None) without blocking
        emg = get_latest(self.w_emg.queue, default=None) if self.w_emg else None
        cop = get_latest(self.w_cop.queue, default=None) if self.w_cop else None
        pose = get_latest(self.w_pose.landmarks_q, default=None) if self.w_pose else None
        ang  = get_latest(self.w_pose.angle_q, default=None) if self.w_pose else None

        # --- Plot updates ---
        if emg:
            self._emg_buf.append(emg.value)
            self._emg_buf = self._emg_buf[-1000:]
            x = np.arange(len(self._emg_buf))
            self.emg_line.set_data(x, self._emg_buf)
            left = max(0, len(self._emg_buf) - 1000)
            self.ax[0, 0].set_xlim(left, left + 1000)

        if cop:
            self.cop_point.set_data([cop.x], [cop.y])

        if pose:
            if pose.landmarks is not None and pose.landmarks.size > 0:
                self.bt_scat.set_offsets(pose.landmarks)

        if ang:
            self._ang_x.append((self._ang_x[-1] + 1) if self._ang_x else 0)
            self._ang_y.append(ang.deg)
            self._ang_x = self._ang_x[-900:]
            self._ang_y = self._ang_y[-900:]
            self.ang_line.set_data(self._ang_x, self._ang_y)
            self.ax[1, 1].set_xlim(
                max(0, (self._ang_x[-1] if self._ang_x else 0) - 900),
                max(900, (self._ang_x[-1] if self._ang_x else 0) + 10)
            )

        # --- Native-rate recording (only push when new sample exists) ---
        self.rec.push_emg(emg)
        self.rec.push_cop(cop)
        self.rec.push_pose(pose)
        self.rec.push_angle(ang)

        self.canvas.draw_idle()
        # schedule next frame (~60 Hz)
        self.root.after(16, self._tick)

    def _stop_all(self):
        self.running = False
        try:
            if self.w_emg: self.w_emg.stop()
        except Exception:
            pass
        try:
            if self.w_cop: self.w_cop.stop()
        except Exception:
            pass
        try:
            if self.w_pose: self.w_pose.stop()
        except Exception:
            pass
        self.w_emg = self.w_cop = self.w_pose = None

    def on_close(self):
        self._stop_all()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
