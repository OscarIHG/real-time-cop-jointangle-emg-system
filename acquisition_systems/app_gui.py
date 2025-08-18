# Tkinter/Matplotlib GUI orchestrator
# -*- coding: utf-8 -*-
"""
Tkinter + Matplotlib GUI orchestrating three acquisition workers:
- EMG (Bluetooth)
- Center of Pressure (Phidgets)
- Pose (MediaPipe)

Also computes and plots joint angle (hip 23–24) and records combined CSV.

Run from project root:
  python -m acquisition_systems.app_gui
"""

import tkinter as tk
import time
from datetime import datetime

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .workers.emg import EMGWorker
from .workers.cop import CoPWorker
from .workers.pose import PoseWorker
from .common.utils import get_latest
from .recorder import Recorder
from .common.config import load_config


# ---------- simple UI builders ----------
def create_control_bar(master: tk.Widget, default_mac: str):
    frame = tk.Frame(master)
    tk.Label(frame, text="Duration (s):").pack(side=tk.LEFT, padx=5)
    e_len = tk.Entry(frame, width=6); e_len.insert(0, "20"); e_len.pack(side=tk.LEFT)

    tk.Label(frame, text="EMG MAC:").pack(side=tk.LEFT, padx=(20, 5))
    e_mac = tk.Entry(frame, width=17); e_mac.insert(0, default_mac); e_mac.pack(side=tk.LEFT)

    tk.Label(frame, text="Filename:").pack(side=tk.LEFT, padx=(20, 5))
    e_name = tk.Entry(frame, width=22); e_name.insert(0, ""); e_name.pack(side=tk.LEFT)

    b_start = tk.Button(frame, text="Start")
    b_start.pack(side=tk.LEFT, padx=8)

    b_save = tk.Button(frame, text="Save CSV")
    b_save.pack(side=tk.LEFT, padx=8)

    frame.pack(fill="x", padx=10, pady=6)
    return e_len, e_mac, e_name, b_start, b_save


def create_subplots(master: tk.Widget):
    fig, ax = plt.subplots(2, 2, figsize=(10, 6))
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    canvas = FigureCanvasTkAgg(fig, master=master)
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)
    return fig, ax, canvas


# ---------- application ----------
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.root.title("Acquisition Systems GUI")

        # controls
        self.e_len, self.e_mac, self.e_name, self.b_start, self.b_save = create_control_bar(root, self.cfg.emg_mac)
        self.b_start.config(command=self.toggle_start)
        self.b_save.config(command=self.save_csv)

        # plots
        self.fig, self.ax, self.canvas = create_subplots(root)
        # EMG
        (self.emg_line,) = self.ax[0, 0].plot([], [], lw=1.3)
        self.ax[0, 0].set_title("Abdominal EMG (V)")
        self.ax[0, 0].set_ylim(0, 5)
        self.ax[0, 0].set_xlim(0, 1000)
        self.ax[0, 0].grid(True, alpha=0.25)
        self._emg_buf = []  # rolling for plot only

        # CoP
        (self.cop_point,) = self.ax[0, 1].plot([], [], "o", ms=8)
        self.ax[0, 1].set_title("Center of Pressure (cm)")
        self.ax[0, 1].set_xlim(-30, 30)
        self.ax[0, 1].set_ylim(-22, 22)
        self.ax[0, 1].set_aspect("equal", adjustable="box")
        self.ax[0, 1].grid(True, alpha=0.3)

        # Landmarks
        self.bt_scat = self.ax[1, 0].scatter([], [], s=12)
        self.ax[1, 0].set_title("Body-Tracking Landmarks (px)")
        self.ax[1, 0].set_xlim(0, self.cfg.cam_width)
        self.ax[1, 0].set_ylim(0, self.cfg.cam_height)
        self.ax[1, 0].invert_yaxis()
        self.ax[1, 0].set_aspect("equal", adjustable="box")
        self.ax[1, 0].grid(True, alpha=0.25)

        # Angle
        (self.ang_line,) = self.ax[1, 1].plot([], [], lw=2)
        self.ax[1, 1].set_title("Joint Angle (Pelvic Obliquity 23–24) [deg]")
        self.ax[1, 1].set_ylim(-90, 90)
        self.ax[1, 1].set_xlim(0, 900)
        self.ax[1, 1].grid(True, alpha=0.3)
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
        name = (self.e_name.get() or "").strip()
        if not name:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            elapsed = 0 if not self.t_start else int(max(0, time.time() - self.t_start))
            name = f"session_{stamp}_{elapsed}s"
        path = self.rec.to_csv(name)
        print(f"[OK] Saved CSV: {path}")

    # ----- main loop -----
    def _tick(self):
        if not self.running:
            return
        now = time.time()
        if now >= self.t_stop:
            self.toggle_start()
            return

        # Pull latest samples (or None)
        emg = get_latest(self.w_emg.queue, default=None) if self.w_emg else None
        cop = get_latest(self.w_cop.queue, default=None) if self.w_cop else None
        pose = get_latest(self.w_pose.landmarks_q, default=None) if self.w_pose else None
        ang  = get_latest(self.w_pose.angle_q, default=None) if self.w_pose else None

        # Plot EMG rolling
        if emg:
            self._emg_buf.append(emg.value)
            self._emg_buf = self._emg_buf[-1000:]
            x = np.arange(len(self._emg_buf))
            self.emg_line.set_data(x, self._emg_buf)
            left = max(0, len(self._emg_buf) - 1000)
            self.ax[0, 0].set_xlim(left, left + 1000)

        # Plot CoP point
        if cop:
            self.cop_point.set_data([cop.x], [cop.y])

        # Plot landmarks
        if pose:
            if pose.landmarks is not None and pose.landmarks.size > 0:
                self.bt_scat.set_offsets(pose.landmarks)

        # Plot angle series
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

        # Record one row (forward-fill inside Recorder)
        rel = now - (self.t_start or now)
        self.rec.add(rel, emg, cop, pose, ang)

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
