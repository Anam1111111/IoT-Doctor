import subprocess
import time
import re
import webbrowser
import sys
import signal
import yaml

processes = []

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

# Update fake_device.py with the new device port
with open("fake_device.py", "r") as f:
    content = f.read()
content = re.sub(r"serial\.Serial\('[^']+'", f"serial.Serial('{device_port}'", content)
with open("fake_device.py", "w") as f:
    f.write(content)

# Update the yaml profile with the new tool port
with open("profiles/fake_device.yaml", "r") as f:
    profile = yaml.safe_load(f)
profile["port"] = tool_port
with open("profiles/fake_device.yaml", "w") as f:
    yaml.dump(profile, f, default_flow_style=False)

print("Ports synced automatically.\n")
time.sleep(0.5)

print("Starting fake device...")
fake_device = subprocess.Popen([sys.executable, "fake_device.py"])
processes.append(fake_device)

time.sleep(1)

print("Starting server...")
server = subprocess.Popen(["uvicorn", "server:app"])
processes.append(server)

time.sleep(2)

print("Opening dashboard...")
webbrowser.open("http://127.0.0.1:8000")

print("\nEverything is running. Press Ctrl+C to stop.\n")

while True:
    time.sleep(1)
