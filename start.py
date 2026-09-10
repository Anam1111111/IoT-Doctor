import subprocess
import time
import re
import webbrowser
import sys
import signal
import os
import yaml

processes = []
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def cleanup(signum=None, frame=None):
    print("\nShutting down...")
    for p in processes:
        p.terminate()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)

print("Starting socat...")
socat = subprocess.Popen(
    ["socat", "-d", "-d", "pty,raw,echo=0", "pty,raw,echo=0"],
    stderr=subprocess.PIPE, text=True
)
processes.append(socat)

# Read socat's stderr until we've captured both PTY paths
ports = []
while len(ports) < 2:
    line = socat.stderr.readline()
    match = re.search(r"PTY is (/dev/\S+)", line)
    if match:
        ports.append(match.group(1))

device_port, tool_port = ports
print(f"Device port: {device_port}")
print(f"Tool port:   {tool_port}")

# Update tools/fake_device.py with the new device port
fake_device_path = os.path.join(BASE_DIR, "tools", "fake_device.py")
with open(fake_device_path, "r") as f:
    content = f.read()
content = re.sub(r"serial\.Serial\('[^']+'", f"serial.Serial('{device_port}'", content)
with open(fake_device_path, "w") as f:
    f.write(content)

# Update the yaml profile with the new tool port
fake_profile_path = os.path.join(BASE_DIR, "profiles", "fake_device.yaml")
with open(fake_profile_path, "r") as f:
    profile = yaml.safe_load(f)
profile["port"] = tool_port
with open(fake_profile_path, "w") as f:
    yaml.dump(profile, f, default_flow_style=False)

print("Ports synced automatically.\n")
time.sleep(0.5)

print("Starting fake device...")
fake_device = subprocess.Popen([sys.executable, fake_device_path], cwd=BASE_DIR)
processes.append(fake_device)

time.sleep(1)

print("Starting server...")
environment = os.environ.copy()
environment["IOT_PROFILE"] = "fake_device.yaml"
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "core.server:app"],
    cwd=BASE_DIR,
    env=environment,
)
processes.append(server)

time.sleep(2)

print("Opening dashboard...")
webbrowser.open("http://127.0.0.1:8000")

print("\nEverything is running. Press Ctrl+C to stop.\n")

while True:
    time.sleep(1)
