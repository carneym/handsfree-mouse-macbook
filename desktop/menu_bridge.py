"""Keep Cocoa's menu event loop separate from Tk and pointer control.

Only local child-process pipes are used. No network listener or input permission
is needed by the menu process. The calibration process remains the sole owner
of the device, calibration and real mouse events.
"""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

VARIABLES = ('transport', 'mode_set', 'action_mode', 'click_method', 'gain',
             'deadzone', 'sensitivity', 'dwell_seconds', 'gestures_enabled',
             'mode_badge_enabled', 'practice', 'notice', 'connection_status')
COMMANDS = {'toggle_computer', 'change_mode_set', 'change_mode', 'change_click_method',
            'start_recenter', 'refresh_devices', 'toggle_connection', 'reset_gestures',
            'update_mode_indicator', 'open_sound_setup', 'start_capture',
            'select_transport', 'save_preferences', 'pause', 'start_guided', 'retry_guided', 'dismiss_guided', 'start_guided_control'}


class MenuBarBridge:
    def __init__(self, app):
        self.app, self.pending = app, queue.Queue()
        self.outgoing = queue.Queue(maxsize=1)
        self.next_sync = 0
        self.closing = False
        if getattr(sys, 'frozen', False):
            helper = Path(sys.executable).resolve().parent.parent / 'Helpers/Head Mouse Menu.app/Contents/MacOS/Head Mouse Menu'
            if not helper.is_file():
                raise RuntimeError('The menu helper is missing. Reinstall Head Mouse.')
            command = [str(helper)]
        else:
            helper = Path(__file__).resolve().parent.parent / 'Head Mouse.app/Contents/Helpers/Head Mouse Menu.app/Contents/MacOS/HeadMouseMenu'
            command = [str(helper), '--menu-helper'] if helper.exists() else [sys.executable, str(Path(__file__).with_name('menu_bar.py')), '--child']
        self.process = subprocess.Popen(command,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self.read, daemon=True, name='head-mouse-menu-reader').start()
        threading.Thread(target=self.write, daemon=True, name='head-mouse-menu-writer').start()
        self.sync(force=True)

    def read(self):
        for line in self.process.stdout:
            try:
                self.pending.put(json.loads(line))
            except ValueError:
                continue
        if not self.closing:
            self.pending.put({'error': 'The menu bar closed. Full setup is still available.'})

    def write(self):
        while True:
            message = self.outgoing.get()
            if message is None:
                return
            try:
                self.process.stdin.write(json.dumps(message, allow_nan=False) + '\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                return

    def send(self, message):
        try:
            self.outgoing.put_nowait(message)
        except queue.Full:
            try:
                self.outgoing.get_nowait()
            except queue.Empty:
                pass
            self.outgoing.put_nowait(message)

    def process_actions(self):
        while True:
            try:
                message = self.pending.get_nowait()
            except queue.Empty:
                return
            try:
                self.apply(message)
            except Exception as error:
                self.app.pause()
                self.app.notice.set(f'Menu action failed. {error}')

    def apply(self, message):
        a = self.app
        if 'error' in message:
            a.stop_guided('The calibration display closed. Restart calibration after reopening the menu.')
            a.pause()
            self.close()
            a.menu_bar = None
            a.root.deiconify()
            a.notice.set(message['error'])
            return
        action, args, kwargs = message.get('action'), message.get('args', []), message.get('kwargs', {})
        if action == 'set_variable':
            name, value = args
            if name not in VARIABLES or name in ('notice', 'connection_status', 'practice'):
                raise ValueError('Unknown menu setting')
            if name in ('gain', 'deadzone', 'sensitivity'):
                from menu_bar import set_tuning
                set_tuning(a, name, value)
            elif name == 'dwell_seconds':
                if not .5 <= float(value) <= 3:
                    raise ValueError('Invalid dwell time')
                a.dwell_seconds.set(round(float(value), 1))
            elif name in ('mode_set', 'transport', 'click_method', 'action_mode'):
                choices = {'mode_set': ('Mode 1', 'Mode 2'), 'transport': ('USB', 'Bluetooth'),
                           'click_method': ('Dwell', 'Sound'), 'action_mode': a.available_modes()}
                if value not in choices[name]:
                    raise ValueError('Invalid menu choice')
                getattr(a, name).set(value)
            else:
                getattr(a, name).set(bool(value))
        elif action == 'device':
            if not a.feed and args[0] in a.ports['values']:
                a.ports.set(args[0])
        elif action == 'show_setup':
            if sys.platform == 'darwin':
                from AppKit import NSApplication
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            a.root.deiconify()
            a.root.lift()
        elif action == 'quit':
            a.root.after_idle(a.close)
        elif action in COMMANDS:
            if action == 'select_transport':
                a.auto_connect = False
            getattr(a, action)(*args, **kwargs)
        else:
            raise ValueError('Unknown menu action')

    def sync(self, force=False):
        now = time.monotonic()
        if not force and now < self.next_sync:
            return
        self.next_sync = now + .1
        a = self.app
        state = {name: getattr(a, name).get() for name in VARIABLES}
        state.update(active=a.active, motion=a.motion is not None, last_rx=a.last_rx,
                     capture=bool(a.capture), recentring=bool(a.recentering), feed=bool(a.feed),
                     right=a.right is not None, down=a.down is not None, scanning=a.scanning,
                     devices=list(a.ports['values']), device=a.ports.get(),
                     guided_running=a.guided_running,
                     guided=a.guided.snapshot(now) if getattr(a, 'guided', None) else None)
        self.send({'state': state})

    def toggle(self):
        # The menu opens once after receiving its first complete state.
        pass

    def close(self):
        self.closing = True
        self.send(None)
        try:
            self.process.terminate()
        except ProcessLookupError:
            pass
        threading.Thread(target=self.process.wait, daemon=True).start()
