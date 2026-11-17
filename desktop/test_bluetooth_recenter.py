"""BLE packet/transport checks and recenter behavior without real pointer events."""
import asyncio
from collections import deque
import struct
import threading
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from ble_feed import BleFeed, PACKET, CONTROL_UUID, DATA_UUID
from gestures import HeadGestures
from motion import PointerMotion, Sample
import test_head_mouse as fixtures


def feed():
    result = BleFeed.__new__(BleFeed)
    result.events = deque(maxlen=256)
    result.lock = threading.Lock()
    result.dropped = 0
    result.failure = None
    result.last_sequence = None
    result.last_notification = None
    result.ever_streamed = False
    result.stopped = threading.Event()
    return result


def packet(sequence, timestamp=12345):
    return PACKET.pack(1, 0, sequence, timestamp, 0, 0, 16384, 131, -262, 393)


class BluetoothTests(unittest.TestCase):
    def test_packet_units_sequence_wrap_duplicates_and_missing_samples(self):
        f = feed()
        for sequence in (65535, 0, 0, 2):
            f.notification(None, packet(sequence))
        events, dropped, failure = f.drain()
        self.assertEqual(len(events), 3)
        self.assertEqual(dropped, 1)
        self.assertIsNone(failure)
        self.assertEqual(events[-1][1].gyro, (1, -2, 3))
        self.assertEqual(events[-1][1].accel, (0, 0, 1))

    def test_invalid_packet_and_restart_are_not_silent_motion(self):
        f = feed()
        f.notification(None, packet(50))
        f.notification(None, packet(0))
        events, _, _ = f.drain()
        self.assertIsInstance(events[1][1], str)
        f.notification(None, b"invalid")
        self.assertIsNotNone(f.drain()[2])

    def test_encryption_read_precedes_subscription_and_close_stops_stream(self):
        f = feed()
        order = []

        class Client:
            is_connected = True
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                order.append("disconnected")
            async def read_gatt_char(self, uuid):
                order.append(("encrypted-read", uuid))
                return b"\x01"
            async def start_notify(self, uuid, callback):
                order.append(("notify", uuid))
                callback(None, packet(1))
            async def write_gatt_char(self, uuid, data, response):
                order.append(("write", uuid, data, response))
                if data == b"\x01":
                    f.stopped.set()
            async def stop_notify(self, uuid):
                order.append(("stop", uuid))
        factory = Mock(return_value=Client())
        f.device, f.client_factory = SimpleNamespace(address="test-device"), factory
        asyncio.run(f.run())
        factory.assert_called_once_with("test-device", timeout=45, pair=True)
        self.assertEqual(order[0], ("encrypted-read", CONTROL_UUID))
        self.assertEqual(order[1], ("notify", DATA_UUID))
        self.assertIn(("write", CONTROL_UUID, b"\x00", True), order)
        self.assertIn(("stop", DATA_UUID), order)
        self.assertEqual(order[-1], "disconnected")

    def test_closing_during_connection_does_not_subscribe_later(self):
        f = feed()
        class Client:
            async def __aenter__(self):
                f.stopped.set()
                return self
            async def __aexit__(self, *_args):
                pass
            async def read_gatt_char(self, _uuid):
                raise AssertionError("Should not access a closed feed")
        f.device, f.client_factory = "test", lambda *_args, **_kwargs: Client()
        asyncio.run(f.run())

    def test_closing_cancels_a_pending_pairing_read_and_disconnects(self):
        entered = threading.Event()
        disconnected = threading.Event()
        class Client:
            is_connected = True
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                disconnected.set()
            async def read_gatt_char(self, _uuid):
                entered.set()
                await asyncio.Event().wait()
        f = BleFeed("test", client_factory=lambda *_args, **_kwargs: Client())
        self.assertTrue(entered.wait(1))
        f.close()
        f.thread.join(1)
        self.assertFalse(f.thread.is_alive())
        self.assertTrue(disconnected.is_set())


class RecenterTests(unittest.TestCase):
    def app(self):
        app = fixtures.CalibrationTests().app()
        app.pointer_status = fixtures.Value()
        app.active = True
        app.practice.set(False)
        app.motion = PointerMotion((0, 0, 0), (1, 0, 0), (0, 1, 0))
        app.mouse = Mock()
        return app

    def test_recenter_pauses_and_resumes_without_moving_pointer_or_changing_bias(self):
        app = self.app()
        bias = app.motion.bias
        with patch("head_mouse.time.monotonic", return_value=10):
            app.start_recenter()
        self.assertFalse(app.active)
        self.assertEqual(app.recentering, (13, True, False))
        app.last_rx = 13
        with patch("sys.platform", "linux"):
            app.finish_recenter(13)
        self.assertTrue(app.active)
        self.assertFalse(app.practice.get())
        self.assertEqual(app.motion.bias, bias)
        app.mouse.move.assert_not_called()
        app.mouse.click.assert_not_called()

    def test_escape_and_stale_data_cancel_auto_resume(self):
        for cancel in (True, False):
            app = self.app()
            with patch("head_mouse.time.monotonic", return_value=10):
                app.start_recenter()
            if cancel:
                app.pause()
            app.finish_recenter(14)
            self.assertFalse(app.active)
            self.assertIsNone(app.recentering)

    def test_gesture_can_trigger_recenter_without_switching_click_mode(self):
        app = self.app()
        app.gestures = HeadGestures([{"direction": "Left-right", "count": 1, "action": "Recenter"}])
        app.gestures_enabled.set(True)
        previous = Sample(0, (0, 0, 1), (0, 0, 0))
        for i in range(40):
            sample = Sample((i+1)*10000, (0, 0, 1), ((-14 if i < 20 else 14), 0, 0))
            app.check_gesture(previous, sample)
            previous = sample
        self.assertIsNotNone(app.recentering)
        self.assertFalse(app.active)
        self.assertEqual(app.action_mode.get(), "Click")

    def test_starting_while_paused_remains_paused_after_recenter(self):
        app = self.app()
        app.active = False
        app.practice.set(True)
        with patch("head_mouse.time.monotonic", return_value=10):
            app.start_recenter()
        app.last_rx = 13
        app.finish_recenter(13)
        self.assertFalse(app.active)

    def test_bluetooth_data_is_processed_without_a_serial_port(self):
        app = self.app()
        app.port = None
        app.transport.set("Bluetooth")
        app.telemetry = fixtures.Value()
        app.feed.drain.return_value = ([(10, Sample(0, (0, 0, 1), (30, 0, 0))),
                                       (10.01, Sample(10000, (0, 0, 1), (30, 0, 0)))], 0, None)
        app.read_stream(10.01)
        self.assertTrue(app.active)
        app.mouse.move.assert_called_once()

    def test_bluetooth_stream_loss_cancels_recenter_resume(self):
        app = self.app()
        app.connection_status = fixtures.Value()
        app.telemetry = fixtures.Value()
        app.transport.set("Bluetooth")
        with patch("head_mouse.time.monotonic", return_value=10):
            app.start_recenter()
        app.interrupt_stream("Bluetooth disconnected")
        app.finish_recenter(13)
        self.assertFalse(app.active)
        self.assertIsNone(app.recentering)


if __name__ == "__main__":
    unittest.main()
