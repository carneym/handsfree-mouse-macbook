"""Transient sound detection from envelope features, never recorded audio."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SoundFrame:
    timestamp: int
    peak: int
    rms: int
    high: int
    samples: int
    status: int = 0


def decode_sound(line):
    fields = line.split(b",")
    if len(fields) != 7 or fields[0] != b"HS1":
        return None
    try:
        timestamp, peak, rms, high, samples, status = map(int, fields[1:])
        if not 0 <= timestamp < 2**32 or any(not 0 <= n <= 65535 for n in (peak, rms, high, samples)) or status not in (0, 1, 2):
            return None
        return SoundFrame(timestamp, peak, rms, high, samples, status)
    except ValueError:
        return None


class SoundClick:
    """A short sharp burst, followed by quiet, produces one event.

    This is a tunable transient detector, not a trained speech classifier.
    Keyboard taps, knocks, or speech plosives can resemble a mouth click.
    """
    def __init__(self, threshold=1800):
        self.threshold = threshold
        self.noise = 32.0
        self.reset()

    def reset(self):
        self.previous = None
        self.last_host = None
        self.warm_until = None
        self.next_click = 0.0
        self.burst = None
        self.message = "Waiting for microphone"

    def update(self, frame, now):
        dt = ((frame.timestamp - self.previous) & 0xffffffff) / 1e6 if self.previous is not None else 0
        if (frame.status or not 0 < dt <= .08 or self.last_host is None
                or not 0 <= now - self.last_host <= .15):
            self.reset()
            self.warm_until = now + .4
        self.previous, self.last_host = frame.timestamp, now
        if frame.status:
            self.message = "Microphone unavailable" if frame.status == 1 else "Microphone off"
            return False
        if not frame.samples or frame.peak < frame.rms or not math.isfinite(now):
            self.burst = None
            return False
        if now < self.warm_until:
            self.noise += .15 * (frame.rms - self.noise)
            self.message = "Measuring background…"
            return False
        if now < self.next_click:
            self.message = "Ready after click cooldown"
            return False
        onset = frame.peak >= self.threshold and frame.rms > max(20, self.noise * 4)
        if self.burst is None:
            if not onset:
                self.noise += .025 * (frame.rms - self.noise)
                self.message = "Ready · make a short click or pop"
                return False
            self.burst = {"duration": 0.0, "quiet": 0, "crest": 0.0, "high": 0.0,
                          "level": frame.rms, "clipped": False}
        burst = self.burst
        if frame.rms > max(self.noise * 2, burst["level"] * .3):
            burst["duration"] += dt
            burst["quiet"] = 0
            burst["crest"] = max(burst["crest"], frame.peak / max(1, frame.rms))
            burst["high"] = max(burst["high"], frame.high / max(1, frame.rms))
            burst["clipped"] |= frame.peak >= 32760
            self.message = "Sound detected…"
            return False
        burst["quiet"] += 1
        if burst["quiet"] < 2:
            return False
        detected = (0 < burst["duration"] <= .14 and burst["crest"] >= 2
                    and burst["high"] >= .25 and not burst["clipped"])
        self.burst = None
        self.message = "Click sound detected" if detected else "Ignored long, soft or clipped sound"
        if detected:
            self.next_click = now + .7
        return detected
