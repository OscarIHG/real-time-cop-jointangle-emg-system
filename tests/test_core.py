import csv
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from acquisition_systems.common.config import ConfigError, _coerce_bool
from acquisition_systems.common.dsp import apply_fft_notch
from acquisition_systems.common.utils import pelvic_obliquity_deg_from_landmarks
from acquisition_systems.common.types import EmgSample
from acquisition_systems.recorder import Recorder
from scripts.post_process_emg import post_process_emg


class CoreBehaviourTests(unittest.TestCase):
    def test_bool_strings_are_parsed_strictly(self):
        self.assertTrue(_coerce_bool("true", field="test", default=False))
        self.assertFalse(_coerce_bool("FALSE", field="test", default=True))
        with self.assertRaises(ConfigError):
            _coerce_bool("not-a-bool", field="test", default=False)

    def test_notch_filter_handles_non_bin_centred_signal(self):
        fs = 1000.0
        t = np.arange(0, 2, 1 / fs)
        raw = np.sin(2 * np.pi * 60.3 * t) + 0.2 * np.sin(2 * np.pi * 10 * t)
        filtered = apply_fft_notch(raw, fs=fs, target_freq=60.0)
        self.assertLess(np.std(filtered), np.std(raw))
        self.assertTrue(np.all(np.isfinite(filtered)))

    def test_pelvic_angle_uses_mediapipe_indices_and_nan_for_invalid(self):
        landmarks = np.full((33, 2), np.nan, dtype=float)
        landmarks[23] = [10.0, 20.0]
        landmarks[24] = [20.0, 10.0]
        self.assertAlmostEqual(
            pelvic_obliquity_deg_from_landmarks(landmarks), 45.0, places=5
        )
        landmarks[23, 0] = math.nan
        self.assertTrue(math.isnan(pelvic_obliquity_deg_from_landmarks(landmarks)))

    def test_recorder_is_bounded_and_resets(self):
        recorder = Recorder(max_samples_per_stream=2)
        recorder.push_emg(EmgSample(0.0, 1.0))
        recorder.push_emg(EmgSample(0.001, 2.0))
        recorder.push_emg(EmgSample(0.002, 3.0))
        self.assertEqual(len(recorder._emg), 2)
        self.assertEqual(recorder.dropped_counts["emg"], 1)
        recorder.clear()
        self.assertEqual(len(recorder._emg), 0)
        self.assertEqual(recorder.dropped_counts["emg"], 0)

    def test_recorder_sanitizes_path_traversal_and_writes_notch_column(self):
        recorder = Recorder()
        for index in range(32):
            recorder.push_emg(EmgSample(index / 1000.0, 1.0))
        with tempfile.TemporaryDirectory() as tmp:
            path = recorder.to_csv_merged(tmp, "../escape")
            self.assertEqual(Path(path).parent.resolve(), Path(tmp).resolve())
            with Path(path).open(newline="") as stream:
                header = next(csv.reader(stream))
            self.assertIn("emg_notch_V", header)

    def test_post_processing_runs_without_gui_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.csv"
            t = np.arange(0, 1, 0.001)
            values = np.sin(2 * np.pi * 60.3 * t)
            import pandas as pd

            pd.DataFrame({"time_s": t, "emg_V": values}).to_csv(path, index=False)
            output = post_process_emg(str(path), show_plot=False)
            processed = pd.read_csv(output)
            self.assertIn("emg_notch_V", processed.columns)
            self.assertIn("emg_envelope", processed.columns)


if __name__ == "__main__":
    unittest.main()
