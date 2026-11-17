"""Automatic calibration: timed prompts, sensor-validated captures, atomic result."""
import math
from motion import zero_gyro, gesture_axis, PointerMotion, seconds

RIGHT_NOTE = 'Only move 5–10 degrees so that your head points towards the edge of the screen.'
SUCCESS_NOTE = 'Click "Turn on computer control" to begin using mouse.'


class GuidedCalibration:
    def __init__(self, now):
        self.phase = 'look'
        self.step = 'zero'
        self.started = now
        self.samples = []
        self.bias = self.right = self.result = None
        self.error = ''
        self.restart_required = False
        self.applied = False
        self.progress = 0

    @property
    def running(self):
        return self.phase in ('look', 'countdown', 'capture')

    def countdown(self, now, step):
        self.phase, self.step, self.started = 'countdown', step, now
        self.samples = []
        self.progress = 0
        self.error = ''

    def tick(self, now):
        if self.phase == 'look' and now - self.started >= 3:
            self.countdown(now, 'zero')
        elif self.phase == 'countdown' and now - self.started >= 3:
            self.phase, self.started = 'capture', now
            self.samples = []
        elif self.phase == 'capture' and now - self.started > 15:
            self.fail('Could not capture a steady reading. Let your head settle, then retry.')

    def collect(self, sample, now):
        self.tick(now)
        if self.phase != 'capture':
            return
        if self.samples and not 0 < seconds(self.samples[-1], sample) <= .06:
            self.fail('Readings were interrupted. Check the connection, then restart.', restart=True)
            return
        self.samples.append(sample)
        if self.step == 'zero':
            while len(self.samples) > 2 and seconds(self.samples[1], sample) >= 2:
                self.samples.pop(0)
        duration = 2 if self.step == 'zero' else 3
        elapsed = seconds(self.samples[0], sample)
        self.progress = min(1, elapsed / duration)
        if elapsed < duration:
            return
        try:
            if self.step == 'zero':
                self.bias = zero_gyro(self.samples)
                self.countdown(now, 'right')
            elif self.step == 'right':
                self.right = gesture_axis(self.samples, self.bias)
                self.countdown(now, 'down')
            else:
                down = gesture_axis(self.samples, self.bias)
                # Validate both directions before exposing any replacement calibration.
                PointerMotion(self.bias, self.right, down)
                self.result = (self.bias, self.right, down)
                self.phase = 'done'
                self.progress = 1
        except ValueError as error:
            if self.step == 'zero':
                # A settling twitch simply extends the capture; it never advances.
                self.error = 'Let your head settle · checking automatically…'
                self.progress = 0
            else:
                self.fail('Use one small 5–10° movement and hold until the bar finishes. '
                          if 'small turn' in str(error) else str(error))

    def fail(self, message, restart=False):
        self.phase, self.error = 'error', message
        self.restart_required = restart
        self.samples = []
        self.progress = 0

    def retry(self, now):
        if self.restart_required:
            self.__init__(now)
        else:
            self.countdown(now, self.step)

    def snapshot(self, now):
        note = RIGHT_NOTE if self.step == 'right' else ''
        title = 'Look here'
        step_title = {'zero':'1 of 3 · Stillness', 'right':'2 of 3 · Turn right',
                      'down':'3 of 3 · Nod down'}[self.step]
        if self.phase == 'countdown':
            count = max(1, 3 - int(now - self.started))
            title = {'zero':'Hold still in ', 'right':'Prepare to move your head right in ',
                     'down':'Return to centre, prepare to nod head down in '}[self.step] + str(count)
        elif self.phase == 'capture':
            title = {'zero':'Hold', 'right':'Move your head right →',
                     'down':'Nod head down towards bottom of screen'}[self.step]
            if self.step == 'zero' and self.error:
                note = self.error
        elif self.phase == 'done':
            title, note = 'Calibrated.', SUCCESS_NOTE
        elif self.phase == 'error':
            title, note = 'Calibration paused', self.error
        return dict(phase=self.phase, title=title, note=note, progress=self.progress,
                    step='' if self.phase in ('look','done') else step_title,
                    restart=self.restart_required)
