"""Three up-down pairs recenter, without confusing pointing or mode gestures."""
import json
from pathlib import Path
import tempfile
import unittest

from gestures import HeadGestures, DEFAULT_RULES, RECENTER_RULE
from motion import Sample
from preferences import load_profile, save_profile
import test_bluetooth_recenter as fixtures


def nods(detector, strokes=6, speed=14, duration=.2, start=-1, sideways=0):
    actions = []
    for stroke in range(strokes):
        for _ in range(round(duration / .01)):
            action = detector.update(sideways, start * (-1)**stroke * speed, .01)
            if action:
                actions.append(action)
    return actions


class VerticalGestureTests(unittest.TestCase):
    def test_exact_up_down_sequence_recenters_once(self):
        detector = HeadGestures()
        self.assertEqual(nods(detector), ["Recenter"])
        self.assertEqual(nods(detector), [])

    def test_single_nod_partial_slow_tiny_diagonal_and_down_first_do_not_trigger(self):
        for parameters in ({"strokes": 2}, {"strokes": 4}, {"strokes": 5}, {"duration": .7},
                           {"speed": 2}, {"speed": 8, "duration": .1},
                           {"sideways": 14}, {"start": 1}):
            with self.subTest(parameters=parameters):
                self.assertEqual(nods(HeadGestures(), **parameters), [])

    def test_gap_discards_partial_sequence_and_partial_nods_leave_dwell_alone(self):
        detector = HeadGestures()
        self.assertEqual(nods(detector, strokes=4), [])
        self.assertFalse(detector.suppress_dwell)
        for _ in range(30):
            detector.update(0, 0, .01)
        self.assertEqual(nods(detector, strokes=2), [])

    def test_saved_profile_gets_new_recenter_rule_once_with_settings_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            old_rules = [{"direction": "Left-right", "count": 2, "action": "Cycle modes"}]
            save_profile(40, 1.2, (1, 0, 0), (0, 1, 0), path, gestures=old_rules,
                         ble_address="saved-device", sensitivity=1.5)
            old = json.loads(path.read_text())
            old["gesture_version"] = 3
            path.write_text(json.dumps(old))
            profile = load_profile(path)
            self.assertEqual(profile["gestures"], DEFAULT_RULES)
            self.assertEqual(profile["ble_address"], "saved-device")
            self.assertEqual(profile["right"], [1, 0, 0])
            self.assertEqual(profile["sensitivity"], 1.5)
            # A deliberate removal in the new editor must persist.
            save_profile(40, 1.2, None, None, path, gestures=old_rules)
            self.assertNotIn(RECENTER_RULE, load_profile(path)["gestures"])

    def test_live_samples_keep_moving_until_sixth_stroke_then_start_recenter(self):
        app = fixtures.RecenterTests().app()
        app.gestures = HeadGestures()
        app.gestures_enabled.set(True)
        app.telemetry = fixtures.fixtures.Value()
        for i in range(120):
            now = 10 + i / 100
            sample = Sample(i * 10000, (0, 0, 1), (0, -14 * (-1)**(i//20), 0))
            app.feed.drain.return_value = ([(now, sample)], 0, None)
            app.read_stream(now)
            if i < 100:
                self.assertIsNone(app.recentering)
                self.assertTrue(app.active)
        self.assertIsNotNone(app.recentering)
        self.assertFalse(app.active)
        self.assertEqual(app.action_mode.get(), "Click")
        app.mouse.move.assert_called()
        app.mouse.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
