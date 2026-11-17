"""Encrypted BLE IMU notifications, buffered independently of the GUI."""
import asyncio
from collections import deque
import struct
import threading
import time

from motion import Sample
from sound_click import SoundFrame
from serial_feed import SerialFeed

SERVICE_UUID = "1c863b10-6d35-4f80-9eb5-71e146bb7930"
DATA_UUID = "1c863b11-6d35-4f80-9eb5-71e146bb7930"
CONTROL_UUID = "1c863b12-6d35-4f80-9eb5-71e146bb7930"
PACKET = struct.Struct("<BBHI6h")


def decode_packet(data):
    if len(data) != PACKET.size:
        raise ValueError("Unexpected Bluetooth packet length")
    version, flags, sequence, timestamp, *counts = PACKET.unpack(data)
    if version != 1 or flags not in (0, 1):
        raise ValueError("Unsupported Bluetooth packet version or status")
    if flags == 1:
        _, _, _, _, peak, rms, high, samples, status, reserved = struct.unpack("<BBHI6H", data)
        if status not in (0, 1, 2) or reserved:
            raise ValueError("Unsupported microphone status")
        return sequence, SoundFrame(timestamp, peak, rms, high, samples, status)
    return sequence, Sample(timestamp, tuple(v/16384 for v in counts[:3]),
                            tuple(v/131 for v in counts[3:]))


def check_bluetooth_usage():
    import sys
    if sys.platform == "darwin":
        from Foundation import NSBundle
        if not NSBundle.mainBundle().objectForInfoDictionaryKey_("NSBluetoothAlwaysUsageDescription"):
            raise RuntimeError("Open Head Mouse.app to use Bluetooth. The plain Python launcher "
                               "does not declare the Bluetooth permission required by macOS.")


async def discover():
    check_bluetooth_usage()
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=5, service_uuids=[SERVICE_UUID], return_adv=True)
    return [(device, advertisement.local_name or device.name or "Head Mouse")
            for device, advertisement in found.values()]


class BleFeed:
    publish = SerialFeed.publish
    drain = SerialFeed.drain

    def __init__(self, device, client_factory=None):
        self.device = device
        self.client_factory = client_factory
        self.events = deque(maxlen=256)
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.dropped = 0
        self.failure = None
        self.last_sequence = None
        self.ever_streamed = False
        self.last_notification = None
        self.loop = self.task = None
        self.sound_enabled = False
        self.thread = threading.Thread(target=self.read, name="head-mouse-bluetooth", daemon=True)
        self.thread.start()

    def notification(self, _sender, data):
        try:
            sequence, sample = decode_packet(data)
        except ValueError as error:
            with self.lock:
                self.failure = str(error)
            return
        if self.last_sequence is not None:
            delta = (sequence - self.last_sequence) & 0xffff
            if delta == 0:
                return  # Never replay duplicate motion.
            if delta >= 0x8000:
                self.publish("Bluetooth packet sequence restarted. Control paused.")
            elif delta != 1:
                with self.lock:
                    self.dropped += delta - 1
        self.last_sequence = sequence
        self.ever_streamed = True
        self.last_notification = time.monotonic()
        self.publish(sample)

    def read(self):
        async def main():
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.current_task()
            if not self.stopped.is_set():
                await self.reconnect()
        try:
            asyncio.run(main())
        except asyncio.CancelledError:
            pass
        except Exception as error:
            if not self.stopped.is_set():
                with self.lock:
                    self.failure = str(error)

    async def reconnect(self):
        delay = 1
        while not self.stopped.is_set():
            try:
                await self.run()
                return
            except Exception as error:
                if self.stopped.is_set():
                    return
                if not self.ever_streamed or isinstance(error, ValueError):
                    raise
                self.publish(f"Bluetooth disconnected. Control paused; reconnecting in {delay} s.")
                self.last_sequence = None
                self.last_notification = None
                until = time.monotonic() + delay
                while not self.stopped.is_set() and time.monotonic() < until:
                    await asyncio.sleep(.05)
                delay = min(8, delay * 2)

    async def run(self):
        if self.client_factory is None:
            check_bluetooth_usage()
            from bleak import BleakClient
            factory = BleakClient
        else:
            factory = self.client_factory
        # Discovery runs in a separate worker/asyncio loop. CoreBluetooth's
        # BLEDevice.details owns that loop's manager, so never pass it across
        # loops. Resolve the stable host-local identifier inside THIS loop.
        address = getattr(self.device, "address", self.device)
        self.publish("Bluetooth connecting. Approve any Head Mouse pairing request.")
        async with factory(address, timeout=45, pair=True) as client:
            if self.stopped.is_set():
                return
            # Reading requires encryption and triggers macOS pairing if needed.
            self.publish("Bluetooth connected. Waiting for encrypted pairing…")
            version = await asyncio.wait_for(client.read_gatt_char(CONTROL_UUID), 45)
            if bytes(version) not in (b"\x01", b"\x02"):
                raise ValueError("Unsupported Head Mouse Bluetooth firmware")
            self.publish("Bluetooth paired. Starting motion readings…")
            await asyncio.wait_for(client.start_notify(DATA_UUID, self.notification), 15)
            await asyncio.wait_for(client.write_gatt_char(CONTROL_UUID, b"\x01", response=True), 10)
            connected_at = time.monotonic()
            mic_applied = None
            try:
                while not self.stopped.is_set():
                    if not client.is_connected:
                        raise ConnectionError("Bluetooth disconnected. Reconnect, then enable control again.")
                    if time.monotonic() - (self.last_notification or connected_at) > 5:
                        raise ConnectionError("Bluetooth connected but motion readings stopped")
                    with self.lock:
                        failure = self.failure
                    if failure:
                        raise ValueError(failure)
                    desired = getattr(self, "sound_enabled", False)
                    if mic_applied != desired:
                        if bytes(version) == b"\x02":
                            await asyncio.wait_for(client.write_gatt_char(CONTROL_UUID, b"\x03" if desired else b"\x02", response=True), 3)
                        elif desired:
                            self.publish(SoundFrame(0, 0, 0, 0, 0, 1))
                        mic_applied = desired
                    await asyncio.sleep(.02)
            finally:
                if client.is_connected:
                    await asyncio.wait_for(client.write_gatt_char(CONTROL_UUID, b"\x00", response=True), 3)
                    await asyncio.wait_for(client.stop_notify(DATA_UUID), 3)

    def set_sound(self, enabled):
        self.sound_enabled = bool(enabled)

    def close(self):
        self.stopped.set()
        if self.loop is not None and self.task is not None:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass  # Worker already exited and closed its event loop.
        # Cancel even a pending pairing/subscribe operation, so switching back
        # to USB cannot leave an invisible BLE connection holding the device.
        self.thread.join(timeout=.1)


async def check_stream(sound=False):
    """Read-only hardware check: never initializes a mouse controller."""
    # An embedded macOS launcher needs its AppKit run loop pumped for native
    # Bluetooth/pairing callbacks, even when this diagnostic has no visible UI.
    import sys
    root = task = None
    if sys.platform == "darwin":
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        async def pump():
            while True:
                root.update()
                await asyncio.sleep(.01)
        task = asyncio.create_task(pump())
    try:
        await _check_stream(sound=sound)
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if root:
            root.destroy()


async def _check_stream(sound=False):
    import json
    from preferences import load_profile
    devices = await discover()
    profile = load_profile() or {}
    selected = next((d for d, _name in devices if d.address == profile.get("ble_address")), None)
    if selected is None and len(devices) == 1:
        selected = devices[0][0]
    if selected is None:
        raise RuntimeError("No unique Head Mouse found; select one in the app first")
    stream = BleFeed(selected)
    stream.set_sound(sound)
    audio = []
    samples, dropped, status = [], 0, []
    first = last = None
    deadline = time.monotonic() + 50
    try:
        while time.monotonic() < deadline:
            events, missing, failure = stream.drain()
            dropped += missing
            if failure:
                raise RuntimeError(failure)
            for received, sample in events:
                if isinstance(sample, str):
                    status.append(sample)
                    print(sample, flush=True)
                elif isinstance(sample, SoundFrame):
                    audio.append(sample)
                elif isinstance(sample, Sample):
                    samples.append(sample)
                    first = received if first is None else first
                    last = received
            if first is not None and time.monotonic() - first >= 10:
                break
            await asyncio.sleep(.02)
        if len(samples) < 100:
            raise RuntimeError("Too few Bluetooth samples received")
        from motion import seconds
        gaps = [seconds(a, b) for a, b in zip(samples, samples[1:])]
        rate = (len(samples)-1)/(last-first)
        healthy = rate >= 60 and max(gaps) <= .06 and not any("disconnected" in s for s in status)
        report = {"device": selected.name, "samples": len(samples),
                          "duration_seconds": round(last-first, 3),
                          "sample_rate_hz": round(rate, 1),
                          "max_device_gap_ms": round(max(gaps)*1000, 2),
                          "missing_packets": dropped, "healthy": healthy, "status": status}
        if sound:
            from statistics import median
            report.update(microphone_frames=len(audio),
                          microphone_peak_max=max((f.peak for f in audio), default=0),
                          microphone_rms_median=median([f.rms for f in audio]) if audio else 0,
                          microphone_errors=sum(f.status != 0 for f in audio))
            healthy &= len(audio) >= 100 and all(f.status == 0 for f in audio)
            report["healthy"] = healthy
        print(json.dumps(report, indent=2))
        if not healthy:
            raise RuntimeError("Bluetooth stream is too slow or interrupted for reliable pointer calibration")
    finally:
        stream.close()
        await asyncio.to_thread(stream.thread.join, 2)
