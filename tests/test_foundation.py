import unittest

from core.config.profile_loader import ProfileLoader
from core.health.monitor import HealthMonitor
from core.normalization.normalizer import EventNormalizer
from core.parser.regex_parser import RegexParser
from core.transport.serial_transport import SerialTransport


class FoundationTests(unittest.TestCase):
    def test_equal_ram_values_do_not_trigger_memory_degradation(self):
        monitor = HealthMonitor()
        monitor.update({"level": "INFO", "message": "Device connected"})
        for _ in range(10):
            monitor.update({"level": "INFO", "message": "FreeRAM=1778b"})

        self.assertNotEqual(
            monitor.status()["reason"],
            "Free RAM decreasing continuously — possible memory leak",
        )

    def test_strictly_decreasing_ram_values_trigger_memory_degradation(self):
        monitor = HealthMonitor()
        monitor.update({"level": "INFO", "message": "Device connected"})
        for ram in (1778, 1770, 1760, 1750, 1740, 1730, 1720, 1710, 1700, 1690):
            monitor.update({"level": "INFO", "message": f"FreeRAM={ram}b"})

        self.assertEqual(monitor.status()["status"], "WARNING")
        self.assertEqual(
            monitor.status()["reason"],
            "Free RAM decreasing continuously — possible memory leak",
        )

    def test_regex_parser_returns_structured_data(self):
        parser = RegexParser(r"\[(\w+)\]\s(.+),\scount=(\d+)")
        self.assertEqual(
            parser.parse("[ERROR] Sensor timeout, count=12"),
            {"level": "ERROR", "message": "Sensor timeout", "count": "12"},
        )

    def test_regex_parser_supports_named_fields(self):
        parser = RegexParser(
            r"\[(?P<level>\w+)\]\s(?P<message>.+),\scount=(?P<count>\d+)"
        )
        self.assertEqual(
            parser.parse("[INFO] Ready, count=1"),
            {"level": "INFO", "message": "Ready", "count": "1"},
        )

    def test_normalizer_preserves_dashboard_fields_and_adds_metadata(self):
        event = EventNormalizer(
            device_id="Arduino UNO",
            level_symbols={"WARN": "!"},
        ).normalize(
            {"level": "WARN", "message": "Low memory", "count": "7"},
            raw="[WARN] Low memory, count=7",
            transport_metadata={
                "transport": "serial",
                "port": "/dev/cu.test",
                "baud_rate": 9600,
            },
        )
        self.assertEqual(event["level"], "WARN")
        self.assertEqual(event["count"], "7")
        self.assertEqual(event["symbol"], "!")
        self.assertEqual(event["transport"], "serial")
        self.assertEqual(event["metadata"]["baud_rate"], 9600)
        self.assertIn("id", event)

    def test_profile_loader_defaults_to_arduino_profile(self):
        profile = ProfileLoader(".").load()
        self.assertEqual(profile["name"], "Arduino UNO")
        self.assertIn("profile_path", profile)

    def test_serial_metadata_reports_connection_configuration(self):
        transport = SerialTransport("/dev/cu.test", 9600)
        self.assertEqual(transport.metadata()["transport"], "serial")
        self.assertEqual(transport.metadata()["port"], "/dev/cu.test")
        self.assertFalse(transport.is_connected())


if __name__ == "__main__":
    unittest.main()
