from flask import Flask, render_template, Response, request
import cv2

app = Flask(__name__)

# Initialize camera
camera = cv2.VideoCapture(0)  # Use 0 for built-in webcam, or change to your Pi camera index

# Video streaming function
def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            _, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

# Route for video streaming
@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# Control commands (for rover movement)
@app.route('/control', methods=['POST'])
def control():
    command = request.form.get("command")
    print(f"Received command: {command}")
    # Here, you would add your GPIO control logic for the Raspberry Pi motors
    return "OK", 200

# Route for the HTML page
@app.route('/')
def index():
    return render_template('index.html')  # Load HTML page

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
