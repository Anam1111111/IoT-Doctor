import unittest

from core.diagnostics import DiagnosticEngine
from core.health.monitor import HealthMonitor
from core.models.finding import Finding
from core.models.metric import Metric


def connection_event(message):
    return {
        "id": message,
        "message": message,
        "level": "ERROR" if "disconnected" in message.lower() else "INFO",
        "event_type": "connection",
    }


def telemetry_event(index):
    return {
        "id": f"telemetry-{index}",
        "message": f"Uptime={index}s, FreeRAM=1778b",
        "level": "INFO",
        "event_type": "log",
    }


class FindingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = DiagnosticEngine()
        self.health = HealthMonitor()

    def process(self, event, metrics=None):
        self.engine.process(event, metrics or [])
        self.health.update(event, metrics=metrics, findings=self.engine.all_findings())

    def test_disconnect_is_active_critical(self):
        self.process(connection_event("Device disconnected - retrying..."))
        finding = self.engine.active_findings()[0]
        self.assertEqual(finding.status, "ACTIVE")
        self.assertEqual(finding.severity, "CRITICAL")
        self.assertEqual(self.health.status()["status"], "CRITICAL")

    def test_reconnect_enters_recovering(self):
        self.process(connection_event("Device disconnected - retrying..."))
        self.process(connection_event("Device connected"))
        finding = self.engine.active_findings()[0]
        self.assertEqual(finding.status, "RECOVERING")
        self.assertEqual(self.health.status()["status"], "RECOVERING")

    def test_five_valid_events_resolve_connection_finding(self):
        self.process(connection_event("Device disconnected - retrying..."))
        self.process(connection_event("Device connected"))
        for index in range(5):
            self.process(telemetry_event(index), [Metric("uptime", index, "seconds")])

        self.assertEqual(self.engine.active_findings(), [])
        history = self.engine.historical_findings()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, "RESOLVED")
        self.assertIn("5 consecutive valid", history[0].resolution_reason)
        self.assertEqual(self.health.status()["status"], "HEALTHY")

    def test_reconnect_count_remains_historical_after_recovery(self):
        self.process(connection_event("Device disconnected - retrying..."))
        self.process(connection_event("Device connected"))
        for index in range(5):
            self.process(telemetry_event(index))
        self.assertEqual(self.health.status()["reconnect_count"], 1)

    def test_disconnect_during_recovery_reactivates_one_finding(self):
        self.process(connection_event("Device disconnected - retrying..."))
        self.process(connection_event("Device connected"))
        for index in range(3):
            self.process(telemetry_event(index))
        self.process(connection_event("Device disconnected - retrying..."))

        self.assertEqual(len(self.engine.active_findings()), 1)
        finding = self.engine.active_findings()[0]
        self.assertEqual(finding.status, "ACTIVE")
        self.assertEqual(self.health.status()["reconnect_count"], 2)

    def test_resolved_findings_remain_in_history(self):
        self.test_five_valid_events_resolve_connection_finding()
        self.assertEqual(self.engine.historical_findings()[0].title, "Connection instability detected")

    def test_health_priority_critical_then_warning_then_recovering(self):
        warning = Finding("WARNING", "Warning", "test", "", "evidence", 1.0, "action")
        critical = Finding("CRITICAL", "Critical", "test", "", "evidence", 1.0, "action")
        recovering = Finding("WARNING", "Recovering", "test", "", "evidence", 1.0, "action", status="RECOVERING")

        self.health.update(connection_event("Device connected"), findings=[warning, critical, recovering])
        self.assertEqual(self.health.status()["status"], "CRITICAL")

        critical.status = "RESOLVED"
        warning.status = "ACTIVE"
        self.health.update(connection_event("Device connected"), findings=[warning, critical, recovering])
        self.assertEqual(self.health.status()["status"], "WARNING")

        warning.status = "RECOVERING"
        self.health.update(connection_event("Device connected"), findings=[warning, critical, recovering])
        self.assertEqual(self.health.status()["status"], "RECOVERING")

        warning.status = "RESOLVED"
        recovering.status = "RESOLVED"
        self.health.update(telemetry_event(1), findings=[warning, critical, recovering])
        self.assertEqual(self.health.status()["status"], "HEALTHY")

    def test_stable_memory_has_no_finding(self):
        for index in range(10):
            self.process(telemetry_event(index), [Metric("free_memory", 1778, "bytes")])
        self.assertEqual(self.engine.active_findings(), [])

    def test_reboot_is_historical_and_does_not_poison_health(self):
        self.process(connection_event("Device connected"))
        for value in (120, 121, 122, 0):
            event = telemetry_event(value)
            self.process(event, [Metric("uptime", value, "seconds")])
        self.assertEqual(self.engine.active_findings(), [])
        self.assertEqual(self.engine.historical_findings()[0].status, "RESOLVED")
        self.assertEqual(self.health.status()["status"], "HEALTHY")

    def test_repeated_disconnects_do_not_duplicate_findings(self):
        for _ in range(5):
            self.process(connection_event("Device disconnected - retrying..."))
        self.assertEqual(len(self.engine.active_findings()), 1)
        self.assertEqual(len(self.engine.historical_findings()), 0)

    def test_three_real_disconnect_cycles_count_three_incidents(self):
        for cycle in range(3):
            self.process(connection_event("Device disconnected - retrying..."))
            self.process(connection_event("Device connected"))
            for index in range(5):
                self.process(telemetry_event(cycle * 5 + index))

        self.assertEqual(self.health.status()["disconnect_incidents"], 3)
        self.assertEqual(self.health.status()["reconnect_attempts"], 0)
        self.assertEqual(len(self.engine.historical_findings()), 3)

    def test_error_spike_resolves_when_error_window_clears(self):
        self.process(connection_event("Device connected"))
        for index in range(5):
            self.process({"id": f"error-{index}", "message": "failure", "level": "ERROR", "event_type": "log"})
        self.assertEqual(self.health.status()["status"], "WARNING")
        for index in range(20):
            self.process(telemetry_event(index))
        self.assertEqual(self.health.status()["status"], "HEALTHY")
        self.assertEqual(self.engine.historical_findings()[0].status, "RESOLVED")


if __name__ == "__main__":
    unittest.main()