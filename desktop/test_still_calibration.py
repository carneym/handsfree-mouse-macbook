"""Automatic steady-window retries, gentle jitter, and rejection of real motion."""
import math
import unittest

from motion import Sample, zero_gyro
import test_head_mouse as fixtures


class StillCalibrationTests(unittest.TestCase):
    def app(self):
        app = fixtures.CalibrationTests().app()
        app.right, app.down = (1, 0, 0), (0, 1, 0)
        app.start_capture("zero", preserve_axes=True)
        return app

    def test_initial_twitch_is_retried_automatically_then_succeeds(self):
        app = self.app()
        start = app.capture[1]
        retried = False
        for i in range(501):
            if app.capture is None:
                break
            gyro = (7 * math.sin(i), 0, 0) if i < 100 else (.3, -2.3, .1)
            app.collect(Sample(i * 10000, (0, 0, 1), gyro), start + i / 100)
            retried |= "automatically" in (app.notice.get() or "")
        self.assertTrue(retried)
        self.assertIsNotNone(app.motion)
        self.assertAlmostEqual(app.bias[1], -2.3, delta=.1)
        self.assertEqual(app.right, (1, 0, 0))
        app.save_preferences.assert_called_once()

    def test_gentle_symmetric_jitter_can_calibrate_without_biasing_the_result(self):
        samples = [Sample(i * 10000, (.005 * math.sin(i), 0, 1),
                          (.3 + 1.4 * math.sin(2 * math.pi * i / 50), -2.3, .1))
                   for i in range(201)]
        bias = zero_gyro(samples)
        self.assertAlmostEqual(bias[0], .3, places=3)

    def test_continuous_motion_times_out_with_guidance_and_keeps_mounting(self):
        app = self.app()
        start = app.capture[1]
        for i in range(1501):
            app.collect(Sample(i * 10000, (0, 0, 1), (6 * math.sin(i / 10), 0, 0)), start+i/100)
            if app.capture is not None:
                self.assertLessEqual(len(app.capture[2]), 202)
        self.assertIsNone(app.capture)
        self.assertIsNone(app.motion)
        self.assertEqual(app.right, (1, 0, 0))
        self.assertIn("USB cable", app.notice.get())

    def test_tilting_with_constant_gravity_magnitude_is_rejected(self):
        samples = [Sample(i * 10000, (math.sin(i / 500), 0, math.cos(i / 500)), (0, 0, 0))
                   for i in range(201)]
        with self.assertRaises(ValueError):
            zero_gyro(samples)

    def test_a_few_small_settling_spikes_do_not_shift_the_zero(self):
        samples = [Sample(i * 10000, (0, 0, 1), (.3 + (4 if i % 50 == 0 else 0), -2.3, .1))
                   for i in range(201)]
        self.assertAlmostEqual(zero_gyro(samples)[0], .3, places=6)

    def test_too_few_samples_and_changing_bias_are_rejected(self):
        with self.assertRaises(ValueError):
            zero_gyro([Sample(0, (0, 0, 1), (0, 0, 0))])
        samples = [Sample(i * 10000, (0, 0, 1), (i / 100, 0, 0)) for i in range(201)]
        with self.assertRaises(ValueError):
            zero_gyro(samples)


if __name__ == "__main__":
    unittest.main()
