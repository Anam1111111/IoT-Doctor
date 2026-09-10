import serial
import re
import yaml
from datetime import datetime

# Load the profile
with open("profiles/fake_device.yaml", "r") as f:
    profile = yaml.safe_load(f)

tool_port = serial.Serial(profile["port"], baudrate=profile["baud_rate"])
pattern = profile["log_pattern"]
symbols = profile["level_symbols"]

log_filename = datetime.now().strftime("session_%Y-%m-%d_%H-%M-%S.log")
log_file = open(log_filename, "a")
print(f"Using profile: {profile['name']}")
print(f"Saving session to: {log_filename}")

while True:
    line = tool_port.readline().decode().strip()
    if not line:
        continue

    match = re.match(pattern, line)
    if match:
        level = match.group(1)
        message = match.group(2)
        count = match.group(3)
        symbol = symbols.get(level, "❓")
        display_line = f"{symbol} level={level} | message={message} | count={count}"
    else:
        display_line = f"❓ Unrecognized line: {line}"

    print(display_line)

    timestamp = datetime.now().strftime("%H:%M:%S")
    log_file.write(f"[{timestamp}] {display_line}\n")
    log_file.flush()