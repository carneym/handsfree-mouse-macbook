"""Sound transient gating, feature transport, and held tilt scrolling."""
import math
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile

from sound_click import SoundClick, SoundFrame, decode_sound
from ble_feed import decode_packet
from motion import Sample
from scroll_motion import TiltScroll
from preferences import load_profile, save_profile
import test_bluetooth_recenter as fixtures


def sound_frames(burst_frames=2, peak=5000, rms=800, high=500):
    # Quiet warmup, burst, and a quiet tail; 20 ms per feature frame.
    values = [(80, 30, 15)] * 30 + [(peak, rms, high)] * burst_frames + [(80, 30, 15)] * 50
    return [SoundFrame(i*20000, p, r, h, 320) for i, (p, r, h) in enumerate(values)]


class SoundTests(unittest.TestCase):
    def test_short_pop_clicks_once_long_tone_clipping_and_quiet_do_not(self):
        for kwargs, expected in (({}, 1), ({"burst_frames": 15}, 0),
                                 ({"peak": 1000, "rms": 750}, 0),
                                 ({"peak": 32767}, 0), ({"high": 50}, 0)):
            detector = SoundClick()
            events = [detector.update(frame, i*.02) for i, frame in enumerate(sound_frames(**kwargs))]
            self.assertEqual(sum(events), expected, kwargs)

    def test_gap_or_reset_cannot_finish_old_sound(self):
        detector = SoundClick()
        frames = sound_frames()
        for i, frame in enumerate(frames[:32]):
            detector.update(frame, i*.02)
        self.assertFalse(detector.update(frames[32], 5))
        detector.reset()
        self.assertFalse(detector.update(frames[33], 5.02))

    def test_usb_and_ble_feature_units_match(self):
        frame = decode_sound(b"HS1,12345,5000,800,500,320,0")
        seq, ble = decode_packet(struct.pack("<BBHI6H", 1, 1, 42, 12345, 5000, 800, 500, 320, 0, 0))
        self.assertEqual(seq, 42)
        self.assertEqual(frame, ble)
        self.assertIsNone(decode_sound(b"HS1,broken"))

    def app(self):
        app = fixtures.RecenterTests().app()
        app.click_method.set("Sound")
        app.dwell_enabled.set(True)
        app.connection_status = fixtures.fixtures.Value()
        app.telemetry = fixtures.fixtures.Value()
        return app

    def test_sound_test_counts_detections_without_any_mouse_event(self):
        app = self.app()
        app.sound_testing = True
        for i, frame in enumerate(sound_frames()):
            self.assertFalse(app.handle_sound(frame, i*.02))
        self.assertEqual(app.sound_tests, 1)
        app.mouse.click.assert_not_called()

    def test_enabled_sound_clicks_once_at_the_end_of_fresh_motion_batch(self):
        app = self.app()
        left = object()
        with patch.dict(sys.modules, {"pynput.mouse": SimpleNamespace(Button=SimpleNamespace(left=left))}):
            for i, frame in enumerate(sound_frames()):
                now = 10 + i * .02
                motion = Sample(i*20000, (0, 0, 1), (0, 0, 0))
                app.feed.drain.return_value = ([(now, motion), (now, frame)], 0, None)
                app.read_stream(now)
        app.mouse.click.assert_called_once_with(left)

    def test_switching_to_dwell_disables_sound_events(self):
        app = self.app()
        app.click_method.set("Dwell")
        for i, frame in enumerate(sound_frames()):
            self.assertFalse(app.handle_sound(frame, i*.02))
        app.mouse.click.assert_not_called()

    def test_method_switch_releases_drag_clears_old_sound_and_turns_mic_off(self):
        app = self.app()
        app.dragging = True
        app.drag_mouse = app.mouse
        app.sound.burst = {"old": True}
        app.dwell_controls, app.sound_setup = Mock(), Mock()
        app.click_method.set("Dwell")
        with patch.dict(sys.modules, {"pynput.mouse": SimpleNamespace(Button=SimpleNamespace(left="left"))}):
            app.change_click_method()
        app.mouse.release.assert_called_once_with("left")
        self.assertIsNone(app.sound.burst)
        app.feed.set_sound.assert_called_once_with(False)

    def test_method_and_sensitivity_are_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            save_profile(22, .8, None, None, path, click_method="Sound", sound_threshold=2300)
            self.assertEqual(load_profile(path)["click_method"], "Sound")
            self.assertEqual(load_profile(path)["sound_threshold"], 2300)

    def test_audio_cannot_mask_lost_imu_or_keep_drag_held(self):
        app = self.app()
        app.dragging = True
        app.drag_mouse = app.mouse
        app.last_rx = 1
        app.feed.drain.return_value = ([(2, SoundFrame(0, 80, 30, 15, 320))], 0, None)
        with patch.dict(sys.modules, {"pynput.mouse": SimpleNamespace(Button=SimpleNamespace(left="left"))}):
            app.read_stream(2)
        self.assertFalse(app.active)
        self.assertFalse(app.dragging)
        app.mouse.release.assert_called_once_with("left")


class ScrollTests(unittest.TestCase):
    def test_live_app_scrolls_during_held_tilt_without_pointer_movement_or_clicks(self):
        app = fixtures.RecenterTests().app()
        app.telemetry = fixtures.fixtures.Value()
        app.action_mode.set("Scroll")
        held_calls = 0
        for i in range(501):
            t = i/100
            angle = min(t, 1)*8 if t < 3 else max(0, 8-(t-3)*8)
            gyro = 8 if t < 1 else -8 if 3 <= t < 4 else 0
            rad = math.radians(angle)
            sample = Sample(i*10000, (-math.sin(rad), 0, math.cos(rad)), (0, gyro, 0))
            app.feed.drain.return_value = ([(10+t, sample)], 0, None)
            app.read_stream(10+t)
            if i == 150:
                held_calls = app.mouse.scroll.call_count
            if i == 250:
                self.assertGreater(app.mouse.scroll.call_count, held_calls)
        app.mouse.move.assert_not_called()
        app.mouse.click.assert_not_called()
        self.assertLess(sum(c.args[1] for c in app.mouse.scroll.call_args_list), 0)

    def test_held_down_tilt_keeps_scrolling_and_neutral_stops(self):
        scroll = TiltScroll()
        axis, bias = (0, 1, 0), (0, 0, 0)
        steps = []
        for i in range(501):
            t = i / 100
            angle = min(t, 1) * 8 if t < 3 else max(0, 8-(t-3)*8)
            gyro = 8 if t < 1 else -8 if 3 <= t < 4 else 0
            rad = math.radians(angle)
            sample = Sample(i*10000, (-math.sin(rad), 0, math.cos(rad)), (0, gyro, 0))
            steps.append(scroll.update(sample, bias, axis))
        self.assertLess(sum(steps[150:250]), 0, "Held down tilt should keep scrolling")
        self.assertEqual(sum(abs(s) for s in steps[450:]), 0, "Neutral must stop")

    def test_up_tilt_scrolls_up_and_reset_establishes_new_neutral(self):
        scroll = TiltScroll()
        for i in range(201):
            angle = max(-8, -i*.08)
            rad = math.radians(angle)
            sample = Sample(i*10000, (-math.sin(rad), 0, math.cos(rad)), (0, -8 if i < 100 else 0, 0))
            result = scroll.update(sample, (0, 0, 0), (0, 1, 0))
        self.assertLess(scroll.angle, -7)
        scroll.reset()
        self.assertEqual(scroll.update(sample, (0, 0, 0), (0, 1, 0)), 0)
        self.assertEqual(scroll.angle, 0)


if __name__ == "__main__":
    unittest.main()
