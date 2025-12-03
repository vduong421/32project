Here is the folder structure in my root folder
32project
├── main.py
└── templates/
    └── dashboard_operator.html

Here is files code:
main.py
```python
from flask import Flask, render_template, redirect, url_for, flash, request, Response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import re
import cv2
import platform
import os
import serial
import time
from dotenv import load_dotenv

# ---------------------- Load Environment ----------------------
load_dotenv()

# ---------------------- GPIO + Arduino Setup ----------------------
IS_PI = platform.system() == "Linux"

if IS_PI:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    print("Running on Raspberry Pi: GPIO enabled")

    # ----- Arduino Serial Setup (for motor control via Arduino) -----
    SERIAL_PORT = os.getenv("ARDUINO_PORT", "/dev/ttyACM0")
    BAUD_RATE = 9600
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)  # allow Arduino to reset
        print(f"Connected to Arduino on {SERIAL_PORT} at {BAUD_RATE} baud")
    except Exception as e:
        ser = None
        print(f"Failed to open Arduino serial port: {e}")
else:
    print("Not running on Raspberry Pi: GPIO simulated")
    from gpiozero import LED, Device
    from gpiozero.pins.mock import MockFactory
    Device.pin_factory = MockFactory()
    ser = None

# Robot pins
PIN_FORWARD = 17
PIN_BACKWARD = 27
PIN_LEFT = 22
PIN_RIGHT = 23

if IS_PI:
    GPIO.setup(PIN_FORWARD, GPIO.OUT)
    GPIO.setup(PIN_BACKWARD, GPIO.OUT)
    GPIO.setup(PIN_LEFT, GPIO.OUT)
    GPIO.setup(PIN_RIGHT, GPIO.OUT)

# ---------------------- App Setup ----------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('MY_SECRET_KEY') or os.urandom(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---------------------- Models ----------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='viewer')  # viewer, operator, admin

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------------- Camera ----------------------
camera = cv2.VideoCapture(0)

def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            continue
        _, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
@login_required
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ---------------------- Robot Movement ----------------------
def move_robot(direction):
    # If running on Pi and Arduino serial is available, send the same commands
    # your friend's test Flask app used: F, B, L, R, S.
    if IS_PI and ser is not None:
        try:
            if direction == "forward":
                ser.write(b"F")
            elif direction == "backward":
                ser.write(b"B")
            elif direction == "left":
                ser.write(b"L")
               
            elif direction == "right":
                ser.write(b"R")
            elif direction == "stop":
                ser.write(b"S")
        except Exception as e:
            print(f"Serial error while sending '{direction}': {e}")
    elif IS_PI:
        # Fallback to direct GPIO control if serial is not available
        GPIO.output(PIN_FORWARD, GPIO.LOW)
        GPIO.output(PIN_BACKWARD, GPIO.LOW)
        GPIO.output(PIN_LEFT, GPIO.LOW)
        GPIO.output(PIN_RIGHT, GPIO.LOW)
        if direction == "forward":
            GPIO.output(PIN_FORWARD, GPIO.HIGH)
        elif direction == "backward":
            GPIO.output(PIN_BACKWARD, GPIO.HIGH)
        elif direction == "left":
            GPIO.output(PIN_LEFT, GPIO.HIGH)
        elif direction == "right":
            GPIO.output(PIN_RIGHT, GPIO.HIGH)
    else:
        print(f"Simulated move: {direction}")

@app.route('/move/<direction>', methods=['POST'])
@login_required
def move(direction):
    if current_user.role not in ['operator', 'admin']:
        return jsonify({"error": "Access denied"}), 403
    move_robot(direction)
    return jsonify({"status": f"Moved {direction}"}), 200

# ---------------------- Routes ----------------------
@app.route('/')
def home():
    # If user already logged in, send them to their dashboard directly
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('dashboard_admin'))
        elif current_user.role == 'operator':
            return redirect(url_for('dashboard_operator'))
        else:
            return redirect(url_for('dashboard_viewer'))

    # Otherwise show the landing page with base video
    return render_template('index.html')


# ---------------------- Register ----------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        # Validation
        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return redirect(url_for('register'))

        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            flash("Invalid email format.", "danger")
            return redirect(url_for('register'))

        if not re.match(r'^(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$', password):
            flash("Password must be at least 8 chars, include 1 uppercase, 1 number, and 1 special character.", "danger")
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password, role='viewer')
        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        flash("Registration successful! Welcome to Viewer Dashboard.", "success")
        return redirect(url_for('dashboard_viewer'))

    return render_template('register.html')

# ---------------------- Login ----------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('dashboard_admin'))
            elif user.role == 'operator':
                flash(f"Welcome {user.username}!", "success")
                return redirect(url_for('dashboard_operator'))
            else:
                flash(f"Welcome {user.username}!", "success")
                return redirect(url_for('dashboard_viewer'))
        else:
            flash("Invalid username or password.", "danger")

    return render_template('login.html')

# ---------------------- Logout ----------------------
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for('login'))

# ---------------------- Dashboards ----------------------
@app.route('/dashboard_viewer')
@login_required
def dashboard_viewer():
    return render_template('dashboard_viewer.html')

@app.route('/dashboard_operator')
@login_required
def dashboard_operator():
    if current_user.role not in ['operator', 'admin']:
        flash("Access denied!", "danger")
        return redirect(url_for('dashboard_viewer'))
    return render_template('dashboard_operator.html')

@app.route('/dashboard_admin')
@login_required
def dashboard_admin():
    if current_user.role != 'admin':
        flash("Access denied!", "danger")
        return redirect(url_for('dashboard_viewer'))
    users = User.query.all()
    existing_operator = User.query.filter_by(role='operator').first()
    return render_template('dashboard_admin.html', users=users, existing_operator=existing_operator)

# ---------------------- Admin Actions ----------------------
@app.route('/approve_operator/<int:user_id>')
@login_required
def approve_operator(user_id):
    if current_user.role != 'admin':
        flash("Access denied!", "danger")
        return redirect(url_for('dashboard_viewer'))

    existing_operator = User.query.filter_by(role='operator').first()
    if existing_operator:
        flash(f"Cannot promote. Operator '{existing_operator.username}' already exists.", "warning")
    else:
        user = User.query.get_or_404(user_id)
        if user.role == 'viewer':
            user.role = 'operator'
            db.session.commit()
            flash(f"{user.username} promoted to operator.", "success")
        else:
            flash(f"{user.username} cannot be promoted.", "warning")
    return redirect(url_for('dashboard_admin'))

@app.route('/demote_operator/<int:user_id>')
@login_required
def demote_operator(user_id):
    if current_user.role != 'admin':
        flash("Access denied!", "danger")
        return redirect(url_for('dashboard_viewer'))

    user = User.query.get_or_404(user_id)
    if user.role == 'operator':
        user.role = 'viewer'
        db.session.commit()
        flash(f"{user.username} demoted to viewer.", "success")
    else:
        flash(f"{user.username} cannot be demoted.", "warning")
    return redirect(url_for('dashboard_admin'))

@app.route('/remove_user/<int:user_id>')
@login_required
def remove_user(user_id):
    if current_user.role != 'admin':
        flash("Access denied!", "danger")
        return redirect(url_for('dashboard_viewer'))

    user = User.query.get_or_404(user_id)
    if user.role != 'admin':
        db.session.delete(user)
        db.session.commit()
        flash(f"{user.username} has been removed.", "success")
    else:
        flash("Cannot remove admin!", "danger")
    return redirect(url_for('dashboard_admin'))

# ---------------------- Auto-create Admin ----------------------
def create_default_admin():
    # Check for existing admin by email or username
    admin = User.query.filter(
        (User.username == 'Admin') | 
        (User.email == 'admin@gmail.com')
    ).first()

    if not admin:
        hashed_password = generate_password_hash("Thisisadmin01!")
        admin = User(
            username='Admin',
            email='admin@gmail.com',
            password=hashed_password,
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()
        print("Default admin created!")
    else:
        print("Admin already exists. Skipping creation.")


# ---------------------- Run App ----------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        create_default_admin()
    app.run(host="0.0.0.0", port=5000, debug=True)
```

templates\dashboard_operator.html
```html
{% extends "base.html" %}

{% block content %}
<div class="dashboard-container full-screen">
    <!-- Top Page Title -->
    <div class="page-title">Web Based Search And Rescue Robot</div>

    <!-- Header with Operator Dashboard and Logout -->
    <div class="dashboard-header">
        <h1 class="dashboard-title-big">Operator Dashboard</h1>
        <a href="{{ url_for('logout') }}" class="btn-logout">Logout</a>
    </div>

    <!-- Single White Box for All Controls -->
    <div class="control-panel">
        <!-- Top Buttons & Timer -->
        <div class="camera-controls">
            <button id="snapshotBtn" class="btn-primary" disabled>Take Snapshot</button>
            <button id="startBtn" class="btn-primary" disabled>Start Recording</button>
            <button id="stopBtn" class="btn-primary" disabled>Stop Recording</button>
            <div id="timer" class="recording-timer">00:00</div>
        </div>

        <!-- Camera Section -->
        <div class="camera-section">
            <div class="video-wrapper">
                <video id="video" autoplay playsinline></video>
                <div id="noCameraMessage">No Camera Detected</div>
            </div>
        </div>

        <!-- Robot Control Section -->
        <div class="robot-controls">
            <div class="control-layout">
                <div class="control-left">
                    <div class="control-buttons">
                        <div class="row">
                            <button class="btn-primary" onclick="moveRobot('forward')">↑ Forward</button>
                        </div>
                        <div class="row">
                            <button class="btn-primary" onclick="moveRobot('left')">← Left</button>
                            <button class="btn-primary" onclick="moveRobot('backward')">↓ Backward</button>
                            <button class="btn-primary" onclick="moveRobot('right')">→ Right</button>
                        </div>
                    </div>
                    <p class="hint">(Use arrow keys to control robot — Space to stop)</p>
                </div>
                <div class="control-right">
                    <div class="toggle-buttons">
                        <div class="toggle-row">
                            <span class="toggle-label">Light</span>
                            <label class="switch">
                                <input type="checkbox" id="lightToggle" onchange="toggleFeature('light')">
                                <span class="slider round"></span>
                            </label>
                        </div>
                        <div class="toggle-row">
                            <span class="toggle-label">Storage</span>
                            <label class="switch">
                                <input type="checkbox" id="storageToggle" onchange="toggleFeature('storage')">
                                <span class="slider round"></span>
                            </label>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
// ---------- CAMERA SETUP ----------
let mediaStream = null;
let mediaRecorder;
let recordedChunks = [];
let timerInterval;
let seconds = 0;

const video = document.getElementById('video');
const noCam = document.getElementById('noCameraMessage');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const snapshotBtn = document.getElementById('snapshotBtn');
const timerDisplay = document.getElementById('timer');

navigator.mediaDevices.getUserMedia({ video: true, audio: true })
.then(stream => {
    mediaStream = stream;
    video.srcObject = stream;
    noCam.style.display = "none";
    snapshotBtn.disabled = false;
    startBtn.disabled = false;
})
.catch(() => {
    noCam.style.display = "flex";
    video.style.display = "none";
});

// -------- SNAPSHOT --------
snapshotBtn.addEventListener('click', () => {
    if (!mediaStream) return alert("No camera detected.");
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext('2d');
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const imageURL = canvas.toDataURL("image/png");
    const a = document.createElement('a');
    a.href = imageURL;
    a.download = 'snapshot.png';
    a.click();
});

// -------- RECORDING --------
startBtn.addEventListener('click', () => {
    if (!mediaStream) return alert("No camera detected.");
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(mediaStream);
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) recordedChunks.push(e.data); };
    mediaRecorder.onstop = saveRecording;
    mediaRecorder.start();
    startBtn.disabled = true;
    stopBtn.disabled = false;
    seconds = 0;
    updateTimer();
    timerInterval = setInterval(updateTimer, 1000);
});

stopBtn.addEventListener('click', () => {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
        clearInterval(timerInterval);
        startBtn.disabled = false;
        stopBtn.disabled = true;
        timerDisplay.textContent = "00:00";
    }
});

function saveRecording() {
    const blob = new Blob(recordedChunks, { type: 'video/webm' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'recording.webm';
    a.click();
}

function updateTimer() {
    seconds++;
    const mins = String(Math.floor(seconds / 60)).padStart(2, '0');
    const secs = String(seconds % 60).padStart(2, '0');
    timerDisplay.textContent = `${mins}:${secs}`;
}

    // Robot control
    function moveRobot(direction) {
        fetch(`/move/${direction}`, { method: 'POST' })
            .then(r => r.text())
            .then(console.log)
            .catch(err => console.error("Robot control error:", err));
    }

    let lightOn = false;
    let storageOpen = false;

    function toggleFeature(feature) {
        if (feature === 'light') {
            const cb = document.getElementById('lightToggle');
            lightOn = cb ? cb.checked : false;
            moveRobot(lightOn ? 'light_on' : 'light_off');
        } else if (feature === 'storage') {
            const cb = document.getElementById('storageToggle');
            storageOpen = cb ? cb.checked : false;
            moveRobot(storageOpen ? 'storage_open' : 'storage_close');
        }
    }

    // Keyboard controls
    document.addEventListener('keydown', e => {
        switch (e.key) {
            case 'ArrowUp': moveRobot('forward'); break;
            case 'ArrowDown': moveRobot('backward'); break;
            case 'ArrowLeft': moveRobot('left'); break;
            case 'ArrowRight': moveRobot('right'); break;
            case ' ': moveRobot('stop'); break;
        }
    });
</script>

<style>
html, body { margin:0; padding:0; height:100%; width:100%; }

.page-title {
    text-align: center;
    font-size: 28px;
    font-weight: 700;
    color: #0a8f0a;
    margin: 10px 0;
}

.dashboard-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 20px 10px 20px;
}
.dashboard-title-big { font-size: 28px; font-weight: bold; margin: 0; }

.btn-logout {
    background: #e74c3c;
    color: white;
    text-decoration: none;
    padding: 6px 12px;
    border-radius: 6px;
    transition: 0.3s;
}
.btn-logout:hover { background-color: #c0392b; }

.control-panel {
    width: 100%;
    height: calc(100vh - 80px);
    background: #fff;
    padding: 15px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    align-items: stretch;
    border-radius: 12px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.1);
}

.camera-controls {
    display: flex;
    justify-content: center; /* centered */
    align-items: center;
    gap: 15px;
    margin-bottom: 10px;
}
.recording-timer {
    font-weight:bold;
    font-size:18px;
}

.camera-section { 
    flex: 1; 
    display: flex; 
    justify-content: center;
    align-items: center;
    margin: 10px 0;
}

/* 16:9 Aspect Ratio for Camera */
.video-wrapper {
    width: 100%;
    max-width: 1400px;
    aspect-ratio: 16 / 9;
    background:#000; 
    border-radius:12px; 
    overflow:hidden; 
    position:relative;
}
video { width:100%; height:100%; object-fit:cover; }
#noCameraMessage {
    display:none; position:absolute; inset:0; background:rgba(30,30,30,0.9);
    color:white; font-size:26px; display:flex; align-items:center; justify-content:center;
}

    .robot-controls {
        background:#f8f8f8; padding:15px; border-radius:12px; box-shadow:0 8px 20px rgba(0,0,0,0.05);
        text-align:left;
    }
    .control-layout {
        display:flex;
        justify-content:flex-start;
        align-items:flex-start;
        gap:32px;
        flex-wrap:wrap;
    }
    .control-left {
        display:flex;
        flex-direction:column;
        align-items:flex-start;
        flex:0 0 auto;
    }
    .control-right {
        display:flex;
        justify-content:flex-start;
        flex:0 0 auto;
        margin-left:24px;
    }
    .control-buttons { display:flex; flex-direction:column; gap:10px; }
    .control-buttons .row { display:flex; justify-content:center; gap:10px; }
    .toggle-buttons {
        display:flex;
        flex-direction:column;
        gap:16px;
        align-items:flex-start;
    }
    .toggle-row {
        display:flex;
        align-items:center;
        gap:10px;
    }
    .toggle-label {
        display:inline-block;
        font-size:16px;
        font-weight:600;
        color:#222;
        min-width:90px;
        text-align:left;
    }
    .switch {
        position:relative;
        display:inline-block;
        width:52px;
        height:30px;
    }
    .switch input {
        opacity:0;
        width:0;
        height:0;
    }
    .slider {
        position:absolute;
        cursor:pointer;
        top:0;
        left:0;
        right:0;
        bottom:0;
        background-color:#555;
        transition:.4s;
    }
    .slider:before {
        position:absolute;
        content:"";
        height:24px;
        width:24px;
        left:3px;
        bottom:3px;
        background-color:white;
        transition:.4s;
    }
    input:checked + .slider {
        background-color:#28a745;
    }
    input:checked + .slider:before {
        transform:translateX(22px);
    }
    .slider.round {
        border-radius:34px;
    }
    .slider.round:before {
        border-radius:50%;
    }
    .hint { font-size:14px; color:#555; }

.btn-primary { background-color:#0a8f0a; color:white; padding:10px 16px; border:none; border-radius:6px; cursor:pointer; font-size:16px; }
.btn-primary:hover { background-color:#087607; }

@media(max-width:768px){
    .page-title { font-size:24px; }
    .dashboard-title-big { font-size:22px; }
    .btn-primary { font-size:14px; padding:8px 12px; }
}
</style>
{% endblock %}
```
