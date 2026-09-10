# -*- coding: utf-8 -*-
"""
PyQtGraph GUI orchestrating EMG, CoP, Pose workers.
Replaces the CPU-bound Matplotlib rendering with high-speed GPU/OpenGL rendering.
"""

if __package__ is None or __package__ == "":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import os
import sys
import time
from collections import deque
from datetime import datetime
import traceback
import queue
from typing import Optional

import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

from acquisition_systems.common.config import load_config, config_to_dict
from acquisition_systems.recorder import Recorder
from acquisition_systems.workers.emg import EMGWorker
from acquisition_systems.workers.cop import CoPWorker
from acquisition_systems.workers.pose import PoseWorker
from acquisition_systems.common.dsp import apply_fft_notch

try:
    from mediapipe.python.solutions.pose import POSE_CONNECTIONS
except Exception:
    POSE_CONNECTIONS = ()

def get_sessions_dir() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    return os.path.join(root, "sessions")

def dated_subdir(base: str) -> str:
    day = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(base, day)
    os.makedirs(path, exist_ok=True)
    return path


class HardwareStartup(QtCore.QObject):
    """Initialize hardware away from Qt's GUI thread."""

    ready = QtCore.pyqtSignal(object, object, object, object)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    @QtCore.pyqtSlot()
    def run(self):
        workers = [None, None, None]
        errors = []
        try:
            workers[0] = EMGWorker(
                self.cfg.emg_mac,
                self.cfg.emg_com_port,
                self.cfg.emg_rfcomm_channel,
                self.cfg.emg_vmin,
                self.cfg.emg_vmax,
                start_token=self.cfg.emg_start_token,
                stop_token=self.cfg.emg_stop_token,
            )
            workers[0].ALLOW_LF = self.cfg.emg_allow_lf
            workers[0].start()
        except Exception as exc:
            errors.append(f"EMG: {exc}")
            workers[0] = None

        try:
            workers[1] = CoPWorker(
                self.cfg.cop_gain,
                self.cfg.cop_x_dist_cm,
                self.cfg.cop_y_dist_cm,
                self.cfg.cop_interval_ms,
                flip_x=self.cfg.cop_flip_x,
                flip_y=self.cfg.cop_flip_y,
                swap_xy=self.cfg.cop_swap_xy,
            )
            workers[1].start()
        except Exception as exc:
            errors.append(f"CoP: {exc}")
            workers[1] = None

        try:
            workers[2] = PoseWorker(
                self.cfg.cam_index,
                self.cfg.cam_width,
                self.cfg.cam_height,
                self.cfg.cam_fps,
                config=config_to_dict(self.cfg),
            )
            workers[2].start()
        except Exception as exc:
            errors.append(f"Pose: {exc}")
            workers[2] = None

        self.ready.emit(workers[0], workers[1], workers[2], errors)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.setWindowTitle("Real-Time CoP-JointAngle-EMG System")
        self.resize(1100, 750)

        # Plot limits
        self.emg_plot_window = int(max(1, self.cfg.emg_plot_window))
        self.angle_plot_window = int(max(1, self.cfg.angle_plot_window))
        self.cop_x_half = float(self.cfg.cop_x_half_range_cm)
        self.cop_y_half = float(self.cfg.cop_y_half_range_cm)

        self._setup_ui()

        # Keep plotting bounded independently from the recording buffers.
        # Filtering an unbounded 1 kHz history on every Qt tick would starve
        # the GUI on a Raspberry Pi.
        emg_capacity = max(min(int(self.emg_plot_window * 1000), 30000), 2000)
        angle_capacity = max(min(int(self.angle_plot_window * 30), 10000), 2000)
        self._emg_buf = deque(maxlen=emg_capacity)
        self._emg_times = deque(maxlen=emg_capacity)
        self._emg_plot_origin = None
        self._ang_buf = deque(maxlen=angle_capacity)
        self._ang_times = deque(maxlen=angle_capacity)
        self._ang_plot_origin = None

        self.rec = Recorder(self.cfg.recording_max_samples_per_stream)

        self.emg_worker = None
        self.cop_worker = None
        self.pose_worker = None

        self.running = False
        self.t_start = None
        self.t_stop = 0.0
        self._pending_duration = 0.0
        self._starting = False
        self._startup_thread = None
        self._startup_worker = None

        # Timer for polling queues. PyQtGraph handles 30 FPS easily.
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._tick)

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        # Control Bar
        control_layout = QtWidgets.QHBoxLayout()
        control_layout.addWidget(QtWidgets.QLabel("Duration (s):"))
        self.e_len = QtWidgets.QLineEdit("20")
        self.e_len.setFixedWidth(60)
        control_layout.addWidget(self.e_len)

        control_layout.addSpacing(20)
        control_layout.addWidget(QtWidgets.QLabel("Filename:"))
        self.e_name = QtWidgets.QLineEdit("")
        self.e_name.setFixedWidth(200)
        control_layout.addWidget(self.e_name)

        self.b_start = QtWidgets.QPushButton("Start")
        self.b_start.setMinimumWidth(80)
        self.b_start.clicked.connect(self.toggle_start)
        control_layout.addWidget(self.b_start)

        self.b_save = QtWidgets.QPushButton("Save CSV")
        self.b_save.setMinimumWidth(80)
        self.b_save.clicked.connect(self.save_csv)
        control_layout.addWidget(self.b_save)

        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Graphics Layout
        pg.setConfigOptions(antialias=True)
        self.glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw)

        # --- EMG ---
        self.p_emg = self.glw.addPlot(title="Abdominal EMG")
        self.p_emg.setLabel('left', "EMG [V]")
        self.p_emg.setYRange(self.cfg.emg_vmin, self.cfg.emg_vmax)
        self.p_emg.showGrid(x=True, y=True, alpha=0.3)
        self.emg_curve = self.p_emg.plot(pen='y', width=1.5)

        # --- CoP ---
        self.p_cop = self.glw.addPlot(title="Center of Pressure [cm]")
        self.p_cop.setLabel('bottom', "X [cm]")
        self.p_cop.setLabel('left', "Y [cm]")
        self.p_cop.setXRange(-self.cop_x_half, self.cop_x_half)
        self.p_cop.setYRange(-self.cop_y_half, self.cop_y_half)
        self.p_cop.setAspectLocked(True)
        self.p_cop.showGrid(x=True, y=True, alpha=0.3)
        self.cop_scatter = pg.ScatterPlotItem(size=12, pen=pg.mkPen(None), brush=pg.mkBrush(255, 50, 50, 255))
        self.p_cop.addItem(self.cop_scatter)

        self.glw.nextRow()

        # --- Pose ---
        self.p_pose = self.glw.addPlot(title="Body-Tracking Landmarks [px]")
        self.p_pose.setXRange(0, self.cfg.cam_width)
        self.p_pose.setYRange(self.cfg.cam_height, 0) # Invert Y for image coordinates
        self.p_pose.setAspectLocked(True)
        self.p_pose.showGrid(x=True, y=True, alpha=0.3)
        self.pose_scatter = pg.ScatterPlotItem(size=8, pen=pg.mkPen(None), brush=pg.mkBrush(0, 255, 255, 255))
        self.p_pose.addItem(self.pose_scatter)
        self.pose_lines = []
        for _ in POSE_CONNECTIONS:
            line = pg.PlotDataItem(pen=pg.mkPen('c', width=1))
            self.p_pose.addItem(line)
            self.pose_lines.append(line)

        # --- Angle ---
        self.p_ang = self.glw.addPlot(title="Joint Angle (Pelvic Obliquity 23-24) [deg]")
        self.p_ang.setLabel('left', "Angle [deg]")
        self.p_ang.setYRange(-90, 90)
        self.p_ang.showGrid(x=True, y=True, alpha=0.3)
        self.ang_curve = self.p_ang.plot(pen='g', width=2)

    def _auto_suffix(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        elapsed = 0 if not self.t_start else int(max(0, time.time() - self.t_start))
        return f"{stamp}_{elapsed}s"

    def toggle_start(self):
        if self._starting:
            return
        if not self.running:
            try:
                dur = float(self.e_len.text() or "20")
            except Exception:
                dur = 20.0
            dur = max(1.0, dur)

            self._pending_duration = dur
            self._starting = True
            self.b_start.setEnabled(False)
            self.b_start.setText("Starting...")
            self.rec.clear()
            self._emg_buf.clear()
            self._emg_times.clear()
            self._emg_plot_origin = None
            self._ang_buf.clear()
            self._ang_times.clear()
            self._ang_plot_origin = None
            
            # Clear plots
            self.emg_curve.setData([])
            self.cop_scatter.setData([], [])
            self.pose_scatter.setData([], [])
            for line in self.pose_lines: line.setData([], [])
            self.ang_curve.setData([])

            self._startup_thread = QtCore.QThread(self)
            self._startup_worker = HardwareStartup(self.cfg)
            self._startup_worker.moveToThread(self._startup_thread)
            self._startup_thread.started.connect(self._startup_worker.run)
            self._startup_worker.ready.connect(self._on_hardware_ready)
            self._startup_worker.ready.connect(self._startup_thread.quit)
            self._startup_thread.finished.connect(self._startup_worker.deleteLater)
            self._startup_thread.finished.connect(self._on_startup_finished)
            self._startup_thread.start()
        else:
            self._stop_all()
            self.b_start.setText("Start")

    @QtCore.pyqtSlot(object, object, object, object)
    def _on_hardware_ready(self, emg_worker, cop_worker, pose_worker, errors):
        self.emg_worker = emg_worker
        self.cop_worker = cop_worker
        self.pose_worker = pose_worker
        for error in errors:
            print(f"[WARNING] {error}")

        if not any((self.emg_worker, self.cop_worker, self.pose_worker)):
            self._starting = False
            self.b_start.setEnabled(True)
            self.b_start.setText("Start")
            QtWidgets.QMessageBox.critical(
                self, "Hardware Error",
                "No hardware could be started. Check the console output.",
            )
            return

        self.t_start = time.time()
        self.t_stop = self.t_start + self._pending_duration
        self.running = True
        self._starting = False
        self.b_start.setEnabled(True)
        self.b_start.setText("Stop")
        self.timer.start(33)

    def _on_startup_finished(self):
        self._startup_thread.deleteLater()
        self._startup_thread = None
        self._startup_worker = None

    def save_csv(self):
        base = (self.e_name.text() or "").strip()
        if not base:
            base = f"session_{self._auto_suffix()}"
            
        out_dir = dated_subdir(get_sessions_dir())
        path = self.rec.to_csv_merged(out_dir, base, reference="auto")
        print(f"[OK] Saved merged CSV: {path}")

    def _tick(self):
        if not self.running:
            return
            
        if time.time() >= self.t_stop:
            self.toggle_start()  # Stop
            return

        try:
            # Drain EMG queue. Every sample is recorded; only the newest is
            # needed for display.
            emg_samples = []
            if self.emg_worker:
                while True:
                    try:
                        emg_samples.append(self.emg_worker.queue.get_nowait())
                    except queue.Empty:
                        break
                for emg in emg_samples:
                    self.rec.push_emg(emg)
            
            # Drain CoP queue
            cop_latest = None
            if self.cop_worker:
                while True:
                    try:
                        cop = self.cop_worker.queue.get_nowait()
                        if cop: self.rec.push_cop(cop)
                        cop_latest = cop
                    except queue.Empty:
                        break

            # Drain Pose queue
            pose_latest = None
            if self.pose_worker:
                while True:
                    try:
                        pose = self.pose_worker.landmarks_q.get_nowait()
                        if pose: self.rec.push_pose(pose)
                        pose_latest = pose
                    except queue.Empty:
                        break

            # Drain Angle queue
            ang_latest = None
            if self.pose_worker:
                while True:
                    try:
                        ang = self.pose_worker.angle_q.get_nowait()
                        if ang: self.rec.push_angle(ang)
                        ang_latest = ang
                    except queue.Empty:
                        break

            # --- High-Performance PyQtGraph Updates ---
            if emg_samples:
                for sample in emg_samples:
                    self._emg_buf.append(sample.value)
                    if self._emg_plot_origin is None:
                        self._emg_plot_origin = sample.t
                    self._emg_times.append(sample.t - self._emg_plot_origin)
                # Apply the zero-phase notch only to a recent display window;
                # the complete filtered stream is persisted by Recorder.
                display_count = min(len(self._emg_buf), 5000)
                plot_data = np.array(list(self._emg_buf)[-display_count:])
                plot_times = np.array(list(self._emg_times)[-display_count:])
                if len(plot_data) > 100:
                    deltas = np.diff(plot_times)
                    valid = deltas[deltas > 0]
                    fs = 1.0 / float(np.median(valid)) if valid.size else 1000.0
                    plot_data = apply_fft_notch(plot_data, fs=fs, target_freq=60.0)

                self.emg_curve.setData(plot_times, plot_data)
                right = float(plot_times[-1])
                display_window = min(float(self.emg_plot_window), 5.0)
                self.p_emg.setXRange(max(0.0, right - display_window), right, padding=0)

            if cop_latest:
                try:
                    self.cop_scatter.setData([float(cop_latest.x)], [float(cop_latest.y)])
                except Exception:
                    pass

            if pose_latest and getattr(pose_latest, "landmarks", None) is not None:
                lm = np.asarray(pose_latest.landmarks)
                if lm.ndim == 1:
                    if lm.size % 2 == 0:
                        lm = lm.reshape(-1, 2)
                    else:
                        lm = lm[: (lm.size // 2) * 2].reshape(-1, 2)
                elif lm.ndim == 2 and lm.shape[1] != 2:
                    lm = lm[:, :2]
                    
                if lm.size > 0:
                    self.pose_scatter.setData(lm[:, 0], lm[:, 1])
                    for line, (i, j) in zip(self.pose_lines, POSE_CONNECTIONS):
                        if i < lm.shape[0] and j < lm.shape[0]:
                            line.setData([lm[i, 0], lm[j, 0]], [lm[i, 1], lm[j, 1]])
                        else:
                            line.setData([], [])

            if ang_latest:
                self._ang_buf.append(ang_latest.deg)
                if self._ang_plot_origin is None:
                    self._ang_plot_origin = ang_latest.t
                self._ang_times.append(ang_latest.t - self._ang_plot_origin)
                self.ang_curve.setData(self._ang_times, self._ang_buf)
                right = float(self._ang_times[-1])
                self.p_ang.setXRange(max(0.0, right - self.angle_plot_window), right, padding=0)
            
        except Exception:
            print("[GUI] Tick error:")
            traceback.print_exc()

    def _stop_all(self):
        self.timer.stop()
        print("[GUI] Stopping all workers...")
        for w in (self.emg_worker, self.cop_worker, self.pose_worker):
            try:
                if w: w.stop()
            except Exception:
                pass
        self.emg_worker = self.cop_worker = self.pose_worker = None
        self.running = False
        self._starting = False
        self.b_start.setEnabled(True)
        print("[GUI] All workers stopped.")

    def closeEvent(self, event):
        if self._startup_thread is not None:
            self._startup_thread.quit()
            self._startup_thread.wait(1000)
        self._stop_all()
        event.accept()


def main():
    # Fix for OpenCV hijacking the Qt plugin path on Linux (causes Wayland/XCB crashes)
    if "QT_QPA_PLATFORM_PLUGIN_PATH" in os.environ:
        os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH")

    app = QtWidgets.QApplication(sys.argv)
    
    # Optional: Apply a dark theme or style
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(25, 25, 25))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ToolTipBase, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
    palette.setColor(QtGui.QPalette.Link, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()