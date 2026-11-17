"""Regression checks for the simulator's calibration and pointer behavior."""
import math
import unittest

from model import Simulator


class SimulatorTests(unittest.TestCase):
    def calibrated(self, mount=35):
        simulator = Simulator()
        simulator.command("settings", {"mount": mount})
        simulator.command("demo", {})
        simulator.advance(20)
        self.assertIsNotNone(simulator.motion, simulator.message)
        self.assertFalse(simulator.active)
        return simulator

    def test_demo_learns_mounting_orientation(self):
        for mount in (-145, 0, 35, 120):
            with self.subTest(mount=mount):
                simulator = self.calibrated(mount)
                simulator.command("toggle", {})
                simulator.command("pose", {"yaw": 5, "pitch": 0})
                simulator.advance(2)
                self.assertGreater(simulator.pointer[0], 720)
                self.assertLess(abs(simulator.pointer[1] - 360), 3)

    def test_manual_three_step_capture(self):
        simulator = Simulator()
        simulator.command("capture", {"step": "zero"})
        simulator.advance(5.1)
        self.assertIsNotNone(simulator.bias)
        for step, pose in (("right", {"yaw": 12, "pitch": 0}),
                           ("down", {"yaw": 0, "pitch": 12})):
            simulator.command("pose", {"yaw": 0, "pitch": 0})
            simulator.advance(1)
            simulator.command("capture", {"step": step})
            simulator.advance(3.1)
            simulator.command("pose", pose)
            simulator.advance(3)
        self.assertIsNotNone(simulator.motion, simulator.message)

    def test_pause_and_focus_loss_stop_pointer(self):
        simulator = self.calibrated()
        simulator.command("toggle", {})
        simulator.interrupt()
        point = list(simulator.pointer)
        simulator.command("pose", {"yaw": 20, "pitch": 20})
        simulator.advance(2)
        self.assertEqual(simulator.pointer, point)
        self.assertFalse(simulator.active)

    def test_rezero_retains_axes_and_removes_changed_bias(self):
        simulator = self.calibrated()
        right, down = simulator.right, simulator.down
        simulator.command("settings", {"bias": 3, "deadzone": .2})
        simulator.command("toggle", {})
        simulator.advance(3)
        self.assertGreater(math.dist(simulator.pointer, (640, 360)), 10)
        simulator.command("rezero", {})
        simulator.advance(6)
        self.assertEqual((simulator.right, simulator.down), (right, down))
        self.assertFalse(simulator.active)
        simulator.command("center", {})
        simulator.command("toggle", {})
        simulator.advance(5)
        self.assertLess(math.dist(simulator.pointer, (640, 360)), 3)

    def test_remount_invalidates_calibration(self):
        simulator = self.calibrated()
        simulator.command("toggle", {})
        simulator.command("settings", {"mount": -80})
        self.assertFalse(simulator.active)
        self.assertIsNone(simulator.motion)
        self.assertTrue(all(result is None for result in simulator.report.values()))

    def test_noisy_still_reading_is_rejected(self):
        simulator = Simulator()
        simulator.command("settings", {"noise": 2})
        simulator.command("capture", {"step": "zero"})
        simulator.advance(6)
        self.assertIsNone(simulator.bias)
        self.assertIn("moved", simulator.message)

    def test_capture_is_cancelled_by_interruption(self):
        simulator = Simulator()
        simulator.command("demo", {})
        simulator.advance(2)
        simulator.interrupt()
        self.assertIsNone(simulator.stage)
        self.assertFalse(simulator.demo)
        self.assertIsNone(simulator.motion)

    def test_target_dwell_and_center(self):
        simulator = self.calibrated()
        simulator.command("toggle", {})
        simulator.pointer = [1280 * .72, 360]
        simulator.advance(.6)
        self.assertEqual(simulator.hits, 1)
        simulator.command("center", {})
        self.assertEqual(simulator.pointer, [640, 360])
        self.assertEqual(simulator.trail, [])

    def test_invalid_inputs_leave_settings_intact(self):
        simulator = Simulator()
        settings = simulator.settings.copy()
        with self.assertRaises(ValueError):
            simulator.command("settings", {"gain": 30, "noise": float("nan")})
        self.assertEqual(simulator.settings, settings)
        for payload in ({"yaw": 26, "pitch": 0}, {"yaw": 0}, {"yaw": float("inf"), "pitch": 0}):
            with self.assertRaises(ValueError):
                simulator.command("pose", payload)


if __name__ == "__main__":
    unittest.main()
