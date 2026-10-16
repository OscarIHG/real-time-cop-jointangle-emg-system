import time
import unittest

import numpy as np

from acquisition_systems.workers.emg import EMGWorker, LineParser
from acquisition_systems.workers.emg_sim import (
    BURST_PERIOD_S, EmgSignalModel, SimulatedEsp32Transport, Xorshift32,
)


class LineParserTests(unittest.TestCase):
    def test_drops_partial_first_fragment(self):
        p = LineParser(0.0, 3.3)
        self.assertEqual(p.feed(b"312\r\n0.1234\r\n0.2000\r\n"), [0.1234, 0.2])

    def test_rejects_out_of_range_instead_of_clamping(self):
        p = LineParser(0.0, 3.3, drop_first_fragment=False)
        self.assertEqual(p.feed(b"312\r\n3.32\r\nabc\r\n1.0\r\n"), [3.3, 1.0])
        self.assertEqual(p.out_of_range, 1)
        self.assertEqual(p.parse_errors, 1)

    def test_lines_split_across_chunks_and_lf(self):
        p = LineParser(drop_first_fragment=False)
        self.assertEqual(p.feed(b"0.12"), [])
        self.assertEqual(p.feed(b"34\r\n0.5\n"), [0.1234, 0.5])


class SignalModelTests(unittest.TestCase):
    def test_xorshift_reference_values(self):
        r = Xorshift32(1)
        self.assertEqual([r.next_u32() for _ in range(3)], [270369, 67634689, 2647435461])

    def test_deterministic_and_in_range(self):
        a = EmgSignalModel(100.0).generate(3000)
        b = EmgSignalModel(100.0).generate(3000)
        self.assertEqual(a, b)
        x = np.asarray(a)
        self.assertGreater(x.min(), 0.15)    # no clipping at 0 V
        self.assertLess(x.max(), 3.3)

    def test_60hz_interference_appears_at_40hz(self):
        x = np.asarray(EmgSignalModel(100.0).generate(2000))
        spec = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(x.size)))
        f = np.fft.rfftfreq(x.size, 1 / 100.0)
        peak = f[np.argmax(spec * (f > 15))]
        self.assertAlmostEqual(peak, 40.0, delta=0.2)

    def test_bursts_are_periodic(self):
        fs = 100.0
        x = np.asarray(EmgSignalModel(fs).generate(int(22 * fs)))
        smooth = np.convolve(x, np.ones(10) / 10, mode="same")
        onsets = np.flatnonzero((smooth[1:] > 0.8) & (smooth[:-1] <= 0.8)) / fs
        self.assertGreaterEqual(onsets.size, 3)
        np.testing.assert_allclose(np.diff(onsets), BURST_PERIOD_S, atol=0.2)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += max(dt, 1e-4)


class SimulatedTransportTests(unittest.TestCase):
    def test_protocol_and_pacing(self):
        clock = FakeClock()
        tr = SimulatedEsp32Transport(100.0, clock=clock, sleep=clock.sleep)
        tr.open()
        self.assertEqual(tr.read(4096, timeout=0.1), b"")     # silent before '1'
        tr.write(b"1")
        data = b""
        while clock.t < 2.0:
            data += tr.read(4096, timeout=0.05)
        lines = data.split(b"\r\n")[:-1]
        self.assertAlmostEqual(len(lines), 201, delta=2)      # 100 Hz, no drift
        tr.write(b"2")
        self.assertEqual(tr.read(4096, timeout=0.1), b"")

    def test_worker_end_to_end_with_simulator(self):
        w = EMGWorker("00:00:00:00:00:00", sample_rate_hz=100.0, source="simulated")
        w.start()
        self.assertTrue(w.wait_ready(2.0))
        time.sleep(2.0)
        w.stop()
        samples = []
        while not w.queue.empty():
            samples.append(w.queue.get_nowait())
        self.assertEqual(w.source, "simulated")
        self.assertAlmostEqual(len(samples), 200, delta=25)
        dt = np.diff([s.t for s in samples])
        np.testing.assert_allclose(dt, 0.01, atol=1e-9)        # reconstructed 100 Hz clock
        self.assertEqual(w.parse_errors, 0)


if __name__ == "__main__":
    unittest.main()
