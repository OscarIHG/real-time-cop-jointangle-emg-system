# -*- coding: utf-8 -*-
"""
Tkinter + Matplotlib GUI orchestrating EMG, CoP, Pose workers with:
- Graceful degradation if some devices are offline.
- Status bar (ONLINE/OFFLINE) per device.
- Merged CSV saving with selectable reference stream.
- Append auto suffix option.
- Plots driven by config.yaml:
    * EMG: window (samples) from cfg.emg_plot_window; ymin>=0.
    * CoP: ranges from cfg.cop_x_half_range_cm / cfg.cop_y_half_range_cm.
    * Pose: pixels (0..cam_w/0..cam_h) con origen abajo-izquierda.
    * Angle: window from cfg.angle_plot_window; y fijo ±90°.
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
from typing import Optional

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from acquisition_systems.common.config import load_config
from acquisition_systems.common.runtime import start_workers_forgiving, stop_workers, StartResult
from acquisition_systems.common.utils import get_latest
from acquisition_systems.recorder import Recorder


# ---------- output directory helpers ----------
def get_sessions_dir() -> str:
    base = os.environ.get("AS_OUTDIR")
    if base:
        return base
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    return os.path.join(root, "sessions")

def dated_subdir(base: str) -> str:
    day = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(base, day)
    os.makedirs(path, exist_ok=True)
    return path


# ---------- UI builders ----------
def create_control_bar(master: tk.Widget, default_mac: str):
    frame = tk.Frame(master)

    # Duration
    tk.Label(frame, text="Duration (s):").pack(side=tk.LEFT, padx=5)
    e_len = tk.Entry(frame, width=6); e_len.insert(0, "20"); e_len.pack(side=tk.LEFT)

    # EMG MAC
    tk.Label(frame, text="EMG MAC:").pack(side=tk.LEFT, padx=(20, 5))
    e_mac = tk.Entry(frame, width=17); e_mac.insert(0, default_mac); e_mac.pack(side=tk.LEFT)

    # Filename
    tk.Label(frame, text="Filename:").pack(side=tk.LEFT, padx=(20, 5))
    e_name = tk.Entry(frame, width=22); e_name.insert(0, ""); e_name.pack(side=tk.LEFT)

    # Append suffix
    append_var = tk.BooleanVar(value=False)
    cb_append = tk.Checkbutton(frame, text="Append auto suffix", variable=append_var)
    cb_append.pack(side=tk.LEFT, padx=8)

    # Reference selector
    tk.Label(frame, text="Reference:").pack(side=tk.LEFT, padx=(20, 5))
    ref_var = tk.StringVar(value="auto")
    ref_combo = ttk.Combobox(frame, textvariable=ref_var,
                             values=("auto", "emg", "cop", "pose", "angle"),
                             width=7, state="readonly")
    ref_combo.pack(side=tk.LEFT)

    # Buttons
    b_start = tk.Button(frame, text="Start"); b_start.pack(side=tk.LEFT, padx=8)
    b_save  = tk.Button(frame, text="Save CSV"); b_save.pack(side=tk.LEFT, padx=8)
    b_quit  = tk.Button(frame, text="Quit"); b_quit.pack(side=tk.LEFT, padx=8)

    frame.pack(fill="x", padx=10, pady=6)
    return e_len, e_mac, e_name, append_var, ref_var, b_start, b_save, b_quit


def create_status_bar(master: tk.Widget):
    frame = tk.Frame(master)
    emg = tk.Label(frame, text="EMG: —", fg="gray")
    cop = tk.Label(frame, text="CoP: —",  fg="gray")
    pose = tk.Label(frame, text="Pose: —", fg="gray")
    for w in (emg, cop, pose):
        w.pack(side=tk.LEFT, padx=12)
    frame.pack(fill="x", padx=10, pady=(0,6))
    return frame, emg, cop, pose


def create_subplots(master: tk.Widget, cam_w: int, cam_h: int,
                    emg_window: int, angle_window: int,
                    cop_x_half: float, cop_y_half: float):
    # Usa constrained_layout para evitar encimados
    fig, ax = plt.subplots(2, 2, figsize=(10, 6), constrained_layout=True)
    canvas = FigureCanvasTkAgg(fig, master=master)
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    # --- EMG ---
    (emg_line,) = ax[0, 0].plot([], [], lw=1.3)
    ax[0, 0].set_title("Abdominal EMG")
    ax[0, 0].set_ylabel("EMG")
    ax[0, 0].set_ylim(0, 5)
    ax[0, 0].set_xlim(0, max(1, int(emg_window)))
    ax[0, 0].margins(x=0, y=0)
    ax[0, 0].grid(True, alpha=0.25)

    # --- CoP (force plate) ---
    (cop_point,) = ax[0, 1].plot([], [], "o", ms=8)
    ax[0, 1].set_title("Center of Pressure [cm]")
    ax[0, 1].set_xlabel("X [cm]"); ax[0, 1].set_ylabel("Y [cm]")
    ax[0, 1].set_xlim(-abs(cop_x_half), abs(cop_x_half))
    ax[0, 1].set_ylim(-abs(cop_y_half), abs(cop_y_half))
    ax[0, 1].set_aspect("equal", adjustable="box")
    ax[0, 1].margins(x=0, y=0)
    ax[0, 1].grid(True, alpha=0.3)
    if getattr(ax[0, 1], "legend_", None) is not None:
        ax[0, 1].legend_.remove()

    # --- Body tracking (px) con 0 abajo-izquierda ---
    bt_scat = ax[1, 0].scatter([], [], s=12)
    ax[1, 0].set_title("Body-Tracking Landmarks [px]")
    ax[1, 0].set_xlabel("x [px]"); ax[1, 0].set_ylabel("y [px]")
    ax[1, 0].set_xlim(0, cam_w)
    ax[1, 0].set_ylim(0, cam_h)   # 0 en la base; sin invertir eje
    ax[1, 0].set_aspect("equal", adjustable="box")
    ax[1, 0].margins(x=0, y=0)
    ax[1, 0].grid(True, alpha=0.25)

    # --- Joint angle (scroll configurable) ---
    (ang_line,) = ax[1, 1].plot([], [], lw=2)
    ax[1, 1].set_title("Joint Angle (Pelvic Obliquity 23–24) [deg]")
    ax[1, 1].set_ylabel("Angle [deg]")
    ax[1, 1].set_ylim(-90, 90)
    ax[1, 1].set_xlim(0, max(1, int(angle_window)))
    ax[1, 1].margins(x=0, y=0)
    ax[1, 1].grid(True, alpha=0.3)

    return fig, ax, canvas, emg_line, cop_point, bt_scat, ang_line


# ---------- App ----------
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.root.title("Acquisition Systems GUI")

        # Plot settings from config
        self.emg_plot_window = int(max(1, self.cfg.emg_plot_window))
        self.angle_plot_window = int(max(1, self.cfg.angle_plot_window))
        self.cop_x_half = float(self.cfg.cop_x_half_range_cm)
        self.cop_y_half = float(self.cfg.cop_y_half_range_cm)

        # Controls
        (self.e_len, self.e_mac, self.e_name, self.append_var, self.ref_var,
         self.b_start, self.b_save, self.b_quit) = create_control_bar(root, self.cfg.emg_mac)
        self.b_start.config(command=self.toggle_start)
        self.b_save.config(command=self.save_csv)
        self.b_quit.config(command=self.on_close)

        # Status bar
        self.status_frame, self.lbl_emg, self.lbl_cop, self.lbl_pose = create_status_bar(root)

        # Plots (drive by config)
        (self.fig, self.ax, self.canvas,
         self.emg_line, self.cop_point, self.bt_scat, self.ang_line) = create_subplots(
            root, self.cfg.cam_width, self.cfg.cam_height,
            self.emg_plot_window, self.angle_plot_window,
            self.cop_x_half, self.cop_y_half
        )
        self._emg_buf = []
        self._ang_buf = []

        # Recorder
        self.rec = Recorder()

        # Workers bundle (StartResult)
        self.started: Optional[StartResult] = None

        # Runtime
        self.running = False
        self.t_start = None
        self.t_stop = 0.0
        # Last data timestamps for dynamic ONLINE/OFFLINE
        self._last_emg = None
        self._last_cop = None
        self._last_pose = None

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----- helpers -----
    def _auto_suffix(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        elapsed = 0 if not self.t_start else int(max(0, time.time() - self.t_start))
        return f"{stamp}_{elapsed}s"

    def _set_status(self, label: tk.Label, name: str, online: bool, msg: str = ""):
        if online:
            label.config(text=f"{name}: ONLINE", fg="green")
        else:
            label.config(text=f"{name}: OFFLINE{(' — ' + msg) if msg else ''}", fg="red")

    def _refresh_status_labels(self):
        if self.started is None:
            for lbl, name in ((self.lbl_emg, "EMG"), (self.lbl_cop, "CoP"), (self.lbl_pose, "Pose")):
                lbl.config(text=f"{name}: —", fg="gray")
            return
        self._set_status(self.lbl_emg, "EMG", self.started.emg is not None, self.started.errors.get("emg", ""))
        self._set_status(self.lbl_cop, "CoP",  self.started.cop is not None, self.started.errors.get("cop", ""))
        self._set_status(self.lbl_pose, "Pose", self.started.pose is not None, self.started.errors.get("pose", ""))

    def _update_dynamic_status(self, now: float, threshold: float = 2.0):
        if not self.started:
            return
        # EMG
        emg_online = self.started.emg is not None and self._last_emg is not None and (now - self._last_emg) < threshold
        emg_msg = "" if self.started.emg else self.started.errors.get("emg", "")
        if self.started.emg and not emg_online:
            emg_msg = "no data"
        self._set_status(self.lbl_emg, "EMG", emg_online if self.started.emg else False, emg_msg)
        # CoP
        cop_online = self.started.cop is not None and self._last_cop is not None and (now - self._last_cop) < threshold
        cop_msg = "" if self.started.cop else self.started.errors.get("cop", "")
        if self.started.cop and not cop_online:
            cop_msg = "no data"
        self._set_status(self.lbl_cop, "CoP", cop_online if self.started.cop else False, cop_msg)
        # Pose
        pose_online = self.started.pose is not None and self._last_pose is not None and (now - self._last_pose) < threshold
        pose_msg = "" if self.started.pose else self.started.errors.get("pose", "")
        if self.started.pose and not pose_online:
            pose_msg = "no data"
        self._set_status(self.lbl_pose, "Pose", pose_online if self.started.pose else False, pose_msg)

    # ----- UI actions -----
    def toggle_start(self):
        if not self.running:
            # duration
            try:
                dur = float(self.e_len.get() or "20")
            except Exception:
                dur = 20.0
            dur = max(1.0, dur)

            # EMG MAC override
            mac = (self.e_mac.get() or "").strip() or self.cfg.emg_mac

            # load cfg copy with overridden MAC
            cfg = load_config()
            cfg.emg_mac = mac

            # Start forgiving
            self.started = start_workers_forgiving(cfg, want_emg=True, want_cop=True, want_pose=True)

            # If nothing started, show status and bail
            if not any((self.started.emg, self.started.cop, self.started.pose)):
                self._refresh_status_labels()
                print("[WARN] No devices online. Nothing to run.")
                return

            # reset plot buffers and timer
            self._emg_buf.clear()
            self._ang_buf.clear()
            self.t_start = time.time()
            self.t_stop = self.t_start + dur
            self.running = True
            self.b_start.config(text="Stop")

            # update status bar
            self._refresh_status_labels()

            # loop
            self._tick()
        else:
            self._stop_all()
            self.b_start.config(text="Start")
            self._refresh_status_labels()

    def save_csv(self):
        base = (self.e_name.get() or "").strip()
        append = bool(self.append_var.get())
        ref = (self.ref_var.get() or "auto").lower()

        if not base:
            base = f"session_{self._auto_suffix()}"
        else:
            if append:
                base = f"{base}-{self._auto_suffix()}"

        out_dir = dated_subdir(get_sessions_dir())
        path = self.rec.to_csv_merged(out_dir, base, reference=ref)
        print(f"[OK] Saved merged CSV: {path}")

    # ----- main loop -----
    def _tick(self):
        if not self.running or self.started is None:
            return
        now = time.time()
        if now >= self.t_stop:
            self.toggle_start()  # stop
            return

        # Latest samples
        emg  = get_latest(self.started.emg.queue,  default=None) if self.started.emg else None
        cop  = get_latest(self.started.cop.queue,  default=None) if self.started.cop else None
        pose = get_latest(self.started.pose.landmarks_q, default=None) if self.started.pose else None
        ang  = get_latest(self.started.pose.angle_q,     default=None) if self.started.pose else None

        # --- EMG plot ---
        if emg:
            self._emg_buf.append(emg.value)
            # buffer grande para scroll suave
            buf_max = max(self.emg_plot_window * 25, 2000)
            self._emg_buf = self._emg_buf[-buf_max:]
            x = np.arange(len(self._emg_buf))
            self.emg_line.set_data(x, self._emg_buf)

            right = len(self._emg_buf)
            left  = max(0, right - self.emg_plot_window)
            self.ax[0, 0].set_xlim(left, left + self.emg_plot_window)

            # auto-ylim en ventana visible, con ymin>=0
            if (right - left) >= min(50, self.emg_plot_window):
                arr = np.asarray(self._emg_buf[left:right], dtype=float)
                lo = float(np.nanpercentile(arr, 1))
                hi = float(np.nanpercentile(arr, 99))
                if hi > lo:
                    margin = 0.15 * (hi - lo)
                    ymin = max(0.0, lo - margin)
                    ymax = hi + margin
                    if ymax - ymin < 1e-3:
                        ymin = 0.0
                        ymax = max(0.5, ymax)
                    self.ax[0, 0].set_ylim(ymin, ymax)

        # --- CoP plot (solo punto) ---
        if cop:
            self.cop_point.set_data([cop.x], [cop.y])

        # --- Pose plot ---
        if pose and pose.landmarks is not None and pose.landmarks.size > 0:
            self.bt_scat.set_offsets(pose.landmarks)

        # --- Angle plot ---
        if ang:
            self._ang_buf.append(ang.deg)
            buf_max = max(self.angle_plot_window * 40, 2000)
            self._ang_buf = self._ang_buf[-buf_max:]
            x = np.arange(len(self._ang_buf))
            self.ang_line.set_data(x, self._ang_buf)
            right = len(self._ang_buf)
            left  = max(0, right - self.angle_plot_window)
            self.ax[1, 1].set_xlim(left, left + self.angle_plot_window)
            # y permanece fijo en [-90, 90]

        # --- Recording ---
        self.rec.push_emg(emg)
        self.rec.push_cop(cop)
        self.rec.push_pose(pose)
        self.rec.push_angle(ang)

        # Timestamps para ONLINE/OFFLINE
        if emg:  self._last_emg  = now
        if cop:  self._last_cop  = now
        if pose: self._last_pose = now

        self.canvas.draw_idle()
        self._update_dynamic_status(now)
        self.root.after(16, self._tick)

    def _stop_all(self):
        if self.started:
            stop_workers(self.started)
        self.running = False
        self.started = None

    def on_close(self):
        self._stop_all()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
