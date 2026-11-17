"""Rapid left-right recognition and interaction with dwell/pointer movement."""
import json
import math
from pathlib import Path
import tempfile
import unittest

from gestures import HeadGestures, CIRCLE_RULES, DEFAULT_RULES
from motion import Sample
from preferences import load_profile, save_profile
import test_gestures as fixtures


def strokes(detector, count=6, speed=14, duration=.2, vertical=0, start=-1):
    actions = []
    for stroke in range(count):
        for _ in range(round(duration / .01)):
            action = detector.update(start * (-1)**stroke * speed, vertical, .01)
            if action:
                actions.append(action)
    return actions


class HorizontalTests(unittest.TestCase):
    def test_two_pairs_cycle_once_starting_either_direction(self):
        for start in (-1, 1):
            detector = HeadGestures()
            self.assertEqual(strokes(detector, count=4, start=start), ["Cycle modes"])
            self.assertEqual(strokes(detector), [])

    def test_smooth_side_to_side_with_gentle_reversals(self):
        detector = HeadGestures()
        actions = []
        for i in range(241):
            action = detector.update(18 * math.sin(2 * math.pi * i / 80), 0, .01)
            if action:
                actions.append(action)
        self.assertEqual(actions, ["Cycle modes"])

    def test_too_few_slow_tiny_vertical_and_diagonal_movements_do_not_switch(self):
        for parameters in ({"count": 2}, {"speed": 2}, {"speed": 8, "duration": .1},
                           {"speed": 6, "duration": .6}, {"vertical": 25},
                           {"speed": 0, "vertical": 15}, {"count": 1, "duration": 2}):
            with self.subTest(parameters=parameters):
                self.assertEqual(strokes(HeadGestures(), **parameters), [])

    def test_pause_and_sample_gap_clear_incomplete_sequence(self):
        for gap in (.01, .5):
            detector = HeadGestures()
            strokes(detector, count=2)
            for _ in range(30):
                detector.update(0, 0, gap)
            self.assertEqual(strokes(detector, count=2), [])

    def test_partial_shake_never_interrupts_dwell(self):
        detector = HeadGestures()
        strokes(detector, count=2)
        self.assertEqual(detector.count, 1)
        self.assertFalse(detector.suppress_dwell)

    def test_short_mapping_waits_for_pause_when_longer_pattern_exists(self):
        detector = HeadGestures([
            {"direction": "Left-right", "count": 1, "action": "Click"},
            {"direction": "Left-right", "count": 3, "action": "Page"}])
        self.assertEqual(strokes(detector, count=2), [])
        actions = [detector.update(0, 0, .01) for _ in range(30)]
        self.assertEqual([a for a in actions if a], ["Click"])
        detector.reset()
        self.assertEqual(strokes(detector), ["Page"])

    def test_default_profile_migrates_once_and_keeps_mounting_and_speed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            save_profile(40, 1.2, (1, 0, 0), (0, 1, 0), path, gestures=CIRCLE_RULES)
            self.assertEqual(load_profile(path)["gestures"], CIRCLE_RULES)
            legacy = json.loads(path.read_text())
            del legacy["gesture_version"]
            path.write_text(json.dumps(legacy))
            profile = load_profile(path)
            self.assertEqual(profile["gestures"], DEFAULT_RULES)
            self.assertEqual(profile["gain"], 40)
            self.assertEqual(profile["right"], [1, 0, 0])
            legacy["gestures"] = [{"direction": "Left-right", "count": 3, "action": "Cycle modes"}]
            legacy["gesture_version"] = 2
            path.write_text(json.dumps(legacy))
            self.assertEqual(load_profile(path)["gestures"], DEFAULT_RULES)
            save_profile(40, 1.2, None, None, path, gestures=legacy["gestures"])
            self.assertEqual(load_profile(path)["gestures"], legacy["gestures"])

    def test_real_sample_pipeline_cycles_modes_and_keeps_movement(self):
        app = fixtures.ModeTests().app()
        app.gestures = HeadGestures()
        app.gestures_enabled.set(True)
        for cycle, expected in enumerate(("Drag", "Scroll", "Click")):
            app.gestures.reset()
            app.last_sample = None
            for i in range(120):
                now = 10 + cycle * 2 + i * .01
                sample = Sample((cycle * 200 + i) * 10000, (0, 0, 1),
                                (-14 * (-1)**(i//20), 0, 0))
                app.feed.drain.return_value = ([(now, sample)], 0, None)
                app.read_stream(now)
            self.assertEqual(app.action_mode.get(), expected)
        app.mouse.move.assert_called()
        app.mouse.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
