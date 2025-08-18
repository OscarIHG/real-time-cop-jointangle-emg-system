# -*- coding: utf-8 -*-
"""
Unified Tk GUI for real-time plots + CSV logging:
  Subplots:
    [0,0] EMG (rolling)
    [0,1] Center of Pressure (scatter, last point)
    [1,0] Body-Tracking landmarks (scatter)
    [1,1] Joint Angle (hip 23–24, deg vs time)

CSV:
  - One wide CSV with columns:
    time_s, emg_V, cop_x_cm, cop_y_cm, angle_deg,
    lm0_x, lm0_y, ..., lm32_x, lm32_y  (MediaPipe Pose 33 landmarks)
  - Logged at ~60 Hz (GUI update rate) with last-known values (forward-fill)
  - If filename is empty, an automatic one is used: session_YYYYmmdd-HHMMSS_{dur}s.csv
"""

import tkinter as tk
import time
import csv
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Local workers
from abdominal_emg import EMGWorker
from center_of_pressure import CoPWorker
from body_tracking import PoseWorker

LM_COUNT = 33  # MediaPipe Pose landmarks


def create_control_bar(master: tk.Widget):
    """Top bar with duration, Start/Stop, and Save CSV name."""
    frame = tk.Frame(master)
    tk.Label(frame, text="Recording length (s):").pack(side=tk.LEFT, padx=5)
    length_entry = tk.Entry(frame, width=6)
    length_entry.insert(0, "20")
    length_entry.pack(side=tk.LEFT)
    start_button = tk.Button(frame, text="Start")
    start_button.pack(side=tk.LEFT, padx=6)
    tk.Label(frame, text="Filename:").pack(side=tk.LEFT, padx=(20, 5))
    filename_entry = tk.Entry(frame, width=22)
    filename_entry.insert(0, "")
    filename_entry.pack(side=tk.LEFT)
    save_button = tk.Button(frame, text="Save CSV")
    save_button.pack(side=tk.LEFT, padx=6)
    frame.pack(fill="x", padx=10, pady=6)
    return length_entry, start_button, filename_entry, save_button


def create_subplots(master: tk.Widget):
    """A 2x2 Matplotlib figure embedded into Tk."""
    fig, ax = plt.subplots(nrows=2, ncols=2, figsize=(10, 6))
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    canvas = FigureCanvasTkAgg(fig, master=master)
    canvas.draw()
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)
    return fig, ax, canvas


class App:
    def __init__(self, master: tk.Tk):
        self.master = master
        self.master.title("Proyecto Modular")

        screen_w, screen_h = master.winfo_screenwidth(), master.winfo_screenheight()
        master.geometry(f"{screen_w}x{screen_h}")

        # Controls
        self.length_entry, self.start_button, self.filename_entry, self.save_button = create_control_bar(master)
        self.start_button.config(command=self.toggle_start)
        self.save_button.config(command=self.save_csv)

        # Subplots / artists
        self.fig, self.ax, self.canvas = create_subplots(master)
        # EMG
        (self.emg_line,) = self.ax[0, 0].plot([], [], lw=1.3)
        self.ax[0, 0].set_title("Abdominal EMG (V)")
        self.ax[0, 0].set_ylim(0, 5)
        self.ax[0, 0].set_xlim(0, 1000)
        self.ax[0, 0].grid(True, alpha=0.25)
        # CoP
        (self.cop_point,) = self.ax[0, 1].plot([], [], "o", ms=8)
        self.ax[0, 1].set_title("Center of Pressure (cm)")
        self.ax[0, 1].set_xlim(-30, 30)
        self.ax[0, 1].set_ylim(-22, 22)
        self.ax[0, 1].set_aspect("equal", adjustable="box")
        self.ax[0, 1].grid(True, alpha=0.3)
        # Body-Tracking landmarks
        self.bt_scat = self.ax[1, 0].scatter([], [], s=12)
        self.ax[1, 0].set_title("Body-Tracking Landmarks (px)")
        self.ax[1, 0].set_xlim(0, 640)
        self.ax[1, 0].set_ylim(0, 480)
        self.ax[1, 0].invert_yaxis()
        self.ax[1, 0].set_aspect("equal", adjustable="box")
        self.ax[1, 0].grid(True, alpha=0.25)
        # Joint angle
        (self.ang_line,) = self.ax[1, 1].plot([], [], lw=2)
        self.ax[1, 1].set_title("Joint Angle (Pelvic Obliquity, hip 23–24) [deg]")
        self.ax[1, 1].set_ylim(-90, 90)
        self.ax[1, 1].set_xlim(0, 900)
        self.ax[1, 1].grid(True, alpha=0.3)
        self.ang_xs, self.ang_ys = [], []

        # Workers
        self.emg = None
        self.cop = None
        self.pose = None

        # Runtime state for logging
        self.running = False
        self.t_start = None
        self.t_stop = 0.0

        # Latest values (forward-filled)
        self.state_emg = np.nan
        self.state_copx = np.nan
        self.state_copy = np.nan
        self.state_angle = np.nan
        self.state_landmarks = None  # np.ndarray (N,2)

        # For plotting EMG window
        self.emg_last_len = 0

        # CSV rows buffer (list of lists)
        self.rows = []

        # Close handler
        self.master.protocol("WM_DELETE_WINDOW", self.on_close)

        # Precompute CSV header
        self.csv_header = self._build_csv_header()

    # ------------------ UI actions ------------------
    def toggle_start(self):
        """Start or stop acquisition."""
        if not self.running:
            # Start
            try:
                length_s = float(self.length_entry.get().strip() or "20")
            except Exception:
                length_s = 20.0
            length_s = max(1.0, length_s)

            self.t_start = time.time()
            self.t_stop = self.t_start + length_s
            self.rows.clear()
            self.state_emg = np.nan
            self.state_copx = np.nan
            self.state_copy = np.nan
            self.state_angle = np.nan
            self.state_landmarks = None
            self.emg_last_len = 0

            # Instantiate and start workers
            self.emg = EMGWorker(plot_window=1000)
            self.emg.start()

            self.cop = CoPWorker(data_interval_ms=10)  # ~100 Hz
            self.cop.start()

            self.pose = PoseWorker(width=640, height=480, fps=30)
            self.pose.start()

            self.running = True
            self.start_button.config(text="Stop")
            self._schedule_update()
        else:
            # Stop
            self._stop_all()
            self.start_button.config(text="Start")

    def save_csv(self):
        """Write the buffered data rows into a CSV file."""
        # Build filename
        name = (self.filename_entry.get() or "").strip()
        if not name:
            # Automatic filename: session_YYYYmmdd-HHMMSS_{dur}s.csv
            dur_s = 0 if self.t_start is None else int(round(max(0, time.time() - self.t_start)))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"session_{stamp}_{dur_s}s"
        if not name.lower().endswith(".csv"):
            name = f"{name}.csv"

        # Ensure we include a header and write rows
        try:
            with open(name, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(self.csv_header)
                writer.writerows(self.rows)
        except Exception as e:
            print(f"[WARN] Could not save CSV: {e}")
            return
        print(f"[OK] Saved CSV -> {name}")

    def on_close(self):
        """Stop everything and close window."""
        self._stop_all()
        self.master.destroy()

    # ------------------ update loop ------------------
    def _schedule_update(self):
        if not self.running:
            return
        self._poll_and_draw()
        self.master.after(16, self._schedule_update)  # ~60 Hz

    def _poll_and_draw(self):
        """Poll all queues (non-blocking), refresh artists, and log one CSV row."""
        now = time.time()
        # Auto-stop on time
        if now >= self.t_stop:
            self.toggle_start()
            return

        # --- EMG (use last sample from rolling window for logging/plot) ---
        if self.emg is not None:
            try:
                roll = self.emg.queue.get_nowait()  # list of floats
                if roll:
                    self.state_emg = float(roll[-1])
                    # Update EMG line
                    x = np.arange(len(roll))
                    self.emg_line.set_data(x, roll)
                    left = max(0, len(roll) - 1000)
                    self.ax[0, 0].set_xlim(left, left + 1000)
            except Exception:
                pass

        # --- CoP (read each queue independently; forward-fill last known) ---
        if self.cop is not None:
            try:
                self.state_copx = float(self._drain_queue(self.cop.copx_q, default=self.state_copx))
            except Exception:
                pass
            try:
                self.state_copy = float(self._drain_queue(self.cop.copy_q, default=self.state_copy))
            except Exception:
                pass
            # Update point with last-known values
            self.cop_point.set_data([self.state_copx], [self.state_copy])

        # --- Body-Tracking landmarks + angle ---
        if self.pose is not None:
            # Landmarks
            try:
                pts_last = self._drain_queue(self.pose.landmarks_q, default=None)
                if pts_last is not None and getattr(pts_last, "size", 0) > 0:
                    self.state_landmarks = pts_last
                    self.bt_scat.set_offsets(self.state_landmarks)
            except Exception:
                pass
            # Angle
            try:
                ang_last = self._drain_queue(self.pose.angle_q, default=self.state_angle)
                if ang_last is not None:
                    self.state_angle = float(ang_last)
                    # Append to plotting series (keep last 900)
                    self.ang_xs.append((self.ang_xs[-1] + 1) if self.ang_xs else 0)
                    self.ang_ys.append(self.state_angle)
                    if len(self.ang_xs) > 900:
                        self.ang_xs = self.ang_xs[-900:]
                        self.ang_ys = self.ang_ys[-900:]
                    self.ang_line.set_data(self.ang_xs, self.ang_ys)
                    self.ax[1, 1].set_xlim(
                        max(0, self.ang_xs[-1] - 900), max(900, self.ang_xs[-1] + 10)
                    )
            except Exception:
                pass

        # --- Append one CSV row (forward-fill last-known values) ---
        if self.t_start is not None:
            t_rel = now - self.t_start
            row = self._build_csv_row(
                t_rel,
                self.state_emg,
                self.state_copx,
                self.state_copy,
                self.state_angle,
                self.state_landmarks,
            )
            self.rows.append(row)

        # Draw once per cycle
        self.canvas.draw_idle()

    # ------------------ helpers ------------------
    @staticmethod
    def _drain_queue(q, default=None):
        """Return the last available item of a queue, or default if empty."""
        last = default
        got_any = False
        while True:
            try:
                last = q.get_nowait()
                got_any = True
            except Exception:
                break
        return last if got_any else default

    def _build_csv_header(self):
        """Build a consistent CSV header with all landmark columns."""
        header = ["time_s", "emg_V", "cop_x_cm", "cop_y_cm", "angle_deg"]
        for i in range(LM_COUNT):
            header.append(f"lm{i}_x")
            header.append(f"lm{i}_y")
        return header

    def _build_csv_row(self, t_s, emg, copx, copy, angle, landmarks):
        """Build one CSV row; landmarks padded to LM_COUNT with NaNs."""
        row = [float(t_s), self._to_float(emg), self._to_float(copx), self._to_float(copy), self._to_float(angle)]
        # Landmarks padding
        lm = np.full((LM_COUNT, 2), np.nan, dtype=float)
        if landmarks is not None and getattr(landmarks, "ndim", 0) == 2 and landmarks.shape[1] >= 2:
            n = min(LM_COUNT, landmarks.shape[0])
            lm[:n, :2] = landmarks[:n, :2]
        # Flatten
        row.extend(lm.reshape(-1).tolist())
        return row

    @staticmethod
    def _to_float(x):
        """Safe float conversion preserving NaN when value is missing."""
        try:
            return float(x)
        except Exception:
            return float("nan")

    # ------------------ stop helpers ------------------
    def _stop_all(self):
        """Stop workers and reset state."""
        if not self.running:
            return
        self.running = False
        try:
            if self.emg: self.emg.stop()
        except Exception:
            pass
        try:
            if self.cop: self.cop.stop()
        except Exception:
            pass
        try:
            if self.pose: self.pose.stop()
        except Exception:
            pass
        self.emg = self.cop = self.pose = None

# ------------------ main ------------------
def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
