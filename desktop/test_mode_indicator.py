"""Badge geometry and lifecycle without generating real computer input."""
import unittest
import struct
from pathlib import Path
from unittest.mock import Mock, patch

from mode_indicator import badge_origin, MODE_STYLE, BADGE_SIZE, icon_state, at_reveal_edge
import test_head_mouse as fixtures


class IndicatorTests(unittest.TestCase):
    def test_badge_stays_visible_near_screen_edges_and_on_negative_origin_screen(self):
        for screen in ((0, 0, 1440, 900), (-1920, -200, 1920, 1080), (1440, 400, 1280, 800)):
            sx, sy, w, h = screen
            for pointer in ((sx+1, sy+1), (sx+w-1, sy+h-1), (sx+1, sy+h-1),
                            (sx+w-1, sy+1), (sx+w/2, sy+h/2)):
                x, y = badge_origin(pointer, screen)
                self.assertGreaterEqual(x, sx+6)
                self.assertGreaterEqual(y, sy+6)
                self.assertLessEqual(x+BADGE_SIZE[0], sx+w-6)
                self.assertLessEqual(y+BADGE_SIZE[1], sy+h-6)
                self.assertFalse(x <= pointer[0] <= x+BADGE_SIZE[0] and y <= pointer[1] <= y+BADGE_SIZE[1])

    def test_badge_follows_mode_and_hides_when_paused_or_disabled(self):
        app = fixtures.CalibrationTests().app()
        app.active = True
        app.practice.set(False)
        app.mode_badge_enabled.set(True)
        badge = Mock()
        with patch("head_mouse.MacModeBadge", return_value=badge), patch("sys.platform", "darwin"):
            app.update_mode_indicator()
        self.assertEqual(badge.show.call_args.args, ("Click",))
        app.change_mode("Page")
        self.assertEqual(badge.show.call_args.args, ("Scroll",))
        app.mode_badge_enabled.set(False)
        app.update_mode_indicator()
        badge.hide.assert_called()
        app.mode_badge_enabled.set(True)
        app.motion = Mock()
        app.pause()
        self.assertFalse(app.active)
        self.assertEqual(badge.hide.call_count, 2)

    def test_practice_colour_changes_without_creating_native_badge(self):
        app = fixtures.CalibrationTests().app()
        app.mode_badge_enabled.set(True)
        with patch("head_mouse.MacModeBadge") as factory:
            app.change_mode("Drag")
        factory.assert_not_called()
        app.canvas.itemconfigure.assert_any_call("crosshair", fill=MODE_STYLE["Drag"][0])

    def test_badge_failure_does_not_stop_mouse_control_or_retry_every_poll(self):
        app = fixtures.CalibrationTests().app()
        app.active = True
        app.practice.set(False)
        app.mode_badge_enabled.set(True)
        with patch("sys.platform", "darwin"), patch("head_mouse.MacModeBadge", side_effect=RuntimeError("unavailable")) as factory:
            app.update_mode_indicator()
            app.update_mode_indicator()
        factory.assert_called_once()
        self.assertTrue(app.active)
        self.assertTrue(app.badge_failed)

    def test_dwell_progress_reaches_icon_and_resets_when_waiting_for_movement(self):
        app = fixtures.CalibrationTests().app()
        app.active = True
        app.practice.set(False)
        app.mode_badge_enabled.set(True)
        app.mode_badge = Mock()
        app.dwell_enabled.set(True)
        app.dwell.waiting_for_movement = False
        app.dwell.progress = .6
        app.update_mode_indicator()
        self.assertEqual(app.mode_badge.show.call_args.kwargs["progress"], .6)
        self.assertTrue(app.mode_badge.show.call_args.kwargs["dwell"])
        app.dwell.waiting_for_movement = True
        app.update_mode_indicator()
        self.assertEqual(app.mode_badge.show.call_args.kwargs["progress"], 0)
        app.click_method.set("Sound")
        app.update_mode_indicator()
        self.assertFalse(app.mode_badge.show.call_args.kwargs["dwell"])

    def test_icon_shapes_timer_bounds_and_recenter_state(self):
        self.assertEqual(icon_state("Click")[1], "mouse-pointer-click")
        self.assertEqual(icon_state("Drag")[1], "hand")
        self.assertEqual(icon_state("Drag", dragging=True)[1], "move")
        self.assertEqual(icon_state("Scroll")[1], "move-vertical")
        self.assertEqual(icon_state("Click", progress=2, dwell=True)[2], 1)
        self.assertEqual(icon_state("Click", progress=float("nan"), dwell=True)[2], 0)
        self.assertEqual(icon_state("Click", progress=.8, dwell=True, recentering=True)[1:4], ("crosshair", 0, False))

    def test_reveal_edges_hide_icon_on_all_monitor_positions(self):
        for sx, sy, w, h in ((0, 0, 1470, 956), (-1920, -200, 1920, 1080)):
            screen = (sx, sy, w, h)
            for point in ((sx+1, sy+h/2), (sx+w-1, sy+h/2), (sx+w/2, sy+1), (sx+w/2, sy+h-1)):
                self.assertTrue(at_reveal_edge(point, screen))
            self.assertFalse(at_reveal_edge((sx+w/2, sy+h/2), screen))

    def test_matching_artwork_has_offline_retina_representations(self):
        folder = Path(__file__).resolve().parent / "assets" / "lucide"
        for name in ("mouse-pointer-click", "hand", "move", "move-vertical", "crosshair"):
            self.assertTrue((folder / (name+".svg")).exists())
            for scale in (1, 2, 3):
                data = (folder / f"{name}@{scale}x.png").read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", data[16:24]), (17*scale, 17*scale))
        self.assertTrue((folder / "LICENSE").exists())


if __name__ == "__main__":
    unittest.main()
