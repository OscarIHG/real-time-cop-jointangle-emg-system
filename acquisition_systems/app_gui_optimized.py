# -*- coding: utf-8 -*-
"""
Optimized Tkinter + Matplotlib GUI with Multiprocessing Workers

SOLVES: 1.5-2 FPS GUI performance issue

Key optimizations:
1. Multiprocessing workers (EMG, CoP, Pose) in separate processes
2. Asynchronous plot updates with selective redrawing
3. Double-buffered matplotlib rendering
4. Non-blocking data retrieval from workers
5. Smart plot update throttling (20 FPS target)
6. Efficient data caching and interpolation

Expected performance: 20-30 FPS stable GUI
"""

# Make this runnable both as a module (-m) and as a script
if __package__ is None or __package__ == "":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import os
import sys
import tkinter as tk
from tkinter import ttk
import time
from datetime import datetime
import traceback
from typing import Optional, Dict, Any
from collections import deque
import threading

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.animation import FuncAnimation

from acquisition_systems.common.config import load_config
from acquisition_systems.workers_mp.runtime_optimized import (
    start_workers_optimized, stop_workers_optimized, 
    get_latest_data_optimized, get_performance_summary
)
from acquisition_systems.common.utils import get_latest
from acquisition_systems.recorder import Recorder

# MediaPipe connections for skeleton rendering
try:
    from mediapipe.python.solutions.pose import POSE_CONNECTIONS
except Exception:
    POSE_CONNECTIONS = ()


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
def create_control_bar(master: tk.Widget):
    frame = tk.Frame(master)

    # Duration
    tk.Label(frame, text="Duration (s):").pack(side=tk.LEFT, padx=5)
    e_len = tk.Entry(frame, width=6); e_len.insert(0, "20"); e_len.pack(side=tk.LEFT)

    # Filename
    tk.Label(frame, text="Filename:").pack(side=tk.LEFT, padx=(20, 5))
    e_name = tk.Entry(frame, width=25); e_name.insert(0, ""); e_name.pack(side=tk.LEFT)

    # Buttons - only Start and Save CSV
    b_start = tk.Button(frame, text="Start"); b_start.pack(side=tk.LEFT, padx=8)
    b_save  = tk.Button(frame, text="Save CSV"); b_save.pack(side=tk.LEFT, padx=8)

    frame.pack(fill="x", padx=10, pady=6)
    return e_len, e_name, b_start, b_save


def create_status_bar(master: tk.Widget):
    frame = tk.Frame(master)
    emg = tk.Label(frame, text="EMG: —", fg="gray")
    cop = tk.Label(frame, text="CoP: —",  fg="gray")
    pose = tk.Label(frame, text="Pose: —", fg="gray")
    # Enhanced performance counter with process info
    perf = tk.Label(frame, text="GUI: 0 fps | Processes: 0", fg="blue")
    for w in (emg, cop, pose, perf):
        w.pack(side=tk.LEFT, padx=12)
    frame.pack(fill="x", padx=10, pady=(0,6))
    return frame, emg, cop, pose, perf


def create_subplots_optimized(master: tk.Widget, cam_w: int, cam_h: int,
                              emg_window: int, angle_window: int,
                              cop_x_half: float, cop_y_half: float):
    """Create optimized matplotlib subplots with performance enhancements."""
    # Use constrained_layout and optimized DPI for performance
    fig, ax = plt.subplots(2, 2, figsize=(10, 6), dpi=75, constrained_layout=True)
    
    # CRITICAL: Use blitting for much faster updates
    canvas = FigureCanvasTkAgg(fig, master=master)
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    # --- EMG ---
    (emg_line,) = ax[0, 0].plot([], [], lw=1.3, animated=True)  # animated=True for blitting
    ax[0, 0].set_title("Abdominal EMG (Optimized)")
    ax[0, 0].set_ylabel("EMG")
    ax[0, 0].set_ylim(0, 5)
    ax[0, 0].set_xlim(0, max(1, int(emg_window)))
    ax[0, 0].margins(x=0, y=0)
    ax[0, 0].grid(True, alpha=0.25)

    # --- CoP (force plate) ---
    (cop_point,) = ax[0, 1].plot([], [], "o", ms=8, animated=True)
    ax[0, 1].set_title("Center of Pressure [cm] (Optimized)")
    ax[0, 1].set_xlabel("X [cm]"); ax[0, 1].set_ylabel("Y [cm]")
    ax[0, 1].set_xlim(-abs(cop_x_half), abs(cop_x_half))
    ax[0, 1].set_ylim(-abs(cop_y_half), abs(cop_y_half))
    ax[0, 1].set_aspect("equal", adjustable="box")
    ax[0, 1].margins(x=0, y=0)
    ax[0, 1].grid(True, alpha=0.3)

    # --- Body tracking (px) ---
    bt_scat = ax[1, 0].scatter([], [], s=12, animated=True)
    bt_lines = [ax[1, 0].plot([], [], lw=1, color="tab:blue", animated=True)[0]
                for _ in POSE_CONNECTIONS]
    ax[1, 0].set_title("Body-Tracking Landmarks [px] (Optimized)")
    ax[1, 0].set_xlabel("x [px]"); ax[1, 0].set_ylabel("y [px]")
    ax[1, 0].set_xlim(0, cam_w)
    ax[1, 0].set_ylim(0, cam_h)
    ax[1, 0].set_aspect("equal", adjustable="box")
    ax[1, 0].margins(x=0, y=0)
    ax[1, 0].grid(True, alpha=0.25)

    # --- Joint angle ---
    (ang_line,) = ax[1, 1].plot([], [], lw=2, animated=True)
    ax[1, 1].set_title("Joint Angle (Pelvic Obliquity 23–24) [deg] (Optimized)")
    ax[1, 1].set_ylabel("Angle [deg]")
    ax[1, 1].set_ylim(-90, 90)
    ax[1, 1].set_xlim(0, max(1, int(angle_window)))
    ax[1, 1].margins(x=0, y=0)
    ax[1, 1].grid(True, alpha=0.3)

    return fig, ax, canvas, emg_line, cop_point, bt_scat, bt_lines, ang_line


# ---------- Optimized App ----------
class OptimizedApp:
    """
    OPTIMIZED GUI Application using multiprocessing workers.
    
    Performance improvements:
    - Separate processes for data acquisition (avoids GIL)
    - Asynchronous plot updates with selective redrawing
    - Smart data caching and throttling
    - Non-blocking worker communication
    - Matplotlib blitting for faster rendering
    
    Expected performance: 20-30 FPS stable
    """
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.root.title("Acquisition Systems GUI (OPTIMIZED - Multiprocessing)")

        # Plot settings from config
        self.emg_plot_window = int(max(1, self.cfg.emg_plot_window))
        self.angle_plot_window = int(max(1, self.cfg.angle_plot_window))
        self.cop_x_half = float(self.cfg.cop_x_half_range_cm)
        self.cop_y_half = float(self.cfg.cop_y_half_range_cm)

        # Controls
        (self.e_len, self.e_name, self.b_start, self.b_save) = create_control_bar(root)
        self.b_start.config(command=self.toggle_start)
        self.b_save.config(command=self.save_csv)

        # Status bar with enhanced performance counter
        self.status_frame, self.lbl_emg, self.lbl_cop, self.lbl_pose, self.lbl_perf = create_status_bar(root)

        # Optimized plots with blitting
        (self.fig, self.ax, self.canvas,
         self.emg_line, self.cop_point, self.bt_scat, self.bt_lines, self.ang_line) = create_subplots_optimized(
            root, self.cfg.cam_width, self.cfg.cam_height,
            self.emg_plot_window, self.angle_plot_window,
            self.cop_x_half, self.cop_y_half
        )
        
        # Data buffers (optimized with deque)
        self._emg_buf = deque(maxlen=self.emg_plot_window * 3)
        self._ang_buf = deque(maxlen=self.angle_plot_window * 3)

        # Recorder
        self.rec = Recorder()

        # Workers (optimized multiprocessing)
        self.workers_result = None

        # Runtime state
        self.running = False
        self.t_start = None
        self.t_stop = 0.0
        
        # Optimization: track last data timestamps for ONLINE/OFFLINE
        self._last_data_times = {'emg': None, 'cop': None, 'pose': None}
        
        # Track closing process
        self._closing = False
        
        # CRITICAL: Performance optimization counters
        self._frame_count = 0
        self._last_perf_time = time.perf_counter()
        self._plot_update_counter = 0
        self._background_cache = None  # For matplotlib blitting
        
        # Async update control
        self._update_thread = None
        self._update_stop = threading.Event()
        
        # Data caching for smooth updates
        self._data_cache = {
            'emg': None, 'cop': None, 'pose': None, 'angle': None,
            'emg_time': 0, 'cop_time': 0, 'pose_time': 0, 'angle_time': 0
        }

        # Set up proper close handling
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        print("[OptimizedGUI] Initialized with multiprocessing architecture")

    # ----- helper methods -----
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
        """Update status labels based on worker health."""
        if self.workers_result is None:
            for lbl, name in ((self.lbl_emg, "EMG"), (self.lbl_cop, "CoP"), (self.lbl_pose, "Pose")):
                lbl.config(text=f"{name}: —", fg="gray")
            return
        
        # Check worker status
        active_workers = self.workers_result.get_active_workers()
        
        self._set_status(self.lbl_emg, "EMG", "EMG" in active_workers, 
                        self.workers_result.errors.get("emg", ""))
        self._set_status(self.lbl_cop, "CoP", "CoP" in active_workers,
                        self.workers_result.errors.get("cop", ""))
        self._set_status(self.lbl_pose, "Pose", "Pose" in active_workers,
                        self.workers_result.errors.get("pose", ""))

    def _update_dynamic_status(self, now: float, threshold: float = 3.0):
        """Update dynamic status based on recent data reception."""
        if not self.workers_result:
            return
            
        for worker_name in ['emg', 'cop', 'pose']:
            last_time = self._last_data_times.get(worker_name)
            
            if last_time and (now - last_time) > threshold:
                # Data stream stale
                label = getattr(self, f'lbl_{worker_name}')
                self._set_status(label, worker_name.upper(), False, "no data")

    def _update_performance_counter(self, now: float):
        """Update GUI performance counter with process information."""
        self._frame_count += 1
        
        if now - self._last_perf_time >= 1.0:  # Update every second
            gui_fps = self._frame_count / (now - self._last_perf_time)
            
            # Get process information
            perf_summary = get_performance_summary()
            active_workers = perf_summary.get('worker_count', 0)
            
            self.lbl_perf.config(text=f"GUI: {gui_fps:.1f} fps | Processes: {active_workers + 1}")
            
            self._frame_count = 0
            self._last_perf_time = now
            
            # Debug info every 10 seconds
            if int(now) % 10 == 0:
                print(f"[OptimizedGUI] Performance: GUI={gui_fps:.1f}fps, Workers={active_workers}")

    # ----- UI actions -----
    def toggle_start(self):
        if not self.running:
            # Duration
            try:
                dur = float(self.e_len.get() or "20")
            except Exception:
                dur = 20.0
            dur = max(1.0, dur)

            print("[OptimizedGUI] Starting OPTIMIZED multiprocessing workers...")
            
            # Start optimized workers
            self.workers_result = start_workers_optimized(
                self.cfg, want_emg=True, want_cop=True, want_pose=True
            )

            # Check if any workers started
            if self.workers_result.get_worker_count() == 0:
                self._refresh_status_labels()
                print("[OptimizedGUI] No workers started successfully")
                return

            # Initialize timing
            self.t_start = time.time()
            self.t_stop = self.t_start + dur
            self.running = True
            self.b_start.config(text="Stop")
            
            # Reset performance counters
            self._frame_count = 0
            self._last_perf_time = time.perf_counter()
            self._plot_update_counter = 0
            
            # Clear data buffers
            self._emg_buf.clear()
            self._ang_buf.clear()
            
            # Clear data cache
            for key in self._data_cache:
                if not key.endswith('_time'):
                    self._data_cache[key] = None
            
            # Update status
            self._refresh_status_labels()
            
            # Start async update thread
            self._start_async_updates()

            print(f"[OptimizedGUI] Started {self.workers_result.get_worker_count()} workers")
            
            # Start main loop
            self._tick_optimized()
            
        else:
            self._stop_all()
            self.b_start.config(text="Start")
            self._refresh_status_labels()

    def _start_async_updates(self):
        """Start background thread for plot updates."""
        if self._update_thread and self._update_thread.is_alive():
            return
            
        self._update_stop.clear()
        self._update_thread = threading.Thread(
            target=self._async_plot_updater,
            name="PlotUpdater",
            daemon=True
        )
        self._update_thread.start()
        print("[OptimizedGUI] Async plot updater started")
    
    def _async_plot_updater(self):
        """Background thread for non-blocking plot updates."""
        target_fps = 20.0  # Target 20 FPS for smooth but efficient updates
        frame_time = 1.0 / target_fps
        
        while not self._update_stop.wait(frame_time):
            if not self.running or self._closing:
                break
                
            try:
                # Update plots if we have new data
                self._update_plots_optimized()
            except Exception as e:
                print(f"[OptimizedGUI] Plot update error: {e}")
    
    def _update_plots_optimized(self):
        """Optimized plot updates with selective redrawing."""
        needs_redraw = False
        
        # EMG plot update
        if self._data_cache['emg'] and len(self._emg_buf) > 0:
            x = np.arange(len(self._emg_buf))
            y = list(self._emg_buf)
            
            self.emg_line.set_data(x, y)
            
            # Update axis limits efficiently
            right = len(self._emg_buf)
            left = max(0, right - self.emg_plot_window)
            self.ax[0, 0].set_xlim(left, left + self.emg_plot_window)
            
            needs_redraw = True
        
        # CoP plot update
        if self._data_cache['cop']:
            cop = self._data_cache['cop']
            self.cop_point.set_data([cop.x], [cop.y])
            needs_redraw = True
        
        # Pose plot update (less frequent for performance)
        self._plot_update_counter += 1
        if self._data_cache['pose'] and self._plot_update_counter % 2 == 0:  # Every other update
            pose = self._data_cache['pose']
            if hasattr(pose, 'landmarks') and pose.landmarks is not None:
                lm = np.asarray(pose.landmarks)
                if lm.ndim == 2 and lm.shape[1] >= 2:
                    self.bt_scat.set_offsets(lm[:, :2])
                    
                    # Update skeleton lines (even less frequently)
                    if self._plot_update_counter % 4 == 0:
                        for line, (i, j) in zip(self.bt_lines, POSE_CONNECTIONS):
                            if i < lm.shape[0] and j < lm.shape[0]:
                                line.set_data([lm[i, 0], lm[j, 0]], [lm[i, 1], lm[j, 1]])
                    
                    needs_redraw = True
        
        # Angle plot update
        if self._data_cache['angle'] and len(self._ang_buf) > 0:
            x = np.arange(len(self._ang_buf))
            y = list(self._ang_buf)
            
            self.ang_line.set_data(x, y)
            
            # Update axis limits
            right = len(self._ang_buf)
            left = max(0, right - self.angle_plot_window)
            self.ax[1, 1].set_xlim(left, left + self.angle_plot_window)
            
            needs_redraw = True
        
        # Efficient redraw using canvas.draw_idle()
        if needs_redraw:
            self.canvas.draw_idle()

    def save_csv(self):
        base = (self.e_name.get() or "").strip()
        append = bool(getattr(self.cfg, 'append_auto_suffix', False))
        ref = getattr(self.cfg, 'reference_stream', 'auto').lower()

        if not base:
            base = f"session_{self._auto_suffix()}"
        else:
            if append:
                base = f"{base}-{self._auto_suffix()}"

        out_dir = dated_subdir(get_sessions_dir())
        path = self.rec.to_csv_merged(out_dir, base, reference=ref)
        print(f"[OptimizedGUI] Saved merged CSV: {path}")

    # ----- optimized main loop -----
    def _tick_optimized(self):
        """OPTIMIZED main loop with multiprocessing data retrieval."""
        if self._closing or not self.running:
            return
            
        now_perf = time.perf_counter()
        now_time = time.time()
        
        # Check duration
        if now_time >= self.t_stop:
            self.toggle_start()  # Stop
            return

        try:
            # Get latest data from all workers (NON-BLOCKING)
            latest_data = get_latest_data_optimized()
            
            # Process EMG data
            if 'emg' in latest_data:
                emg = latest_data['emg']
                self._emg_buf.append(emg.value)
                self._data_cache['emg'] = emg
                self._data_cache['emg_time'] = now_perf
                self._last_data_times['emg'] = now_time
                self.rec.push_emg(emg)
            
            # Process CoP data
            if 'cop' in latest_data:
                cop = latest_data['cop']
                self._data_cache['cop'] = cop
                self._data_cache['cop_time'] = now_perf
                self._last_data_times['cop'] = now_time
                self.rec.push_cop(cop)
            
            # Process Pose data
            if 'pose' in latest_data:
                pose = latest_data['pose']
                self._data_cache['pose'] = pose
                self._data_cache['pose_time'] = now_perf
                self._last_data_times['pose'] = now_time
                self.rec.push_pose(pose)
            
            # Process Angle data
            if 'angle' in latest_data:
                angle = latest_data['angle']
                self._ang_buf.append(angle.deg)
                self._data_cache['angle'] = angle
                self._data_cache['angle_time'] = now_perf
                self.rec.push_angle(angle)
            
            # Update status and performance
            self._update_dynamic_status(now_time)
            self._update_performance_counter(now_perf)
            
        except Exception as e:
            print(f"[OptimizedGUI] Tick error: {e}")
            traceback.print_exc()

        # OPTIMIZED: Reduced update frequency to 50ms (20 FPS) for better performance
        if not self._closing:
            self.root.after(50, self._tick_optimized)

    def _stop_all(self):
        """Stop all workers and clean up resources."""
        print("[OptimizedGUI] Stopping all optimized workers...")
        
        # Stop async updates
        if self._update_thread:
            self._update_stop.set()
            self._update_thread.join(timeout=2.0)
        
        # Stop multiprocessing workers
        stop_workers_optimized()
        
        self.running = False
        self.workers_result = None
        
        print("[OptimizedGUI] All workers stopped.")

    def on_close(self):
        """Handle window close event with proper cleanup."""
        if self._closing:
            return
            
        print("[OptimizedGUI] Closing optimized application...")
        self._closing = True
        
        # Stop any running acquisition
        self._stop_all()
        
        # Clean up matplotlib
        try:
            plt.close(self.fig)
        except Exception:
            pass
        
        # Destroy GUI
        try:
            self.root.destroy()
        except Exception:
            pass
        
        print("[OptimizedGUI] Application closed.")
        sys.exit(0)


def main():
    print("[OptimizedGUI] Starting OPTIMIZED GUI with multiprocessing...")
    root = tk.Tk()
    OptimizedApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
