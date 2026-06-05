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
from datetime import datetime
import traceback
import queue
from typing import Optional

import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

try:
    import scipy.signal as signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from acquisition_systems.common.config import load_config
from acquisition_systems.recorder import Recorder
from acquisition_systems.workers.emg import EMGWorker
from acquisition_systems.workers.cop import CoPWorker
from acquisition_systems.workers.pose import PoseWorker

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

        self._emg_buf = []
        self._emg_filtered_buf = []
        self._ang_buf = []

        self.rec = Recorder()

        self.emg_worker = None
        self.cop_worker = None
        self.pose_worker = None

        self.running = False
        self.t_start = None
        self.t_stop = 0.0

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

        self.cb_filter = QtWidgets.QCheckBox("Filtered EMG (Paper)")
        self.cb_filter.setChecked(True)
        if not HAS_SCIPY:
            self.cb_filter.setEnabled(False)
            self.cb_filter.setToolTip("SciPy not installed. Filtering disabled.")
        control_layout.addWidget(self.cb_filter)

        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Graphics Layout
        pg.setConfigOptions(antialias=True)
        self.glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw)

        # --- EMG ---
        self.p_emg = self.glw.addPlot(title="Abdominal EMG")
        self.p_emg.setLabel('left', "EMG [V]")
        self.p_emg.setYRange(0, 5)
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
        if not self.running:
            try:
                dur = float(self.e_len.text() or "20")
            except Exception:
                dur = 20.0
            dur = max(1.0, dur)

            print("[GUI] Starting EMG Worker...")
            try:
                self.emg_worker = EMGWorker(
                    self.cfg.emg_mac,
                    getattr(self.cfg, 'emg_com_port', 'COM3'),
                    self.cfg.emg_rfcomm_channel,
                    self.cfg.emg_vmin,
                    self.cfg.emg_vmax,
                    start_token=self.cfg.emg_start_token,
                    stop_token=self.cfg.emg_stop_token,
                )
                self.emg_worker.ALLOW_LF = bool(getattr(self.cfg, 'emg_allow_lf', False))
                self.emg_worker.start()
            except Exception as e:
                print(f"[WARNING] Could not start EMG Worker (Bluetooth). It will be disabled. Error: {e}")
                self.emg_worker = None

            print("[GUI] Starting CoP Worker...")
            try:
                self.cop_worker = CoPWorker(
                    self.cfg.cop_gain, self.cfg.cop_x_dist_cm, self.cfg.cop_y_dist_cm, self.cfg.cop_interval_ms,
                    flip_x=self.cfg.cop_flip_x, flip_y=self.cfg.cop_flip_y, swap_xy=self.cfg.cop_swap_xy
                )
                self.cop_worker.start()
            except Exception as e:
                print(f"[WARNING] Could not start CoP Worker (Force Plate). It will be disabled. Error: {e}")
                self.cop_worker = None

            print("[GUI] Starting Pose Worker...")
            try:
                self.pose_worker = PoseWorker(
                    self.cfg.cam_index, self.cfg.cam_width, self.cfg.cam_height, getattr(self.cfg, 'cam_fps', 30)
                )
                self.pose_worker.start()
            except Exception as e:
                print(f"[WARNING] Could not start Pose Worker (Camera). It will be disabled. Error: {e}")
                self.pose_worker = None
                
            if not any([self.emg_worker, self.cop_worker, self.pose_worker]):
                QtWidgets.QMessageBox.critical(self, "Hardware Error", "No hardware could be started! Check logs.")
                self._stop_all()
                return

            self._emg_buf.clear()
            self._emg_filtered_buf.clear()
            self._ang_buf.clear()
            
            # Clear plots
            self.emg_curve.setData([])
            self.cop_scatter.setData([], [])
            self.pose_scatter.setData([], [])
            for line in self.pose_lines: line.setData([], [])
            self.ang_curve.setData([])

            self.t_start = time.time()
            self.t_stop = self.t_start + dur
            self.running = True
            self.b_start.setText("Stop")
            
            # Since PyQtGraph is highly optimized, we can run GUI ticks much faster (30 FPS)
            self.timer.start(33)
        else:
            self._stop_all()
            self.b_start.setText("Start")

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
            # Drain EMG queue
            new_emg_vals = []
            emg_latest = None
            if self.emg_worker:
                while not self.emg_worker.queue.empty():
                    try:
                        emg = self.emg_worker.queue.get_nowait()
                        if emg: 
                            self.rec.push_emg(emg)
                            new_emg_vals.append(emg)
                        emg_latest = emg
                    except queue.Empty:
                        break
            
            # Drain CoP queue
            cop_latest = None
            if self.cop_worker:
                while not self.cop_worker.queue.empty():
                    try:
                        cop = self.cop_worker.queue.get_nowait()
                        if cop: self.rec.push_cop(cop)
                        cop_latest = cop
                    except queue.Empty:
                        break

            # Drain Pose queue
            pose_latest = None
            if self.pose_worker:
                while not self.pose_worker.landmarks_q.empty():
                    try:
                        pose = self.pose_worker.landmarks_q.get_nowait()
                        if pose: self.rec.push_pose(pose)
                        pose_latest = pose
                    except queue.Empty:
                        break

            # Drain Angle queue
            ang_latest = None
            if self.pose_worker:
                while not self.pose_worker.angle_q.empty():
                    try:
                        ang = self.pose_worker.angle_q.get_nowait()
                        if ang: self.rec.push_angle(ang)
                        ang_latest = ang
                    except queue.Empty:
                        break

            # --- High-Performance PyQtGraph Updates ---
            if new_emg_vals:
                self._emg_buf.extend([s.value for s in new_emg_vals])
                self._emg_filtered_buf.extend([s.filtered for s in new_emg_vals])
                
                self._emg_buf = self._emg_buf[-max(self.emg_plot_window * 1000, 2000):]
                self._emg_filtered_buf = self._emg_filtered_buf[-max(self.emg_plot_window * 1000, 2000):]
                
                if HAS_SCIPY and self.cb_filter.isChecked():
                    self.emg_curve.setData(self._emg_filtered_buf)
                    plot_buf_len = len(self._emg_filtered_buf)
                else:
                    self.emg_curve.setData(self._emg_buf)
                    plot_buf_len = len(self._emg_buf)
                
                # Update X range based on the buffer being plotted
                left = max(0, plot_buf_len - self.emg_plot_window * 1000)
                self.p_emg.setXRange(left, left + self.emg_plot_window * 1000, padding=0)

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
                self._ang_buf = self._ang_buf[-max(self.angle_plot_window * 40, 2000):]
                self.ang_curve.setData(self._ang_buf)
                right = len(self._ang_buf)
                left  = max(0, right - self.angle_plot_window)
                self.p_ang.setXRange(left, left + self.angle_plot_window, padding=0)
            
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
        print("[GUI] All workers stopped.")

    def closeEvent(self, event):
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