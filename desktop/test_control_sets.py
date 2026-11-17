"""Control sets must dispatch the correct buttons and keep dwell one-shot."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import test_head_mouse as fixtures
from motion import PointerMotion, Sample
from preferences import load_profile, save_profile
from mode_indicator import icon_state


class ControlSetTests(unittest.TestCase):
    def app(self):
        app = fixtures.CalibrationTests().app()
        app.active = True
        app.practice.set(False)
        from unittest.mock import Mock
        app.mouse = Mock()
        return app

    def test_mode_two_cycles_and_recenter_remains_independent(self):
        app = self.app()
        app.mode_set.set('Mode 2')
        app.gestures_enabled.set(True)
        app.motion = PointerMotion((0, 0, 0), (1, 0, 0), (0, 1, 0))
        with patch.object(app.gestures, 'update', return_value='Cycle modes'):
            for expected in ('Double click', 'Right click', 'Click'):
                app.check_gesture(None, Sample(0, (0, 0, 1), (0, 0, 0)))
                self.assertEqual(app.action_mode.get(), expected)
        app.change_mode('Scroll')
        self.assertEqual(app.action_mode.get(), 'Click')

    def test_switch_set_releases_drag_and_clears_pending_dwell(self):
        app = self.app()
        app.dragging = True
        app.drag_mouse = app.mouse
        app.action_mode.set('Drag')
        app.dwell.progress = .9
        app.mode_set.set('Mode 2')
        with patch.dict(sys.modules, {'pynput.mouse': SimpleNamespace(Button=SimpleNamespace(left='left'))}):
            app.change_mode_set()
        app.mouse.release.assert_called_once_with('left')
        self.assertFalse(app.dragging)
        self.assertEqual(app.action_mode.get(), 'Click')
        self.assertEqual(app.dwell.progress, 0)
        app.mode_picker.configure.assert_called_with(values=('Click', 'Double click', 'Right click'))
        app.save_preferences.assert_called_once()

    def test_dwell_dispatches_one_action_and_requires_movement_to_repeat(self):
        for mode, args in [('Double click', ('left', 2)), ('Right click', ('right',))]:
            with self.subTest(mode=mode):
                app = self.app()
                app.mode_set.set('Mode 2')
                app.action_mode.set(mode)
                app.dwell_enabled.set(True)
                app.mouse.position = (0, 0)
                with patch.dict(sys.modules, {'pynput.mouse': SimpleNamespace(Button=SimpleNamespace(left='left', right='right'))}):
                    app.update_dwell(0)
                    app.mouse.position = (30, 0)
                    for i in range(1, 40):
                        app.update_dwell(i / 10)
                app.mouse.click.assert_called_once_with(*args)
                app.mouse.press.assert_not_called()
                self.assertTrue(icon_state(mode, progress=.5, dwell=True)[3])

    def test_practice_never_sends_clicks_to_computer(self):
        app = self.app()
        app.practice.set(True)
        for mode in ('Double click', 'Right click'):
            app.action_mode.set(mode)
            app.perform_click()
        self.assertEqual(app.practice_clicks, 2)
        app.mouse.click.assert_not_called()

    def test_set_persists_and_old_profiles_default_to_mode_one(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profile.json'
            save_profile(22, .8, None, None, path, mode_set='Mode 2')
            self.assertEqual(load_profile(path)['mode_set'], 'Mode 2')
            app = self.app()
            with patch('head_mouse.load_profile', return_value=load_profile(path)):
                app.restore_profile()
            self.assertEqual(app.available_modes(), ('Click', 'Double click', 'Right click'))
            with patch('head_mouse.load_profile', return_value={'gain':22, 'deadzone':.8}):
                app.restore_profile()
            self.assertEqual(app.available_modes(), ('Click', 'Drag', 'Scroll'))
