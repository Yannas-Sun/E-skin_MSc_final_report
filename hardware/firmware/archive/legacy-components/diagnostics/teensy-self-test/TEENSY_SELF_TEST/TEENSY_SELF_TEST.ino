// Standalone Teensy 4.1 sanity test.
// Disconnect the STM32 Host SPI wiring while running this sketch because
// LED_BUILTIN is GPIO13, which is also the default SPI SCK pin.

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t BLINK_INTERVAL_MS = 500;
constexpr uint32_t REPORT_INTERVAL_MS = 1000;

uint32_t lastBlinkMs = 0;
uint32_t lastReportMs = 0;
uint32_t reportCount = 0;
bool ledState = false;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  Serial.begin(SERIAL_BAUD);

  // Allow the USB serial connection to enumerate, but never block startup.
  const uint32_t waitStartMs = millis();
  while (!Serial && (millis() - waitStartMs < 3000)) {
  }

  Serial.println("TEENSY_SELF_TEST START");
  Serial.println("Expected: LED toggles every 500 ms; this line updates every second.");
}

void loop() {
  const uint32_t nowMs = millis();

  if (nowMs - lastBlinkMs >= BLINK_INTERVAL_MS) {
    lastBlinkMs = nowMs;
    ledState = !ledState;
    digitalWrite(LED_BUILTIN, ledState ? HIGH : LOW);
  }

  if (nowMs - lastReportMs >= REPORT_INTERVAL_MS) {
    lastReportMs = nowMs;
    ++reportCount;
    Serial.print("TEENSY_SELF_TEST PASS count=");
    Serial.print(reportCount);
    Serial.print(" uptime_ms=");
    Serial.println(nowMs);
  }
}
