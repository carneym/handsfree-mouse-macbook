"""Native event payloads are tested without moving the computer pointer."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from macos_pointer import constrain_to_displays, post_motion


class PointerEventTests(unittest.TestCase):
    def quartz(self):
        q = SimpleNamespace(kCGEventMouseMoved=5, kCGMouseEventDeltaX=4,
                            kCGMouseEventDeltaY=5, kCGHIDEventTap=0)
        q.CGEventCreateMouseEvent = Mock(return_value={})
        q.CGEventSetIntegerValueField = Mock()
        q.CGEventPost = Mock()
        return q

    def test_push_against_bottom_edge_carries_downward_motion(self):
        q = self.quartz()
        post_motion(q, "hid-source", (700, 955), (700, 959), displays=[(0, 0, 1470, 956)])
        q.CGEventCreateMouseEvent.assert_called_once_with("hid-source", 5, (700, 955), 0)
        q.CGEventSetIntegerValueField.assert_any_call({}, q.kCGMouseEventDeltaX, 0)
        q.CGEventSetIntegerValueField.assert_any_call({}, q.kCGMouseEventDeltaY, 4)
        q.CGEventPost.assert_called_once_with(q.kCGHIDEventTap, {})

    def test_drag_type_and_negative_monitor_coordinates_are_preserved(self):
        q = self.quartz()
        button = SimpleNamespace(value=((1, 2, 6), 0))
        post_motion(q, "source", (-120, -30), (-125, -35), button)
        q.CGEventCreateMouseEvent.assert_called_once_with("source", 6, (-125, -35), 0)
        q.CGEventSetIntegerValueField.assert_any_call({}, q.kCGMouseEventDeltaX, -5)
        q.CGEventSetIntegerValueField.assert_any_call({}, q.kCGMouseEventDeltaY, -5)

    def test_adjacent_display_is_reachable_without_clamping_to_main(self):
        displays = [(0, 0, 1470, 956), (-1920, -200, 1920, 1080)]
        self.assertEqual(constrain_to_displays((-5, 200), displays), (-5, 200))
        self.assertEqual(constrain_to_displays((-1930, -210), displays), (-1920, -200))

    def test_gap_uses_nearest_display_and_valid_fractional_position_is_kept(self):
        displays = [(0, 0, 100, 100), (200, 0, 100, 100)]
        self.assertEqual(constrain_to_displays((170, 50), displays), (200, 50))
        self.assertEqual(constrain_to_displays((22.5, 98.5), displays), (22.5, 98.5))


if __name__ == "__main__":
    unittest.main()
