# XIAO nRF52840 Sense USB + Bluetooth firmware

This sketch reads the board's onboard LSM6DS3 IMU and streams the same HM1 rows used by the desktop calibration tool.

## Build and upload

In Arduino IDE, add Seeed's board index to the additional board-manager URLs:

```text
https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
```

Install **Seeed nRF52 Boards 1.1.13**, select **Seeed XIAO nRF52840 Sense**, and install **Seeed Arduino LSM6DS3 2.0.8** through Library Manager. Open `xiao_head_mouse.ino`, select the XIAO USB port and upload.

The verified compile uses these dependencies. The core includes Adafruit TinyUSB Library 1.7.0. If using the CLI on macOS, make Python available as `python` in the toolchain's PATH and use a supported UTF-8 locale, such as `en_IE.UTF-8`. This Seeed core's compile flags also require a sketch path without spaces. Copy the sketch to a temporary directory if the project path contains spaces.

The CLI board identifier is:

```text
Seeeduino:nrf52:xiaonRF52840Sense
```

## USB data

Open the serial port at **115200 baud**. A connection prints a firmware identification banner, followed by rows:

```text
# HM1,XIAO Head Mouse USB+BLE v1.2.0,LSM6DS3,PDM-features,100Hz
HM1,timestamp_us,ax,ay,az,gx,gy,gz
```

Data rows contain numbers. The timestamp wraps at 32 bits. Acceleration values use 16384 counts/g and gyro values use 131 counts/(degree/second), matching `desktop/motion.py`. These are normalized protocol counts, converted from the LSM6DS3's native scale by Seeed's driver.

The IMU runs at 104 Hz with the acceleration range set to ±2 g and gyro range set to ±245°/s. Fresh rows are requested approximately every 10 ms. Short reads or I2C errors trigger initialization retries. USB stalls cause samples to be dropped rather than accumulating old data.

The microphone starts powered down and is enabled only on request. It supplies 16 kHz mono PDM samples to a short temporary RAM buffer. Only 20 ms peak/RMS/high-frequency summaries leave the board. USB commands `M1\n` and `M0\n` enable/disable it; features use `HS1,timestamp_us,peak,rms,high,sample_count,status` rows. Status `0` is ready, `1` is initialization failure. The charging-current selection is left at the board's low setting, approximately 50 mA. The battery voltage-read path remains enabled as described by Seeed. Check the actual battery's charging specification before connecting it.

## Calibrate

Close other serial monitors. Open the desktop app, choose USB or Bluetooth and follow Hold still, Turn right and Nod down. Start in Practice area, then enable Computer control. This firmware supplies motion readings; it does not send HID mouse events. Bluetooth HID and a wearable pause button remain future work.

## Bluetooth protocol

The board advertises **Head Mouse** and service `1c863b10-6d35-4f80-9eb5-71e146bb7930`. One peripheral connection is enabled. Bluefruit handles encrypted Just Works pairing/bond storage; no numeric PIN or physical authentication is provided. Disconnecting restarts advertising. USB streaming remains available for fallback/power while the app selects a single source for mouse control.

- Data characteristic: `1c863b11-6d35-4f80-9eb5-71e146bb7930`, encrypted notifications, fixed 20-byte payload.
- Control: `1c863b12-6d35-4f80-9eb5-71e146bb7930`, encrypted read/write. Read returns capability version `2`; write byte `1` to stream and `0` to stop, `3` to enable the microphone, `2` to disable it. Stream and microphone stop on disconnect. Clients accept legacy capability version `1` for motion, without sending unsupported mic commands.
- Motion layout: little endian `<BBHI6h`: packet version `1`, type `0`, wrapping uint16 sequence, wrapping uint32 microseconds, acceleration XYZ then gyro XYZ in the same normalized counts as USB.
- Microphone layout: little endian `<BBHI6H`: packet version `1`, type `1`, shared sequence and timestamp, then peak, RMS, high-frequency RMS (half first-difference), sample count, status, reserved `0`. Both message types use the same encrypted notification characteristic and sequence counter, so no GATT database change/re-pairing is needed.

The 20-byte packet fits the default ATT payload. IMU acquisition remains approximately 100 Hz; packets may be dropped when the link cannot keep up. Eight notification slots prevent the default single-slot transmit buffer from blocking IMU sampling on each radio event. The preferred connection interval is 15–30 ms, with an explicit 15 ms request when streaming starts; the host negotiates the actual interval. The desktop detects sequence gaps, discards old motion and pauses on a stale stream. No HID service or battery-percentage service is advertised.

The live Mac check received 935 samples in 10.009 seconds (93.3 Hz), no missing packets, and a maximum device timestamp gap of 20.51 ms. This verifies this setup, not radio performance at every range or mounting position. The initial single-slot implementation delivered only about 17 Hz and was replaced before completion.

With microphone features enabled, the live check received 935 motion samples and 501 microphone frames over about ten seconds, no missing packets or microphone errors, and a maximum motion timestamp gap of 30.27 ms. This verifies acquisition/transport, not real-world tongue-click recognition accuracy.

The browser simulator continues to generate virtual IMU data. It has its own calibration state.

## References

- [Seeed board setup, charging and voltage-read guidance](https://wiki.seeedstudio.com/XIAO_BLE/)
- [Seeed IMU driver](https://github.com/Seeed-Studio/Seeed_Arduino_LSM6DS3)
