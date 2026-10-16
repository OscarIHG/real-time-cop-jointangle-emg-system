# -*- coding: utf-8 -*-
"""
PyQtGraph GUI (default, fastest renderer) on top of AcquisitionSession.

Same 2x2 layout as the paper's Fig. 3: Abdominal EMG | Center of Pressure /
Body-Tracking | Joint Angle. Hardware connects when the window opens (live
preview); Start/Stop bound the recording; Tare re-zeroes the plate; Save writes
the dataset in a background thread so the event loop never blocks.
"""

if __package__ is None or __package__ == "":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import os
import sys
import threading
import time
import traceback

import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

from acquisition_systems.session import AcquisitionSession

try:
    from mediapipe.python.solutions.pose import POSE_CONNECTIONS
except Exception:
    POSE_CONNECTIONS = ()


class _Bridge(QtCore.QObject):
    """Delivers results from background threads to the GUI thread."""
    done = QtCore.pyqtSignal(str, object)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, session: AcquisitionSession, args=None):
        super().__init__()
        self.session = session
        self.cfg = session.cfg
        self.args = args
        self.setWindowTitle("Real-Time CoP-JointAngle-EMG System")
        self.resize(1100, 750)
        self._bridge = _Bridge()
        self._bridge.done.connect(self._on_background_done)
        self._busy = set()
        self._connected = False
        self._closing = False
        self._tick_ms = []
        self._frames = 0
        self._fps_t = time.perf_counter()
        self.gui_fps = 0.0
        self._conn_x = np.array([i for pair in POSE_CONNECTIONS for i in pair], dtype=int)
        self._setup_ui()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._tick)
        self._run_background("connect", self.session.connect)

    # ---------- UI ----------
    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(QtWidgets.QLabel("Enter recording length in seconds (s):"))
        self.e_len = QtWidgets.QLineEdit(str(int(getattr(self.args, "duration", 20) or 20)))
        self.e_len.setFixedWidth(60)
        bar.addWidget(self.e_len)
        self.b_start = QtWidgets.QPushButton("Start")
        self.b_start.clicked.connect(self.toggle_start)
        bar.addWidget(self.b_start)
        bar.addSpacing(20)
        bar.addWidget(QtWidgets.QLabel("Filename:"))
        self.e_name = QtWidgets.QLineEdit("")
        self.e_name.setFixedWidth(200)
        bar.addWidget(self.e_name)
        self.b_save = QtWidgets.QPushButton("Save")
        self.b_save.clicked.connect(self.save)
        bar.addWidget(self.b_save)
        self.b_tare = QtWidgets.QPushButton("Tare")
        self.b_tare.clicked.connect(self.tare)
        bar.addWidget(self.b_tare)
        bar.addStretch()
        layout.addLayout(bar)
        for b in (self.b_start, self.b_save, self.b_tare):
            b.setEnabled(False)

        self.status = QtWidgets.QLabel("Connecting hardware...")
        layout.addWidget(self.status)

        pg.setConfigOptions(antialias=False)
        self.glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw)
        cfg = self.cfg

        self.p_emg = self.glw.addPlot(title="Abdominal EMG")
        self.p_emg.setLabel("left", "EMG [V]"); self.p_emg.setLabel("bottom", "Time [s]")
        self.p_emg.setYRange(cfg.emg_vmin, cfg.emg_vmax, padding=0)
        self.p_emg.setXRange(-cfg.emg_plot_window, 0, padding=0)
        self.p_emg.showGrid(x=True, y=True, alpha=0.3)
        self.emg_curve = self.p_emg.plot(pen=pg.mkPen("y", width=1))

        self.p_cop = self.glw.addPlot(title="Center of Pressure [cm]")
        self.p_cop.setXRange(-cfg.cop_x_half_range_cm, cfg.cop_x_half_range_cm, padding=0)
        self.p_cop.setYRange(-cfg.cop_y_half_range_cm, cfg.cop_y_half_range_cm, padding=0)
        self.p_cop.setAspectLocked(True)
        self.p_cop.addLine(x=0, pen=pg.mkPen((150, 150, 150), width=1))
        self.p_cop.addLine(y=0, pen=pg.mkPen((150, 150, 150), width=1))
        self.cop_scatter = pg.ScatterPlotItem(size=12, pen=pg.mkPen(None), brush=pg.mkBrush(31, 119, 180, 255))
        self.p_cop.addItem(self.cop_scatter)

        self.glw.nextRow()
        self.p_pose = self.glw.addPlot(title="Body-Tracking [px]")
        self.p_pose.setXRange(0, cfg.cam_width, padding=0)
        self.p_pose.setYRange(0, cfg.cam_height, padding=0)
        self.p_pose.invertY(True)   # image coordinates: y grows downwards
        self.p_pose.setAspectLocked(True)
        self.p_pose.showGrid(x=True, y=True, alpha=0.3)
        self.pose_lines = self.p_pose.plot(pen=pg.mkPen("b", width=2), connect="pairs")
        self.pose_scatter = pg.ScatterPlotItem(size=7, pen=pg.mkPen(None), brush=pg.mkBrush(220, 30, 30, 255))
        self.p_pose.addItem(self.pose_scatter)

        self.p_ang = self.glw.addPlot(title="Joint Angle (pelvic obliquity 23-24) [deg]")
        self.p_ang.setLabel("bottom", "Time [s]")
        lim = cfg.angle_plot_limit_deg
        self.p_ang.setYRange(-lim, lim, padding=0)
        self.p_ang.setXRange(0, cfg.angle_plot_window, padding=0)
        self.p_ang.showGrid(x=True, y=True, alpha=0.3)
        self.ang_curve = self.p_ang.plot(pen=pg.mkPen("b", width=2), connect="finite")

    # ---------- background work ----------
    def _run_background(self, name, fn, *a):
        self._busy.add(name)

        def work():
            try:
                result = fn(*a)
            except Exception as exc:
                traceback.print_exc()
                result = exc
            self._bridge.done.emit(name, result)

        threading.Thread(target=work, name=f"gui-{name}", daemon=True).start()

    @QtCore.pyqtSlot(str, object)
    def _on_background_done(self, name, result):
        self._busy.discard(name)
        if name == "connect":
            self._connected = True
            for b in (self.b_start, self.b_save, self.b_tare):
                b.setEnabled(True)
            self.b_tare.setEnabled(self.session.cop is not None)
            errs = {k: v for k, v in (result or {}).items() if v} if isinstance(result, dict) else {}
            if errs:
                print(f"[GUI] Offline modules: {errs}")
            self.timer.start(self.cfg.gui_update_ms)
            if getattr(self.args, "autostart", False):
                QtCore.QTimer.singleShot(1500, self.toggle_start)
        elif name == "save":
            self.b_save.setEnabled(True)
            if isinstance(result, Exception):
                QtWidgets.QMessageBox.warning(self, "Save failed", str(result))
            else:
                print(f"[OK] Saved: {result.get('merged')}")
                if getattr(self.args, "exit_after", False):
                    self.close()
        elif name == "tare":
            self.b_tare.setEnabled(True)
            print(f"[GUI] Tare: {result}")
        elif name == "close":
            self._closing = True
            self.close()

    # ---------- controls ----------
    def toggle_start(self):
        if self.session.state == "idle":
            try:
                dur = max(1.0, float(self.e_len.text() or "20"))
            except ValueError:
                dur = 20.0
            self.session.start_recording(dur)
            self.p_ang.setXRange(0, dur, padding=0)
            self.b_start.setText("Stop")
            self.b_save.setEnabled(False)
        else:
            self.session.stop_recording()

    def save(self):
        snapshot = self.session.snapshot()   # copy on the GUI thread
        self.b_save.setEnabled(False)
        self._run_background("save", self.session.export, snapshot, self.e_name.text())

    def tare(self):
        self.b_tare.setEnabled(False)
        self._run_background("tare", self.session.tare)

    # ---------- refresh ----------
    def _tick(self):
        t_start = time.perf_counter()
        try:
            live = self.session.poll()
            if live.new_emg:
                self.emg_curve.setData(live.emg_t, live.emg_v)
            if live.new_cop:
                if live.cop_xy is None:
                    self.cop_scatter.setData([], [])
                else:
                    self.cop_scatter.setData([live.cop_xy[0]], [live.cop_xy[1]])
            if live.pose is not None:
                lm = live.pose.landmarks
                if live.pose.detected:
                    self.pose_scatter.setData(lm[:, 0], lm[:, 1])
                    if self._conn_x.size:
                        pts = lm[self._conn_x]
                        self.pose_lines.setData(pts[:, 0], pts[:, 1])
                else:
                    self.pose_scatter.setData([], [])
                    self.pose_lines.setData([], [])
                if live.angle_t.size:
                    self.ang_curve.setData(live.angle_t, live.angle_v)
                    if live.state == "idle" and live.angle_t[-1] > self.cfg.angle_plot_window:
                        right = float(live.angle_t[-1])
                        self.p_ang.setXRange(right - self.cfg.angle_plot_window, right, padding=0)
            if live.recording_done:
                self.b_start.setText("Start")
                self.b_save.setEnabled(True)
                if getattr(self.args, "autosave", False):
                    self.save()
            state = f"REC {live.elapsed_s:5.1f}/{live.duration_s:.0f} s | " if live.state != "idle" else ""
            self.status.setText(f"{state}{self.session.status_text()} | GUI {self.gui_fps:.0f} FPS")
        except Exception:
            print("[GUI] Tick error:")
            traceback.print_exc()
        self._tick_ms.append((time.perf_counter() - t_start) * 1000)
        self._frames += 1
        now = time.perf_counter()
        if now - self._fps_t >= 1.0:
            self.gui_fps = self._frames / (now - self._fps_t)
            self._frames, self._fps_t = 0, now

    def closeEvent(self, event):
        if self._closing:
            self.timer.stop()
            _print_gui_stats("qt", self._tick_ms)
            event.accept()
            return
        event.ignore()
        self.timer.stop()
        self.status.setText("Stopping hardware...")
        self._run_background("close", self.session.close)


def _print_gui_stats(name, tick_ms):
    if tick_ms:
        a = np.asarray(tick_ms[5:] or tick_ms)
        print(f"[GUI-{name}] ticks={a.size} tick_ms p50={np.percentile(a, 50):.2f} p95={np.percentile(a, 95):.2f}")


def run(args=None, session: AcquisitionSession = None):
    # Fix for OpenCV hijacking the Qt plugin path on Linux (causes Wayland/XCB crashes)
    os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(25, 25, 25))
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    app.setPalette(palette)
    window = MainWindow(session or AcquisitionSession(emg_source=getattr(args, "emg_source", None)), args)
    window.show()
    return app.exec_()


def main():
    from acquisition_systems.app_gui import main as launcher
    return launcher(["--gui", "qt"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
