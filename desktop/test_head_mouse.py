"""Regression checks for saved mounting, practice mode and permission handling."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from head_mouse import HeadMouse
from dwell import DwellClick
from sound_click import SoundClick
from scroll_motion import TiltScroll
from gestures import HeadGestures, CIRCLE_RULES
from motion import PointerMotion, Sample, decode
from preferences import load_profile, save_profile


class Value:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class CalibrationTests(unittest.TestCase):
    def app(self):
        app = HeadMouse.__new__(HeadMouse)
        app.active = False
        app.bias = app.right = app.down = app.motion = app.mouse = None
        app.capture = None
        app.rezero = False
        app.recentering = None
        app.transport = Value("USB")
        app.ble_address = app.ble_name = None
        app.notice = Value()
        app.gain, app.deadzone = Value(22), Value(.8)
        app.practice = Value(True)
        app.dwell = DwellClick()
        app.click_method = Value("Dwell")
        app.sound_threshold = Value(1800)
        app.sound = SoundClick()
        app.sound_testing = False
        app.sound_tests = 0
        app.sound_learning_until = None
        app.sound_background = []
        app.sound_status = Value()
        app.sound_level = Value(0)
        app.last_sound_rx = None
        app.dwell_enabled = Value(False)
        app.dwell_seconds = Value(1.0)
        app.dwell_status = Value()
        app.practice_clicks = 0
        app.sensitivity = Value(1.0)
        app.mode_set = Value("Mode 1")
        app.mode_picker = Mock()
        app.action_mode = Value("Click")
        app.gestures_enabled = Value(False)
        app.gesture_status = Value()
        app.gestures = HeadGestures(CIRCLE_RULES)
        app.dragging = False
        app.drag_mouse = None
        app.scroll_remainder = 0.0
        app.scroll = TiltScroll()
        app.practice_scroll = 0
        app.mode_badge_enabled = Value(False)
        app.mode_badge = None
        app.badge_failed = False
        app.badge_flash_until = 0.0
        app.dwell_progress = {}
        app.canvas = Mock()
        app.progress = {}
        app.recenter_button = Mock()
        app.update_buttons = Mock()
        app.save_preferences = Mock()
        app.port = Mock()
        app.feed = Mock()
        app.feed.drain.return_value = ([], 0, None)
        app.last_rx = 1
        app.last_sample = None
        return app

    def test_saved_mounting_requires_a_new_zero(self):
        app = self.app()
        profile = {"gain": 18, "deadzone": 1.2, "right": [1, 0, 0], "down": [0, 1, 0]}
        with patch("head_mouse.load_profile", return_value=profile):
            app.restore_profile()
        self.assertEqual(app.right, [1, 0, 0])
        self.assertIsNone(app.bias)
        self.assertIsNone(app.motion)
        self.assertFalse(app.active)

    def test_restored_mounting_keeps_movement_captures_disabled_until_zeroed(self):
        app = self.app()
        app.right, app.down = (1, 0, 0), (0, 1, 0)
        app.calibration = [Mock(), Mock(), Mock()]
        app.arm = app.computer_button = app.rezero_button = app.cancel_button = Mock()
        app.step_labels = [Value(), Value(), Value()]
        app.pointer_status = Value()
        HeadMouse.update_buttons(app)
        self.assertEqual(app.calibration[1].configure.call_args.kwargs["state"], "disabled")
        self.assertEqual(app.calibration[2].configure.call_args.kwargs["state"], "disabled")

    def test_rezero_keeps_axes_and_builds_motion(self):
        app = self.app()
        app.right, app.down = (1, 0, 0), (0, 1, 0)
        app.start_capture("zero", preserve_axes=True)
        start = app.capture[1]
        for i in range(201):
            app.collect(Sample(i*10000, (0, 0, 1), (.3, -.4, .1)), start+i*.01)
        self.assertIsNotNone(app.motion)
        self.assertEqual(app.right, (1, 0, 0))
        self.assertFalse(app.active)
        app.save_preferences.assert_called_once()

    def test_starting_full_calibration_clears_old_mounting(self):
        app = self.app()
        app.right, app.down = (1, 0, 0), (0, 1, 0)
        app.start_capture("zero")
        self.assertIsNone(app.right)
        self.assertIsNone(app.down)
        self.assertIsNone(app.motion)

    def test_practice_needs_no_mouse_permission_or_controller(self):
        app = self.app()
        app.motion = PointerMotion((0, 0, 0), (1, 0, 0), (0, 1, 0))
        controller = Mock()
        with patch("sys.platform", "darwin"), patch.dict(sys.modules, {
            "Quartz": SimpleNamespace(CGPreflightPostEventAccess=lambda: False),
            "pynput.mouse": SimpleNamespace(Controller=controller),
        }):
            app.toggle_pointer()
        self.assertTrue(app.active)
        controller.assert_not_called()
        app.feed.drain.assert_called_once()

    def test_computer_mode_requires_permission(self):
        app = self.app()
        app.practice.set(False)
        app.motion = PointerMotion((0, 0, 0), (1, 0, 0), (0, 1, 0))
        with patch("sys.platform", "darwin"), patch.dict(sys.modules, {
            "Quartz": SimpleNamespace(CGPreflightPostEventAccess=lambda: False),
        }):
            app.toggle_pointer()
        self.assertFalse(app.active)
        self.assertIn("macOS has blocked", app.notice.get())

    def test_live_samples_move_only_the_practice_crosshair(self):
        app = self.app()
        app.active = True
        app.motion = PointerMotion((0, 0, 0), (1, 0, 0), (0, 1, 0))
        app.mouse = Mock()
        app.canvas = Mock()
        app.canvas.winfo_width.return_value = 700
        app.canvas.winfo_height.return_value = 150
        app.practice_position = [350, 75]
        app.last_rx = None
        app.connection_status = Value()
        app.telemetry = Value()
        for batch in range(50):
            now = 10 + batch * .02
            events = [
                (now - .01 * (1 - j), decode(
                    f"HM1,{(batch*2+j)*10000},0,0,16384,1310,0,0".encode()))
                for j in range(2)]
            app.feed.drain.return_value = (events, 0, None)
            app.read_stream(now)
        self.assertGreater(app.practice_position[0], 450)
        self.assertEqual(app.practice_position[1], 75)
        app.mouse.move.assert_not_called()
        app.canvas.move.assert_called()


class ProfileTests(unittest.TestCase):
    def test_round_trip_and_invalid_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            self.assertIsNone(load_profile(path))
            save_profile(22, .8, (1, 0, 0), (0, 1, 0), path)
            self.assertEqual(load_profile(path)["right"], [1, 0, 0])
            self.assertEqual(load_profile(path)["dwell_seconds"], 1.0)
            save_profile(22, .8, (1, 0, 0), (0, 1, 0), path, dwell_seconds=1.5)
            self.assertEqual(load_profile(path)["dwell_seconds"], 1.5)
            legacy = json.loads(path.read_text())
            del legacy["dwell_seconds"]
            path.write_text(json.dumps(legacy))
            self.assertEqual(load_profile(path)["dwell_seconds"], 1.0)
            path.write_text(json.dumps({"version": 1, "gain": 22, "deadzone": .8,
                                        "right": [1, 0, 0], "down": [1, 0, 0]}))
            self.assertIsNone(load_profile(path))
            path.write_text("{broken")
            self.assertIsNone(load_profile(path))

    def test_preferences_without_calibration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            save_profile(30, 1.1, None, None, path)
            profile = load_profile(path)
            self.assertEqual(profile["gain"], 30)
            self.assertIsNone(profile["right"])


if __name__ == "__main__":
    unittest.main()
