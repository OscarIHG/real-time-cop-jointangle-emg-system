import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from acquisition_systems.common.types import CopSample, EmgSample, PoseSample
from acquisition_systems.recorder import Recorder


def read_csv(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def pose(t, detected=True, angle=1.5):
    lm = np.full((33, 2), np.nan if not detected else 100.0, dtype=np.float32)
    return PoseSample(t=t, landmarks=lm, angle_deg=angle if detected else math.nan, detected=detected)


class RecorderTests(unittest.TestCase):
    def build(self):
        rec = Recorder(emg_fs=100.0)
        t0 = 1000.0
        rec.set_window(t0, t0 + 2.0)
        for k in range(-5, 205):                       # 100 Hz EMG (some outside the window)
            rec.push_emg(EmgSample(t0 + k * 0.01, 0.3))
        for k in range(250):                           # 125 Hz CoP
            rec.push_cop(CopSample(t0 + k * 0.008, 1.0, 2.0, 70.0, (17.5,) * 4))
        rec.push_pose(pose(t0 + 0.2))
        rec.push_pose(pose(t0 + 0.6, detected=False))
        return rec, t0

    def test_window_and_native_streams_are_lossless(self):
        rec, _ = self.build()
        self.assertEqual(rec.counts()["emg"], 201)
        self.assertEqual(rec.counts()["cop"], 250)
        with tempfile.TemporaryDirectory() as tmp:
            paths = rec.export(tmp, "s")
            self.assertEqual(len(read_csv(paths["cop"])), 250)
            self.assertEqual(len(read_csv(paths["emg"])), 201)
            meta = json.loads(Path(paths["meta"]).read_text())
            self.assertEqual(meta["samples"]["cop"], 250)

    def test_merged_uses_emg_timeline_without_duplicates(self):
        rec, _ = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            rows = read_csv(rec.export(tmp, "s")["merged"])
        times = [float(r["time_s"]) for r in rows]
        self.assertEqual(len(rows), 201)
        self.assertEqual(len(set(times)), len(times))
        self.assertAlmostEqual(times[0], 0.0)           # common origin t0
        self.assertEqual(float(rows[50]["cop_x_cm"]), 1.0)

    def test_pose_loss_becomes_nan_not_stale(self):
        rec, _ = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            rows = read_csv(rec.export(tmp, "s")["merged"])
        self.assertTrue(math.isnan(float(rows[10]["angle_deg"])))   # before first frame
        self.assertEqual(float(rows[40]["angle_deg"]), 1.5)
        self.assertAlmostEqual(float(rows[40]["pose_t_s"]), 0.2, places=5)
        self.assertTrue(math.isnan(float(rows[80]["angle_deg"])))   # subject lost at 0.6 s

    def test_notch_column_filters_at_100hz(self):
        rec = Recorder(emg_fs=100.0)
        t = np.arange(0, 10, 0.01)
        for ti, v in zip(t, 0.3 + 0.1 * np.sin(2 * np.pi * 60 * t)):
            rec.push_emg(EmgSample(ti, float(v)))
        with tempfile.TemporaryDirectory() as tmp:
            rows = read_csv(rec.export(tmp, "s")["emg"])
        notch = np.array([float(r["emg_notch_V"]) for r in rows])
        self.assertLess(np.std(notch), 0.01)            # interference (aliased to 40 Hz) removed


if __name__ == "__main__":
    unittest.main()
