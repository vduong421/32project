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

# ---------------------- GPIO + Arduino + Camera Setup ----------------------
IS_PI = platform.system() == "Linux"

if IS_PI:
    import RPi.GPIO as GPIO
    from picamera2 import Picamera2
    import threading

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

# ---------------------- Camera (PiCamera2 when on Pi, cv2.VideoCapture otherwise) ----------------------
if IS_PI:
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
    picam2.start()
    frame_lock = threading.Lock()
    camera = None
else:
    picam2 = None
    frame_lock = None
    camera = cv2.VideoCapture(0)

def generate_frames():
    while True:
        if IS_PI and picam2 is not None:
            # Raspberry Pi: use Picamera2 (same style as your friend's working code)
            with frame_lock:
                frame = picam2.capture_array()

            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue
        else:
            # Laptop / non-Pi: fall back to local webcam
            if camera is None:
                break
            success, frame = camera.read()
            if not success:
                continue
            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue

        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )

@app.route('/video_feed')
@login_required
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ---------------------- Robot Movement ----------------------
def move_robot(direction):
    # If running on Pi and Arduino serial is available, send commands: F, B, L, R, S
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
            else:
                # Unknown extra commands (light/storage toggles etc.)
                print(f"Unknown direction command received: {direction}")
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
        elif direction == "stop":
            pass
        else:
            print(f"Unknown GPIO direction command received: {direction}")
    else:
        # Non-Pi dev mode
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
