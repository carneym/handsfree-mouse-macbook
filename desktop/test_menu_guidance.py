"""Connection cues, post-calibration activation, and the faster scroll rate."""
import math
import unittest
from unittest.mock import Mock, patch
from guided_calibration import GuidedCalibration
from menu_bar import connection_tab, calibration_needed
from motion import Sample
from scroll_motion import TiltScroll
import test_head_mouse as fixtures


class MenuGuidanceTests(unittest.TestCase):
    def test_disconnection_and_reopening_choose_settings(self):
        self.assertEqual(connection_tab('Controls',None,False),'Settings')
        self.assertEqual(connection_tab('Controls',True,False),'Settings')
        self.assertEqual(connection_tab('Controls',False,False,opening=True),'Settings')
        self.assertEqual(connection_tab('Settings',False,True),'Controls')
        self.assertEqual(connection_tab('Settings',True,True),'Settings')
        # Users can still inspect Controls after the automatic navigation.
        self.assertEqual(connection_tab('Controls',False,False),'Controls')

    def test_calibration_hint_requires_connection_and_clears_after_zero(self):
        app=fixtures.CalibrationTests().app()
        app.feed=None
        self.assertFalse(calibration_needed(app))
        app.feed=Mock()
        self.assertTrue(calibration_needed(app))
        app.motion=Mock()
        self.assertFalse(calibration_needed(app))

    def test_finish_button_only_starts_after_success_and_fresh_readings(self):
        app=fixtures.CalibrationTests().app()
        app.toggle_computer=Mock()
        app.guided=GuidedCalibration(100)
        app.start_guided_control()
        app.toggle_computer.assert_not_called()
        app.guided.phase='done'
        app.guided.applied=True
        app.last_rx=100
        with patch('head_mouse.time.monotonic',return_value=101):
            app.start_guided_control()
        app.toggle_computer.assert_not_called()
        self.assertIsNotNone(app.guided)
        with patch('head_mouse.time.monotonic',return_value=100.1):
            app.start_guided_control()
        app.toggle_computer.assert_called_once()
        self.assertIsNone(app.guided)

    def test_eight_degree_held_nod_scrolls_twice_previous_rate_and_is_capped(self):
        for angle, sensitivity, expected in [(8,1,24),(20,3,50)]:
            with self.subTest(angle=angle):
                scroll=TiltScroll()
                steps=[]
                for i in range(401):
                    t=i/100
                    a=min(t,1)*angle
                    r=math.radians(a)
                    sample=Sample(i*10000,(-math.sin(r),0,math.cos(r)),(0,angle if t<1 else 0,0))
                    steps.append(scroll.update(sample,(0,0,0),(0,1,0),sensitivity))
                self.assertAlmostEqual(-sum(steps[300:400]),expected,delta=1)
