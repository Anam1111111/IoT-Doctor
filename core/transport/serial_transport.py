import serial
from core.transport.base import Transport

class SerialTransport(Transport):
    def __init__(self, port, baud_rate):
        self.port = port
        self.baud_rate = baud_rate
        self.connection = None

    def connect(self):
        self.connection = serial.Serial(self.port, baudrate=self.baud_rate)

    def read_line(self):
        return self.connection.readline().decode(errors="ignore").strip()

    def is_connected(self):
        return self.connection is not None and self.connection.is_open
