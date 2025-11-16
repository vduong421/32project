// Motor 1 Pins (Front Right)
const int RPWM1 = 9;
const int LPWM1 = 10;

// Motor 2 Pins (Front Left)
const int RPWM2 = 11;
const int LPWM2 = 12;

// Motor 3 Pins (Back Right)
const int RPWM3 = 6;
const int LPWM3 = 7;

// Motor 4 Pins (Back Left)
const int RPWM4 = 5;
const int LPWM4 = 4;

// Speed control
const int MAX_SPEED = 64;        // ~25% of 255; you can increase if needed
int currentSpeed = 0;            // current PWM value
int targetSpeed = 0;             // what we’re ramping toward

char currentDirection = 'S';     // 'F','B','L','R','S'

unsigned long lastRampUpdate = 0;
const unsigned long RAMP_INTERVAL = 50; // ms between speed steps
const int SPEED_STEP = 4;               // how much we change per step

void setup() {
  Serial.begin(9600);

  pinMode(RPWM1, OUTPUT); pinMode(LPWM1, OUTPUT);
  pinMode(RPWM2, OUTPUT); pinMode(LPWM2, OUTPUT);
  pinMode(RPWM3, OUTPUT); pinMode(LPWM3, OUTPUT);
  pinMode(RPWM4, OUTPUT); pinMode(LPWM4, OUTPUT);

  stopMotors();
}

void loop() {
  // --- Handle serial commands from Raspberry Pi ---
  if (Serial.available() > 0) {
    char cmd = Serial.read();

    if (cmd == 'F' || cmd == 'B' || cmd == 'L' || cmd == 'R') {
      currentDirection = cmd;
      targetSpeed = MAX_SPEED;   // ramp up toward this
    } else if (cmd == 'S') {
      currentDirection = 'S';
      targetSpeed = 0;           // ramp down to 0
    }
  }

  // --- Ramp speed toward targetSpeed ---
  unsigned long now = millis();
  if (now - lastRampUpdate >= RAMP_INTERVAL) {
    lastRampUpdate = now;

    if (currentSpeed < targetSpeed) {
      currentSpeed += SPEED_STEP;
      if (currentSpeed > targetSpeed) currentSpeed = targetSpeed;
    } else if (currentSpeed > targetSpeed) {
      currentSpeed -= SPEED_STEP;
      if (currentSpeed < targetSpeed) currentSpeed = targetSpeed;
    }

    applyMotion();
  }
}

// ===== Motor control helpers =====

// Map left/right speeds into your 4 motors (tank style)
void setSideSpeeds(int leftSpeed, int rightSpeed) {
  // Constrain to [0, 255]
  leftSpeed  = constrain(leftSpeed,  -255, 255);
  rightSpeed = constrain(rightSpeed, -255, 255);

  // Right side (Motors 1 & 3)
  if (rightSpeed > 0) {
    analogWrite(RPWM1, rightSpeed); analogWrite(LPWM1, 0);
    analogWrite(RPWM3, rightSpeed); analogWrite(LPWM3, 0);
  } else if (rightSpeed < 0) {
    int s = -rightSpeed;
    analogWrite(LPWM1, s); analogWrite(RPWM1, 0);
    analogWrite(LPWM3, s); analogWrite(RPWM3, 0);
  } else {
    analogWrite(RPWM1, 0); analogWrite(LPWM1, 0);
    analogWrite(RPWM3, 0); analogWrite(LPWM3, 0);
  }

  // Left side (Motors 2 & 4) – wiring reversed
  if (leftSpeed > 0) {
    // forward for left side
    analogWrite(LPWM2, leftSpeed); analogWrite(RPWM2, 0);
    analogWrite(LPWM4, leftSpeed); analogWrite(RPWM4, 0);
  } else if (leftSpeed < 0) {
    int s = -leftSpeed;
    // backward for left side
    analogWrite(RPWM2, s); analogWrite(LPWM2, 0);
    analogWrite(RPWM4, s); analogWrite(LPWM4, 0);
  } else {
    analogWrite(RPWM2, 0); analogWrite(LPWM2, 0);
    analogWrite(RPWM4, 0); analogWrite(LPWM4, 0);
  }
}

void applyMotion() {
  int s = currentSpeed;

  switch (currentDirection) {
    case 'F':
      // forward: both sides forward
      setSideSpeeds(s, s);
      break;
    case 'B':
      // backward: both sides backward
      setSideSpeeds(-s, -s);
      break;
    case 'L':
      // tank turn left: left side backward, right side forward
      setSideSpeeds(-s, s);
      break;
    case 'R':
      // tank turn right: left side forward, right side backward
      setSideSpeeds(s, -s);
      break;
    case 'S':
    default:
      // stop (ramp will bring speed to 0)
      if (currentSpeed == 0) {
        stopMotors();
      } else {
        // still ramping down; keep speeds symmetric
        setSideSpeeds(0, 0);
      }
      break;
  }
}

void stopMotors() {
  analogWrite(RPWM1, 0); analogWrite(LPWM1, 0);
  analogWrite(RPWM2, 0); analogWrite(LPWM2, 0);
  analogWrite(RPWM3, 0); analogWrite(LPWM3, 0);
  analogWrite(RPWM4, 0); analogWrite(LPWM4, 0);
}
