"""Gravity-referenced tilt-to-scroll with gyro smoothing and a neutral zone."""
import math
from motion import dot, seconds


def unit(vector):
    length = math.hypot(*vector)
    return tuple(v / length for v in vector) if length > 1e-6 else None


class TiltScroll:
    def reset(self):
        self.reference = self.previous = None
        self.angle = self.remainder = 0.0

    def __init__(self):
        self.reset()

    def update(self, sample, bias, down_axis, sensitivity=1.0):
        axis = unit(down_axis)
        gravity = unit(sample.accel)
        dt = seconds(self.previous, sample) if self.previous else 0
        self.previous = sample
        if axis is None or gravity is None:
            return 0
        if self.reference is None or not 0 < dt <= .06:
            self.reference = gravity
            self.angle = self.remainder = 0.0
            return 0
        rate = dot(tuple(v-b for v, b in zip(sample.gyro, bias)), down_axis)
        self.angle += rate * dt
        if .85 <= math.hypot(*sample.accel) <= 1.15:
            # Project gravity onto the plane normal to the calibrated nod axis.
            p0 = tuple(g-dot(self.reference, axis)*a for g, a in zip(self.reference, axis))
            p = tuple(g-dot(gravity, axis)*a for g, a in zip(gravity, axis))
            if math.hypot(*p0) > .2 and math.hypot(*p) > .2:
                cross = (p[1]*p0[2]-p[2]*p0[1], p[2]*p0[0]-p[0]*p0[2], p[0]*p0[1]-p[1]*p0[0])
                absolute = math.degrees(math.atan2(dot(cross, axis), dot(p, p0)))
                alpha = 1 - math.exp(-dt / .4)
                self.angle += alpha * (absolute-self.angle)
        self.angle = max(-35, min(35, self.angle))
        speed = math.copysign(max(0, abs(self.angle)-2.0), self.angle) * 4 * sensitivity
        speed = max(-50, min(50, speed))
        if speed == 0:
            self.remainder = 0
            return 0
        self.remainder -= speed * dt  # Negative mouse wheel is down.
        steps = math.trunc(self.remainder)
        self.remainder -= steps
        return steps
