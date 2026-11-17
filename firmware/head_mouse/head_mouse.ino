#include <Wire.h>

// MPU-6050 at +/-2 g and +/-250 degrees/second.
constexpr unsigned long SAMPLE_US = 10000;
constexpr unsigned long RETRY_MS = 500;
uint8_t imuAddress = 0x68;
bool imuReady = false;
unsigned long lastSample = 0;
unsigned long retryAt = 0;

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readRegisters(uint8_t reg, uint8_t *data, uint8_t count) {
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0 ||
      Wire.requestFrom(imuAddress, count) != count) {
    return false;
  }
  for (uint8_t i = 0; i < count; ++i) {
    data[i] = Wire.read();
  }
  return true;
}

bool startImu() {
  for (imuAddress = 0x68; imuAddress <= 0x69; ++imuAddress) {
    uint8_t id;
    if (readRegisters(0x75, &id, 1) && id == 0x68) {
      return writeRegister(0x6B, 0x01) &&  // Wake, use gyro clock
             writeRegister(0x6C, 0x00) &&  // Enable all axes
             writeRegister(0x1A, 0x03) &&  // ~44 Hz low-pass filter
             writeRegister(0x19, 9) &&     // 1 kHz / (1 + 9)
             writeRegister(0x1B, 0) &&
             writeRegister(0x1C, 0);
    }
  }
  return false;
}

int16_t readWord(const uint8_t *bytes) {
  return static_cast<int16_t>((static_cast<uint16_t>(bytes[0]) << 8) | bytes[1]);
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
#if defined(WIRE_HAS_TIMEOUT)
  Wire.setWireTimeout(3000, true);
#endif
  retryAt = millis();
}

void loop() {
  if (!imuReady) {
    if (static_cast<int32_t>(millis() - retryAt) < 0) {
      return;
    }
    imuReady = startImu();
    if (!imuReady) {
      Serial.println(F("# MPU-6050 not responding. Check power and I2C."));
      retryAt = millis() + RETRY_MS;
      return;
    }
    delay(100);
    Serial.println(F("# HM1,t_us,ax,ay,az,gx,gy,gz (signed raw counts)"));
    lastSample = micros();
  }

  const unsigned long now = micros();
  if (now - lastSample < SAMPLE_US) {
    return;
  }
  lastSample = now;

  uint8_t data[14];  // Accelerometer, temperature, then gyroscope.
  if (!readRegisters(0x3B, data, sizeof(data))) {
    Serial.println(F("# IMU read failed. Reconnecting."));
    imuReady = false;
    retryAt = millis() + RETRY_MS;
    return;
  }

  Serial.print(F("HM1,"));
  Serial.print(now);
  for (uint8_t offset = 0; offset < sizeof(data); offset += 2) {
    if (offset != 6) {
      Serial.print(',');
      Serial.print(readWord(data + offset));
    }
  }
  Serial.println();
}
