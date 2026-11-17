"""Freshness and background USB reading regressions, using virtual serial I/O."""
import threading
import time
import unittest
from unittest.mock import Mock

import serial

from motion import PointerMotion, Sample
from serial_feed import SerialFeed
import test_head_mouse as fixtures


def row(index):
    return f"HM1,{index*10000},0,0,16384,1310,0,0\n".encode()


class SerialFeedTests(unittest.TestCase):
    def setUp(self):
        self.port = serial.serial_for_url("loop://", timeout=.05)
        self.feed = SerialFeed(self.port)

    def tearDown(self):
        self.feed.close()
        self.port.close()
        self.assertFalse(self.feed.thread.is_alive())

    def wait_events(self, count):
        result = []
        deadline = time.monotonic() + 1
        while len(result) < count and time.monotonic() < deadline:
            events, _, failure = self.feed.drain()
            self.assertIsNone(failure)
            result.extend(events)
            time.sleep(.005)
        self.assertEqual(len(result), count)
        return result

    def test_partial_lines_and_status_are_decoded(self):
        self.port.write(row(1)[:10])
        time.sleep(.02)
        self.port.write(row(1)[10:] + b"# HM1,device ready\n" + row(2))
        events = self.wait_events(3)
        self.assertEqual(events[0][1].timestamp, 10000)
        self.assertEqual(events[1][1], "HM1,device ready")
        self.assertEqual(events[2][1].timestamp, 20000)

    def test_reader_keeps_receiving_while_gui_is_blocked(self):
        def produce():
            for i in range(30):
                self.port.write(row(i))
                time.sleep(.01)
        producer = threading.Thread(target=produce)
        producer.start()
        try:
            # Represents an OS or GUI call holding the application callback.
            time.sleep(.2)
            events, _, failure = self.feed.drain()
            self.assertIsNone(failure)
            self.assertGreaterEqual(len(events), 10)
            self.assertLess(time.monotonic() - events[-1][0], .08)
        finally:
            producer.join()

    def test_queue_is_bounded_and_reports_dropped_history(self):
        for i in range(300):
            self.feed.publish(Sample(i, (0, 0, 1), (0, 0, 0)))
        events, dropped, failure = self.feed.drain()
        self.assertEqual(len(events), 256)
        self.assertEqual(dropped, 44)
        self.assertEqual(events[-1][1].timestamp, 299)
        self.assertIsNone(failure)

    def test_serial_failure_reaches_the_gui(self):
        self.port.close()
        deadline = time.monotonic() + 1
        failure = None
        while not failure and time.monotonic() < deadline:
            _, _, failure = self.feed.drain()
            time.sleep(.005)
        self.assertIsNotNone(failure)


class FreshnessTests(unittest.TestCase):
    def app(self):
        app = fixtures.CalibrationTests().app()
        app.active = True
        app.practice.set(False)
        app.motion = PointerMotion((0, 0, 0), (1, 0, 0), (0, 1, 0))
        app.mouse = Mock()
        app.connection_status = fixtures.Value()
        app.telemetry = fixtures.Value()
        return app

    def test_delayed_gui_with_fresh_usb_data_keeps_computer_control_on(self):
        app = self.app()
        events = [(1.1, Sample(110000, (0, 0, 1), (10, 0, 0)))]
        events += [(2 - .01 * (3-i), Sample(200000+i*10000, (0, 0, 1), (10, 0, 0)))
                   for i in range(4)]
        app.feed.drain.return_value = (events, 0, None)
        app.read_stream(2)
        self.assertTrue(app.active)
        self.assertFalse(app.practice.get())
        self.assertEqual(app.last_rx, 2)
        app.mouse.move.assert_called_once()
        self.assertLess(abs(app.mouse.move.call_args.args[0]), 20)

    def test_a_buffered_device_restart_still_pauses_computer_control(self):
        app = self.app()
        app.feed.drain.return_value = (
            [(1.1, "HM1,device restarted"), (2, Sample(10000, (0, 0, 1), (10, 0, 0)))],
            0, None)
        app.read_stream(2)
        self.assertFalse(app.active)
        app.mouse.move.assert_not_called()

    def test_stale_buffer_stops_control(self):
        app = self.app()
        app.feed.drain.return_value = ([(1.2, Sample(120000, (0, 0, 1), (10, 0, 0)))], 0, None)
        app.read_stream(2)
        self.assertFalse(app.active)
        app.mouse.move.assert_not_called()

    def test_a_delayed_capture_is_cancelled_without_affecting_saved_axes(self):
        app = self.app()
        app.active = False
        app.right = (1, 0, 0)
        app.down = (0, 1, 0)
        app.capture = ("zero", 0, [])
        events = [(1.1, Sample(110000, (0, 0, 1), (0, 0, 0))),
                  (2, Sample(200000, (0, 0, 1), (0, 0, 0)))]
        app.feed.drain.return_value = (events, 0, None)
        app.read_stream(2)
        self.assertIsNone(app.capture)
        self.assertEqual(app.right, (1, 0, 0))
        self.assertFalse(app.active)


if __name__ == "__main__":
    unittest.main()
