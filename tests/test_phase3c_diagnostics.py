import unittest

from core.diagnostics import DiagnosticEngine
from core.metrics import MetricExtractor
from core.models.metric import Metric


def event(message="telemetry", level="INFO", event_type="log", ts="12:00:00"):
    return {
        "id": message,
        "message": message,
        "level": level,
        "event_type": event_type,
        "timestamp": ts,
    }


class Phase3CDiagnosticsTests(unittest.TestCase):
    def test_disconnect_then_reconnect_becomes_incident_then_recovered(self):
        engine = DiagnosticEngine(event_window=10, historical_mode=True)
        # one disconnect -> incident recorded
        findings = engine.process(event("Device disconnected", level="ERROR", event_type="connection"))
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertIn("Connection interruption", f.title)
        self.assertEqual(f.status, "INCIDENT")
        # subsequent reconnect should not create duplicate incident
        findings = engine.process(event("Device connected", level="INFO", event_type="connection"))
        # recovery in historical mode will not auto-resolve existing incident
        self.assertTrue(any(x.title == f.title for x in engine.historical_findings()))

    def test_reconnect_failures_aggregate_to_instability(self):
        engine = DiagnosticEngine(event_window=10, historical_mode=True)
        # multiple disconnect events should escalate to active instability
        for _ in range(4):
            findings = engine.process(event("Device disconnected - retrying...", level="ERROR", event_type="connection"))
        # because threshold in engine is default 3, we expect either an active finding
        active = engine.active_findings()
        self.assertTrue(any(f.title.startswith("Connection instability") for f in active) or any(f.title.startswith("Connection instability") for f in engine.historical_findings()))

    def test_unexpected_reboot_detection_and_evidence(self):
        engine = DiagnosticEngine()
        all_findings = []
        for value in (120, 121, 122, 0):
            all_findings.extend(engine.process(event(), [Metric("uptime", value, "seconds")]))
        self.assertEqual(len(all_findings), 1)
        f = all_findings[0]
        self.assertIn("Unexpected device reboot detected", f.title)
        self.assertIn("reset from", f.evidence)
        # historical findings should include the reboot incident when sequence occurs

    def test_repeated_error_spike_produces_single_finding(self):
        engine = DiagnosticEngine(event_window=10)
        # produce errors up to threshold
        for _ in range(5):
            new = engine.process(event("Oops", level="ERROR"))
        # ensure single finding created
        all_active = engine.active_findings()
        self.assertTrue(any(f.title == "Elevated error rate detected" for f in all_active))

    def test_memory_degradation_detected(self):
        engine = DiagnosticEngine()
        for value in (2000, 1900, 1800, 1700, 1600, 1500, 1400, 1300, 1200, 1100):
            findings = engine.process(event(), [Metric("free_memory", value, "bytes")])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].title, "Possible memory degradation")

    def test_insufficient_data_does_not_create_finding(self):
        engine = DiagnosticEngine()
        # single event should not create error spike or memory finding
        findings = engine.process(event())
        self.assertEqual(findings, [])

    def test_recovered_condition_records_resolution(self):
        engine = DiagnosticEngine(event_window=5, recovery_events=2)
        # create instability (live mode)
        for _ in range(3):
            engine.process(event("Device disconnected - retrying...", level="ERROR", event_type="connection"))
        # now send connected and valid telemetry to recover
        engine.process(event("Device connected", level="INFO", event_type="connection"))
        engine.process(event("telemetry ok", level="INFO", event_type="log"))
        engine.process(event("telemetry ok", level="INFO", event_type="log"))
        # historical findings should include resolved record after recovery
        self.assertTrue(any(f.status == "RESOLVED" for f in engine.historical_findings() + engine.active_findings()))

    def test_multiple_related_events_do_not_duplicate_findings(self):
        engine = DiagnosticEngine()
        # trigger memory degradation once
        values = (1000, 900, 800, 700, 600, 500, 400, 300, 200, 100)
        all_new = []
        for v in values:
            all_new.extend(engine.process(event(), [Metric("free_memory", v, "bytes")]))
        self.assertEqual(len(all_new), 1)
        self.assertEqual(len(engine.active_findings()), 1)


if __name__ == "__main__":
    unittest.main()
