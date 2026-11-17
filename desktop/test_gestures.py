"""Synthetic head trajectories and mode/backend integration checks."""
import math
import random
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gestures import CircleGestures, validate_rules
from motion import PointerMotion, Sample
from preferences import load_profile, save_profile
import test_head_mouse as fixtures


def circles(detector, count=3, clockwise=False, radius=2, period=1.5):
    actions = []
    steps = round(period / .01)
    for i in range(steps * count + 1):
        angle = 2 * math.pi * i / steps
        speed = radius * 2 * math.pi / period
        action = detector.update(speed * math.cos(angle),
                                 speed * math.sin(angle) * (1 if clockwise else -1), .01)
        if action:
            actions.append(action)
    return actions


class GestureTests(unittest.TestCase):
    def test_three_anticlockwise_circles_switch_once_with_cooldown(self):
        detector = CircleGestures()
        self.assertEqual(circles(detector), ["Cycle modes"])
        self.assertTrue(detector.busy)
        self.assertEqual(circles(detector, 1), [])

    def test_wrong_direction_straight_turns_and_noise_do_not_switch(self):
        detector = CircleGestures()
        self.assertEqual(circles(detector, clockwise=True), [])
        detector.reset()
        actions = [detector.update(5 * (-1)**(i//50), 0, .01) for i in range(600)]
        self.assertFalse(any(actions))
        actions = [detector.update(.4 * math.sin(i), .4 * math.cos(i), .01) for i in range(600)]
        self.assertFalse(any(actions))

    def test_different_sizes_and_speeds(self):
        for radius, period in ((1, .8), (4, 2.5), (2, 1.0)):
            with self.subTest(radius=radius, period=period):
                self.assertEqual(circles(CircleGestures(), radius=radius, period=period), ["Cycle modes"])

    def test_elliptical_circles_with_sensor_noise(self):
        detector = CircleGestures()
        noise = random.Random(42)
        actions = []
        for i in range(451):
            angle = i * 2 * math.pi / 150
            action = detector.update(10 * math.cos(angle) + noise.uniform(-.15, .15),
                                     -7 * math.sin(angle) + noise.uniform(-.15, .15), .01)
            if action:
                actions.append(action)
        self.assertEqual(actions, ["Cycle modes"])

    def test_short_mapping_waits_when_a_longer_mapping_exists(self):
        detector = CircleGestures([
            {"direction": "Anticlockwise", "count": 1, "action": "Click"},
            {"direction": "Anticlockwise", "count": 3, "action": "Page"}])
        self.assertEqual(circles(detector, 1), [])
        actions = [detector.update(0, 0, .01) for _ in range(50)]
        self.assertEqual([a for a in actions if a], ["Click"])
        detector.reset()
        self.assertEqual(circles(detector), ["Page"])

    def test_pause_and_missing_samples_discard_partial_sequences(self):
        detector = CircleGestures()
        circles(detector, 2)
        detector.update(0, 0, .5)
        self.assertEqual(circles(detector, 1), [])
        detector.reset()
        circles(detector, 2)
        for _ in range(50):
            detector.update(0, 0, .01)
        self.assertEqual(circles(detector, 1), [])

    def test_duplicate_patterns_rejected_and_preferences_saved(self):
        rules = [{"direction": "Clockwise", "count": 2, "action": "Page"}]
        with self.assertRaises(ValueError):
            validate_rules(rules + rules)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            save_profile(22, .8, None, None, path, sensitivity=2.3, gestures=rules)
            self.assertEqual(load_profile(path)["sensitivity"], 2.3)
            self.assertEqual(load_profile(path)["gestures"], rules)

    def test_small_correction_after_settling_does_not_restart_dwell_guard(self):
        detector = CircleGestures()
        circles(detector, 1)
        self.assertTrue(detector.suppress_dwell)
        for _ in range(20):
            detector.update(0, 0, .01)
        self.assertFalse(detector.suppress_dwell)
        detector.update(1.1, 0, .01)
        self.assertEqual(detector.count, 1)
        self.assertFalse(detector.suppress_dwell)


class ModeTests(unittest.TestCase):
    def app(self):
        app = fixtures.CalibrationTests().app()
        app.active = True
        app.practice.set(False)
        app.motion = PointerMotion((0, 0, 0), (1, 0, 0), (0, 1, 0))
        app.mouse = Mock()
        app.connection_status = fixtures.Value()
        app.telemetry = fixtures.Value()
        return app

    def stream(self, app, rate=(5, 0, 0)):
        for i in range(100):
            now = 10 + i * .01
            sample = Sample(i * 10000, (0, 0, 1), rate)
            app.feed.drain.return_value = ([(now, sample)], 0, None)
            app.read_stream(now)

    def test_live_sensitivity_changes_computer_motion_but_not_practice(self):
        distances = []
        for sensitivity in (1, 2):
            app = self.app()
            app.sensitivity.set(sensitivity)
            self.stream(app)
            distances.append(sum(call.args[0] for call in app.mouse.move.call_args_list))
        self.assertAlmostEqual(distances[1] / distances[0], 2, delta=.03)
        app = self.app()
        app.practice.set(True)
        app.practice_position = [0, 75]
        app.canvas.winfo_width.return_value = 10000
        app.canvas.winfo_height.return_value = 150
        app.sensitivity.set(3)
        self.stream(app)
        self.assertEqual(app.practice_position[0], distances[0])
        app.mouse.move.assert_not_called()

    def test_page_scrolls_down_without_moving_or_clicking_pointer(self):
        app = self.app()
        app.action_mode.set("Page")
        app.dwell_enabled.set(True)
        self.stream(app, (0, 8, 0))
        self.assertLess(sum(call.args[1] for call in app.mouse.scroll.call_args_list), 0)
        app.mouse.move.assert_not_called()
        app.update_dwell(11)
        app.mouse.click.assert_not_called()

    def test_dwell_picks_up_and_releases_drag_and_pause_releases(self):
        app = self.app()
        app.action_mode.set("Drag")
        app.dwell_enabled.set(True)
        app.mouse.position = (0, 0)
        left = object()
        with patch.dict(sys.modules, {"pynput.mouse": SimpleNamespace(Button=SimpleNamespace(left=left))}):
            app.update_dwell(0)
            app.mouse.position = (30, 0)
            for i in range(1, 16):
                app.update_dwell(i / 10)
            self.assertTrue(app.dragging)
            app.mouse.press.assert_called_once_with(left)
            app.mouse.position = (60, 0)
            for i in range(16, 31):
                app.update_dwell(i / 10)
            self.assertFalse(app.dragging)
            app.mouse.release.assert_called_once_with(left)
            app.dragging = True
            app.drag_mouse = app.mouse
            app.pause()
            self.assertFalse(app.dragging)
            self.assertEqual(app.mouse.release.call_count, 2)

    def test_mode_change_dwell_off_and_usb_loss_release_drag(self):
        for operation in (lambda a: a.change_mode("Page"), lambda a: a.toggle_dwell(),
                          lambda a: a.interrupt_stream("lost")):
            app = self.app()
            app.dragging = True
            app.drag_mouse = app.mouse
            with patch.dict(sys.modules, {"pynput.mouse": SimpleNamespace(Button=SimpleNamespace(left="left"))}):
                operation(app)
            app.mouse.release.assert_called_once_with("left")
            self.assertFalse(app.dragging)

    def test_calibrated_gestures_cycle_all_modes_independently_of_sensitivity(self):
        app = self.app()
        app.gestures_enabled.set(True)
        app.sensitivity.set(3)
        index = 0
        for expected in ("Drag", "Scroll", "Click"):
            app.gestures.reset()
            previous = Sample(index * 10000, (0, 0, 1), (0, 0, 0))
            for i in range(451):
                index += 1
                angle = i * 2 * math.pi / 150
                sample = Sample(index * 10000, (0, 0, 1),
                                (8.38 * math.cos(angle), -8.38 * math.sin(angle), 0))
                app.check_gesture(previous, sample)
                previous = sample
            self.assertEqual(app.action_mode.get(), expected)
        app.mouse.click.assert_not_called()

    def test_gestures_and_cooldown_preserve_every_pointer_delta(self):
        paths = []
        for enabled in (False, True):
            app = self.app()
            app.gestures_enabled.set(enabled)
            # Cycle Click -> Drag preserves pointer output in both modes.
            for i in range(650):
                now = 10 + i * .01
                angle = i * 2 * math.pi / 150
                rate = ((8.38 * math.cos(angle), -8.38 * math.sin(angle), 0)
                        if i <= 450 else (5, 0, 0))
                app.feed.drain.return_value = ([(now, Sample(i * 10000, (0, 0, 1), rate))], 0, None)
                app.read_stream(now)
            paths.append([call.args for call in app.mouse.move.call_args_list])
            if enabled:
                self.assertEqual(app.action_mode.get(), "Drag")
        self.assertEqual(paths[0], paths[1])

    def test_mode_switch_cooldown_does_not_block_dwell(self):
        app = self.app()
        app.practice.set(True)
        app.practice_position = [0, 0]
        app.gestures_enabled.set(True)
        app.dwell_enabled.set(True)
        app.gestures.cooldown = 2
        app.update_dwell(0)
        app.practice_position = [30, 0]
        for i in range(1, 121):
            app.update_dwell(i / 100)
        self.assertEqual(app.practice_clicks, 1)
        app.mouse.click.assert_not_called()

    def test_small_curved_aiming_movements_do_not_cancel_dwell(self):
        app = self.app()
        app.practice.set(True)
        app.practice_position = [0, 0]
        app.dwell_enabled.set(True)
        app.gestures_enabled.set(True)
        app.update_dwell(0)
        previous = Sample(0, (0, 0, 1), (0, 0, 0))
        for i in range(1, 151):
            angle = math.pi * i / 150
            sample = Sample(i * 10000, (0, 0, 1),
                            (1.2 * math.cos(angle), -1.2 * math.sin(angle), 0))
            # A small curved correction stays within the dwell radius.
            app.practice_position = [30 + 2 * math.sin(angle), 2 * math.cos(angle)]
            app.check_gesture(previous, sample)
            app.update_dwell(i / 100)
            previous = sample
        self.assertGreater(abs(app.gestures.turn), math.pi / 2)
        self.assertEqual(app.practice_clicks, 1)
        self.assertFalse(app.gestures.suppress_dwell)

    def test_validated_circle_suspends_then_settling_allows_dwell_without_rearming(self):
        app = self.app()
        app.practice.set(True)
        app.practice_position = [30, 0]
        app.dwell_enabled.set(True)
        app.gestures_enabled.set(True)
        circles(app.gestures, 1)
        self.assertTrue(app.gestures.suppress_dwell)
        app.update_dwell(0)
        self.assertFalse(app.dwell.waiting_for_movement)
        for i in range(1, 141):
            app.gestures.update(0, 0, .01)
            app.update_dwell(i / 100)
            if i == 20:
                self.assertEqual(app.gestures.count, 1)
                self.assertFalse(app.gestures.suppress_dwell)
                self.assertGreater(app.dwell.progress, 0)
        self.assertEqual(app.practice_clicks, 1)

    def test_dwell_can_begin_in_new_mode_immediately_after_gesture(self):
        app = self.app()
        app.practice.set(True)
        app.practice_position = [30, 0]
        app.dwell_enabled.set(True)
        app.gestures_enabled.set(True)
        app.gestures.rules = [{"direction": "Anticlockwise", "count": 1, "action": "Click"}]
        previous = Sample(0, (0, 0, 1), (0, 0, 0))
        for i in range(151):
            angle = 2 * math.pi * i / 150
            sample = Sample((i+1) * 10000, (0, 0, 1),
                            (8.38 * math.cos(angle), -8.38 * math.sin(angle), 0))
            app.check_gesture(previous, sample)
            previous = sample
        self.assertGreater(app.gestures.cooldown, 0)
        self.assertFalse(app.dwell.waiting_for_movement)
        for i in range(121):
            app.update_dwell(i / 100)
        self.assertEqual(app.practice_clicks, 1)


if __name__ == "__main__":
    unittest.main()
