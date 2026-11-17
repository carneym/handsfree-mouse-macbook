# Neon Drift · optional flight lab

A small original first-person arcade flying game for practising head-mouse control. Its neon runway and gate flying are inspired by futuristic arcade racers; it uses no Wipeout assets. Everything renders locally with Canvas, with no packages, accounts, network services or audio recordings.

This folder is a separate experiment. It imports nothing from calibration, connects to no IMU, changes no firmware/settings, and starts no device-control code. It uses the normal computer pointer, so a regular mouse also works.

## Launch

On macOS, double-click **Launch Flight Lab.command** in this folder. It starts its own local server and opens your default browser. Keep that terminal window open while playing; Ctrl+C stops the server.

Or run from the project folder:

```sh
.venv/bin/python arcade_practice/server.py --open
```

The default URL is `http://127.0.0.1:8766/`, separate from the calibration simulator on port 8765. Use `--port 8767` if that port is occupied. The server binds only to loopback and serves only the five game assets.

## Fly

1. Calibrate Head Mouse normally, choose **Click** or **Drag** pointer mode (Scroll mode will scroll rather than steer), and turn Computer control on. You can leave clicking off: steering needs no clicks after launching. Sound/dwell can also activate the menu buttons, or use your regular mouse.
2. Start with **Free flight**, **Wide gates**, speed 28 or lower, and **Comfort view** on.
3. Select **Launch flight**. A three-second countdown gives you time to bring the pointer back toward the middle.
4. Move the pointer left/right/up/down to steer the ship. Forward flight is automatic. Aim the fixed centre reticle through the glowing gates. Missing a gate resets the score chain but never destroys the ship.
5. **Esc**, **P**, or the Pause button pauses the game. Focus loss, a hidden tab, leaving the flight area, a delayed frame, or prolonged absence of steering also pauses it. Resume includes another countdown. End flight shows gates, accuracy, score and best streak.

**Time trial** lasts 60 seconds of actual flight time; countdowns and pauses do not consume it. The speed slider and smaller gates add difficulty. Sound effects start off and can be enabled explicitly.

Game pause does not turn off Head Mouse computer control. Use its normal OFF control to stop system pointer movement. Recenter/gesture recognition still belongs to the Head Mouse app; this game does not take over those controls or lock/hide the system pointer. It is a practice game, not a calibration or diagnostic measurement.

## Remove

Stop its server and delete only `arcade_practice/`. Calibration, Bluetooth, the desktop app and the existing simulator continue working. No game link or dependency is added to the calibration app. The optional note in the project README can also be removed.

## Checks

```sh
node --test arcade_practice/test_flight.mjs
```

Tests cover gate tracking and scoring, the timed run, misses/restarts, input bounds and delayed-frame handling. Browser checks cover launch/pause/resume and the rendered scene.
