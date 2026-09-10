import serial
import time
import random

device_port = serial.Serial('/dev/ttys001', baudrate=9600)

levels = ["[INFO]", "[WARN]", "[ERROR]"]
messages = ["Wi-Fi connected", "Low memory", "Sensor timeout", "Battery at 20%"]

count = 0
while True:
    level = random.choice(levels)
    msg = random.choice(messages)
    line = f"{level} {msg}, count={count}\n"
    device_port.write(line.encode())
    print(f"Sent: {line.strip()}")
    count += 1
    time.sleep(1)