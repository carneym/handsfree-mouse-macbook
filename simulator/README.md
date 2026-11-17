# Head mouse simulator

Run the virtual head mouse locally before the hardware arrives. It uses the actual calibration, serial sample decoder and pointer movement code in `desktop/motion.py`.

## Start

Python 3.10 or newer is sufficient. The simulator uses only Python's standard library and the project's motion module.

From the project directory:

```sh
python3 simulator/server.py
```

Open **http://127.0.0.1:8765** in a browser. Keep the terminal running. Press Ctrl+C in that terminal to stop the server. Use `python3 simulator/server.py --port 8766` if port 8765 is occupied, then open the URL it prints.

One shared simulation runs per server. Use one browser tab. Refreshing the page reconnects to the current simulation. Restarting the server starts fresh.

## First try

1. Click **Run calibration demo**. The virtual head performs the three captures automatically over approximately 17 seconds, including preparation countdowns.
2. Click **Enable preview**.
3. Use the **Turn right 12°** and **Nod down 12°** buttons or the angle sliders. For finer control, click inside the preview and hold the arrow keys. Release a key to hold the current head angle.
4. Aim at the orange target. Keeping the pointer inside it for 0.4 seconds advances to the next target.
5. Try sensitivity and dead-zone adjustments, then repeat the target exercise.

A short press on **Enable/Pause preview** represents the proposed wearable pause button. **Re-zero sensor** represents its proposed long-press behavior, with a three-second preparation countdown and two-second still capture. These are simulated button actions. The wearable firmware integration remains to be implemented.

## Manual calibration

Each capture has a three-second preparation countdown.

1. Click **Hold still → Capture**, and leave the controls alone during the two-second capture.
2. Click **Look right → Capture**. Wait for **GO**, then click **Turn right 12°** once. Hold that pose until the capture ends.
3. Click **Face forward** and let the pose settle.
4. Click **Nod down → Capture**. At **GO**, click **Nod down 12°** once. Wait for completion.
5. Return to face forward while paused, let the pose settle, then enable the preview.

The angle sliders or arrow keys also work for making the calibration gestures.

## Sensor experiments

Expand **Sensor conditions & calibration readings**.

- **Mounting twist** changes how the sensor axes sit on the glasses. Changing it clears calibration so you can learn the new orientation.
- **Gyro noise** adds independent noise to each gyro sample. A high setting can make the still capture fail, as it would with motion during zeroing.
- **Gyro bias strength** adds a steady sensor offset. Change it after calibration to create drift. Lower the dead zone to 0.2°/s to make the effect easier to see. Use **Re-zero sensor** and hold still to measure the new bias while retaining the learned movement axes.

Live readings include gyro rates, acceleration, the pointer coordinates and the captured gyro bias.

## Movement behavior

The preview represents relative angular movement. Turning moves the pointer, and holding a pose stops it after a brief smoothing tail. Returning to face forward while enabled moves the pointer back. Pause first if you want to reposition your head without moving the pointer.

The virtual screen is 1280 × 720 pixels. The sensitivity value uses these virtual pixels. Screen edges clamp the simulated pointer.

Esc pauses, or cancels a calibration capture. Space toggles the preview when focus is outside a form control. Losing browser focus pauses the preview. A gap of more than 0.5 seconds between server updates also pauses it or cancels an active capture.

## Model and limits

The simulator generates 100 Hz accelerometer and gyro samples, quantizes them into the project's signed-count USB format, and passes them through the real sample decoder. Small-angle yaw and pitch rates are mapped into rotated sensor axes, with independent Gaussian gyro noise and a configurable fixed bias.

The real `zero_gyro`, `gesture_axis` and `PointerMotion` routines process those samples. The automatic demo returns the virtual head to center while paused after calibration.

This is a simplified small-angle model. It does not predict actual sensor temperature drift, BLE delivery timing, OS pointer acceleration, ergonomic comfort or hardware mounting vibration. The preview moves a cursor inside its own canvas. Hardware sensor drivers, Bluetooth pairing and wearable button firmware still require testing on the XIAO.

## Checks

```sh
python3 -m unittest discover -s simulator -p 'test_*.py' -v
```

Regression tests cover automatic and manual calibration, several mounting orientations, pause, changed-bias re-zeroing, target dwell, remount invalidation, noisy capture rejection and invalid inputs.
