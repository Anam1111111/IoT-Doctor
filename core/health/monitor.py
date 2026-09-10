class HealthMonitor:
    """
    Watches the stream of events and derives a live health picture:
    connection state, error rate, and simple rule-based status.
    Uses only real data already flowing through the system.
    """

    def __init__(self, window_size=20):
        self.window_size = window_size
        self.recent_events = []
        self.connected = False
        self.reconnect_count = 0
        self.disconnect_incidents = 0
        self.reconnect_attempts = 0
        self.connection_state = "DISCONNECTED"
        self.last_free_ram = None
        self.findings = []

    def update(
        self,
        event,
        metrics=None,
        findings=None,
        connection_state=None,
        disconnect_incidents=None,
        reconnect_attempts=None,
    ):
        self.recent_events.append(event)
        if len(self.recent_events) > self.window_size:
            self.recent_events.pop(0)

        if event["message"] == "Device connected":
            self.connected = True
        elif "disconnected" in event["message"].lower():
            self.connected = False
            self.reconnect_count += 1
            self.disconnect_incidents = self.reconnect_count

        for metric in metrics or []:
            name = metric.name if hasattr(metric, "name") else metric.get("name")
            if name == "free_memory":
                self.last_free_ram = (
                    metric.value if hasattr(metric, "value") else metric.get("value")
                )

        if findings is not None:
            self.findings = list(findings)
        self.set_connection_metrics(
            connection_state=connection_state,
            disconnect_incidents=disconnect_incidents,
            reconnect_attempts=reconnect_attempts,
        )

    def set_connection_metrics(
        self,
        connection_state=None,
        disconnect_incidents=None,
        reconnect_attempts=None,
    ):
        if connection_state is not None:
            self.connection_state = connection_state
        if disconnect_incidents is not None:
            self.disconnect_incidents = disconnect_incidents
            self.reconnect_count = disconnect_incidents
        if reconnect_attempts is not None:
            self.reconnect_attempts = reconnect_attempts

    def status(self):
        error_count = sum(1 for e in self.recent_events if e["level"] == "ERROR")
        warn_count = sum(1 for e in self.recent_events if e["level"] == "WARN")

        # Rule-based status, not an arbitrary score
        active_findings = [finding for finding in self.findings if self._finding_status(finding) == "ACTIVE"]
        recovering = any(self._finding_status(finding) == "RECOVERING" for finding in self.findings)
        if any(self._finding_severity(finding) == "CRITICAL" for finding in active_findings):
            level = "CRITICAL"
            reason = self._finding_reason("CRITICAL", active_findings)
        elif any(self._finding_severity(finding) == "WARNING" for finding in active_findings):
            level = "WARNING"
            reason = self._finding_reason("WARNING", active_findings)
        elif recovering:
            level = "RECOVERING"
            reason = "Device reconnected. Waiting for stable telemetry..."
        elif not self.connected:
            level = "CRITICAL"
            reason = "Device not connected"
        elif error_count >= 5:
            level = "WARNING"
            reason = f"{error_count} errors in last {self.window_size} events"
        else:
            level = "HEALTHY"
            reason = "Normal operation"

        return {
            "connected": self.connected,
            "reconnect_count": self.reconnect_count,
            "disconnect_incidents": self.disconnect_incidents,
            "reconnect_attempts": self.reconnect_attempts,
            "connection_state": self.connection_state,
            "free_ram": self.last_free_ram,
            "errors_recent": error_count,
            "warnings_recent": warn_count,
            "status": level,
            "reason": reason,
            "findings": [self._finding_dict(finding) for finding in self.findings],
        }

    @staticmethod
    def _finding_severity(finding):
        return finding.severity if hasattr(finding, "severity") else finding.get("severity")

    @staticmethod
    def _finding_status(finding):
        return finding.status if hasattr(finding, "status") else finding.get("status", "ACTIVE")

    def _finding_reason(self, severity, findings):
        for finding in findings:
            if self._finding_severity(finding) == severity:
                return finding.title if hasattr(finding, "title") else finding.get("title")
        return "Diagnostic finding detected"

    @staticmethod
    def _finding_dict(finding):
        return finding.to_dict() if hasattr(finding, "to_dict") else finding
