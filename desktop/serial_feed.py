"""Read and timestamp USB samples independently of GUI and mouse event delays."""
from collections import deque
import threading
import time

import serial

from motion import decode
from sound_click import decode_sound


class SerialFeed:
    def __init__(self, port):
        self.port = port
        self.events = deque(maxlen=256)
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.dropped = 0
        self.failure = None
        self.sound_enabled = False
        self.thread = threading.Thread(target=self.read, name="head-mouse-usb", daemon=True)
        self.thread.start()

    def publish(self, event):
        with self.lock:
            if len(self.events) == self.events.maxlen:
                self.dropped += 1
            self.events.append((time.monotonic(), event))

    def read(self):
        buffer = bytearray()
        mic_applied = False  # Firmware powers up/disconnects with the mic off.
        try:
            while not self.stopped.wait(.005):
                if mic_applied != self.sound_enabled:
                    self.port.write(b"M1\n" if self.sound_enabled else b"M0\n")
                    mic_applied = self.sound_enabled
                waiting = self.port.in_waiting
                if not waiting:
                    continue
                buffer.extend(self.port.read(min(waiting, 16384)))
                *lines, remainder = buffer.split(b"\n")
                buffer = bytearray(remainder) if len(remainder) <= 100 else bytearray()
                for line in lines:
                    if line.startswith(b"#"):
                        self.publish(line[1:].decode("ascii", errors="replace").strip())
                    else:
                        sample = decode(line) or decode_sound(line)
                        if sample is not None:
                            self.publish(sample)
        except (OSError, serial.SerialException) as error:
            with self.lock:
                self.failure = str(error)

    def set_sound(self, enabled):
        self.sound_enabled = bool(enabled)

    def drain(self):
        with self.lock:
            events = list(self.events)
            self.events.clear()
            dropped, self.dropped = self.dropped, 0
            return events, dropped, self.failure

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=.5)
