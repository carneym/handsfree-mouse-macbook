#include <Adafruit_TinyUSB.h>
#include <LSM6DS3.h>
#include <Wire.h>
#include <math.h>
#include <bluefruit.h>
#include <PDM.h>

#if !defined(TARGET_SEEED_XIAO_NRF52840_SENSE)
#error "Select Seeed nRF52 Boards > Seeed XIAO nRF52840 Sense."
#endif

// The desktop HM1 protocol always uses 16384 counts/g and 131 counts/(deg/s).
// Convert the LSM6DS3 measurements into that representation before sending.
constexpr uint32_t SAMPLE_US = 10000;
constexpr uint32_t RETRY_MS = 500;
constexpr uint8_t IMU_ADDRESS = 0x6A;
LSM6DS3 imu(I2C_MODE, IMU_ADDRESS);
bool imuReady = false;
bool usbWasConnected = false;
uint32_t lastSample = 0;
uint32_t retryAt = 0;
BLEService headService("1c863b10-6d35-4f80-9eb5-71e146bb7930");
BLECharacteristic headData("1c863b11-6d35-4f80-9eb5-71e146bb7930");
BLECharacteristic headControl("1c863b12-6d35-4f80-9eb5-71e146bb7930");
volatile bool bleStreaming = false;
uint16_t sequence = 0;
volatile bool micRequested = false;
bool micRunning = false;
bool previousMicRequest = false;
volatile bool audioPending = false;
volatile uint64_t audioSquares = 0, audioHighSquares = 0;
volatile uint16_t audioPeak = 0, audioCount = 0;
volatile uint32_t audioTime = 0;
int32_t micDC = 0, previousAudio = 0;
uint32_t lastMicError = 0;

void microphoneData() {
  int16_t pcm[320];
  const int bytes = PDM.read(pcm, min(PDM.available(), static_cast<int>(sizeof(pcm))));
  const int count = bytes / 2;
  uint64_t squares = 0, highSquares = 0;
  uint16_t peak = 0;
  for (int i = 0; i < count; ++i) {
    micDC += (static_cast<int32_t>(pcm[i]) - micDC) / 128;
    const int32_t value = constrain(static_cast<int32_t>(pcm[i]) - micDC, -32767, 32767);
    const int32_t high = (value - previousAudio) / 2;
    previousAudio = value;
    peak = max(peak, static_cast<uint16_t>(abs(value)));
    squares += static_cast<int64_t>(value) * value;
    highSquares += static_cast<int64_t>(high) * high;
  }
  audioSquares = squares;
  audioHighSquares = highSquares;
  audioPeak = peak;
  audioCount = count;
  audioTime = micros();
  audioPending = true;
}

void serviceMicrophone(bool usbConnected) {
  if (!usbConnected && !Bluefruit.connected()) micRequested = false;
  const bool requested = micRequested;
  if (requested != previousMicRequest) {
    previousMicRequest = requested;
    if (micRunning) PDM.end();
    micRunning = false;
    audioPending = false;
    micDC = previousAudio = 0;
    if (requested) {
      PDM.setBufferSize(640); // 320 mono samples, one 20 ms feature window.
      PDM.onReceive(microphoneData);
      micRunning = PDM.begin(1, 16000);
      if (micRunning) PDM.setGain(20);
    } else {
      digitalWrite(PIN_PDM_PWR, LOW);
    }
  }
  if (!requested) return;
  const bool failed = !micRunning;
  if (!audioPending && (!failed || millis() - lastMicError < 250)) return;
  uint64_t squares, highSquares;
  uint16_t peak, count;
  uint32_t timestamp;
  noInterrupts();
  squares = audioSquares;
  highSquares = audioHighSquares;
  peak = audioPeak;
  count = audioCount;
  timestamp = audioTime;
  audioPending = false;
  interrupts();
  if (failed) {
    lastMicError = millis();
    timestamp = micros();
    peak = count = 0;
  }
  const uint16_t rms = count ? sqrt(static_cast<double>(squares) / count) : 0;
  const uint16_t high = count ? sqrt(static_cast<double>(highSquares) / count) : 0;
  uint8_t packet[20] = {1, 1}; // Type 1: envelope features, never raw audio.
  const uint16_t seq = sequence++;
  packet[2] = seq & 0xff;
  packet[3] = seq >> 8;
  for (uint8_t i = 0; i < 4; ++i) packet[4+i] = (timestamp >> (8*i)) & 0xff;
  const uint16_t features[] = {peak, rms, high, count, static_cast<uint16_t>(failed ? 1 : 0), 0};
  for (uint8_t i = 0; i < 6; ++i) {
    packet[8+2*i] = features[i] & 0xff;
    packet[9+2*i] = features[i] >> 8;
  }
  if (bleStreaming && Bluefruit.connected() && headData.notifyEnabled()) headData.notify(packet, sizeof(packet));
  char line[80];
  const int length = snprintf(line, sizeof(line), "HS1,%lu,%u,%u,%u,%u,%u\n",
                             static_cast<unsigned long>(timestamp), peak, rms, high, count, failed ? 1 : 0);
  if (usbConnected && length > 0 && Serial.availableForWrite() >= length) Serial.write(reinterpret_cast<uint8_t*>(line), length);
}

void controlWritten(uint16_t handle, BLECharacteristic*, uint8_t* data, uint16_t length) {
  if (length != 1) return;
  if (data[0] == 0) { bleStreaming = false; micRequested = false; }
  if (data[0] == 1) bleStreaming = true;
  if (data[0] == 2) micRequested = false;
  if (data[0] == 3) micRequested = true;
  if (data[0] == 1) {
    BLEConnection* connection = Bluefruit.Connection(handle);
    if (connection) connection->requestConnectionParameter(12, 0, 400); // 15 ms, no slave latency.
  }
  headControl.write8(2); // Version 2 adds optional microphone envelope features.
}

void bleDisconnected(uint16_t, uint8_t) {
  bleStreaming = false;
  micRequested = false;
}

void startBluetooth() {
  // The default single notification slot blocks sampling until the next radio
  // event. Buffer a short connection event's worth of fixed-size samples.
  Bluefruit.configPrphConn(23, 6, 8, 1);
  Bluefruit.begin(1, 0);
  Bluefruit.setName("Head Mouse");
  Bluefruit.Periph.setConnInterval(12, 24); // Preferred 15–30 ms; request 15 ms on stream start.
  Bluefruit.Periph.setDisconnectCallback(bleDisconnected);
  headService.begin();
  headData.setProperties(CHR_PROPS_NOTIFY);
  headData.setPermission(SECMODE_ENC_NO_MITM, SECMODE_NO_ACCESS);
  headData.setFixedLen(20);
  headData.begin();
  headControl.setProperties(CHR_PROPS_READ | CHR_PROPS_WRITE);
  headControl.setPermission(SECMODE_ENC_NO_MITM, SECMODE_ENC_NO_MITM);
  headControl.setFixedLen(1);
  headControl.setWriteCallback(controlWritten);
  headControl.begin();
  headControl.write8(2);
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addService(headService);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 160);
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);
}

bool status(const char *message) {
  if (Serial && Serial.availableForWrite() >= static_cast<int>(strlen(message) + 2)) {
    Serial.println(message);
    return true;
  }
  return false;
}

bool readRegisters(uint8_t reg, uint8_t *bytes, uint8_t count) {
  Wire1.beginTransmission(IMU_ADDRESS);
  Wire1.write(reg);
  if (Wire1.endTransmission(false) != 0 ||
      Wire1.requestFrom(IMU_ADDRESS, count) != count) {
    return false;
  }
  for (uint8_t i = 0; i < count; ++i) {
    bytes[i] = Wire1.read();
  }
  return true;
}

int16_t signedWord(const uint8_t *bytes) {
  return static_cast<int16_t>(static_cast<uint16_t>(bytes[0]) |
                              (static_cast<uint16_t>(bytes[1]) << 8));
}

int16_t protocolCount(float value) {
  return static_cast<int16_t>(lroundf(constrain(value, -32768.0f, 32767.0f)));
}

bool startImu() {
  imu.settings.accelRange = 2;
  imu.settings.accelSampleRate = 104;
  imu.settings.gyroRange = 245;
  imu.settings.gyroSampleRate = 104;
  if (imu.begin() != IMU_SUCCESS) {
    return false;
  }
  // Latch each complete word until read and increment during a burst read.
  uint8_t control;
  return imu.readRegister(&control, LSM6DS3_ACC_GYRO_CTRL3_C) == IMU_SUCCESS &&
         imu.writeRegister(LSM6DS3_ACC_GYRO_CTRL3_C, control | 0x44) == IMU_SUCCESS;
}

void setup() {
  // Keep the board's low charging-current selection and voltage-read path.
  pinMode(PIN_CHARGING_CURRENT, INPUT);
  pinMode(VBAT_ENABLE, OUTPUT);
  digitalWrite(VBAT_ENABLE, LOW);
  pinMode(PIN_PDM_PWR, OUTPUT);
  digitalWrite(PIN_PDM_PWR, LOW);
  Serial.begin(115200);
  startBluetooth();
  retryAt = millis();
}

void loop() {
  const bool usbConnected = static_cast<bool>(Serial);
  if (usbConnected && !usbWasConnected) {
    usbWasConnected = status("# HM1,XIAO Head Mouse USB+BLE v1.2.0,LSM6DS3,PDM-features,100Hz");
  } else if (!usbConnected) {
    usbWasConnected = false;
  }
  static bool micCommand = false;
  for (uint8_t n = 0; n < 16 && Serial.available(); ++n) {
    const char c = Serial.read();
    if (micCommand && (c == '0' || c == '1')) micRequested = (c == '1');
    micCommand = (c == 'M');
  }
  serviceMicrophone(usbConnected);

  if (!imuReady) {
    if (static_cast<int32_t>(millis() - retryAt) < 0) {
      delay(1);
      return;
    }
    imuReady = startImu();
    if (!imuReady) {
      status("# IMU initialization failed. Retrying.");
      retryAt = millis() + RETRY_MS;
      return;
    }
    lastSample = micros();
  }

  const uint32_t now = micros();
  if (now - lastSample < SAMPLE_US) {
    delay(1);
    return;
  }
  lastSample += SAMPLE_US;
  if (now - lastSample >= SAMPLE_US) {
    lastSample = now;
  }

  uint8_t ready;
  uint8_t data[12];  // Gyro XYZ, then accelerometer XYZ, little endian.
  if (!readRegisters(LSM6DS3_ACC_GYRO_STATUS_REG, &ready, 1)) {
    imuReady = false;
  } else if ((ready & 0x03) != 0x03) {
    return;
  } else if (!readRegisters(LSM6DS3_ACC_GYRO_OUTX_L_G, data, sizeof(data))) {
    imuReady = false;
  }
  if (!imuReady) {
    status("# IMU read failed. Retrying.");
    retryAt = millis() + RETRY_MS;
    return;
  }

  int16_t accel[3];
  int16_t gyro[3];
  for (uint8_t axis = 0; axis < 3; ++axis) {
    gyro[axis] = protocolCount(imu.calcGyro(signedWord(data + axis * 2)) * 131.0f);
    accel[axis] = protocolCount(imu.calcAccel(signedWord(data + 6 + axis * 2)) * 16384.0f);
  }

  // Exactly 20 bytes fits the default BLE ATT payload without MTU negotiation.
  // Version, flags, sequence, timestamp, acceleration XYZ, gyro XYZ; little endian.
  uint8_t packet[20] = {1, 0};
  const uint16_t seq = sequence++;
  packet[2] = seq & 0xff;
  packet[3] = seq >> 8;
  for (uint8_t i = 0; i < 4; ++i) packet[4+i] = (now >> (8*i)) & 0xff;
  for (uint8_t i = 0; i < 6; ++i) {
    const uint16_t value = static_cast<uint16_t>(i < 3 ? accel[i] : gyro[i-3]);
    packet[8+2*i] = value & 0xff;
    packet[9+2*i] = value >> 8;
  }
  if (bleStreaming && Bluefruit.connected() && headData.notifyEnabled()) {
    headData.notify(packet, sizeof(packet));
  }

  char line[96];
  const int length = snprintf(line, sizeof(line), "HM1,%lu,%d,%d,%d,%d,%d,%d\n",
                              static_cast<unsigned long>(now),
                              accel[0], accel[1], accel[2],
                              gyro[0], gyro[1], gyro[2]);
  // Drop a sample if the USB host stalls, preserving complete fresh rows.
  if (usbConnected && length > 0 && length < static_cast<int>(sizeof(line)) &&
      Serial.availableForWrite() >= length) {
    Serial.write(reinterpret_cast<const uint8_t *>(line), length);
  }
}
