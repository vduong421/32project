Admin
Thisisadmin01!

user
Thisisuser01!

viewer
Thisisviewer01!


 * Running on http://127.0.0.1:5000
 * Running on http://10.0.0.89:5000



## IMPORTANT INSTALL STEPS (MUST FOLLOW)
sudo apt install -y libcamera-dev libcamera-apps python3-libcamera python3-kms++ python3-picamera2
cd ~/Desktop/32project
rm -rf venv
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
