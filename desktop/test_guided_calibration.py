"""Real sample validation, automatic transitions and cancellation guarantees."""
import unittest
from unittest.mock import Mock, patch

from guided_calibration import GuidedCalibration, RIGHT_NOTE, SUCCESS_NOTE
from motion import Sample, PointerMotion
import test_head_mouse as fixtures


def capture(flow, start, rate=(0,0,0), duration=3.02):
    for i in range(round(duration*100)+1):
        now=start+i*.01
        flow.collect(Sample(round(now*1_000_000),(0,0,1),rate),now)


def successful_flow():
    flow=GuidedCalibration(0)
    flow.tick(3)
    capture(flow,6,duration=2.02)
    capture(flow,11.02,(2.5,0,0))
    capture(flow,17.04,(0,2.5,0))
    return flow


class GuidedCalibrationTests(unittest.TestCase):
    def test_prompts_countdown_and_successful_auto_advance(self):
        flow=GuidedCalibration(0)
        self.assertEqual(flow.snapshot(0)['title'],'Look here')
        flow.tick(2.99)
        self.assertEqual(flow.phase,'look')
        flow.tick(3)
        self.assertEqual(flow.snapshot(3)['title'],'Hold still in 3')
        self.assertEqual(flow.snapshot(4)['title'],'Hold still in 2')
        self.assertEqual(flow.snapshot(5)['title'],'Hold still in 1')
        capture(flow,6,duration=2.02)
        self.assertEqual((flow.phase,flow.step),('countdown','right'))
        self.assertEqual(flow.snapshot(8.02)['note'],RIGHT_NOTE)
        capture(flow,11.02,(2.5,0,0))
        self.assertEqual((flow.phase,flow.step),('countdown','down'))
        self.assertIn('Return to centre',flow.snapshot(14.04)['title'])
        capture(flow,17.04,(0,2.5,0))
        self.assertEqual(flow.phase,'done')
        self.assertEqual(flow.snapshot(21)['title'],'Calibrated.')
        self.assertEqual(flow.snapshot(21)['note'],SUCCESS_NOTE)
        self.assertEqual(flow.result,((0,0,0),(1,0,0),(0,1,0)))

    def test_time_alone_never_calibrates_without_samples(self):
        flow=GuidedCalibration(0)
        flow.tick(3)
        flow.tick(6)
        flow.tick(8.1)
        self.assertEqual(flow.phase,'capture')
        self.assertIsNone(flow.result)
        flow.tick(22)
        self.assertEqual(flow.phase,'error')

    def test_unsteady_zero_extends_and_then_recovers_automatically(self):
        flow=GuidedCalibration(0)
        flow.tick(3)
        for i in range(250):
            t=6+i*.01
            flow.collect(Sample(round(t*1e6),(0,0,1),(5 if i%2 else -5,0,0)),t)
        self.assertEqual((flow.phase,flow.step),('capture','zero'))
        self.assertIsNone(flow.result)
        capture(flow,8.5,duration=2.2)
        self.assertEqual((flow.phase,flow.step),('countdown','right'))

    def test_missing_movement_requires_retry_and_does_not_advance(self):
        flow=GuidedCalibration(0)
        flow.tick(3)
        capture(flow,6,duration=2.02)
        capture(flow,11.02)
        self.assertEqual((flow.phase,flow.step),('error','right'))
        flow.retry(15)
        self.assertEqual(flow.snapshot(15)['title'],'Prepare to move your head right in 3')
        capture(flow,18,(2.5,0,0))
        self.assertEqual(flow.step,'down')

    def test_same_direction_nod_rejected_and_interruption_restarts_everything(self):
        flow=GuidedCalibration(0)
        flow.tick(3)
        capture(flow,6,duration=2.02)
        capture(flow,11.02,(2.5,0,0))
        capture(flow,17.04,(2.5,0,0))
        self.assertEqual(flow.phase,'error')
        self.assertIsNone(flow.result)
        flow.fail('Device disconnected',restart=True)
        flow.retry(30)
        self.assertEqual((flow.phase,flow.step),('look','zero'))
        self.assertIsNone(flow.bias)

    def test_old_mounting_preserved_on_cancel_and_control_never_starts(self):
        app=fixtures.CalibrationTests().app()
        app.bias=(.2,.3,.4)
        app.right,app.down=(1,0,0),(0,1,0)
        app.motion=PointerMotion(app.bias,app.right,app.down)
        old_motion=app.motion
        with patch('head_mouse.time.monotonic',return_value=1.1):
            app.start_guided()
        app.toggle_computer()
        app.toggle_pointer()
        self.assertFalse(app.active)
        self.assertIs(app.motion,old_motion)
        app.dismiss_guided()
        self.assertEqual(app.bias,(.2,.3,.4))
        self.assertIs(app.motion,old_motion)
        app.save_preferences.assert_not_called()

    def test_success_commits_once_and_does_not_enable_pointer(self):
        app=fixtures.CalibrationTests().app()
        app.guided=successful_flow()
        app.finish_guided(21)
        app.finish_guided(22)
        self.assertEqual(app.right,(1,0,0))
        self.assertEqual(app.down,(0,1,0))
        self.assertIsNotNone(app.motion)
        self.assertFalse(app.active)
        app.save_preferences.assert_called_once()
