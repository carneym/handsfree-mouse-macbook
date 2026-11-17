"""Dwell timing, cancellation and computer-control integration regressions."""
import tkinter as tk
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dwell import DwellClick
import test_head_mouse as fixtures


class DwellTests(unittest.TestCase):
    def test_movement_required_before_first_click_and_after_each_click(self):
        dwell = DwellClick()
        self.assertFalse(dwell.update((0, 0), 0))
        for i in range(1, 21):
            self.assertFalse(dwell.update((0, 0), i / 10))
        dwell.update((30, 0), 2.1)
        clicks = [dwell.update((30, 0), i / 10) for i in range(22, 51)]
        self.assertEqual(sum(clicks), 1)
        self.assertTrue(dwell.waiting_for_movement)
        dwell.update((60, 0), 5.1)
        clicks = [dwell.update((60, 0), i / 10) for i in range(52, 66)]
        self.assertEqual(sum(clicks), 1)

    def test_moving_outside_radius_restarts_countdown(self):
        dwell = DwellClick()
        dwell.update((0, 0), 0)
        dwell.update((30, 0), .1)
        for i in range(2, 8):
            self.assertFalse(dwell.update((30, 0), i / 10))
        dwell.update((45, 0), .8)
        for i in range(9, 18):
            self.assertFalse(dwell.update((45, 0), i / 10))
        self.assertTrue(dwell.update((45, 0), 1.9))

    def test_small_jitter_is_tolerated(self):
        dwell = DwellClick(seconds=.5)
        dwell.update((0, 0), 0)
        dwell.update((30, 0), .1)
        clicks = [dwell.update((30 + (-1)**i, 1), i / 10) for i in range(2, 9)]
        self.assertEqual(sum(clicks), 1)

    def test_stall_reset_and_pause_cannot_complete_an_old_countdown(self):
        dwell = DwellClick()
        dwell.update((0, 0), 0)
        dwell.update((30, 0), .1)
        dwell.update((30, 0), .2)
        self.assertFalse(dwell.update((30, 0), 3))
        self.assertTrue(dwell.waiting_for_movement)
        dwell.reset()
        self.assertFalse(dwell.update((30, 0), 4))
        self.assertEqual(dwell.progress, 0)


class DwellIntegrationTests(unittest.TestCase):
    def app(self):
        return fixtures.CalibrationTests().app()

    def test_master_switch_moves_from_practice_to_computer_and_back(self):
        app = self.app()
        app.motion = Mock()
        app.active = True
        app.practice.set(True)
        app.mouse = Mock()
        with patch("sys.platform", "darwin"), patch.dict(sys.modules, {
            "Quartz": SimpleNamespace(CGPreflightPostEventAccess=lambda: True),
        }):
            app.toggle_computer()
        self.assertTrue(app.active)
        self.assertFalse(app.practice.get())
        app.toggle_computer()
        self.assertFalse(app.active)
        self.assertTrue(app.practice.get())
        self.assertIsNone(app.dwell.started_at)

    def test_master_switch_cannot_bypass_permission(self):
        app = self.app()
        app.motion = Mock()
        with patch("sys.platform", "darwin"), patch.dict(sys.modules, {
            "Quartz": SimpleNamespace(CGPreflightPostEventAccess=lambda: False),
        }):
            app.toggle_computer()
        self.assertFalse(app.active)
        self.assertTrue(app.practice.get())

    def test_practice_records_one_click_without_os_mouse_events(self):
        app = self.app()
        app.active = True
        app.dwell_enabled.set(True)
        app.practice_position = [0, 0]
        app.mouse = Mock()
        app.update_dwell(0)
        app.practice_position = [30, 0]
        for i in range(1, 26):
            app.update_dwell(i / 10)
        self.assertEqual(app.practice_clicks, 1)
        app.mouse.click.assert_not_called()

    def test_computer_dwell_sends_one_left_click_and_stops_when_off(self):
        app = self.app()
        app.active = True
        app.practice.set(False)
        app.dwell_enabled.set(True)
        app.mouse = Mock()
        app.motion = Mock()
        app.mouse.position = (0, 0)
        app.update_dwell(0)
        app.mouse.position = (30, 0)
        left = object()
        with patch.dict(sys.modules, {"pynput.mouse": SimpleNamespace(Button=SimpleNamespace(left=left))}):
            for i in range(1, 26):
                app.update_dwell(i / 10)
            app.toggle_computer()
            for i in range(26, 36):
                app.update_dwell(i / 10)
        app.mouse.click.assert_called_once_with(left)
        self.assertFalse(app.active)

    def test_usb_interruption_cancels_dwell_and_computer_control(self):
        app = self.app()
        app.active = True
        app.practice.set(False)
        app.motion = Mock()
        app.mouse = Mock()
        app.dwell_enabled.set(True)
        app.dwell.update((0, 0), 0)
        app.dwell.update((30, 0), .1)
        app.feed.drain.return_value = ([], 0, None)
        app.connection_status = fixtures.Value()
        app.telemetry = fixtures.Value()
        app.read_stream(2)
        app.update_dwell(2)
        self.assertFalse(app.active)
        self.assertIsNone(app.dwell.started_at)
        app.mouse.click.assert_not_called()

    def test_invalid_duration_does_not_click_or_stop_movement(self):
        app = self.app()
        app.active = True
        app.dwell_enabled.set(True)
        app.dwell_seconds = Mock()
        app.dwell_seconds.get.side_effect = tk.TclError("empty field")
        app.update_dwell(0)
        self.assertTrue(app.active)
        self.assertIn("Choose", app.dwell_status.get())

    def test_disabling_dwell_cancels_a_pending_click(self):
        app = self.app()
        app.active = True
        app.dwell_enabled.set(True)
        app.practice_position = [0, 0]
        app.update_dwell(0)
        app.practice_position = [30, 0]
        app.update_dwell(.1)
        app.dwell_enabled.set(False)
        app.reset_dwell()
        app.update_dwell(.2)
        self.assertIsNone(app.dwell.started_at)
        self.assertEqual(app.practice_clicks, 0)


if __name__ == "__main__":
    unittest.main()
