import unittest

import numpy as np

from acquisition_systems.common.dsp import (
    RealtimeEmgFilter, StreamingIIRNotch, alias_frequency, butter_lowpass_sos, fft_notch,
    hilbert_envelope, iir_notch_sos, lowpass_filter, powerline_targets,
)


def tone_power(x, fs, freq):
    x = np.asarray(x) - np.mean(x)
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    f = np.fft.rfftfreq(x.size, 1 / fs)
    k = int(np.argmin(np.abs(f - freq)))
    return spec[max(0, k - 2):k + 3].max()


class AliasingTests(unittest.TestCase):
    def test_alias_frequency(self):
        self.assertAlmostEqual(alias_frequency(60, 100), 40)
        self.assertAlmostEqual(alias_frequency(120, 100), 20)
        self.assertAlmostEqual(alias_frequency(180, 100), 20)
        self.assertAlmostEqual(alias_frequency(60, 1000), 60)

    def test_targets_skip_dc_alias(self):
        self.assertEqual(powerline_targets(100, 60, 5), [40.0, 20.0])  # 300 Hz aliases to DC

    def test_sampled_60hz_is_a_40hz_tone(self):
        n = np.arange(1000)
        np.testing.assert_allclose(np.sin(2 * np.pi * 60 * n / 100), -np.sin(2 * np.pi * 40 * n / 100), atol=1e-9)


class FftNotchTests(unittest.TestCase):
    def setUp(self):
        self.fs = 100.0
        t = np.arange(0, 20, 1 / self.fs)
        self.clean = 0.4 + 0.2 * np.sin(2 * np.pi * 2 * t)
        self.raw = self.clean + 0.1 * np.sin(2 * np.pi * 60 * t)  # sampled 60 Hz interference

    def test_removes_aliased_powerline_at_100hz(self):
        out = fft_notch(self.raw, self.fs, 60.0)
        att = 20 * np.log10(tone_power(out, self.fs, 40) / tone_power(self.raw, self.fs, 40))
        self.assertLess(att, -30.0)

    def test_preserves_signal_dc_and_edges(self):
        out = fft_notch(self.raw, self.fs, 60.0)
        self.assertGreater(np.corrcoef(out, self.clean)[0, 1], 0.99)
        self.assertAlmostEqual(out.mean(), self.raw.mean(), places=3)
        edge = int(0.05 * out.size)
        err = np.abs(out - self.clean)
        self.assertLess(err[:edge].max(), 0.05)   # no spike at t=0
        self.assertLess(err[-edge:].max(), 0.05)

    def test_short_windows_work(self):
        out = fft_notch(self.raw[:500], self.fs, 60.0)
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertEqual(out.size, 500)


class StreamingTests(unittest.TestCase):
    def test_chunked_iir_matches_single_pass(self):
        from scipy import signal
        fs = 100.0
        x = np.random.default_rng(1).normal(size=2000) + 1.0
        sos = iir_notch_sos(fs, 60.0)
        ref = signal.sosfilt(sos, x, zi=signal.sosfilt_zi(sos) * x[0])[0]
        f = StreamingIIRNotch(fs, 60.0)
        out = np.concatenate([f.process(c) for c in np.array_split(x, 37)])
        np.testing.assert_allclose(out, ref, atol=1e-10)

    def test_realtime_filter_window_is_bounded(self):
        for method in ("fft", "iir"):
            f = RealtimeEmgFilter(100.0, window_s=5.0, method=method)
            for k in range(30):
                t = np.arange(k * 50, (k + 1) * 50) / 100.0
                f.extend(t, 0.3 + 0.1 * np.sin(2 * np.pi * 60 * t))
            t, v = f.window()
            self.assertEqual(t.size, 500)
            self.assertEqual(v.size, 500)


class PostProcessingDspTests(unittest.TestCase):
    def test_butterworth_is_sixth_order(self):
        self.assertEqual(butter_lowpass_sos(100.0, 10.0, 6).shape, (3, 6))

    def test_hilbert_envelope_has_no_edge_spike(self):
        fs = 100.0
        t = np.arange(0, 10, 1 / fs)
        x = lowpass_filter(0.3 + 0.05 * np.sin(2 * np.pi * 0.5 * t), fs)
        env = hilbert_envelope(x)
        self.assertLess(env[:20].max(), 0.5)
        self.assertLess(np.abs(env - x).max(), 0.1)


if __name__ == "__main__":
    unittest.main()
