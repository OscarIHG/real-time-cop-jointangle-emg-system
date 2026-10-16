# -*- coding: utf-8 -*-
"""
Tkinter + Matplotlib GUI, laid out like the paper's Fig. 3, on top of
AcquisitionSession.

Rendering uses blitting: the static parts of each subplot (axes, ticks,
titles, grid) are cached once per resize, and every tick only restores the
cached background and redraws the animated artists of the subplots that
changed (``line.set_data`` + ``draw_artist`` + ``blit``). This avoids
``ax.clear()`` + ``ax.plot()`` + full ``canvas.draw()``, which costs hundreds
of milliseconds per frame on a Raspberry Pi 4.

Tk is not thread-safe: hardware connect/close, tare and saving run in worker
threads that report back through a queue drained by ``root.after``.
"""

if __package__ is None or __package__ == "":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure

from acquisition_systems.session import AcquisitionSession

try:
    from mediapipe.python.solutions.pose import POSE_CONNECTIONS
except Exception:
    POSE_CONNECTIONS = ()


class TkApp:
    def __init__(self, root: tk.Tk, session: AcquisitionSession, args=None):
        self.root = root
        self.session = session
        self.cfg = session.cfg
        self.args = args
        self._results: queue.Queue = queue.Queue()
        self._closing = False
        self._destroyed = False
        self._tick_ms = []
        self._frames = 0
        self._fps_t = time.perf_counter()
        self.gui_fps = 0.0
        self._conn = np.array(list(POSE_CONNECTIONS), dtype=int).reshape(-1, 2)
        self._bg = {}

        root.title("Real-Time CoP-JointAngle-EMG System")
        root.geometry("1100x780")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build_controls()
        self._build_figure()
        self._run_background("connect", self.session.connect)
        self.root.after(self.cfg.gui_update_ms, self._tick)

    # ---------- layout ----------
    def _build_controls(self):
        bar = tk.Frame(self.root)
        bar.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
        tk.Label(bar, text="Enter recording length in seconds (s):").pack(side=tk.LEFT)
        self.e_len = tk.Entry(bar, width=8)
        self.e_len.insert(0, str(int(getattr(self.args, "duration", 20) or 20)))
        self.e_len.pack(side=tk.LEFT, padx=4)
        self.b_start = tk.Button(bar, text="Start", width=8, command=self.toggle_start, state=tk.DISABLED)
        self.b_start.pack(side=tk.LEFT, padx=4)
        tk.Label(bar, text="Filename:").pack(side=tk.LEFT, padx=(20, 0))
        self.e_name = tk.Entry(bar, width=24)
        self.e_name.pack(side=tk.LEFT, padx=4)
        self.b_save = tk.Button(bar, text="Save", width=8, command=self.save, state=tk.DISABLED)
        self.b_save.pack(side=tk.LEFT, padx=4)
        self.b_tare = tk.Button(bar, text="Tare", width=8, command=self.tare, state=tk.DISABLED)
        self.b_tare.pack(side=tk.LEFT, padx=4)
        self.status = tk.Label(self.root, text="Connecting hardware...", anchor="w")
        self.status.pack(side=tk.TOP, fill=tk.X, padx=6)

    def _build_figure(self):
        cfg = self.cfg
        self.fig = Figure(figsize=(11, 7), dpi=100)
        (self.ax_emg, self.ax_cop), (self.ax_pose, self.ax_ang) = self.fig.subplots(2, 2)

        ax = self.ax_emg
        ax.set_title("Abdominal EMG")
        ax.set_xlim(-cfg.emg_plot_window, 0)
        ax.set_ylim(cfg.emg_vmin, cfg.emg_vmax)
        ax.set_xlabel("Time [s]"); ax.set_ylabel("EMG [V]")
        (self.l_emg,) = ax.plot([], [], lw=0.8, color="tab:blue", animated=True)

        ax = self.ax_cop
        ax.set_title("Center of Pressure")
        xh, yh = cfg.cop_x_half_range_cm, cfg.cop_y_half_range_cm
        ax.set_xlim(-xh, xh); ax.set_ylim(-yh, yh)
        ax.set_xticks([-xh, 0, xh]); ax.set_yticks([-yh, 0, yh])
        ax.axhline(0, color="0.8", lw=0.8); ax.axvline(0, color="0.8", lw=0.8)
        (self.l_cop,) = ax.plot([], [], "o", ms=9, color="tab:blue", animated=True)

        ax = self.ax_pose
        ax.set_title("Body-Tracking")
        ax.set_xlim(0, cfg.cam_width); ax.set_ylim(cfg.cam_height, 0)  # image coordinates
        self.lc_pose = LineCollection([], colors="blue", linewidths=1.5, animated=True)
        ax.add_collection(self.lc_pose)
        (self.l_pose,) = ax.plot([], [], "o", ms=4, color="red", animated=True)

        ax = self.ax_ang
        ax.set_title("Joint Angle")
        lim = cfg.angle_plot_limit_deg
        ax.set_ylim(-lim, lim)
        ax.set_xlim(0, cfg.angle_plot_window)
        ax.set_xlabel("Time [s]"); ax.set_ylabel("Pelvic obliquity [deg]")
        (self.l_ang,) = ax.plot([], [], lw=1.2, color="blue", animated=True)

        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("draw_event", self._on_draw)
        self._artists = {
            self.ax_emg: (self.l_emg,), self.ax_cop: (self.l_cop,),
            self.ax_pose: (self.lc_pose, self.l_pose), self.ax_ang: (self.l_ang,),
        }
        self.canvas.draw()

    def _on_draw(self, _event):
        """Cache static backgrounds after any full draw (startup, resize, limit change)."""
        self._bg = {ax: self.canvas.copy_from_bbox(ax.bbox) for ax in self._artists}
        for ax, artists in self._artists.items():
            for a in artists:
                ax.draw_artist(a)

    def _blit(self, axes):
        if not self._bg:
            return
        for ax in axes:
            self.canvas.restore_region(self._bg[ax])
            for a in self._artists[ax]:
                ax.draw_artist(a)
            self.canvas.blit(ax.bbox)

    def _set_angle_xlim(self, left, right):
        self.ax_ang.set_xlim(left, right)
        self.canvas.draw()  # static background changed; draw_event re-caches it

    # ---------- background work ----------
    def _run_background(self, name, fn, *a):
        def work():
            try:
                result = fn(*a)
            except Exception as exc:
                traceback.print_exc()
                result = exc
            self._results.put((name, result))
        threading.Thread(target=work, name=f"gui-{name}", daemon=True).start()

    def _handle_results(self):
        while True:
            try:
                name, result = self._results.get_nowait()
            except queue.Empty:
                return
            if name == "connect":
                for b in (self.b_start, self.b_save):
                    b.config(state=tk.NORMAL)
                self.b_tare.config(state=tk.NORMAL if self.session.cop is not None else tk.DISABLED)
                errs = {k: v for k, v in result.items() if v} if isinstance(result, dict) else {}
                if errs:
                    print(f"[GUI] Offline modules: {errs}")
                if getattr(self.args, "autostart", False):
                    self.root.after(1500, self.toggle_start)
            elif name == "save":
                self.b_save.config(state=tk.NORMAL)
                if isinstance(result, Exception):
                    messagebox.showwarning("Save failed", str(result))
                else:
                    print(f"[OK] Saved: {result.get('merged')}")
                    if getattr(self.args, "exit_after", False):
                        self.on_close()
            elif name == "tare":
                self.b_tare.config(state=tk.NORMAL)
                print(f"[GUI] Tare: {result}")
            elif name == "close":
                _print_gui_stats("tk", self._tick_ms)
                self._destroyed = True
                self.root.destroy()
                return

    # ---------- controls ----------
    def toggle_start(self):
        if self.session.state == "idle":
            try:
                dur = max(1.0, float(self.e_len.get() or "20"))
            except ValueError:
                dur = 20.0
            self.session.start_recording(dur)
            self._set_angle_xlim(0, dur)
            self.b_start.config(text="Stop")
            self.b_save.config(state=tk.DISABLED)
        else:
            self.session.stop_recording()

    def save(self):
        snapshot = self.session.snapshot()   # copy on the Tk thread
        self.b_save.config(state=tk.DISABLED)
        self._run_background("save", self.session.export, snapshot, self.e_name.get())

    def tare(self):
        self.b_tare.config(state=tk.DISABLED)
        self._run_background("tare", self.session.tare)

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        self.status.config(text="Stopping hardware...")
        self._run_background("close", self.session.close)

    # ---------- refresh ----------
    def _tick(self):
        t_start = time.perf_counter()
        try:
            self._handle_results()
            if self._destroyed:
                return
            if self._closing:
                self.root.after(50, self._tick)
                return
            live = self.session.poll()
            dirty = []
            if live.new_emg:
                self.l_emg.set_data(live.emg_t, live.emg_v)
                dirty.append(self.ax_emg)
            if live.new_cop:
                if live.cop_xy is None:
                    self.l_cop.set_data([], [])
                else:
                    self.l_cop.set_data([live.cop_xy[0]], [live.cop_xy[1]])
                dirty.append(self.ax_cop)
            if live.pose is not None:
                lm = live.pose.landmarks
                if live.pose.detected:
                    self.l_pose.set_data(lm[:, 0], lm[:, 1])
                    self.lc_pose.set_segments(lm[self._conn] if self._conn.size else [])
                else:
                    self.l_pose.set_data([], [])
                    self.lc_pose.set_segments([])
                dirty.append(self.ax_pose)
                if live.angle_t.size:
                    self.l_ang.set_data(live.angle_t, live.angle_v)
                    left, right = self.ax_ang.get_xlim()
                    if live.state == "idle" and live.angle_t[-1] > right:
                        # Page the preview window (rare full redraw instead of scrolling every tick).
                        span = self.cfg.angle_plot_window
                        self._set_angle_xlim(live.angle_t[-1] - span / 2, live.angle_t[-1] + span / 2)
                    dirty.append(self.ax_ang)
            self._blit(dirty)
            if live.recording_done:
                self.b_start.config(text="Start")
                self.b_save.config(state=tk.NORMAL)
                if getattr(self.args, "autosave", False):
                    self.save()
            if self._frames == 0:
                state = f"REC {live.elapsed_s:5.1f}/{live.duration_s:.0f} s | " if live.state != "idle" else ""
                self.status.config(text=f"{state}{self.session.status_text()} | GUI {self.gui_fps:.0f} FPS")
        except Exception:
            print("[GUI] Tick error:")
            traceback.print_exc()
        self._tick_ms.append((time.perf_counter() - t_start) * 1000)
        self._frames += 1
        now = time.perf_counter()
        if now - self._fps_t >= 1.0:
            self.gui_fps = self._frames / (now - self._fps_t)
            self._frames, self._fps_t = 0, now
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        self.root.after(max(1, self.cfg.gui_update_ms - elapsed_ms), self._tick)


def _print_gui_stats(name, tick_ms):
    if tick_ms:
        a = np.asarray(tick_ms[5:] or tick_ms)
        print(f"[GUI-{name}] ticks={a.size} tick_ms p50={np.percentile(a, 50):.2f} p95={np.percentile(a, 95):.2f}")


def run(args=None, session: AcquisitionSession = None):
    root = tk.Tk()
    TkApp(root, session or AcquisitionSession(emg_source=getattr(args, "emg_source", None)), args)
    root.mainloop()
    return 0


def main():
    from acquisition_systems.app_gui import main as launcher
    return launcher(["--gui", "tk"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
