"""Small-angle virtual IMU driving the desktop tool's real calibration engine."""
from __future__ import annotations

import math
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from motion import PointerMotion, Sample, decode, gesture_axis, zero_gyro

STEP = 0.01
SCREEN = (1280, 720)
DURATIONS = {"zero": 2, "right": 3, "down": 3}
TARGETS = ((.72, .5), (.72, .72), (.32, .72), (.32, .3), (.58, .3))


class Simulator:
    def __init__(self):
        self.rng = random.Random(42)
        self.settings = {"gain": 22.0, "deadzone": 0.8, "noise": 0.12,
                         "bias": 1.0, "mount": 35.0}
        self.time = 0.0
        self.yaw = self.pitch = 0.0
        self.target_yaw = self.target_pitch = 0.0
        self.bias = self.right = self.down = self.motion = None
        self.sample = Sample(0, (0, 0, 1), (0, 0, 0))
        self.last_delta = (0, 0)
        self.active = False
        self.stage = None
        self.capture_start = 0.0
        self.samples = []
        self.demo = False
        self.rezero = False
        self.report = {"zero": None, "right": None, "down": None}
        self.message = "Run the calibration demo, or start with Hold still."
        self.pointer = [SCREEN[0] / 2, SCREEN[1] / 2]
        self.trail = []
        self.target_index = 0
        self.hits = 0
        self.dwell = 0.0
        self.last_hit = -10.0

    def pause(self):
        self.active = False
        if self.motion:
            self.motion.reset()
        self.last_delta = (0, 0)

    def cancel(self):
        self.pause()
        self.stage = None
        self.demo = self.rezero = False
        self.samples = []
        self.target_yaw, self.target_pitch = self.yaw, self.pitch
        self.message = "Paused. Calibration capture cancelled."

    def interrupt(self):
        if self.stage:
            self.cancel()
        elif self.active:
            self.pause()
            self.target_yaw, self.target_pitch = self.yaw, self.pitch
            self.message = "Paused after the simulator lost focus or stopped receiving updates."

    def start_capture(self, stage, demo=False, rezero=False):
        if stage not in DURATIONS:
            raise ValueError("Unknown calibration step.")
        if stage != "zero" and self.bias is None:
            raise ValueError("Capture the still reading first.")
        if stage == "down" and self.right is None:
            raise ValueError("Capture a right turn first.")
        if rezero and self.motion is None:
            raise ValueError("Complete calibration before re-zeroing.")
        self.pause()
        self.stage = stage
        self.demo = demo
        self.rezero = rezero
        self.samples = []
        self.capture_start = self.time + 3
        if not rezero:
            self.motion = None
            if stage == "zero":
                self.bias = self.right = self.down = None
                self.report = {"zero": None, "right": None, "down": None}
            elif stage == "right":
                self.right = self.down = None
                self.report["right"] = self.report["down"] = None
            else:
                self.down = None
                self.report["down"] = None
        self.message = "Get ready."

    def finish_capture(self):
        stage = self.stage
        self.stage = None
        try:
            if stage == "zero":
                self.bias = zero_gyro(self.samples)
                self.report["zero"] = {"bias": list(self.bias)}
                self.message = "Still reading saved. Capture a right turn next."
                if self.rezero:
                    self.motion = PointerMotion(self.bias, self.right, self.down)
                    self.message = "Gyro bias updated. Press Enable preview when ready."
            else:
                axis = gesture_axis(self.samples, self.bias)
                if stage == "right":
                    self.right = axis
                    self.report["right"] = {"axis": list(axis)}
                    self.message = "Right turn saved. Return to center, then capture a nod down."
                else:
                    self.motion = PointerMotion(self.bias, self.right, axis)
                    self.down = axis
                    self.report["down"] = {"axis": list(axis)}
                    self.message = "Calibration complete. Enable preview to try small movements."
        except ValueError as error:
            self.message = str(error)
            self.demo = self.rezero = False
            return
        if self.demo and stage != "down":
            next_stage = "right" if stage == "zero" else "down"
            self.start_capture(next_stage, demo=True)
        else:
            if self.demo:
                self.yaw = self.pitch = self.target_yaw = self.target_pitch = 0.0
            self.demo = self.rezero = False

    def axes(self):
        angle = math.radians(self.settings["mount"])
        tilt = math.radians(25)
        right = (math.cos(angle), math.sin(angle), 0)
        down = (-math.sin(angle) * math.cos(tilt),
                math.cos(angle) * math.cos(tilt), math.sin(tilt))
        third = tuple(right[(i + 1) % 3] * down[(i + 2) % 3]
                      - right[(i + 2) % 3] * down[(i + 1) % 3] for i in range(3))
        return right, down, third

    def tick(self):
        self.time += STEP
        elapsed = self.time - self.capture_start
        if self.demo:
            yaw = pitch = 0.0
            if self.stage != "zero" and elapsed >= 0:
                progress = min(1, elapsed / 1.2)
                angle = 12 * (0.5 - 0.5 * math.cos(math.pi * progress))
                yaw = angle if self.stage == "right" else 0
                pitch = angle if self.stage == "down" else 0
            self.target_yaw, self.target_pitch = yaw, pitch

        # Cap virtual neck speed and ease toward the requested pose.
        old_yaw, old_pitch = self.yaw, self.pitch
        self.yaw += max(-0.45, min(0.45, (self.target_yaw - self.yaw) * .18))
        self.pitch += max(-0.45, min(0.45, (self.target_pitch - self.pitch) * .18))
        yaw_rate = (self.yaw - old_yaw) / STEP
        pitch_rate = (self.pitch - old_pitch) / STEP
        right, down, third = self.axes()
        bias = (.6, -.35, .2)
        gyro = tuple(yaw_rate * r + pitch_rate * d + zero * self.settings["bias"]
                     + self.rng.gauss(0, self.settings["noise"])
                     for r, d, zero in zip(right, down, bias))
        tilt = math.radians(self.pitch)
        accel = tuple(math.cos(tilt) * r - math.sin(tilt) * t for r, t in zip(right, third))

        # Exercise the same signed-count wire format and decoder as real USB data.
        counts = [round(v * scale) for vector, scale in ((accel, 16384), (gyro, 131))
                  for v in vector]
        line = "HM1," + ",".join(map(str, [round(self.time * 1_000_000) % 2**32] + counts))
        self.sample = decode(line.encode("ascii"))
        self.last_delta = (0, 0)

        if self.stage and elapsed >= -1e-7:
            self.samples.append(self.sample)
            if elapsed >= DURATIONS[self.stage] - 1e-7:
                self.finish_capture()
        elif self.active:
            self.last_delta = self.motion.update(self.sample, self.settings["gain"],
                                                  self.settings["deadzone"])
            for i, delta in enumerate(self.last_delta):
                self.pointer[i] = max(0, min(SCREEN[i], self.pointer[i] + delta))
            if any(self.last_delta):
                self.trail.append(list(self.pointer))
                self.trail = self.trail[-160:]
            target = TARGETS[self.target_index]
            distance = math.hypot(*(p - fraction * size
                                    for p, fraction, size in zip(self.pointer, target, SCREEN)))
            self.dwell = self.dwell + STEP if distance < 27 else 0.0
            if self.dwell >= .4:
                self.hits += 1
                self.target_index = (self.target_index + 1) % len(TARGETS)
                self.dwell = 0
                self.last_hit = self.time

    def advance(self, elapsed):
        for _ in range(max(0, round(elapsed / STEP))):
            self.tick()

    def command(self, action, payload):
        if action == "demo":
            self.start_capture("zero", demo=True)
        elif action == "capture":
            if self.stage:
                raise ValueError("Finish or cancel the current capture first.")
            self.start_capture(payload.get("step"))
        elif action == "rezero":
            if self.stage:
                raise ValueError("Finish or cancel the current capture first.")
            self.start_capture("zero", rezero=True)
        elif action == "pause":
            self.interrupt()
            self.message = "Preview paused."
        elif action == "cancel":
            self.cancel()
        elif action == "toggle":
            if self.active:
                self.pause()
                self.message = "Preview paused. You can return your virtual head to center."
            elif self.motion is not None and self.stage is None:
                self.motion.reset()
                self.active = True
                self.message = "Preview enabled. Move gently toward the orange target."
            else:
                raise ValueError("Complete calibration before enabling the preview.")
        elif action == "pose":
            if self.demo:
                raise ValueError("The demo is controlling the virtual head.")
            values = [payload.get("yaw"), payload.get("pitch")]
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 25 for v in values):
                raise ValueError("Head angles must be between −25° and +25°.")
            self.target_yaw, self.target_pitch = values
        elif action == "center":
            self.pointer = [SCREEN[0] / 2, SCREEN[1] / 2]
            self.trail = []
            self.dwell = 0
            if self.motion:
                self.motion.reset()
        elif action == "settings":
            limits = {"gain": (4, 65), "deadzone": (.2, 5), "noise": (0, 2),
                      "bias": (0, 3), "mount": (-180, 180)}
            if not payload or set(payload) - set(limits):
                raise ValueError("Unknown setting.")
            for key, value in payload.items():
                low, high = limits[key]
                if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"Invalid value for {key}.")
            if self.stage:
                raise ValueError("Finish or cancel calibration before changing settings.")
            if "mount" in payload and payload["mount"] != self.settings["mount"]:
                self.pause()
                self.bias = self.right = self.down = self.motion = None
                self.report = {"zero": None, "right": None, "down": None}
                self.message = "Mounting angle changed. Repeat calibration."
            self.settings.update(payload)
        else:
            raise ValueError("Unknown command.")

    def state(self):
        phase = "ready"
        remaining = 0
        if self.stage:
            elapsed = self.time - self.capture_start
            phase = "countdown" if elapsed < 0 else "capture"
            remaining = math.ceil(-elapsed if elapsed < 0 else max(0, DURATIONS[self.stage] - elapsed))
        target = TARGETS[self.target_index]
        return {
            "time": self.time, "settings": self.settings,
            "pose": {"yaw": self.yaw, "pitch": self.pitch,
                     "targetYaw": self.target_yaw, "targetPitch": self.target_pitch},
            "gyro": self.sample.gyro, "accel": self.sample.accel,
            "pointer": self.pointer, "delta": self.last_delta, "trail": self.trail,
            "active": self.active, "calibrated": self.motion is not None,
            "stage": self.stage, "phase": phase, "remaining": remaining, "demo": self.demo,
            "report": self.report, "message": self.message, "rezero": self.rezero,
            "target": [target[0] * SCREEN[0], target[1] * SCREEN[1]],
            "hits": self.hits, "dwell": self.dwell / .4,
            "hitFlash": self.time - self.last_hit < .5,
            "screen": SCREEN,
        }
