import serial
from core.transport.base import Transport
import logging
import os

class SerialTransport(Transport):
    def __init__(self, port, baud_rate, timeout=1.0):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.connection = None
        self._buffer = bytearray()

    def connect(self):
        self.close()
        serial_options = {
            "baudrate": self.baud_rate,
            "timeout": self.timeout,
        }
        if hasattr(serial.Serial, "exclusive"):
            serial_options["exclusive"] = True
        self.connection = serial.Serial(self.port, **serial_options)
        self._buffer.clear()

    def receive(self):
        if not self.is_connected():
            raise serial.SerialException("Serial transport is not connected")

        newline_index = self._buffer.find(b"\n")
        if newline_index >= 0:
            line = self._pop_line(newline_index)
            # Forensic debug logging (enabled via FORENSIC=1)
            try:
                if os.environ.get("FORENSIC") == "1":
                    logging.getLogger("forensic").debug(
                        "RAW:%r | BUFFER_AFTER_APPEND:%r | EXTRACTED:%r",
                        bytes(line, "utf-8", errors="ignore") if isinstance(line, str) else line,
                        bytes(self._buffer),
                        line,
                    )
            except Exception:
                pass
            return line

        available = getattr(self.connection, "in_waiting", 0)
        chunk = self.connection.read(available or 1)
        if not chunk:
            if not self.is_connected():
                raise serial.SerialException("Serial connection closed")
            return None

        self._buffer.extend(chunk)
        newline_index = self._buffer.find(b"\n")
        if newline_index < 0:
            return None
        line = self._pop_line(newline_index)
        try:
            if os.environ.get("FORENSIC") == "1":
                logging.getLogger("forensic").debug(
                    "RAW:%r | BUFFER_AFTER_APPEND:%r | EXTRACTED:%r",
                    chunk,
                    bytes(self._buffer),
                    line,
                )
        except Exception:
            pass
        return line

    def _pop_line(self, newline_index):
        line = bytes(self._buffer[:newline_index])
        del self._buffer[: newline_index + 1]
        return line.decode(errors="ignore").rstrip("\r")

    def is_connected(self):
        return self.connection is not None and self.connection.is_open

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self._buffer.clear()

    def metadata(self):
        return {
            "transport": "serial",
            "port": self.port,
            "baud_rate": self.baud_rate,
            "connected": self.is_connected(),
        }
