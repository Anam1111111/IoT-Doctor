import unittest
from core.diagnostics import DiagnosticEngine


def ev(msg, level="ERROR"):
    return {"id": msg, "message": msg, "level": level, "event_type": "log", "timestamp": "12:00:00"}


class PersistentFailureTests(unittest.TestCase):
    def test_persistent_failure_escalates_to_critical(self):
        engine = DiagnosticEngine(event_window=50, historical_mode=True)
        seq = [
            "timeout waiting for sensor",
            "timeout waiting for sensor",
            "timeout waiting for sensor",
            "timeout waiting for sensor",
            "timeout waiting for sensor",
            "command failed after maximum retries",
            "communication failure: verification could not complete",
        ]
        findings = []
        for m in seq:
            findings.extend(engine.process(ev(m)))
        # Expect at least one CRITICAL persistent communication finding
        crit = [f for f in engine.historical_findings() + engine.active_findings() if getattr(f, 'severity', '').upper() == 'CRITICAL']
        self.assertTrue(crit, "Expected a CRITICAL finding for persistent failure")
        # Ensure the finding remains unresolved (no recovery in sequence)
        self.assertTrue(all(getattr(f, 'status', 'INCIDENT') != 'RESOLVED' for f in crit))

    def test_error_spike_still_detected_as_warning(self):
        engine = DiagnosticEngine(event_window=20)
        for _ in range(6):
            engine.process(ev("intermittent timeout", level="ERROR"))
        warnings = [f for f in engine.active_findings() if getattr(f, 'category', None) == 'errors']
        self.assertTrue(warnings and warnings[0].severity == 'WARNING')

    def test_short_recovered_burst_does_not_escalate(self):
        engine = DiagnosticEngine(event_window=50)
        # short burst then recovery message should not escalate to persistent
        seq = [
            "timeout waiting for sensor",
            "timeout waiting for sensor",
            "acknowledgment received",
        ]
        for m in seq:
            engine.process(ev(m))
        crit = [f for f in engine.active_findings() if getattr(f, 'severity', '').upper() == 'CRITICAL']
        self.assertFalse(crit)


if __name__ == '__main__':
    unittest.main()
