import unittest

from core.diagnostics import DiagnosticEngine
from core.metrics import MetricExtractor
from core.models.metric import Metric


def event(message="telemetry", level="INFO", event_type="log"):
    return {
        "id": message,
        "message": message,
        "level": level,
        "event_type": event_type,
        "timestamp": "12:00:00",
    }


class DiagnosticEngineTests(unittest.TestCase):
    def test_metric_extractor_supports_profile_defined_arduino_metrics(self):
        extractor = MetricExtractor(
            {
                "uptime": {
                    "source": "message",
                    "pattern": r"Uptime=(?P<value>\d+)s",
                    "unit": "seconds",
                },
                "free_memory": {
                    "source": "message",
                    "pattern": r"FreeRAM=(?P<value>\d+)b",
                    "unit": "bytes",
                },
            }
        )
        metrics = extractor.extract(event("Uptime=27s, FreeRAM=1778b"))
        self.assertEqual([(metric.name, metric.value) for metric in metrics], [
            ("uptime", 27),
            ("free_memory", 1778),
        ])

    def test_stable_memory_does_not_create_finding(self):
        engine = DiagnosticEngine()
        for _ in range(10):
            findings = engine.process(event(), [Metric("free_memory", 1778, "bytes")])
        self.assertEqual(findings, [])
        self.assertEqual(engine.active_findings(), [])

    def test_strict_memory_decline_creates_finding(self):
        engine = DiagnosticEngine()
        findings = []
        for value in (1778, 1770, 1760, 1750, 1740, 1730, 1720, 1710, 1700, 1690):
            findings = engine.process(event(), [Metric("free_memory", value, "bytes")])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].title, "Possible memory degradation")
        self.assertEqual(findings[0].severity, "WARNING")

    def test_uptime_reset_creates_reboot_finding(self):
        engine = DiagnosticEngine()
        findings = []
        for value in (120, 121, 122, 0):
            findings = engine.process(event(), [Metric("uptime", value, "seconds")])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].title, "Unexpected device reboot detected")
        self.assertIn("reset from 122 seconds to 0 seconds", findings[0].evidence)

    def test_small_uptime_decrease_does_not_create_reboot_finding(self):
        engine = DiagnosticEngine()
        for value in (72, 70):
            findings = engine.process(event(), [Metric("uptime", value, "seconds")])
        self.assertEqual(findings, [])

    def test_small_uptime_decrease_is_not_reboot_evidence(self):
        engine = DiagnosticEngine()
        for value in (100, 98):
            findings = engine.process(event(), [Metric("uptime", value, "seconds")])
        self.assertEqual(findings, [])

    def test_same_uptime_has_no_reboot_finding(self):
        engine = DiagnosticEngine()
        for value in (100, 100):
            findings = engine.process(event(), [Metric("uptime", value, "seconds")])
        self.assertEqual(findings, [])

    def test_out_of_order_uptime_sequence_has_no_reboot_finding(self):
        engine = DiagnosticEngine()
        for value in (72, 70, 71):
            findings = engine.process(event(), [Metric("uptime", value, "seconds")])
        self.assertEqual(findings, [])

    def test_near_zero_reset_from_high_uptime_creates_reboot_finding(self):
        engine = DiagnosticEngine()
        for value in (500, 1):
            findings = engine.process(event(), [Metric("uptime", value, "seconds")])
        self.assertEqual(len(findings), 1)
        self.assertIn("reset from 500 seconds to 1 seconds", findings[0].evidence)

    def test_reboot_sequence_creates_one_incident(self):
        engine = DiagnosticEngine()
        all_findings = []
        for value in (72, 73, 74, 0, 1, 2):
            all_findings.extend(
                engine.process(event(), [Metric("uptime", value, "seconds")])
            )
        self.assertEqual(len(all_findings), 1)
        self.assertEqual(len(engine.historical_findings()), 1)

    def test_repeated_startup_values_create_one_incident(self):
        engine = DiagnosticEngine()
        all_findings = []
        for value in (72, 0, 0, 1):
            all_findings.extend(
                engine.process(event(), [Metric("uptime", value, "seconds")])
            )
        self.assertEqual(len(all_findings), 1)
        self.assertEqual(len(engine.historical_findings()), 1)

    def test_39_to_zero_sequence_creates_one_incident(self):
        engine = DiagnosticEngine()
        all_findings = []
        for value in (39, 0, 1, 2):
            all_findings.extend(
                engine.process(event(), [Metric("uptime", value, "seconds")])
            )
        self.assertEqual(len(all_findings), 1)
        self.assertIn("reset from 39 seconds to 0 seconds", all_findings[0].evidence)

    def test_normal_uptime_progression_has_no_reboot_finding(self):
        engine = DiagnosticEngine()
        for value in (120, 121, 122, 123):
            findings = engine.process(event(), [Metric("uptime", value, "seconds")])
        self.assertEqual(findings, [])

    def test_error_spike_threshold(self):
        engine = DiagnosticEngine()
        for _ in range(4):
            self.assertEqual(engine.process(event(level="ERROR")), [])
        findings = engine.process(event(level="ERROR"))
        self.assertEqual(findings[0].title, "Elevated error rate detected")

    def test_connection_instability_threshold(self):
        engine = DiagnosticEngine()
        findings = engine.process(event("Device disconnected", event_type="connection"))
        self.assertEqual(findings[0].title, "Connection instability detected")

    def test_active_finding_is_deduplicated(self):
        engine = DiagnosticEngine()
        values = (1778, 1770, 1760, 1750, 1740, 1730, 1720, 1710, 1700, 1690, 1680)
        all_new_findings = []
        for value in values:
            all_new_findings.extend(
                engine.process(event(), [Metric("free_memory", value, "bytes")])
            )
        self.assertEqual(len(all_new_findings), 1)
        self.assertEqual(len(engine.active_findings()), 1)


if __name__ == "__main__":
    unittest.main()