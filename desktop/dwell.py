"""Movement-to-arm dwell detection using monotonic time and pointer coordinates."""
import math


class DwellClick:
    def __init__(self, seconds=1.0, radius=8.0, rearm_distance=16.0):
        self.seconds = seconds
        self.radius = radius
        self.rearm_distance = rearm_distance
        self.reset()

    def reset(self):
        self.anchor = None
        self.started_at = None
        self.last_update = None
        self.waiting_for_movement = True
        self.progress = 0.0

    def arm(self):
        """A confirmed gesture already supplies the movement needed to arm."""
        self.reset()
        self.waiting_for_movement = False

    def suspend(self, position, now):
        """Cancel timing during a confirmed gesture, keeping dwell armed."""
        self.arm()
        self.anchor = tuple(position)
        self.started_at = self.last_update = now

    def update(self, position, now):
        if self.last_update is not None and not 0 <= now - self.last_update <= .25:
            self.reset()
        self.last_update = now
        if self.anchor is None:
            self.anchor = tuple(position)
            if not self.waiting_for_movement:
                self.started_at = now
            return False

        distance = math.dist(position, self.anchor)
        if self.waiting_for_movement:
            self.progress = 0.0
            if distance >= self.rearm_distance:
                self.waiting_for_movement = False
                self.anchor = tuple(position)
                self.started_at = now
            return False

        if distance > self.radius:
            self.anchor = tuple(position)
            self.started_at = now
            self.progress = 0.0
            return False

        self.progress = min(1.0, (now - self.started_at) / self.seconds)
        if self.progress < 1.0:
            return False

        self.anchor = tuple(position)
        self.started_at = None
        self.waiting_for_movement = True
        return True
