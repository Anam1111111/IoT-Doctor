import asyncio
import unittest

import serial

from core.parser.regex_parser import RegexParser
from core.server import handle_transport_failure, health, process_serial_data, record_reconnect_attempt
from core.transport.serial_transport import SerialTransport


class FakeSerialConnection:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.is_open = True

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, size):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.is_open = False


class FailingSerialConnection(FakeSerialConnection):
    def read(self, size):
        raise serial.SerialException("device read failed")


class RuntimeSerialTests(unittest.TestCase):
    def test_complete_serial_line_returns_one_message(self):
        transport = SerialTransport("/dev/test", 9600)
        transport.connection = FakeSerialConnection([b"full line\n"])

        self.assertEqual(transport.receive(), "full line")

    def test_partial_serial_data_is_buffered_until_newline(self):
        transport = SerialTransport("/dev/test", 9600)
        transport.connection = FakeSerialConnection([b"full ", b"line\n"])

        self.assertIsNone(transport.receive())
        self.assertEqual(transport.receive(), "full line")

    def test_two_complete_lines_are_returned_one_at_a_time(self):
        transport = SerialTransport("/dev/test", 9600)
        transport.connection = FakeSerialConnection([
            b"[INFO] Uptime=168s, FreeRAM=1778b, count=168\n"
            b"[INFO] Uptime=169s, FreeRAM=1778b, count=169\n"
        ])

        self.assertEqual(
            transport.receive(),
            "[INFO] Uptime=168s, FreeRAM=1778b, count=168",
        )
        self.assertEqual(
            transport.receive(),
            "[INFO] Uptime=169s, FreeRAM=1778b, count=169",
        )

    def test_partial_line_followed_by_two_complete_lines(self):
        transport = SerialTransport("/dev/test", 9600)
        transport.connection = FakeSerialConnection([
            b"[INFO] Uptime=168s, FreeRAM=17",
            b"78b, count=168\n[INFO] Uptime=169s, FreeRAM=1778b, count=169\n",
        ])

        self.assertIsNone(transport.receive())
        self.assertEqual(
            transport.receive(),
            "[INFO] Uptime=168s, FreeRAM=1778b, count=168",
        )
        self.assertEqual(
            transport.receive(),
            "[INFO] Uptime=169s, FreeRAM=1778b, count=169",
        )

    def test_timeout_without_data_is_not_a_disconnect(self):
        transport = SerialTransport("/dev/test", 9600)
        transport.connection = FakeSerialConnection([b""])

        self.assertIsNone(transport.receive())
        self.assertTrue(transport.is_connected())

    def test_genuine_serial_failure_is_raised(self):
        transport = SerialTransport("/dev/test", 9600)
        transport.connection = FailingSerialConnection([])

        with self.assertRaises(serial.SerialException):
            transport.receive()

    def test_genuine_serial_failure_enters_disconnect_path(self):
        server_module = __import__("core.server", fromlist=["transport"])
        original_transport = server_module.transport
        original_state = server_module.connection_state

        class FailedTransport:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

            def metadata(self):
                return {"transport": "serial", "port": "/dev/test"}

        failed_transport = FailedTransport()
        server_module.transport = failed_transport
        server_module.connection_state = "CONNECTED"
        before = health.reconnect_count
        try:
            asyncio.run(handle_transport_failure(serial.SerialException("read failed")))
        finally:
            server_module.transport = original_transport
            server_module.connection_state = original_state

        self.assertTrue(failed_transport.closed)
        self.assertEqual(health.reconnect_count, before + 1)

    def test_reconnect_attempt_does_not_increment_disconnect_incidents(self):
        server_module = __import__("core.server", fromlist=["reconnect_attempts"])
        original_attempts = server_module.reconnect_attempts
        original_state = server_module.connection_state
        before_incidents = health.disconnect_incidents
        before_attempts = health.reconnect_attempts
        try:
            record_reconnect_attempt(serial.SerialException("port still unavailable"))
            record_reconnect_attempt(serial.SerialException("port still unavailable"))
            attempts_after_retry = health.reconnect_attempts
        finally:
            server_module.reconnect_attempts = original_attempts
            server_module.connection_state = original_state
            health.set_connection_metrics(reconnect_attempts=before_attempts)

        self.assertEqual(health.disconnect_incidents, before_incidents)
        self.assertEqual(attempts_after_retry, before_attempts + 2)
        self.assertEqual(health.reconnect_attempts, before_attempts)

    def test_valid_arduino_message_is_structured(self):
        parser = RegexParser(r"\[(\w+)\]\s(.+),\scount=(\d+)")

        self.assertEqual(
            parser.parse("[INFO] Uptime=411s, FreeRAM=1778b, count=411"),
            {
                "level": "INFO",
                "message": "Uptime=411s, FreeRAM=1778b",
                "count": "411",
            },
        )

    def test_malformed_data_is_safe_to_parse(self):
        parser = RegexParser(r"\[(\w+)\]\s(.+),\scount=(\d+)")
        self.assertIsNone(parser.parse("FreeRAM=1778b, count=409"))

    def test_parser_receives_only_complete_logical_messages(self):
        transport = SerialTransport("/dev/test", 9600)
        transport.connection = FakeSerialConnection([
            b"[INFO] Uptime=168s, FreeRAM=1778b, count=168\n"
            b"[INFO] Uptime=169s, FreeRAM=1778b, count=169\n",
        ])
        parser = RegexParser(r"\[(\w+)\]\s(.+),\scount=(\d+)")
        received = []

        for _ in range(2):
            raw_data = transport.receive()
            received.append(raw_data)
            self.assertIsNotNone(parser.parse(raw_data))

        self.assertEqual(received, [
            "[INFO] Uptime=168s, FreeRAM=1778b, count=168",
            "[INFO] Uptime=169s, FreeRAM=1778b, count=169",
        ])

    def test_serial_options_request_exclusive_port_access(self):
        self.assertTrue(hasattr(serial.Serial, "exclusive"))

    def test_parser_failure_does_not_increment_reconnect_count(self):
        original_parser = __import__("core.server", fromlist=["parser"]).parser

        class FailingParser:
            def parse(self, raw_data):
                raise ValueError("parser failed")

        server_module = __import__("core.server", fromlist=["parser"])
        server_module.parser = FailingParser()
        before = health.reconnect_count
        try:
            with self.assertRaises(ValueError):
                process_serial_data("not a valid event")
        finally:
            server_module.parser = original_parser

        self.assertEqual(health.reconnect_count, before)


if __name__ == "__main__":
    unittest.main()