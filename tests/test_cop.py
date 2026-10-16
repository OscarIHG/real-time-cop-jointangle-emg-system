import math
import unittest

from acquisition_systems.common.utils import cop_from_forces
from acquisition_systems.workers.cop import CopFrameAssembler

X, Y = 48.38, 33.04


def legacy_display(n):
    """CoP exactly as the previous release computed it (with flip_y=True)."""
    f = sum(n)
    m_ap = -n[0] - n[1] + n[2] + n[3]
    m_ml = -n[0] + n[1] + n[2] - n[3]
    return (X / 2) * (m_ml / f), -((Y / 2) * (m_ap / f))


class CopEquationTests(unittest.TestCase):
    def test_all_load_on_ch0(self):
        c1, c2, fz = cop_from_forces([10, 0, 0, 0], X, Y)
        self.assertAlmostEqual(c1, X / 2)
        self.assertAlmostEqual(c2, -Y / 2)
        self.assertAlmostEqual(fz, 10)

    def test_uniform_load_is_centred(self):
        c1, c2, _ = cop_from_forces([5, 5, 5, 5], X, Y)
        self.assertAlmostEqual(c1, 0.0)
        self.assertAlmostEqual(c2, 0.0)

    def test_whole_difference_is_divided_by_fz(self):
        # The printed equation (F1+F4) - (F2+F3)/Fz would give 30 - 50/80 here.
        c1, _, _ = cop_from_forces([20, 25, 25, 10], X, Y)
        self.assertAlmostEqual(c1, (X / 2) * ((30 - 50) / 80))

    def test_unloaded_plate_is_nan_not_zero(self):
        c1, c2, _ = cop_from_forces([0.01, -0.02, 0.0, 0.015], X, Y, min_fz=49.0)
        self.assertTrue(math.isnan(c1) and math.isnan(c2))

    def test_orientation_matches_previous_release(self):
        for n in ([30, 10, 5, 20], [1, 50, 2, 3], [12, 12, 30, 1]):
            c1, c2, _ = cop_from_forces(n, X, Y)
            old_x, old_y = legacy_display(n)
            self.assertAlmostEqual(-c1, old_x)   # cop_flip_x: true
            self.assertAlmostEqual(-c2, old_y)   # cop_flip_y: true

    def test_cop_stays_inside_cell_polygon(self):
        c1, c2, _ = cop_from_forces([0, 0, 80, 0], X, Y)
        self.assertLessEqual(abs(c1), X / 2)
        self.assertLessEqual(abs(c2), Y / 2)


class FrameAssemblerTests(unittest.TestCase):
    def test_one_frame_per_four_fresh_channels(self):
        a = CopFrameAssembler()
        frames = []
        for k in range(10):
            for ch in (0, 2, 1, 3):
                out = a.update(ch, ch + k, k + ch / 10)
                if out:
                    frames.append(out)
        self.assertEqual(len(frames), 10)
        self.assertEqual(frames[3][0], [3, 4, 5, 6])

    def test_bunched_out_of_order_events_keep_periods_together(self):
        # CH3 is delayed by two periods, then its callbacks arrive in a burst.
        a = CopFrameAssembler()
        events = []
        for k in range(10):
            events += [(ch, 100 * k + ch, k * 0.008) for ch in (0, 1, 2)]
        events += [(3, 100 * k + 3, k * 0.008 + 0.02) for k in range(10)]
        frames = [f for f in (a.update(*e) for e in events) if f]
        self.assertEqual(len(frames), 10)                       # exactly one per period
        for k, (values, t) in enumerate(frames):
            self.assertEqual(values, [100 * k, 100 * k + 1, 100 * k + 2, 100 * k + 3])
            self.assertAlmostEqual(t, k * 0.008)                 # earliest callback

    def test_stalled_channels_are_realigned_by_time(self):
        a = CopFrameAssembler(max_lag=3, interval_s=0.008)
        for k in range(5):                                       # only CH0 delivers (others stalled)
            self.assertIsNone(a.update(0, k, k * 0.008))
        frames = []
        for k in range(5, 10):
            for ch in range(4):
                out = a.update(ch, k, k * 0.008 + 0.0005 * ch)
                if out:
                    frames.append(out)
        self.assertEqual([f[0] for f in frames], [[k] * 4 for k in range(5, 10)])

    def test_missing_channel_is_bounded_and_counted(self):
        a = CopFrameAssembler(max_lag=5)
        for k in range(8):
            for ch in (0, 1, 2):                                  # CH3 never reports
                self.assertIsNone(a.update(ch, 1.0, k))
        self.assertEqual(a.incomplete_frames, 9)


if __name__ == "__main__":
    unittest.main()
