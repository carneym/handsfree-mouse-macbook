"""Head gestures in calibrated angles, independent of pointer sensitivity."""
import math

CIRCLE_RULES = [{"direction": "Anticlockwise", "count": 3, "action": "Cycle modes"}]
THREE_PAIR_RULES = [{"direction": "Left-right", "count": 3, "action": "Cycle modes"}]
RECENTER_RULE = {"direction": "Up-down", "count": 3, "action": "Recenter"}
DEFAULT_RULES = [{"direction": "Left-right", "count": 2, "action": "Cycle modes"}, RECENTER_RULE]
ACTIONS = ("Cycle modes", "Click", "Drag", "Scroll", "Double click", "Right click", "Recenter")
DIRECTIONS = ("Left-right", "Up-down", "Anticlockwise", "Clockwise")


def validate_rules(rules):
    if not isinstance(rules, list) or len(rules) > 6:
        raise ValueError("Use up to six gestures")
    seen = set()
    for rule in rules:
        if (not isinstance(rule, dict) or rule.get("direction") not in DIRECTIONS
                or type(rule.get("count")) is not int or not 1 <= rule["count"] <= 3
                or rule.get("action") not in ACTIONS + ("Page",)):
            raise ValueError("Choose a pattern, 1–3 repetitions and an action")
        key = (rule["direction"], rule["count"])
        if key in seen:
            raise ValueError("Each pattern can have only one action")
        seen.add(key)
    return [dict(rule) for rule in rules]


class CircleGestures:
    def __init__(self, rules=None):
        self.rules = validate_rules(CIRCLE_RULES if rules is None else rules)
        self.reset()

    def reset(self):
        self.clock = self.cooldown = self.idle = self.sequence_time = 0.0
        self.count = 0
        self.direction = None
        self.pending = None
        self.dwell_guard = False
        self.clear_loop()

    def clear_loop(self):
        self.angle = None
        self.turn = self.path = self.elapsed = self.x = self.y = 0.0
        self.bounds = [0.0, 0.0, 0.0, 0.0]

    @property
    def busy(self):
        return self.cooldown > 0 or self.count > 0

    @property
    def suppress_dwell(self):
        # Direction changes alone are common while aiming. Only a completed,
        # validated circle in a configured direction can interrupt a dwell.
        # Release the guard quickly when the user settles, independent of the
        # longer sequence timeout and mode-switch cooldown.
        return self.dwell_guard

    def fire(self, action):
        self.reset()
        self.cooldown = 2.0
        return action

    def update(self, vx, vy, dt):
        if not 0 < dt <= .06 or not all(math.isfinite(v) for v in (vx, vy)):
            self.reset()
            return None
        if self.cooldown > 0:
            self.cooldown = max(0, self.cooldown - dt)
            return None
        self.sequence_time += dt
        if self.sequence_time > 12:
            self.reset()
        speed = math.hypot(vx, vy)
        if speed < 1:
            self.idle += dt
            if self.idle >= .15:
                self.dwell_guard = False
            if self.idle > .45:
                action = self.pending
                self.reset()
                return self.fire(action) if action else None
            return None
        self.idle = 0
        if speed > 80:
            self.reset()
            return None
        angle = math.atan2(-vy, vx)  # Screen Y is down; positive turns are anticlockwise.
        if self.angle is not None:
            change = (angle - self.angle + math.pi) % (2 * math.pi) - math.pi
            if abs(change) > math.pi / 3 or (abs(self.turn) > .7 and
                    change * math.copysign(1, self.turn) < -.25):
                self.clear_loop()
            else:
                self.turn += change
        self.angle = angle
        self.x += vx * dt
        self.y += vy * dt
        self.path += speed * dt
        self.elapsed += dt
        self.bounds = [min(self.bounds[0], self.x), max(self.bounds[1], self.x),
                       min(self.bounds[2], self.y), max(self.bounds[3], self.y)]
        if self.elapsed > 4 or self.path > 70:
            self.reset()
            return None
        if abs(self.turn) < 2 * math.pi - .08:
            return None
        width, height = self.bounds[1] - self.bounds[0], self.bounds[3] - self.bounds[2]
        valid = (.4 <= self.elapsed <= 4 and 4 <= self.path <= 70
                 and .9 <= width <= 20 and .9 <= height <= 20
                 and .35 <= width / height <= 2.85
                 and math.hypot(self.x, self.y) <= max(.5, self.path * .2))
        direction = "Anticlockwise" if self.turn > 0 else "Clockwise"
        self.clear_loop()
        if not valid:
            self.reset()
            return None
        self.count = self.count + 1 if direction == self.direction else 1
        self.direction = direction
        matches = [r for r in self.rules if r["direction"] == direction]
        self.pending = next((r["action"] for r in matches if r["count"] == self.count), None)
        if self.pending and not any(r["count"] > self.count for r in matches):
            return self.fire(self.pending)
        if not any(r["count"] >= self.count for r in matches):
            self.reset()
        else:
            self.dwell_guard = True
        return None


class HorizontalGestures:
    """Alternating primary-axis strokes; the engine swaps axes for nods."""
    def __init__(self, rules, first_sign=None):
        self.rules = rules
        self.first_sign = first_sign
        self.reset()

    def reset(self):
        self.strokes = self.sign = 0
        self.travel = self.stroke_time = self.elapsed = self.idle = self.off_axis = 0.0
        self.confirmed = False
        self.pending = None

    @property
    def count(self):
        return self.strokes // 2

    def finish(self, action):
        self.reset()
        return action

    def update(self, vx, vy, dt):
        if not self.rules:
            return None
        self.elapsed += dt
        self.stroke_time += dt
        if self.elapsed > 3 or abs(vx) > 120 or abs(vy) > 120:
            self.reset()
            return None
        if abs(vx) < 5:
            self.idle += dt
            if self.idle > .25:
                return self.finish(self.pending)
            return None
        self.idle = 0
        if abs(vy) > abs(vx) * .65:
            self.off_axis += dt
            if self.off_axis > .08:
                self.reset()
            return None
        self.off_axis = 0
        sign = 1 if vx > 0 else -1
        if not self.sign and self.first_sign is not None and sign != self.first_sign:
            self.reset()
            return None
        if sign != self.sign:
            if self.sign and not self.confirmed:
                self.reset()
            self.sign = sign
            self.travel = 0.0
            self.stroke_time = dt
            self.confirmed = False
        self.travel += abs(vx) * dt
        if self.travel > 12 or self.stroke_time > .55:
            self.reset()
            return None
        if self.confirmed or self.travel < 1.5 or self.stroke_time < .06:
            return None
        self.confirmed = True
        self.strokes += 1
        self.pending = None
        if self.strokes % 2:
            return None
        self.pending = next((r["action"] for r in self.rules if r["count"] == self.count), None)
        if self.pending and not any(r["count"] > self.count for r in self.rules):
            return self.finish(self.pending)
        if not any(r["count"] >= self.count for r in self.rules):
            self.reset()
        return None


class HeadGestures:
    """Share one cooldown between configured shake and circle gestures."""
    def __init__(self, rules=None):
        self.rules = DEFAULT_RULES if rules is None else rules

    @property
    def rules(self):
        return self._rules

    @rules.setter
    def rules(self, rules):
        self._rules = validate_rules(rules)
        self.circles = CircleGestures([r for r in self._rules if r["direction"] in ("Clockwise", "Anticlockwise")])
        self.horizontal = HorizontalGestures([r for r in self._rules if r["direction"] == "Left-right"])
        self.vertical = HorizontalGestures([r for r in self._rules if r["direction"] == "Up-down"], first_sign=-1)
        self.reset()

    def reset(self):
        self.cooldown = 0.0
        self.circles.reset()
        self.horizontal.reset()
        self.vertical.reset()

    @property
    def count(self):
        return max(self.horizontal.count, self.vertical.count, self.circles.count)

    @property
    def turn(self):
        return self.circles.turn

    @property
    def busy(self):
        return self.cooldown > 0 or self.horizontal.strokes > 0 or self.vertical.strokes > 0 or self.circles.busy

    @property
    def suppress_dwell(self):
        # A partial shake never interrupts dwell; only a completed shake
        # changes mode and starts a fresh countdown.
        return self.circles.suppress_dwell

    @property
    def progress_text(self):
        if self.vertical.strokes:
            return f"{self.vertical.count} up–down pair(s)"
        if self.horizontal.strokes:
            return f"{self.horizontal.count} left–right pair(s)"
        if any(r["direction"] == "Left-right" for r in self.rules):
            repeats = max(r["count"] for r in self.rules if r["direction"] == "Left-right")
            if any(r["direction"] == "Up-down" for r in self.rules):
                nods = max(r["count"] for r in self.rules if r["direction"] == "Up-down")
                return f"Left–right ×{repeats} · up–down ×{nods}"
            return f"Left–right ×{repeats} · either way first"
        return f"{self.circles.count} circle(s) detected"

    def update(self, vx, vy, dt):
        if not 0 < dt <= .06 or not all(math.isfinite(v) for v in (vx, vy)):
            self.reset()
            return None
        if self.cooldown:
            self.cooldown = max(0, self.cooldown - dt)
            return None
        action = (self.horizontal.update(vx, vy, dt) or self.vertical.update(vy, vx, dt)
                  or self.circles.update(vx, vy, dt))
        if action:
            self.reset()
            self.cooldown = 2.0
        return action
