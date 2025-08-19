# Example: use fake workers
# -*- coding: utf-8 -*-
"""
Demo: simulated EMG/CoP/Pose/Angle without hardware.
Generates synthetic signals compatible with Recorder/to_csv_merged.
"""

import os
import sys
import time
import math
import queue
import threading
import argparse
from datetime import datetime
import numpy as np

# Allow running directly
if __package__ is None or __package__ == "":
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from acquisition_systems.common.utils import put_latest
from acquisition_systems.common.types import EmgSample, CopSample, PoseSample, AngleSample
from acquisition_systems.recorder import Recorder

# ---------- fake workers ----------
class FakeEMG:
    def __init__(self, fs=500, amp=0.8, noise=0.05):
        self.fs = fs
        self.amp = amp
        self.noise = noise
        self.queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._th = None
        self._t = 0

    def start(self):
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()

    def _loop(self):
        dt = 1.0 / self.fs
        while not self._stop.is_set():
            # 20 Hz burst-like signal + noise
            v = self.amp * max(0.0, math.sin(2*math.pi*20*self._t)) + np.random.normal(0, self.noise)
            put_latest(self.queue, EmgSample(t=time.perf_counter(), value=float(max(0.0, v))))
            self._t += dt
            time.sleep(dt)

    def stop(self):
        self._stop.set()
        if self._th:
            self._th.join(timeout=1.0)

class FakeCoP:
    def __init__(self, hz=100, x_half=27.92, y_half=20.32):
        self.hz = hz
        self.xh = x_half
        self.yh = y_half
        self.queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._th = None
        self._t = 0

    def start(self):
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()

    def _loop(self):
        dt = 1.0 / self.hz
        while not self._stop.is_set():
            # small Lissajous inside plate
            x = 0.7*self.xh * math.sin(0.4*self._t) * math.cos(0.1*self._t)
            y = 0.7*self.yh * math.cos(0.3*self._t) * math.sin(0.07*self._t)
            put_latest(self.queue, CopSample(t=time.perf_counter(), x=float(x), y=float(y)))
            self._t += dt
            time.sleep(dt)

    def stop(self):
        self._stop.set()
        if self._th:
            self._th.join(timeout=1.0)

class FakePose:
    def __init__(self, hz=30, w=640, h=480):
        self.hz = hz
        self.w = w
        self.h = h
        self.landmarks_q = queue.Queue(maxsize=1)
        self.angle_q = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._th = None
        self._t = 0

    def start(self):
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()

    def _loop(self):
        dt = 1.0 / self.hz
        n = 33
        while not self._stop.is_set():
            # jittered landmarks in px
            lm = np.zeros((n, 2), dtype=np.float32)
            # simple skeleton-ish scatter
            cx = self.w * 0.5 + 50*np.sin(0.5*self._t)
            cy = self.h * 0.5 + 40*np.cos(0.3*self._t)
            for i in range(n):
                lm[i, 0] = cx + np.random.uniform(-20, 20)
                lm[i, 1] = cy + np.random.uniform(-20, 20)
            t = time.perf_counter()
            put_latest(self.landmarks_q, PoseSample(t=t, landmarks=lm))
            # angle: a slow sinusoid in degrees
            ang = 20.0 * math.sin(0.8*self._t)
            put_latest(self.angle_q, AngleSample(t=t, deg=float(ang)))
            self._t += dt
            time.sleep(dt)

    def stop(self):
        self._stop.set()
        if self._th:
            self._th.join(timeout=1.0)

# ---------- paths ----------
def get_sessions_dir():
    base = os.environ.get("AS_OUTDIR")
    if base:
        return base
    root = os.path.abspath(os.path.dirname(__file__) + "/..")
    return os.path.join(root, "sessions")

def dated_subdir(base: str) -> str:
    day = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(base, day)
    os.makedirs(path, exist_ok=True)
    return path

def auto_suffix() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Simulated demo (no hardware).")
    ap.add_argument("--duration", type=float, default=10.0, help="Seconds to generate")
    ap.add_argument("--name", type=str, default="demo_sim", help="Base name for CSV")
    ap.add_argument("--save", action="store_true", help="Save merged CSV at the end")
    args = ap.parse_args()

    w_emg = FakeEMG(fs=500)
    w_cop = FakeCoP(hz=100)
    w_pose = FakePose(hz=30, w=640, h=480)

    for w in (w_emg, w_cop, w_pose):
        w.start()

    rec = Recorder()
    t_end = time.time() + max(1.0, args.duration)
    try:
        while time.time() < t_end:
            rec.push_emg(  w_emg.queue.get_nowait()  if not w_emg.queue.empty() else None)
            rec.push_cop(  w_cop.queue.get_nowait()  if not w_cop.queue.empty() else None)
            rec.push_pose( w_pose.landmarks_q.get_nowait() if not w_pose.landmarks_q.empty() else None)
            rec.push_angle(w_pose.angle_q.get_nowait()     if not w_pose.angle_q.empty() else None)
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        for w in (w_emg, w_cop, w_pose):
            w.stop()

    if args.save:
        out_dir = dated_subdir(get_sessions_dir())
        base = f"{args.name}-{auto_suffix()}"
        path = rec.to_csv_merged(out_dir, base, reference="auto")
        print(f"[OK] Saved merged CSV: {path}")
    else:
        print("[OK] Demo finished (not saved).")

if __name__ == "__main__":
    main()
