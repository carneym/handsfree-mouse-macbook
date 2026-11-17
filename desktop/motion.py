"""USB sample decoding, calibration, and relative pointer motion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, pstdev

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Sample:
    timestamp: int
    accel: Vec
    gyro: Vec


def decode(line: bytes) -> Sample | None:
    parts = line.split(b",")
    if len(parts) != 8 or parts[0] != b"HM1":
        return None
    try:
        timestamp, *counts = map(int, parts[1:])
    except ValueError:
        return None
    if not 0 <= timestamp < 2**32 or any(not -32768 <= n <= 32767 for n in counts):
        return None
    ax, ay, az, gx, gy, gz = counts
    return Sample(timestamp, (ax / 16384, ay / 16384, az / 16384),
                  (gx / 131, gy / 131, gz / 131))


def seconds(previous: Sample, current: Sample) -> float:
    return ((current.timestamp - previous.timestamp) & 0xFFFFFFFF) / 1_000_000


def zero_gyro(samples: list[Sample]) -> Vec:
    if (len(samples) < 60 or seconds(samples[0], samples[-1]) < 1.9
            or any(not 0 < seconds(a, b) <= .06 for a, b in zip(samples, samples[1:]))
            or any(not math.isfinite(v) for s in samples for v in (*s.accel, *s.gyro))):
        raise ValueError("Waiting for a continuous steady reading.")
    axes = list(zip(*(sample.gyro for sample in samples)))
    # Trim the outer 10% at each end so a few settling spikes do not pull
    # the zero away from the quiet majority. Validate motion using ALL samples.
    trim = max(1, len(samples) // 10)
    bias = tuple(mean(sorted(axis)[trim:-trim]) for axis in axes)
    gravity = [math.hypot(*sample.accel) for sample in samples]
    half = len(samples) // 2
    if (math.hypot(*bias) > 12 or any(pstdev(axis) > 1.2 for axis in axes)
            or any(abs(mean(axis[:half]) - mean(axis[half:])) > .6 for axis in axes)
            or not 0.8 < mean(gravity) < 1.2 or pstdev(gravity) > 0.04
            or any(pstdev(axis) > .025 for axis in zip(*(s.accel for s in samples)))):
        raise ValueError("The sensor moved during zeroing. Hold still and try again.")
    return bias


def gesture_axis(samples: list[Sample], bias: Vec) -> Vec:
    rotation = [0.0, 0.0, 0.0]
    for previous, current in zip(samples, samples[1:]):
        dt = seconds(previous, current)
        for axis in range(3):
            rate = (previous.gyro[axis] + current.gyro[axis]) / 2 - bias[axis]
            rotation[axis] += rate * dt
    angle = math.hypot(*rotation)
    if not 3 <= angle <= 55:
        raise ValueError("Use one small turn, about 10–20°, and hold until capture ends.")
    return tuple(value / angle for value in rotation)


def dot(a: Vec, b: Vec) -> float:
    return sum(x * y for x, y in zip(a, b))


def screen_axes(right: Vec, down: Vec) -> tuple[Vec, Vec]:
    # Solve for coefficients in the two measured directions, even if
    # they are slightly skewed. Each gesture should drive only one axis.
    overlap = dot(right, down)
    if abs(overlap) > 0.75:
        raise ValueError("Right and down were too similar. Repeat the down gesture.")
    scale = 1 - overlap * overlap
    return (
        tuple((r - overlap * d) / scale for r, d in zip(right, down)),
        tuple((d - overlap * r) / scale for r, d in zip(right, down)),
    )


class PointerMotion:
    def __init__(self, bias: Vec, right: Vec, down: Vec):
        self.bias = bias
        self.axes = screen_axes(right, down)
        self.reset()

    def reset(self):
        self.previous = None
        self.filtered = [0.0, 0.0]
        self.remainder = [0.0, 0.0]

    def update(self, sample: Sample, gain: float, deadzone: float) -> tuple[int, int]:
        dt = seconds(self.previous, sample) if self.previous else 0
        if not 0 < dt <= 0.06:
            self.reset()
            self.previous = sample
            return 0, 0
        self.previous = sample
        rate = tuple(value - zero for value, zero in zip(sample.gyro, self.bias))
        alpha = 1 - math.exp(-dt / 0.035)
        delta = []
        for axis, direction in enumerate(self.axes):
            speed = dot(rate, direction)
            self.filtered[axis] += alpha * (speed - self.filtered[axis])
            speed = self.filtered[axis]
            speed = math.copysign(max(0, abs(speed) - deadzone), speed)
            speed = min(180, max(-180, speed))
            distance = speed * gain * dt + self.remainder[axis]
            whole = math.trunc(distance)
            self.remainder[axis] = distance - whole
            delta.append(whole)
        return tuple(delta)
