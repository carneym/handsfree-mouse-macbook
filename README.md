# Handsfree Mouse

Control a Mac pointer with small head turns and nods using a **Seeed Studio XIAO nRF52840 Sense** mounted on glasses or an ear clip. A menu bar app connects over USB or Bluetooth, guides calibration, and provides dwell or mouth-sound clicking, scrolling and gesture controls.

The current desktop app is named **Head Mouse**. This repository is **Handsfree Mouse**; the existing app name, Bluetooth device name and saved-settings paths are retained for compatibility.

## Project status

- **Working:** macOS app, XIAO USB/Bluetooth sensor firmware, guided calibration, pointer movement, clicking, dragging, scrolling and gestures.
- **Current app release:** 1.4.0, packaged for **Apple silicon Macs running macOS 14 or later**.
- **Included:** browser simulator, an optional arcade practice game and prototype glasses-mount enclosure files.
- **Planned:** direct Bluetooth mouse firmware and an iPad companion app. **The current firmware is not a standalone Bluetooth mouse, and the Mac app does not run on iPadOS.**

This is an experimental accessibility project. Fit, comfortable movement ranges and sound detection need testing for each person and mounting position.

## How it works

```text
Head movement / mouth sound
          ↓
XIAO Sense IMU / microphone
          ↓ USB or encrypted Bluetooth sensor data
Mac app: calibration → filtering → gestures / click detection
          ↓
macOS pointer, mouse buttons and scrolling
```

The Mac performs the motion and click processing and must remain running. USB and Bluetooth use the same processing engine. The Bluetooth firmware currently supports one connected host at a time.

## Hardware

| Component | Purpose |
| --- | --- |
| Seeed Studio XIAO nRF52840 Sense | nRF52840 processor, six-axis IMU, microphone and Bluetooth |
| USB-C data cable | Initial firmware upload, USB operation and power |
| Secure glasses/ear mount | Keeps the sensor orientation fixed relative to the head |
| Optional compatible battery | Untethered operation after charging and battery suitability are checked |

Use the **Sense** variant for the built-in IMU and microphone. See the [XIAO firmware guide](firmware/xiao_head_mouse/README.md) for board setup, upload instructions and the USB/Bluetooth protocol.

The [original Arduino Nano + MPU-6050 sketch](firmware/head_mouse/head_mouse.ino) is also retained. The maintained wearable setup uses the XIAO Sense.

## Use the Mac app

A packaged app can be built using the instructions below. Generated `.app`, `.dmg` and `.zip` installers are excluded from Git; copying or cloning this repository does not include a prebuilt installer.

1. Upload the [XIAO firmware](firmware/xiao_head_mouse/README.md) to the board.
2. Install **Head Mouse.app** in Applications and open it. Click its pointer icon in the menu bar.
3. In **Settings**, select USB or Bluetooth, find/select the XIAO and connect. Approve Bluetooth access or pairing if requested.
4. Allow **Head Mouse** under **System Settings → Privacy & Security → Accessibility** for computer pointer control.
5. Wear the device in its intended position and select **Calibrate…** in Controls.
6. Follow the centred prompts: look forward, hold still, turn right by about **5–10°**, return to centre and nod down. Each valid capture advances automatically.
7. After **Calibrated.**, select **Turn on computer control**, or Done to return to the menu.

Computer control starts **off**. Dwell clicking and mode gestures default **on**. The menu opens in Settings when disconnected. A connected device needing calibration shows an orange Calibrate button; a usable calibration returns it to the normal colour.

### Calibration and stopping

Calibration has a transparent background, bold instructions, countdowns and live progress bars. Stillness validation looks for a continuous steady two-second window and can extend while the device settles. Invalid movement offers a retry. Cancel or **Esc** keeps the previous calibration; settings are replaced only when the whole sequence succeeds.

- **Turn off computer control** stops pointer movement and clicks.
- **Disconnect** or **Quit Head Mouse** also stops control and releases a held drag.
- **Esc** pauses while the full setup window has keyboard focus; it is not a system-wide emergency shortcut.
- Closing the full setup window leaves the menu bar app running.
- Lost or stale motion readings pause control and release held buttons.

After reopening or reconnecting, use **Re-zero drift** if the mounting is unchanged. Run full calibration if the device has shifted. **Recenter head · 3 s** pauses movement while you return to a comfortable position, preserving the actual pointer location.

## Controls

| Setting | Behaviour |
| --- | --- |
| Mode 1 | Click → Drag → Scroll |
| Mode 2 | Click → Double click → Right click |
| Dwell | Hold the pointer still to perform the selected action; default 1 second, adjustable from 0.5–3 seconds |
| Sound | A tongue click or mouth pop performs the selected action; use Sound setup / test first |
| Pointer speed | Base movement gain |
| Ignore tiny movements | Suppresses small unintended movements |
| Computer sensitivity | Live multiplier for computer pointer movement; also scales scrolling |
| Scroll | Tilt/nod down to scroll down, up for up; return to neutral to stop |

Drag mode uses one activation to pick up and another to release. Scroll mode suspends clicking and uses a roughly two-degree neutral zone. More tilt increases speed, up to a capped maximum.

Dwell requires movement to arm and movement after a completed click before another click can occur. The mode icon’s halo shows the dwell countdown. The icon uses distinct colours/markers for click, drag, scroll, double click and right click, and stays within screen edges.

### Default gestures

- **Two quick left–right pairs:** cycle actions within the selected mode set. Four alternating strokes; either direction can start.
- **Three up–down pairs, starting up:** recenter the head.

Gestures use small calibrated head movements and do not stop normal pointer movement while being recognised. Mode switching is suspended while a drag is held. **Edit gestures…** in full setup changes the mappings.

### Sound clicking and privacy

Sound detection uses short transient/envelope measurements, not a trained speech or tongue-click classifier. Speech, knocks or other sharp noises can trigger it; test in the intended environment before enabling computer control.

The XIAO microphone runs only when Sound mode or sound testing requests it. Firmware sends short summaries such as peak and RMS levels. **Raw audio is not transmitted, recorded or uploaded by the application.** The computer’s microphone is not used.

## Run from source

The tested development environment is **arm64 Python 3.14 with Tk on macOS**. Install Python/Tk first and verify Tk with `python3.14 -m tkinter`.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r desktop/requirements.txt
.venv/bin/python desktop/build_macos_app.py
open "Head Mouse.app"
```

The development launcher declares Bluetooth usage and uses this checkout and virtual environment in place. Rebuild it after moving the project. It is different from the self-contained release app.

For USB-only development:

```sh
.venv/bin/python desktop/head_mouse.py
```

A plain Python launch can have a different macOS permission identity; use the native launcher for normal Bluetooth testing. Choose the current serial port in Settings rather than relying on a port name from another Mac.

### Build the standalone app and installers

On an Apple silicon Mac:

```sh
.venv/bin/python -m pip install -r packaging/requirements-build.txt
.venv/bin/python packaging/build_release.py
```

Outputs are placed in `release/`: an Apple silicon DMG, ZIP installer, installation instructions and verification metadata. The app bundles Python, its native dependencies, icons and a separate menu helper; recipients do not need Homebrew or Python. See [build details](packaging/BUILD.txt) and [installation instructions](packaging/INSTALL.txt).

The build checks architecture, minimum macOS version, code signatures and external library dependencies. Installers include dependency notices and matching build sources, and exclude saved profiles. The current personal/testing package is **ad-hoc signed, not Apple notarized**. Developer ID signing is available through `--identity`; public distribution also needs Apple's notarization/stapling process.

Installed app settings are stored at:

```text
~/Library/Application Support/Head Mouse/profile.json
```

Development runs use `desktop/.head_mouse_profile.json`. Both contain user/device-specific settings; neither is committed. Each new Mac needs its own device setup, permission approval and calibration.

## Simulator and optional practice game

The simulator works without hardware:

```sh
python3 simulator/server.py
```

Open **http://127.0.0.1:8765**. It generates virtual IMU samples and uses the desktop motion engine. See the [simulator guide](simulator/README.md) for controls and modelling limits.

The separate **Neon Drift** arcade experiment lets you practise pointer movement:

```sh
python3 arcade_practice/server.py --open
```

It runs locally on port 8766 and does not configure the device or calibration. See [arcade practice](arcade_practice/README.md). The entire `arcade_practice/` folder can be removed without affecting the head mouse.

## Enclosure prototype

The [enclosure folder](enclosure/README.md) contains an editable CAD generator, STL files and a strap-fit test for attaching the XIAO/battery enclosure to glasses. Check component dimensions and glasses-arm fit before printing the full enclosure. These are prototype files, not a validated fit for every frame or battery.

## Tests and diagnostics

```sh
.venv/bin/python -m unittest discover -s desktop -p 'test_*.py'
.venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
node --test arcade_practice/test_flight.mjs
```

The desktop suite covers calibration, stale-stream handling, pointer event payloads, dwell, sound, gestures, scrolling, menu commands and portable preferences. Tests mock computer input rather than moving the real pointer.

For a packaged build, these checks do not connect to the device or generate pointer events:

```sh
"/Applications/Head Mouse.app/Contents/MacOS/Head Mouse" --diagnose
"/Applications/Head Mouse.app/Contents/MacOS/Head Mouse" --self-check
```

Tests and component checks do not replace real-device testing of comfort, direction, latency, drift or sound false positives.

## Repository layout

| Folder | Contents |
| --- | --- |
| `desktop/` | Mac app, motion/click processing, menu helper, calibration overlay and tests |
| `firmware/xiao_head_mouse/` | Current XIAO Sense USB/Bluetooth firmware |
| `firmware/head_mouse/` | Original Nano/MPU-6050 prototype |
| `packaging/` | Standalone app/installer build, verification, icons and dependency notices/sources |
| `simulator/` | Hardware-free calibration and movement simulator |
| `arcade_practice/` | Optional, removable pointer-practice game |
| `enclosure/` | CAD generator, previews and prototype print files |

## iPad roadmap

An iPad version is planned, including support for an iPad Pro 13-inch M4. It needs updated XIAO firmware that performs motion processing and sends Bluetooth HID mouse commands directly, plus an optional native iPad companion app for pairing, guided calibration and settings. iPadOS would provide its system pointer and AssistiveTouch dwell behaviour. **This functionality is not implemented in this repository yet.**

## Licenses

Third-party software and artwork retain their original licenses. Lucide artwork includes its license in `desktop/assets/lucide/`; packaging includes runtime notices and the matching pynput LGPL source archive. No project-wide open-source license has been selected for the original application code.
