"""Persist mounting axes and preferences. A fresh gyro zero is required on load."""
import json
import math
import os
from pathlib import Path
import tempfile
import sys

from motion import screen_axes
from gestures import DEFAULT_RULES, CIRCLE_RULES, THREE_PAIR_RULES, RECENTER_RULE, validate_rules

def profile_path(*, frozen=None, home=None):
    if frozen is None:
        frozen = getattr(sys, "frozen", False)
    if frozen:
        return (Path.home() if home is None else Path(home)) / "Library/Application Support/Head Mouse/profile.json"
    return Path(__file__).resolve().parent / ".head_mouse_profile.json"


PROFILE_PATH = profile_path()


def load_profile(path=PROFILE_PATH):
    try:
        profile = json.loads(path.read_text())
        if profile["version"] != 1:
            raise ValueError("Unsupported profile version")
        gain, deadzone = profile["gain"], profile["deadzone"]
        if not 4 <= gain <= 65 or not .2 <= deadzone <= 5:
            raise ValueError("Preferences out of range")
        dwell_seconds = profile.get("dwell_seconds", 1.0)
        if not .5 <= dwell_seconds <= 3:
            raise ValueError("Dwell duration out of range")
        profile["dwell_seconds"] = dwell_seconds
        sensitivity = profile.get("sensitivity", 1.0)
        if not isinstance(sensitivity, (int, float)) or not .5 <= sensitivity <= 3:
            raise ValueError("Sensitivity out of range")
        profile["sensitivity"] = sensitivity
        if profile.get("click_method", "Dwell") not in ("Dwell", "Sound"):
            raise ValueError("Invalid click method")
        if profile.get("mode_set", "Mode 1") not in ("Mode 1", "Mode 2"):
            raise ValueError("Invalid control set")
        if profile.get("transport", "USB") not in ("USB", "Bluetooth"):
            raise ValueError("Invalid transport")
        threshold = profile.get("sound_threshold", 1800)
        if not isinstance(threshold, (int, float)) or not 400 <= threshold <= 12000:
            raise ValueError("Invalid sound threshold")
        for key in ("ble_address", "ble_name"):
            value = profile.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > 200):
                raise ValueError("Invalid saved Bluetooth device")
        profile["gestures"] = validate_rules(profile.get("gestures", DEFAULT_RULES))
        if profile.get("gesture_version", 1) == 1 and profile["gestures"] == CIRCLE_RULES:
            profile["gestures"] = validate_rules(DEFAULT_RULES)
        if profile.get("gesture_version", 1) < 3 and profile["gestures"] == THREE_PAIR_RULES:
            profile["gestures"] = validate_rules(DEFAULT_RULES)
        if (profile.get("gesture_version", 1) < 4 and len(profile["gestures"]) < 6
                and not any(r["direction"] == "Up-down" and r["count"] == 3 for r in profile["gestures"])):
            profile["gestures"] = validate_rules(profile["gestures"] + [RECENTER_RULE])
        axes = [profile.get("right"), profile.get("down")]
        if any(axis is not None for axis in axes):
            for axis in axes:
                if (not isinstance(axis, list) or len(axis) != 3
                        or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in axis)
                        or abs(math.hypot(*axis) - 1) > .01):
                    raise ValueError("Invalid mounting axis")
            screen_axes(*axes)
        return profile
    except (OSError, ValueError, TypeError, KeyError):
        return None


def save_profile(gain, deadzone, right, down, path=PROFILE_PATH, *, dwell_seconds=1.0,
                 sensitivity=1.0, gestures=None, ble_address=None, ble_name=None,
                 click_method="Dwell", sound_threshold=1800, mode_set="Mode 1", transport="USB"):
    profile = {"version": 1, "gain": gain, "deadzone": deadzone,
               "right": right, "down": down, "dwell_seconds": dwell_seconds,
               "sensitivity": sensitivity,
               "gesture_version": 4,
               "ble_address": ble_address, "ble_name": ble_name,
               "transport": transport, "mode_set": mode_set, "click_method": click_method, "sound_threshold": sound_threshold,
               "gestures": validate_rules(DEFAULT_RULES if gestures is None else gestures)}
    filename = None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False,
                                         prefix=".head_mouse_", suffix=".tmp") as output:
            filename = output.name
            json.dump(profile, output, allow_nan=False)
            output.write("\n")
        os.replace(filename, path)
    finally:
        if filename and os.path.exists(filename):
            os.unlink(filename)
