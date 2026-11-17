"""Calibrate a USB head mouse and send relative pointer motion."""

import argparse
import asyncio
import math
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import serial
from serial.tools import list_ports

from motion import PointerMotion, gesture_axis, seconds, zero_gyro, dot
from gestures import HeadGestures, DEFAULT_RULES, DIRECTIONS, ACTIONS, validate_rules
from preferences import load_profile, save_profile
from dwell import DwellClick
from serial_feed import SerialFeed
from mode_indicator import MODE_STYLE, MacModeBadge
from ble_feed import BleFeed, discover, check_bluetooth_usage
from sound_click import SoundClick, SoundFrame
from scroll_motion import TiltScroll
from guided_calibration import GuidedCalibration

MODE_SETS = {"Mode 1": ("Click", "Drag", "Scroll"),
             "Mode 2": ("Click", "Double click", "Right click")}

BAUD = 115200
STALE_AFTER = 0.25
PROMPTS = {
    "zero": "Face the screen and hold still.",
    "right": "Face forward. At GO, turn slightly right, then hold.",
    "down": "Face forward. At GO, nod slightly down, then hold.",
}


class HeadMouse:
    def __init__(self, root):
        self.root = root
        self.menu_bar = None
        self._servicing_controls = False
        self.port = None
        self.feed = None
        self.last_rx = None
        self.last_sample = None
        self.capture = None
        self.guided = None
        self.bias = self.right = self.motion = self.mouse = None
        self.active = False
        self.down = None
        self.rezero = False
        self.recentering = None
        self.transport = tk.StringVar(value="USB")
        self.ble_results = queue.Queue()
        self.ble_devices = {}
        self.scanning = False
        self.auto_connect = False
        self.ble_address = self.ble_name = None
        self.practice_position = [350.0, 90.0]
        self.notice = tk.StringVar(value="Connect your XIAO to begin.")
        self.telemetry = tk.StringVar(value="Waiting for sensor readings")
        self.connection_status = tk.StringVar(value="USB · disconnected")
        self.pointer_status = tk.StringVar(value="Paused")
        self.gain = tk.DoubleVar(value=22)
        self.deadzone = tk.DoubleVar(value=0.8)
        self.practice = tk.BooleanVar(value=True)
        self.details = tk.BooleanVar(value=False)
        self.dwell_enabled = tk.BooleanVar(value=True)
        self.dwell_seconds = tk.DoubleVar(value=1.0)
        self.dwell_status = tk.StringVar(value="Dwell clicks off")
        self.dwell = DwellClick()
        self.click_method = tk.StringVar(value="Dwell")
        self.sound_threshold = tk.DoubleVar(value=1800)
        self.sound = SoundClick()
        self.sound_status = tk.StringVar(value="Sound test paused")
        self.sound_level = tk.DoubleVar(value=0)
        self.sound_testing = False
        self.sound_tests = 0
        self.sound_learning_until = None
        self.sound_background = []
        self.last_sound_rx = None
        self.practice_clicks = 0
        self.sensitivity = tk.DoubleVar(value=1.0)
        self.mode_set = tk.StringVar(value="Mode 1")
        self.action_mode = tk.StringVar(value="Click")
        self.gestures_enabled = tk.BooleanVar(value=True)
        self.gesture_status = tk.StringVar(value="Gestures off")
        self.gestures = HeadGestures()
        self.dragging = False
        self.drag_mouse = None
        self.scroll_remainder = 0.0
        self.scroll = TiltScroll()
        self.practice_scroll = 0
        self.mode_badge_enabled = tk.BooleanVar(value=True)
        self.mode_badge = None
        self.badge_failed = False
        self.badge_flash_until = 0.0
        self.step_labels = []
        self.profile_error = ""
        self.restore_profile()

        root.title("Head Mouse · Live calibration")
        root.configure(background="#f1f5f3")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Helvetica", 12))
        style.configure("TFrame", background="#f1f5f3")
        style.configure("TLabel", background="#f1f5f3", foreground="#19333d")
        style.configure("Title.TLabel", font=("Helvetica", 23, "bold"))
        style.configure("Hint.TLabel", font=("Helvetica", 10), foreground="#58717a")
        style.configure("Status.TLabel", font=("Helvetica", 11, "bold"))
        style.configure("TButton", padding=(12, 8))
        style.configure("Primary.TButton", background="#087e77", foreground="white",
                        font=("Helvetica", 13, "bold"), padding=(16, 12))
        style.map("Primary.TButton", background=[("active", "#09645f"), ("disabled", "#bacdc7")])
        style.configure("Stop.TButton", background="#a54435", foreground="white",
                        font=("Helvetica", 13, "bold"), padding=(16, 12))
        style.map("Stop.TButton", background=[("active", "#84372b")])
        style.configure("TLabelframe", background="#f1f5f3")
        style.configure("TLabelframe.Label", background="#f1f5f3",
                        foreground="#19333d", font=("Helvetica", 12, "bold"))
        style.configure("TRadiobutton", background="#f1f5f3")
        style.configure("TCheckbutton", background="#f1f5f3")
        panel = ttk.Frame(root, padding=20)
        panel.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        panel.columnconfigure(0, weight=1)

        header = ttk.Frame(panel)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Head Mouse", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.connection_status, style="Status.TLabel").grid(
            row=0, column=1, sticky="e")
        ttk.Label(header, text="Live XIAO control · calibrate, practise, then move the pointer",
                  style="Hint.TLabel").grid(row=1, columnspan=2, sticky="w")

        connection = ttk.Frame(panel)
        connection.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        connection.columnconfigure(1, weight=1)
        self.transport_picker = ttk.Combobox(connection, width=9, state="readonly",
                                             textvariable=self.transport, values=("USB", "Bluetooth"))
        self.transport_picker.grid(row=0, column=0, padx=(0, 6))
        self.transport_picker.bind("<<ComboboxSelected>>", lambda _event: self.select_transport())
        self.ports = ttk.Combobox(connection, width=23, state="readonly")
        self.ports.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(connection, text="Find device", command=self.refresh_devices).grid(row=0, column=2, padx=4)
        self.connect = ttk.Button(connection, text="Connect USB", command=self.toggle_connection)
        self.connect.grid(row=0, column=3, padx=(4, 0))
        ttk.Button(connection, text="Forget", command=self.forget_bluetooth).grid(row=0, column=4, padx=(4, 0))

        calibration = ttk.LabelFrame(panel, text="1  Calibrate your mounting", padding=12)
        calibration.grid(row=2, column=0, sticky="ew")
        for column in range(3):
            calibration.columnconfigure(column, weight=1)
        self.calibration = []
        for column, (step, label) in enumerate(zip(PROMPTS, ("1. Hold still", "2. Turn right", "3. Nod down"))):
            variable = tk.StringVar(value=label)
            self.step_labels.append(variable)
            button = ttk.Button(calibration, textvariable=variable,
                                command=lambda step=step: self.start_capture(step))
            button.grid(row=0, column=column, sticky="ew", padx=3)
            self.calibration.append(button)
        ttk.Label(calibration, textvariable=self.notice, wraplength=680,
                  font=("Helvetica", 12)).grid(row=1, columnspan=3, sticky="w", pady=(12, 8))
        self.progress = ttk.Progressbar(calibration, maximum=100)
        self.progress.grid(row=2, columnspan=3, sticky="ew")
        self.rezero_button = ttk.Button(calibration, text="Re-zero drift",
                                       command=lambda: self.start_capture("zero", preserve_axes=True))
        self.rezero_button.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.cancel_button = ttk.Button(calibration, text="Cancel capture", command=self.cancel_capture)
        self.cancel_button.grid(row=3, column=2, sticky="e", pady=(8, 0))

        movement = ttk.LabelFrame(panel, text="2  Try the movement", padding=12)
        movement.grid(row=3, column=0, sticky="ew", pady=12)
        movement.columnconfigure(0, weight=1)
        modes = ttk.Frame(movement)
        modes.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(modes, text="Computer control off uses the practice area",
                  style="Hint.TLabel").grid(row=0, column=0, padx=(0, 18))
        ttk.Label(modes, textvariable=self.pointer_status, style="Status.TLabel").grid(row=0, column=1)
        self.canvas = tk.Canvas(movement, width=700, height=120, background="#17333f",
                                highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<Configure>", lambda _event: self.draw_practice())
        self.draw_practice()
        actions = ttk.Frame(movement)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.arm = ttk.Button(actions, text="Start practice", style="Primary.TButton",
                              command=self.toggle_pointer)
        self.arm.grid(row=0, column=0, sticky="w")
        self.computer_button = ttk.Button(actions, text="Computer control OFF · turn on",
                                         style="Primary.TButton", command=self.toggle_computer)
        self.computer_button.grid(row=0, column=1, padx=8)
        self.recenter_button = ttk.Button(actions, text="Recenter head · 3 s", command=self.start_recenter)
        self.recenter_button.grid(
            row=0, column=2, padx=4)
        ttk.Label(actions, text="Esc pauses · R recenters while this window has focus.",
                  style="Hint.TLabel").grid(row=1, columnspan=3, sticky="w", pady=(6, 0))

        dwell_panel = ttk.Frame(movement)
        dwell_panel.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(dwell_panel, text="Click method").grid(row=0, column=0, sticky="w", padx=(0, 12))
        method_picker = ttk.Combobox(dwell_panel, textvariable=self.click_method,
                                    values=("Dwell", "Sound"), state="readonly", width=7)
        method_picker.grid(row=0, column=1, padx=(0, 8))
        method_picker.bind("<<ComboboxSelected>>", lambda _event: self.change_click_method())
        self.dwell_controls = ttk.Frame(dwell_panel)
        self.dwell_controls.grid(row=0, column=2)
        ttk.Label(self.dwell_controls, text="Hold for").grid(row=0, column=0)
        ttk.Spinbox(self.dwell_controls, from_=0.5, to=3.0, increment=0.1, width=4,
                    textvariable=self.dwell_seconds).grid(row=0, column=1, padx=5)
        ttk.Label(self.dwell_controls, text="seconds").grid(row=0, column=2, padx=(0, 10))
        self.sound_setup = ttk.Button(dwell_panel, text="Sound setup / test…", command=self.open_sound_setup)
        self.sound_setup.grid(row=0, column=2)
        self.sound_setup.grid_remove()
        self.dwell_progress = ttk.Progressbar(dwell_panel, maximum=100, length=100)
        self.dwell_progress.grid(row=0, column=3, padx=(0, 10))
        ttk.Label(dwell_panel, textvariable=self.dwell_status, style="Hint.TLabel").grid(
            row=0, column=4, sticky="w")
        self.dwell_seconds.trace_add("write", self.change_dwell_time)

        gesture_panel = ttk.Frame(movement)
        gesture_panel.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        set_panel = ttk.Frame(movement)
        set_panel.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(set_panel, text="Control set").grid(row=0, column=0, padx=(0, 5))
        set_picker = ttk.Combobox(set_panel, textvariable=self.mode_set,
                                 values=tuple(MODE_SETS), state="readonly", width=8)
        set_picker.grid(row=0, column=1)
        set_picker.bind("<<ComboboxSelected>>", lambda _event: self.change_mode_set())
        ttk.Label(set_panel, text="Mode 1: Click / Drag / Scroll   ·   Mode 2: Click / Double click / Right click",
                  style="Hint.TLabel").grid(row=0, column=2, padx=12)
        gesture_panel.grid_configure(row=5)
        ttk.Label(gesture_panel, text="Action").grid(row=0, column=0, padx=(0, 5))
        self.mode_picker = ttk.Combobox(gesture_panel, textvariable=self.action_mode,
                                  values=MODE_SETS[self.mode_set.get()], state="readonly", width=12)
        self.mode_picker.grid(row=0, column=1)
        self.mode_picker.bind("<<ComboboxSelected>>", lambda _event: self.change_mode(self.action_mode.get()))
        ttk.Checkbutton(gesture_panel, text="Mode gestures", variable=self.gestures_enabled,
                        command=self.reset_gestures).grid(row=0, column=2, padx=12)
        ttk.Button(gesture_panel, text="Edit gestures…", command=self.edit_gestures).grid(row=0, column=3)
        ttk.Label(gesture_panel, textvariable=self.gesture_status, style="Hint.TLabel").grid(
            row=1, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Checkbutton(gesture_panel, text="Mode icon + timer", variable=self.mode_badge_enabled,
                        command=self.update_mode_indicator).grid(row=1, column=3, sticky="w", pady=(4, 0))

        tuning = ttk.Frame(panel)
        tuning.grid(row=4, column=0, sticky="ew")
        for column, (label, variable, low, high) in enumerate((
            ("Pointer speed", self.gain, 4, 65),
            ("Ignore tiny movements", self.deadzone, .2, 5),
            ("Computer sensitivity ×", self.sensitivity, .5, 3),
        )):
            cell = ttk.Frame(tuning)
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 18) if column < 2 else 0)
            tuning.columnconfigure(column, weight=1)
            value = tk.StringVar(value=f"{variable.get():.1f}")
            ttk.Label(cell, text=label).grid(row=0, column=0, sticky="w")
            ttk.Label(cell, textvariable=value, style="Status.TLabel").grid(row=0, column=1, sticky="e")
            cell.columnconfigure(0, weight=1)
            ttk.Scale(cell, from_=low, to=high, variable=variable,
                      command=lambda number, value=value: value.set(f"{float(number):.1f}")).grid(
                row=1, columnspan=2, sticky="ew", pady=6)
            variable.trace_add("write", lambda *_args, variable=variable, value=value:
                               value.set(f"{variable.get():.1f}"))
            variable.trace_add("write", lambda *_args: self.save_preferences())
        ttk.Checkbutton(panel, text="Show live sensor readings", variable=self.details,
                        command=self.toggle_details).grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.sensor_label = ttk.Label(panel, textvariable=self.telemetry, style="Hint.TLabel")
        self.sensor_label.grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.sensor_label.grid_remove()
        ttk.Label(panel, text="USB or Bluetooth · settings are saved on this computer",
                  style="Hint.TLabel").grid(row=7, column=0, sticky="w", pady=(10, 0))
        root.bind("<Escape>", lambda _event: self.dismiss_guided() if getattr(self, "guided", None) else self.cancel_capture() if self.capture else self.pause())
        root.bind("<KeyPress-r>", self.recenter_key)
        root.protocol("WM_DELETE_WINDOW", self.hide_setup)
        if sys.platform == "darwin":
            root.createcommand("tk::mac::Quit", self.close)
        self.refresh_ports()
        self.change_click_method(save=False)
        self.update_buttons()
        if sys.platform == "darwin":
            try:
                from menu_bridge import MenuBarBridge
                self.menu_bar = MenuBarBridge(self)
            except Exception as error:
                self.notice.set(f"Menu bar unavailable. Full setup is still available. {error}")
        self.poll()

    @property
    def guided_running(self):
        return bool(getattr(self, "guided", None) and self.guided.running)

    def start_guided(self):
        now = time.monotonic()
        if not self.feed or self.last_rx is None or now - self.last_rx > STALE_AFTER:
            self.notice.set("Connect the XIAO and wait for fresh readings before calibrating.")
            return
        self.pause()
        self.capture = None
        self.rezero = False
        self.guided = GuidedCalibration(now)
        self.notice.set("Guided calibration started. Look at the centre of the screen.")
        self.update_buttons()

    def retry_guided(self):
        if (getattr(self, "guided", None) and self.guided.phase == "error"
                and self.last_rx is not None and time.monotonic() - self.last_rx <= STALE_AFTER):
            self.guided.retry(time.monotonic())
            self.update_buttons()

    def start_guided_control(self):
        guided = getattr(self, "guided", None)
        if not guided or guided.phase != "done" or not guided.applied:
            return
        if self.last_rx is None or time.monotonic() - self.last_rx > STALE_AFTER:
            self.notice.set("Readings stopped. Reconnect before turning on computer control.")
            return
        self.dismiss_guided()
        self.toggle_computer()

    def dismiss_guided(self):
        if getattr(self, "guided", None):
            finished = self.guided.phase == "done"
            self.guided = None
            self.notice.set("Calibrated. Turn on computer control when ready." if finished else
                            "Calibration cancelled. Previous calibration kept; control remains off.")
            self.update_buttons()

    def finish_guided(self, now):
        guided = getattr(self, "guided", None)
        if not guided:
            return
        guided.tick(now)
        if guided.result is not None and not guided.applied:
            bias, right, down = guided.result
            motion = PointerMotion(bias, right, down)
            self.bias, self.right, self.down, self.motion = bias, right, down, motion
            guided.applied = True
            self.save_preferences()
            self.notice.set("Calibrated. Turn on computer control when ready.")
            self.update_buttons()

    def stop_guided(self, message):
        if getattr(self, "guided", None) and self.guided.phase != "done":
            self.guided.fail(message, restart=True)
            self.update_buttons()

    def hide_setup(self):
        if self.menu_bar:
            self.root.withdraw()
        else:
            self.close()

    def restore_profile(self):
        profile = load_profile()
        if profile:
            self.gain.set(profile["gain"])
            self.deadzone.set(profile["deadzone"])
            self.dwell_seconds.set(profile.get("dwell_seconds", 1.0))
            self.sensitivity.set(profile.get("sensitivity", 1.0))
            self.gestures.rules = validate_rules(profile.get("gestures", DEFAULT_RULES))
            self.right = profile.get("right")
            self.down = profile.get("down")
            self.ble_address = profile.get("ble_address")
            self.ble_name = profile.get("ble_name")
            self.mode_set.set(profile.get("mode_set", "Mode 1"))
            if self.action_mode.get() not in MODE_SETS[self.mode_set.get()]:
                self.action_mode.set("Click")
            if hasattr(self, "mode_picker"):
                self.mode_picker.configure(values=MODE_SETS[self.mode_set.get()])
            self.click_method.set(profile.get("click_method", "Dwell"))
            self.sound_threshold.set(profile.get("sound_threshold", 1800))

    def save_preferences(self):
        try:
            # Keep the last complete mounting while a fresh capture is underway.
            profile = load_profile()
            right, down = self.right, self.down
            if right is None or down is None:
                right = profile.get("right") if profile else None
                down = profile.get("down") if profile else None
            duration = self.dwell_duration()
            if duration is None:
                return
            save_profile(self.gain.get(), self.deadzone.get(), right, down, dwell_seconds=duration,
                         sensitivity=self.sensitivity.get(), gestures=self.gestures.rules,
                         ble_address=self.ble_address, ble_name=self.ble_name,
                         click_method=self.click_method.get(), sound_threshold=self.sound_threshold.get(),
                         mode_set=self.mode_set.get(), transport=self.transport.get())
            self.profile_error = ""
        except tk.TclError:
            return  # A spinbox edit may temporarily be empty.
        except (OSError, ValueError) as error:
            self.profile_error = f"Settings could not be saved. {error}"
            self.notice.set(self.profile_error)

    def toggle_details(self):
        if self.details.get():
            self.sensor_label.grid()
        else:
            self.sensor_label.grid_remove()

    def reset_gestures(self):
        self.gestures.reset()
        self.reset_dwell()
        self.gesture_status.set(self.gestures.progress_text if self.gestures_enabled.get()
                                else "Gestures off")

    def edit_gestures(self):
        self.pause()
        dialog = tk.Toplevel(self.root)
        dialog.title("Mode gestures")
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=16)
        frame.grid()
        ttk.Label(frame, text="Default: left–right ×2, four alternating strokes in about 1–2 seconds.\n"
                  "Recenter: up–down ×3, six alternating strokes, starting up.\n"
                  "Small movements, about 2–4° each. Left–right may start either way; nods start up.\n"
                  "Cycle modes follows the selected control set. Gestures pause while dragging.\n"
                  "Direct action gestures apply only when that action belongs to the selected set.").grid(
                      row=0, columnspan=4, sticky="w", pady=(0, 12))
        rows = []
        for index in range(6):
            rule = self.gestures.rules[index] if index < len(self.gestures.rules) else None
            enabled = tk.BooleanVar(value=rule is not None)
            direction = tk.StringVar(value=rule["direction"] if rule else "Left-right")
            count = tk.StringVar(value=str(rule["count"]) if rule else "2")
            action = tk.StringVar(value=("Scroll" if rule["action"] == "Page" else rule["action"]) if rule else "Cycle modes")
            rows.append((enabled, direction, count, action))
            ttk.Checkbutton(frame, variable=enabled).grid(row=index+1, column=0)
            for col, var, values, width in ((1, direction, DIRECTIONS, 15),
                                            (2, count, ("1", "2", "3"), 3),
                                            (3, action, ACTIONS, 12)):
                ttk.Combobox(frame, textvariable=var, values=values, state="readonly",
                             width=width).grid(row=index+1, column=col, padx=4, pady=3)
        message = tk.StringVar(value="Tick a row to add it; untick to remove it.")
        ttk.Label(frame, textvariable=message).grid(row=7, columnspan=4, pady=10)

        def save():
            try:
                rules = validate_rules([{"direction": d.get(), "count": int(c.get()), "action": a.get()}
                                        for e, d, c, a in rows if e.get()])
            except ValueError as error:
                message.set(str(error))
                return
            self.gestures.rules = rules
            self.reset_gestures()
            self.save_preferences()
            dialog.destroy()
        ttk.Button(frame, text="Save gestures", command=save).grid(row=8, column=3)

    def release_drag(self):
        if self.dragging:
            controller = self.drag_mouse
            if controller:
                from pynput.mouse import Button
                controller.release(Button.left)
            self.dragging = False
            self.drag_mouse = None

    def sync_microphone(self):
        if self.feed and hasattr(self.feed, "set_sound"):
            self.feed.set_sound(self.click_method.get() == "Sound" and
                                (self.dwell_enabled.get() or self.sound_testing))

    def change_click_method(self, save=True):
        try:
            self.release_drag()
        except Exception as error:
            self.pause()
            self.notice.set(f"Could not release drag. {error}")
        self.sound.reset()
        self.reset_dwell()
        if self.click_method.get() == "Sound":
            self.dwell_controls.grid_remove()
            self.sound_setup.grid()
        else:
            self.sound_setup.grid_remove()
            self.dwell_controls.grid()
        self.sync_microphone()
        if save:
            self.save_preferences()

    def open_sound_setup(self):
        if getattr(self, "guided", None):
            self.dismiss_guided()
        self.pause()
        dialog = tk.Toplevel(self.root)
        dialog.title("Sound click · test first")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.grid()
        ttk.Label(frame, text="Wear the XIAO where you will use it. Make a short tongue click or mouth pop.\n"
                  "This window counts detections without clicking the computer.\n"
                  "Also test speech, typing and background noise for unwanted detections.").grid(row=0, sticky="w")
        ttk.Progressbar(frame, variable=self.sound_level, maximum=12000, length=430).grid(row=1, sticky="ew", pady=12)
        ttk.Label(frame, textvariable=self.sound_status, wraplength=460).grid(row=2, sticky="w")
        ttk.Label(frame, text="Minimum click level · lower is more sensitive").grid(row=3, sticky="w", pady=(12, 0))
        ttk.Scale(frame, from_=400, to=12000, variable=self.sound_threshold,
                  command=lambda _value: self.save_preferences()).grid(row=4, sticky="ew")
        ttk.Button(frame, text="Learn background · stay quiet for 3 s", command=self.learn_sound_background).grid(row=5, pady=8)
        ttk.Label(frame, text="Short sharp noises can still resemble clicks. Raise the level if needed.\n"
                  "Only sound levels/features leave the board; no audio recording is sent or saved.",
                  style="Hint.TLabel").grid(row=6, sticky="w", pady=6)
        self.sound_testing = True
        self.sound_tests = 0
        self.sound.reset()
        self.sync_microphone()
        def close():
            self.sound_testing = False
            self.sound_learning_until = None
            self.sound.reset()
            self.sync_microphone()
            dialog.destroy()
        ttk.Button(frame, text="Done · return paused", command=close).grid(row=7, pady=(8, 0))
        dialog.protocol("WM_DELETE_WINDOW", close)

    def learn_sound_background(self):
        self.sound_background = []
        self.sound_learning_until = time.monotonic() + 3
        self.sound.reset()
        self.sound_status.set("Stay quiet · learning background for 3 seconds…")

    def handle_sound(self, frame, now):
        self.last_sound_rx = now
        if self.click_method.get() != "Sound":
            return False
        self.sound_level.set(frame.peak)
        self.sound.threshold = self.sound_threshold.get()
        if self.sound_learning_until is not None:
            if frame.status == 0:
                self.sound_background.append(frame.rms)
            if now >= self.sound_learning_until:
                from statistics import median
                if self.sound_background:
                    self.sound.noise = max(1, median(self.sound_background))
                    self.sound_status.set("Background learned. Try a click or pop.")
                else:
                    self.sound_status.set("No microphone readings received.")
                self.sound_learning_until = None
                self.sound.reset()
            return False
        detected = self.sound.update(frame, now)
        self.sound_status.set(f"Test detections: {self.sound_tests} · {self.sound.message}")
        if self.sound_testing:
            if detected:
                self.sound_tests += 1
                self.sound_status.set(f"Test detections: {self.sound_tests} · click/pop detected")
            return False
        if self.action_mode.get() in ("Page", "Scroll"):
            self.dwell_status.set("Scroll mode · clicking paused")
            return False
        self.dwell_status.set(self.sound.message if self.dwell_enabled.get() else "Sound clicks off")
        return (detected and self.active and self.dwell_enabled.get() and not self.capture
                and not self.recentering and self.last_rx is not None and now - self.last_rx <= STALE_AFTER
                and not (self.gestures_enabled.get() and self.gestures.suppress_dwell))

    def perform_click(self):
        if not self.active or self.action_mode.get() in ("Page", "Scroll"):
            return
        if self.action_mode.get() == "Drag":
            if self.dragging:
                self.release_drag()
            else:
                self.dragging = True
                if not self.practice.get():
                    from pynput.mouse import Button
                    self.drag_mouse = self.mouse
                    self.mouse.press(Button.left)
            self.dwell_status.set("Holding · click again to drop" if self.dragging else "Released")
        elif self.practice.get():
            self.practice_clicks += 1
            self.canvas.itemconfigure("practice-count", text=f"Practice actions {self.practice_clicks} · {self.action_mode.get()}")
            self.dwell_status.set(f"Practice: {self.action_mode.get()}")
        else:
            from pynput.mouse import Button
            mode = self.action_mode.get()
            button = Button.right if mode == "Right click" else Button.left
            self.mouse.click(button, 2) if mode == "Double click" else self.mouse.click(button)
            self.dwell_status.set({"Click": "Clicked", "Double click": "Double clicked",
                                   "Right click": "Right clicked"}[mode])
        self.badge_flash_until = time.monotonic() + .18

    def toggle_dwell(self):
        if not self.dwell_enabled.get():
            try:
                self.release_drag()
            except Exception as error:
                self.pause()
                self.notice.set(f"Could not release drag. {error}")
        self.reset_dwell()
        self.sound.reset()
        self.sync_microphone()

    def available_modes(self):
        return MODE_SETS[self.mode_set.get()]

    def change_mode_set(self):
        # Release a held mouse button before moving into a different control set.
        self.change_mode("Click")
        self.mode_picker.configure(values=self.available_modes())
        self.reset_gestures()
        self.save_preferences()

    def change_mode(self, mode):
        if mode == "Page":
            mode = "Scroll"
        if mode not in self.available_modes():
            self.notice.set(f"{mode} is unavailable in {self.mode_set.get()}.")
            return
        try:
            self.release_drag()
        except Exception as error:
            self.pause()
            self.notice.set(f"Could not release drag. {error}")
            return
        self.action_mode.set(mode)
        self.scroll_remainder = 0.0
        self.scroll.reset()
        self.sound.reset()
        self.reset_dwell()
        self.update_mode_indicator()
        self.notice.set({"Click": "Click mode · use your selected sound or dwell action to click.",
                         "Drag": "Drag mode · click to pick up, move, then click again to release.",
                         "Double click": "Double click · one sound or dwell action sends two left clicks.",
                         "Right click": "Right click · one sound or dwell action opens the context menu.",
                         "Scroll": "Scroll mode · tilt down to scroll down, up for up; neutral stops. Recenter resets neutral."}[mode])

    def check_gesture(self, previous, sample):
        if not self.gestures_enabled.get() or self.dragging:
            return False
        rate = tuple(v - b for v, b in zip(sample.gyro, self.motion.bias))
        action = self.gestures.update(*(dot(rate, axis) for axis in self.motion.axes),
                                      seconds(previous, sample) if previous else 0)
        if action:
            if action == "Recenter":
                self.start_recenter()
                return True
            modes = self.available_modes()
            current = "Scroll" if self.action_mode.get() == "Page" else self.action_mode.get()
            mode = action if action != "Cycle modes" else modes[(modes.index(current) + 1) % 3]
            self.change_mode(mode)
            if self.dwell_enabled.get() and self.action_mode.get() == mode and mode not in ("Page", "Scroll"):
                self.dwell.arm()
        self.gesture_status.set(f"Mode: {self.action_mode.get()} · " +
                                ("switched · movement continues" if self.gestures.cooldown else
                                 self.gestures.progress_text))
        return self.gestures.busy or bool(action)

    def update_mode_indicator(self):
        mode = self.action_mode.get()
        colour, title = MODE_STYLE[mode]
        self.canvas.itemconfigure("crosshair", fill=colour)
        self.canvas.itemconfigure("mode-label", fill=colour, text=title)
        if (self.active or self.recentering) and not self.practice.get() and self.mode_badge_enabled.get() and not self.badge_failed:
            try:
                if self.mode_badge is None:
                    if sys.platform != "darwin":
                        raise RuntimeError("The pointer badge is currently available on macOS")
                    self.mode_badge = MacModeBadge()
                timer = (self.active and self.dwell_enabled.get() and self.click_method.get() == "Dwell"
                         and mode not in ("Page", "Scroll") and not self.capture and not self.recentering)
                progress = self.dwell.progress if timer and not self.dwell.waiting_for_movement else 0
                self.mode_badge.show(mode, progress=progress, dwell=bool(timer), dragging=self.dragging,
                                     clicked=time.monotonic() < self.badge_flash_until,
                                     recentering=bool(self.recentering))
            except Exception as error:
                self.badge_failed = True
                if self.mode_badge:
                    self.mode_badge.hide()
                self.notice.set(f"Pointer badge unavailable; control is still active. {error}")
        elif self.mode_badge:
            self.mode_badge.hide()

    def center_practice(self):
        self.practice_position = [self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2]
        self.reset_dwell()
        self.draw_practice()

    def recenter_key(self, event):
        if event.widget.winfo_class() not in ("Entry", "TEntry", "TSpinbox", "TCombobox"):
            self.start_recenter()

    def start_recenter(self):
        if self.guided_running:
            return
        if self.motion is None or self.capture or self.last_rx is None:
            return
        resume, practice = self.active, self.practice.get()
        self.pause()
        self.practice.set(practice)
        self.recentering = (time.monotonic() + 3, resume, practice)
        self.notice.set("Recenter: return your head to a comfortable forward position. 3…")
        self.pointer_status.set("Recentering")
        self.update_buttons()

    def finish_recenter(self, now):
        if not self.recentering:
            return
        deadline, resume, practice = self.recentering
        if now < deadline:
            self.notice.set(f"Recenter: face forward comfortably. {math.ceil(deadline-now)}…")
            return
        self.recentering = None
        if self.last_rx is None or now - self.last_rx > STALE_AFTER or self.motion is None:
            self.pause()
            self.notice.set("Recenter cancelled because readings stopped. Reconnect, then enable control.")
            return
        self.motion.reset()
        self.last_sample = None
        self.feed.drain()
        self.practice.set(practice)
        if resume:
            self.toggle_pointer()
        self.reset_dwell()
        self.notice.set("Head recentered. Pointer position kept." + (" Control resumed." if self.active else ""))
        self.update_buttons()

    def connection_name(self):
        return self.transport.get()

    def select_transport(self):
        if self.feed:
            self.disconnect("Connection changed. Control paused.")
        self.ports.set("")
        self.connect.configure(text=f"Connect {self.connection_name()}")
        self.connection_status.set(f"{self.connection_name()} · disconnected")
        self.refresh_devices()

    def refresh_devices(self):
        if self.connection_name() == "USB":
            self.refresh_ports()
            return
        if self.feed or self.scanning:
            return
        self.scanning = True
        self.notice.set("Looking for Head Mouse over Bluetooth…")
        def scan():
            try:
                result, error = asyncio.run(discover()), None
            except Exception as exc:
                result, error = [], str(exc)
            self.ble_results.put((result, error))
        threading.Thread(target=scan, daemon=True).start()

    def process_discovery(self):
        try:
            results, error = self.ble_results.get_nowait()
        except queue.Empty:
            return
        self.scanning = False
        if self.connection_name() != "Bluetooth" or self.feed:
            return
        if error:
            self.notice.set(f"Bluetooth scan failed. {error}")
            return
        self.ble_devices = {f"{name} · {device.address[-8:]}": device for device, name in results}
        self.ports["values"] = list(self.ble_devices)
        selected = next((label for label, d in self.ble_devices.items() if d.address == self.ble_address),
                        next(iter(self.ble_devices), ""))
        self.ports.set(selected)
        self.notice.set("Select Head Mouse and Connect Bluetooth." if selected else
                        "No Head Mouse found. Power the XIAO and check that Bluetooth firmware is installed.")
        if self.auto_connect and selected and (len(self.ble_devices) == 1 or
                self.ble_devices[selected].address == self.ble_address):
            self.auto_connect = False
            self.toggle_connection()

    def forget_bluetooth(self):
        if self.connection_name() != "Bluetooth":
            return
        if self.feed:
            self.disconnect("Bluetooth disconnected.")
        self.ble_address = self.ble_name = None
        self.save_preferences()
        self.ports.set("")
        self.notice.set("Saved device selection forgotten. To remove an OS pairing, use Bluetooth settings.")

    def draw_practice(self):
        self.canvas.delete("all")
        width, height = max(700, self.canvas.winfo_width()), max(120, self.canvas.winfo_height())
        for x in range(0, width, 35):
            self.canvas.create_line(x, 0, x, height, fill="#254652")
        for y in range(0, height, 30):
            self.canvas.create_line(0, y, width, y, fill="#254652")
        self.canvas.create_text(14, 14, anchor="nw", fill="#94b7bd",
                                text="PRACTICE AREA · move the crosshair with small turns and nods",
                                font=("Helvetica", 10))
        tx, ty = width * .75, height * .6
        self.canvas.create_oval(tx-14, ty-14, tx+14, ty+14, outline="#eda36b", width=2)
        x, y = self.practice_position
        self.canvas.create_line(x-8, y, x+8, y, fill="#d0f5e9", width=2, tags="crosshair")
        self.canvas.create_line(x, y-8, x, y+8, fill="#d0f5e9", width=2, tags="crosshair")
        self.canvas.create_text(x+14, y+14, anchor="nw", text="", font=("Helvetica", 10, "bold"),
                                tags=("crosshair", "mode-label"))
        self.canvas.create_text(width-14, 14, anchor="ne", fill="#eda36b",
                                text=f"Practice actions {self.practice_clicks} · {self.action_mode.get()}", font=("Helvetica", 10),
                                tags="practice-count")
        self.update_mode_indicator()

    def toggle_computer(self):
        if self.guided_running:
            return
        if getattr(self, "guided", None):
            self.dismiss_guided()
        if self.recentering:
            return
        if self.active and not self.practice.get():
            self.pause()
            self.notice.set("Computer control off. Start practice to use the on-screen area.")
            return
        if self.motion is None or self.last_rx is None or self.capture:
            return
        self.pause()
        self.practice.set(False)
        self.toggle_pointer()
        if not self.active:
            self.practice.set(True)
            self.update_buttons()

    def reset_dwell(self):
        self.dwell.reset()
        self.badge_flash_until = 0.0
        self.dwell_status.set(("Waiting for click/pop" if self.dwell_enabled.get() else "Sound clicks off")
                              if self.click_method.get() == "Sound" else
                              ("Move to arm dwell" if self.dwell_enabled.get() else "Dwell clicks off"))
        if hasattr(self, "dwell_progress"):
            self.dwell_progress["value"] = 0
            self.canvas.delete("dwell-ring")

    def change_dwell_time(self, *_args):
        self.reset_dwell()
        duration = self.dwell_duration()
        if duration is not None:
            self.dwell.seconds = duration
            self.save_preferences()
        else:
            self.dwell_status.set("Choose 0.5–3 seconds")

    def dwell_duration(self):
        try:
            duration = self.dwell_seconds.get()
        except (tk.TclError, ValueError):
            return None
        return duration if math.isfinite(duration) and .5 <= duration <= 3 else None

    def update_dwell(self, now):
        if not self.active or not self.dwell_enabled.get() or self.click_method.get() != "Dwell":
            return
        if self.action_mode.get() in ("Page", "Scroll"):
            self.reset_dwell()
            self.dwell_status.set("Scroll mode")
            return
        try:
            duration = self.dwell_duration()
            if duration is None:
                self.reset_dwell()
                self.dwell_status.set("Choose 0.5–3 seconds")
                return
            self.dwell.seconds = duration
            position = self.practice_position if self.practice.get() else self.mouse.position
            if self.gestures_enabled.get() and self.gestures.suppress_dwell:
                self.dwell.suspend(position, now)
                self.dwell_progress["value"] = 0
                self.canvas.delete("dwell-ring")
                self.dwell_status.set("Circle confirmed · hold still to dwell")
                return
            clicked = self.dwell.update(position, now)
            self.dwell_progress["value"] = self.dwell.progress * 100
            self.canvas.delete("dwell-ring")
            if self.dwell.waiting_for_movement:
                self.dwell_status.set("Move to arm dwell")
            else:
                remaining = duration * (1 - self.dwell.progress)
                verb = ("Release" if self.dragging else "Pick up") if self.action_mode.get() == "Drag" else self.action_mode.get().capitalize()
                self.dwell_status.set(f"{verb} in {remaining:.1f} s")
                if self.practice.get():
                    x, y = self.practice_position
                    self.canvas.create_arc(x-18, y-18, x+18, y+18, start=90,
                                           extent=-360*self.dwell.progress, outline="#a6e6ca",
                                           width=3, style="arc", tags="dwell-ring")
            if clicked:
                self.perform_click()
        except Exception as error:
            self.pause()
            self.notice.set(f"Dwell click failed. {error}")

    def cancel_capture(self):
        self.capture = None
        self.rezero = False
        self.progress["value"] = 0
        self.notice.set("Capture cancelled. Choose a calibration step when ready.")
        self.update_buttons()

    def refresh_ports(self):
        ports = sorted(list_ports.comports())
        devices = [port.device for port in ports]
        selected = self.ports.get()
        self.ports["values"] = devices
        if selected not in devices:
            xiao = next((port.device for port in ports if port.vid == 0x2886
                         and port.pid in (0x8045, 0x0045)), None)
            self.ports.set(xiao or (devices[0] if len(devices) == 1 else ""))

    def toggle_connection(self):
        if self.feed:
            self.disconnect("Disconnected.")
            return
        device = self.ports.get()
        if not device:
            self.notice.set("Power the XIAO, then click Find device and select it.")
            return
        try:
            if self.connection_name() == "Bluetooth":
                check_bluetooth_usage()
                selected = self.ble_devices.get(device)
                if selected is None:
                    self.notice.set("Click Find device and select a Head Mouse first.")
                    return
                self.feed = BleFeed(selected)
                self.ble_address, self.ble_name = selected.address, selected.name or "Head Mouse"
                self.save_preferences()
            else:
                self.port = serial.Serial(device, BAUD, timeout=.05)
                self.feed = SerialFeed(self.port)
        except (OSError, serial.SerialException, RuntimeError) as error:
            self.notice.set(f"Could not open {device}. {error}")
            return
        self.connect.configure(text="Disconnect")
        self.ports.configure(state="disabled")
        self.sync_microphone()
        self.transport_picker.configure(state="disabled")
        self.connection_status.set(f"{self.connection_name()} · connecting")
        self.notice.set("Waiting for the XIAO. Bluetooth may ask you to approve pairing.")
        self.update_buttons()

    def disconnect(self, message):
        self.stop_guided("Device disconnected. Reconnect, then restart calibration.")
        self.pause()
        self.capture = None
        self.last_rx = None
        self.last_sample = None
        self.bias = self.right = self.down = self.motion = None
        if self.feed:
            self.feed.close()
            self.feed = None
        if self.port:
            port, self.port = self.port, None
            try:
                port.close()
            except OSError:
                pass
        self.restore_profile()
        self.connect.configure(text=f"Connect {self.connection_name()}")
        self.ports.configure(state="readonly")
        self.transport_picker.configure(state="readonly")
        self.connection_status.set(f"{self.connection_name()} · disconnected")
        self.telemetry.set("Waiting for IMU data")
        self.notice.set(message)
        self.update_buttons()

    def close(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        if self.menu_bar:
            self.menu_bar.close()
            self.menu_bar = None
        self.save_preferences()
        self.disconnect("")
        if self.mode_badge:
            self.mode_badge.close()
        self.root.destroy()

    def update_buttons(self):
        ready = self.last_rx is not None and self.capture is None and not self.active and not self.recentering and not self.guided_running
        for button, available in zip(
            self.calibration,
            (True, self.bias is not None, self.bias is not None and self.right is not None),
        ):
            button.configure(state="normal" if ready and available else "disabled")
        computer_active = self.active and not self.practice.get()
        self.arm.configure(
            text="Pause practice" if self.active and self.practice.get() else "Start practice",
            state="normal" if self.practice.get() and
            (self.active or (ready and self.motion is not None)) else "disabled",
        )
        self.computer_button.configure(
            text="Computer control ON · turn off" if computer_active else "Computer control OFF · turn on",
            style="Stop.TButton" if computer_active else "Primary.TButton",
            state="normal" if computer_active or
            (self.last_rx is not None and self.capture is None and self.motion is not None and
             not self.recentering and not self.guided_running) else "disabled",
        )
        self.rezero_button.configure(
            state="normal" if ready and self.right is not None and self.down is not None else "disabled")
        self.cancel_button.configure(state="normal" if self.capture else "disabled")
        self.recenter_button.configure(state="normal" if self.motion is not None and
                                       self.last_rx is not None and not self.capture and not self.recentering else "disabled")
        for variable, title, complete in zip(
            self.step_labels, ("1. Hold still", "2. Turn right", "3. Nod down"),
            (self.bias is not None, self.right is not None, self.down is not None),
        ):
            variable.set(("✓ " if complete else "") + title)
        self.pointer_status.set(("Practice active" if self.practice.get() else "Pointer active")
                                if self.active else "Recentering" if self.recentering else "Paused")

    def pause(self):
        was_recentering = self.recentering is not None
        self.recentering = None
        release_error = None
        try:
            self.release_drag()
        except Exception as error:
            release_error = error
        self.gestures.reset()
        self.scroll_remainder = 0.0
        self.scroll.reset()
        self.sound.reset()
        self.reset_dwell()
        if self.active or was_recentering:
            self.active = False
            self.practice.set(True)
            self.motion.reset()
            self.notice.set("Paused. Reposition your head, then press Start when ready.")
        self.update_buttons()
        if release_error:
            self.notice.set(f"Mouse release failed. {release_error}")
        self.update_mode_indicator()

    def toggle_pointer(self):
        if self.guided_running:
            return
        if self.active:
            self.pause()
            return
        if self.motion is None or self.last_rx is None or self.capture:
            return
        if self.recentering:
            return
        try:
            if not self.practice.get() and sys.platform == "darwin":
                import Quartz
                if not Quartz.CGPreflightPostEventAccess():
                    self.notice.set(
                        "macOS has blocked mouse control. Allow Head Mouse in System Settings "
                        "→ Privacy & Security → Accessibility, then turn Computer control on again."
                    )
                    return
            if not self.practice.get() and self.mouse is None:
                if sys.platform == "darwin":
                    from macos_pointer import create_controller
                    self.mouse = create_controller()
                else:
                    from pynput.mouse import Controller
                    self.mouse = Controller()
            # Controller initialization can pause the UI. Begin with fresh data.
            self.feed.drain()
            self.last_sample = None
            self.last_rx = time.monotonic()
        except Exception as error:
            self.notice.set(f"Could not start movement. {error}")
            return
        self.motion.reset()
        self.scroll.reset()
        self.reset_gestures()
        self.reset_dwell()
        self.active = True
        self.notice.set("Practice active. Turn or nod slightly to move the crosshair."
                        if self.practice.get() else
                        "Computer control active. Use OFF, Esc in this window, or Disconnect to stop.")
        self.update_buttons()
        self.update_mode_indicator()

    def start_capture(self, step, preserve_axes=False):
        if getattr(self, "guided", None):
            self.dismiss_guided()
        self.pause()
        self.rezero = preserve_axes
        # Discard downstream results when repeating an earlier step.
        self.motion = None
        if step == "zero":
            self.bias = None
        if step in ("zero", "right") and not preserve_axes:
            self.right = self.down = None
        if step == "down":
            self.down = None
        self.capture = (step, time.monotonic() + 3, [])
        self.zero_check_at = 0.0
        self.progress["value"] = 0
        self.notice.set(PROMPTS[step] + " Starting in 3…")
        self.update_buttons()

    def collect(self, sample, now):
        step, starts_at, samples = self.capture
        if now < starts_at:
            self.progress["value"] = 0
            self.notice.set(f"{PROMPTS[step]}  Starting in {math.ceil(starts_at - now)}…")
            return
        samples.append(sample)
        if step == "zero":
            # Keep a moving two-second window: a brief twitch no longer fails
            # the entire capture and forces the user to press the button again.
            while len(samples) > 2 and seconds(samples[1], sample) >= 2:
                samples.pop(0)
            if now - starts_at >= 15:
                self.capture = None
                self.rezero = False
                self.progress["value"] = 0
                self.notice.set("Could not find a steady reading yet. Rest your head or support the device, "
                                "let the USB cable hang loosely, then try Hold still again.")
                self.update_buttons()
                return
        duration = 2 if step == "zero" else 3
        elapsed = seconds(samples[0], sample)
        self.progress["value"] = min(100, elapsed / duration * 100)
        if elapsed < duration:
            prompt = {"zero": "Hold still", "right": "GO → turn right once, then hold",
                      "down": "GO ↓ nod down once, then hold"}[step]
            self.notice.set(f"{prompt}… {math.ceil(duration - elapsed)}")
            return
        if step == "zero":
            if now < self.zero_check_at:
                return
            self.zero_check_at = now + .15
            try:
                zero_gyro(samples)
            except ValueError:
                self.notice.set("Let your head settle · checking automatically… "
                                f"{max(1, math.ceil(15 - (now - starts_at)))} seconds remaining.")
                return
        self.capture = None
        try:
            if step == "zero":
                self.bias = zero_gyro(samples)
                if self.rezero and self.right is not None and self.down is not None:
                    self.motion = PointerMotion(self.bias, self.right, self.down)
                    self.notice.set("Drift zeroed. Mounting axes kept. Press Start when ready.")
                else:
                    self.notice.set("Still reading saved. Click 2. Turn right, then wait for GO.")
            elif step == "right":
                self.right = gesture_axis(samples, self.bias)
                self.notice.set("Right turn saved. Return to center, then click 3. Nod down.")
            else:
                down = gesture_axis(samples, self.bias)
                self.motion = PointerMotion(self.bias, self.right, down)
                self.down = down
                self.notice.set("Calibration saved. Return to center, then press Start practice.")
            if self.motion:
                self.save_preferences()
        except ValueError as error:
            self.notice.set(str(error))
        self.rezero = False
        self.update_buttons()

    def interrupt_stream(self, message):
        self.stop_guided(message + " Reconnect, then restart calibration.")
        self.pause()
        self.last_rx = None
        self.last_sample = None
        self.capture = None
        self.rezero = False
        self.progress["value"] = 0
        self.connection_status.set(f"{self.connection_name()} · waiting for data")
        self.telemetry.set("Waiting for IMU data")
        self.notice.set(message)
        self.update_buttons()

    def read_stream(self, now):
        events, dropped, failure = self.feed.drain()
        if failure:
            self.disconnect(f"{self.connection_name()} connection lost. {failure}")
            return
        if not events:
            if self.last_rx is not None and now - self.last_rx > STALE_AFTER:
                self.interrupt_stream("Readings stopped. Check the device and connection.")
            return
        if now - events[-1][0] > STALE_AFTER:
            self.interrupt_stream("Readings are stale. Check the device and connection.")
            return

        # Discard old motion after a slow GUI/OS call. The reader keeps running,
        # so freshness comes from sample receipt times, not GUI callback timing.
        fresh = [(received, event) for received, event in events
                 if isinstance(event, str) or now - received <= .06]
        if dropped or len(fresh) < len(events):
            if self.motion:
                self.motion.reset()
            self.last_sample = None
            self.gestures.reset()
            self.reset_dwell()
            self.stop_guided("Capture interrupted by a delayed update. Restart calibration.")
            if self.capture:
                self.cancel_capture()
                self.notice.set("Capture interrupted by a delayed update. Repeat this step.")
        dx = dy = 0
        scroll_steps = 0
        sound_requested = False
        latest = None
        for received, event in fresh:
            if isinstance(event, str):
                message = event
                if message.startswith("HM1,"):
                    message = "IMU started. Waiting for samples."
                self.interrupt_stream(message)
                latest = None
                continue
            if isinstance(event, SoundFrame):
                sound_requested |= self.handle_sound(event, received)
                continue
            sample = event
            if self.last_sample and not 0 < seconds(self.last_sample, sample) <= .06:
                self.interrupt_stream("IMU samples were interrupted.")
            if self.last_rx is None:
                self.last_rx = received
                if self.motion:
                    self.notice.set("Readings restored. Press Start when ready.")
                elif self.right is not None and self.down is not None:
                    self.notice.set("Saved mounting loaded. Click Re-zero drift and hold still. "
                                    "Repeat all three steps if the mounting changed.")
                else:
                    self.notice.set("XIAO connected. Click 1. Hold still to begin calibration.")
                self.connection_status.set(f"{self.connection_name()} · XIAO connected")
                self.update_buttons()
            self.last_rx = received
            previous = self.last_sample
            self.last_sample = sample
            latest = sample
            if self.guided_running:
                self.guided.collect(sample, received)
            elif self.capture:
                self.collect(sample, received)
            elif self.active:
                self.check_gesture(previous, sample)
                if not self.active:
                    dx = dy = 0
                    continue
                gain = self.gain.get() * (1 if self.practice.get() else self.sensitivity.get())
                if self.action_mode.get() == "Scroll":
                    scroll_steps += self.scroll.update(sample, self.motion.bias, self.motion.axes[1],
                                                       1 if self.practice.get() else self.sensitivity.get())
                x, y = self.motion.update(sample, gain, self.deadzone.get())
                dx += x
                dy += y
        if latest:
            accel = "  ".join(f"{v:+.2f}" for v in latest.accel)
            gyro = "  ".join(f"{v:+.1f}" for v in latest.gyro)
            self.telemetry.set(f"Accel (g)  {accel}     Gyro (°/s)  {gyro}")
        if self.last_rx is not None and now - self.last_rx > STALE_AFTER:
            self.interrupt_stream("Motion readings stopped. Control paused.")
            return
        if self.active and self.action_mode.get() == "Scroll":
            try:
                if self.practice.get():
                    self.practice_scroll -= scroll_steps
                    self.canvas.itemconfigure("practice-count", text=f"Scroll {self.practice_scroll} · tilt {self.scroll.angle:+.1f}°")
                elif scroll_steps:
                    self.mouse.scroll(0, scroll_steps)
            except Exception as error:
                self.pause()
                self.notice.set(f"Scroll failed. {error}")
            dx = dy = 0
        if self.active and (dx or dy):
            try:
                if self.action_mode.get() == "Page":
                    self.scroll_remainder -= dy / 40
                    steps = math.trunc(self.scroll_remainder)
                    self.scroll_remainder -= steps
                    if self.practice.get():
                        self.practice_scroll -= steps
                        self.canvas.itemconfigure("practice-count", text=f"Scroll position {self.practice_scroll}")
                    elif steps:
                        self.mouse.scroll(0, steps)
                elif self.practice.get():
                    width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
                    old_x, old_y = self.practice_position
                    self.practice_position[0] = max(0, min(width, old_x + dx))
                    self.practice_position[1] = max(0, min(height, old_y + dy))
                    self.canvas.move("crosshair", self.practice_position[0] - old_x,
                                     self.practice_position[1] - old_y)
                    if self.dragging:
                        self.canvas.itemconfigure("practice-count", text="Holding · dwell again to release")
                else:
                    self.mouse.move(dx, dy)
            except Exception as error:
                self.pause()
                self.notice.set(f"Mouse control failed. {error}")
        if sound_requested and self.active:
            try:
                self.perform_click()
            except Exception as error:
                self.pause()
                self.notice.set(f"Sound click failed. {error}")

    def service_controls(self):
        if getattr(self, "_servicing_controls", False):
            return
        self._servicing_controls = True
        try:
            self.process_discovery()
            if self.feed:
                try:
                    self.read_stream(time.monotonic())
                    if self.feed:
                        self.update_dwell(time.monotonic())
                except (OSError, serial.SerialException) as error:
                    self.disconnect(f"{self.connection_name()} connection lost. {error}")
            self.finish_guided(time.monotonic())
            self.finish_recenter(time.monotonic())
            if self.click_method.get() == "Sound" and (self.sound_testing or self.dwell_enabled.get()):
                if self.last_sound_rx is None or time.monotonic() - self.last_sound_rx > .3:
                    self.sound_status.set("Waiting for XIAO microphone · check connection and firmware")
            self.update_mode_indicator()
        finally:
            self._servicing_controls = False

    def poll(self):
        if self.menu_bar:
            self.menu_bar.process_actions()
        self.service_controls()
        if self.menu_bar:
            self.menu_bar.sync()
        self.root.after(20, self.poll)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="USB serial port to connect when the app opens")
    parser.add_argument("--menu-helper", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--self-check", action="store_true", help="Verify bundled components without connecting or controlling the mouse")
    parser.add_argument("--diagnose", action="store_true", help="Show launcher metadata and exit")
    parser.add_argument("--bluetooth", action="store_true", help="Find and connect to the Bluetooth head mouse")
    parser.add_argument("--check-bluetooth", action="store_true", help="Check raw Bluetooth readings without controlling the pointer")
    parser.add_argument("--check-sound", action="store_true", help="Check XIAO microphone features and motion without mouse input")
    parser.add_argument("--sound-setup", action="store_true", help="Open the non-clicking sound test")
    args = parser.parse_args()
    if args.menu_helper:
        from menu_bar import run_child
        run_child()
        raise SystemExit(0)
    if args.self_check:
        import json
        from packaged_checks import run_checks
        print(json.dumps(run_checks(), indent=2))
        raise SystemExit(0)
    if args.diagnose:
        from Foundation import NSBundle
        print("Bundle:", NSBundle.mainBundle().bundlePath())
        print("Bluetooth usage:", NSBundle.mainBundle().objectForInfoDictionaryKey_("NSBluetoothAlwaysUsageDescription"))
        print("Python:", sys.executable)
        import Quartz
        print("Mouse control allowed:", bool(Quartz.CGPreflightPostEventAccess()))
        raise SystemExit(0)
    if args.check_bluetooth or args.check_sound:
        from ble_feed import check_stream
        asyncio.run(check_stream(sound=args.check_sound))
        raise SystemExit(0)
    window = tk.Tk()
    app = HeadMouse(window)
    if args.port:
        app.ports.set(args.port)
        app.toggle_connection()
    elif args.bluetooth or (load_profile() or {}).get("transport", "Bluetooth" if app.ble_address else "USB") == "Bluetooth":
        app.auto_connect = True
        app.transport.set("Bluetooth")
        app.select_transport()
    if args.sound_setup:
        app.click_method.set("Sound")
        app.change_click_method()
        window.after(500, app.open_sound_setup)
    if app.menu_bar and not args.sound_setup:
        window.withdraw()
        window.after(500, app.menu_bar.toggle)
    else:
        window.lift()
    window.mainloop()
