import serial
from core.transport.base import Transport

class SerialTransport(Transport):
    def __init__(self, port, baud_rate, timeout=1.0):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.connection = None

    def connect(self):
        self.close()
        self.connection = serial.Serial(
            self.port,
            baudrate=self.baud_rate,
            timeout=self.timeout,
        )

    def receive(self):
        if not self.is_connected():
            raise serial.SerialException("Serial transport is not connected")
        return self.connection.readline().decode(errors="ignore").strip()

    def is_connected(self):
        return self.connection is not None and self.connection.is_open

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def metadata(self):
        return {
            "transport": "serial",
            "port": self.port,
            "baud_rate": self.baud_rate,
            "connected": self.is_connected(),
        }
