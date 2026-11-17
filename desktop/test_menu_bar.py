"""Menu commands share the existing app state without posting mouse events."""
import queue
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from menu_bar import ready_for_control, set_tuning, set_transport, RemoteApp
from menu_bridge import MenuBarBridge
from preferences import save_profile, load_profile
import test_head_mouse as fixtures


class MenuBarTests(unittest.TestCase):
    def app(self):
        app = fixtures.CalibrationTests().app()
        app.root = Mock()
        app.scanning = False
        return app

    def bridge(self, app):
        bridge = MenuBarBridge.__new__(MenuBarBridge)
        bridge.app = app
        bridge.pending = queue.Queue()
        return bridge

    def test_control_requires_calibration_and_fresh_stream(self):
        app = self.app()
        self.assertFalse(ready_for_control(app))
        app.motion = Mock()
        self.assertTrue(ready_for_control(app))
        app.capture = ('zero', 0, [])
        self.assertFalse(ready_for_control(app))
        app.capture = None
        app.recentering = {'resume': True}
        self.assertFalse(ready_for_control(app))

    def test_remote_boolean_flags_do_not_enable_uncalibrated_control(self):
        app = RemoteApp()
        app.state = {'motion':False, 'last_rx':1, 'capture':False, 'recentring':False}
        self.assertFalse(ready_for_control(app))
        app.state['motion'] = True
        self.assertTrue(ready_for_control(app))
        app.state['capture'] = True
        self.assertFalse(ready_for_control(app))

    def test_pointer_settings_use_same_variables_and_enforce_ranges(self):
        app = self.app()
        for name, value in [('gain', 34.2), ('deadzone', 1.1), ('sensitivity', 2.3)]:
            set_tuning(app, name, value)
            self.assertEqual(getattr(app, name).get(), value)
        for value in (0, 6, float('nan')):
            with self.assertRaises(ValueError):
                set_tuning(app, 'deadzone', value)

    def test_transport_change_uses_existing_disconnect_and_discovery_path(self):
        app = self.app()
        app.select_transport = Mock()
        app.auto_connect = True
        set_transport(app, 'Bluetooth')
        self.assertEqual(app.transport.get(), 'Bluetooth')
        self.assertFalse(app.auto_connect)
        app.select_transport.assert_called_once()
        app.save_preferences.assert_called_once()
        set_transport(app, 'Bluetooth')
        app.select_transport.assert_called_once()

    def test_mode_and_click_commands_reset_existing_detectors(self):
        app = self.app()
        bridge = self.bridge(app)
        app.change_mode_set = Mock()
        app.change_click_method = Mock()
        for name, value, command in [('mode_set', 'Mode 2', 'change_mode_set'), ('click_method', 'Sound', 'change_click_method')]:
            bridge.apply({'action':'set_variable', 'args':[name, value]})
            bridge.apply({'action':command})
            self.assertEqual(getattr(app, name).get(), value)
            getattr(app, command).assert_called_once()
        with self.assertRaises(ValueError):
            bridge.apply({'action':'set_variable', 'args':['transport', 'Wifi']})

    def test_command_failure_pauses_instead_of_escaping_poll(self):
        app = self.app()
        app.pause = Mock()
        bridge = self.bridge(app)
        bridge.pending.put({'action':'not a command'})
        bridge.process_actions()
        app.pause.assert_called_once()
        self.assertIn('Menu action failed', app.notice.get())

    def test_helper_failure_pauses_and_reopens_full_setup(self):
        app = self.app()
        app.pause = Mock()
        bridge = self.bridge(app)
        app.menu_bar = bridge
        bridge.close = Mock()
        bridge.apply({'error':'Menu helper stopped'})
        app.pause.assert_called_once()
        bridge.close.assert_called_once()
        self.assertIsNone(app.menu_bar)
        app.root.deiconify.assert_called_once()

    def test_latest_snapshot_replaces_blocked_writer_without_blocking_pointer(self):
        bridge = self.bridge(self.app())
        bridge.outgoing = queue.Queue(maxsize=1)
        bridge.send({'state':'old'})
        bridge.send({'state':'new'})
        self.assertEqual(bridge.outgoing.get_nowait(), {'state':'new'})

    def test_settings_remember_transport_without_losing_calibration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profile.json'
            save_profile(22, .8, [1,0,0], [0,1,0], path, transport='Bluetooth', mode_set='Mode 2')
            profile = load_profile(path)
            self.assertEqual(profile['transport'], 'Bluetooth')
            self.assertEqual(profile['right'], [1,0,0])
