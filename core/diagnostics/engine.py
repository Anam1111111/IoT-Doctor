from datetime import datetime

from core.models.finding import Finding


class _Rule:
    key = ""

    def evaluate(self, events, metrics):
        raise NotImplementedError


class _UnexpectedRebootRule(_Rule):
    key = "unexpected_reboot"

    def __init__(self, minimum_previous_uptime=10, startup_uptime=2):
        self.minimum_previous_uptime = minimum_previous_uptime
        self.startup_uptime = startup_uptime

    def evaluate(self, events, metrics):
        uptimes = [metric.value for metric in metrics if metric.name == "uptime"]
        if len(uptimes) < 2:
            return None
        previous_uptime = uptimes[-2]
        current_uptime = uptimes[-1]
        if (
            previous_uptime < self.minimum_previous_uptime
            or current_uptime > self.startup_uptime
            or current_uptime >= previous_uptime
        ):
            return None
        return Finding(
            severity="WARNING",
            title="Unexpected device reboot detected",
            category="reboot",
            description="Device uptime reset unexpectedly.",
            evidence=(
                f"Uptime reset from {previous_uptime} seconds to "
                f"{current_uptime} seconds."
            ),
            confidence=1.0,
            recommended_action=(
                "Inspect events immediately before the restart for watchdog, "
                "crash, power, or connectivity indicators."
            ),
        )


class _MemoryDegradationRule(_Rule):
    key = "memory_degradation"

    def __init__(self, window_size=10):
        self.window_size = window_size

    def evaluate(self, events, metrics):
        values = [metric.value for metric in metrics if metric.name == "free_memory"]
        if len(values) < self.window_size:
            return None
        recent = values[-self.window_size :]
        if not all(recent[index] > recent[index + 1] for index in range(len(recent) - 1)):
            return None
        return Finding(
            severity="WARNING",
            title="Possible memory degradation",
            category="memory",
            description="Free memory decreased consistently across the observed window.",
            evidence=(
                f"Free memory decreased across {self.window_size} consecutive "
                "observations."
            ),
            confidence=1.0,
            recommended_action=(
                "Continue monitoring memory usage and inspect allocation behavior."
            ),
        )


class _ErrorSpikeRule(_Rule):
    key = "error_spike"

    def __init__(self, window_size=20, threshold=5):
        self.window_size = window_size
        self.threshold = threshold

    def evaluate(self, events, metrics):
        recent = events[-self.window_size :]
        error_count = sum(
            1
            for event in recent
            if event.get("level") == "ERROR" and event.get("event_type") != "connection"
        )
        if error_count < self.threshold:
            return None
        return Finding(
            severity="WARNING",
            title="Elevated error rate detected",
            category="errors",
            description="The device produced an unusually high number of errors.",
            evidence=(
                f"{error_count} ERROR events occurred within the configured "
                f"observation window of {self.window_size} events."
            ),
            confidence=1.0,
            recommended_action="Inspect the recent ERROR messages and affected device subsystem.",
        )


class _ConnectionInstabilityRule(_Rule):
    key = "connection_instability"

    def __init__(self, window_size=20, threshold=3):
        self.window_size = window_size
        self.threshold = threshold

    def evaluate(self, events, metrics):
        recent = events[-self.window_size :]
        disconnects = sum(
            1
            for event in recent
            if event.get("event_type") == "connection"
            and "disconnected" in event.get("message", "").lower()
        )
        if disconnects < self.threshold:
            return None
        return Finding(
            severity="WARNING",
            title="Connection instability detected",
            category="connectivity",
            description="The device disconnected repeatedly during the observation window.",
            evidence=(
                f"{disconnects} disconnect events occurred within the configured "
                f"observation window of {self.window_size} events."
            ),
            confidence=1.0,
            recommended_action="Inspect the serial connection, power stability, and device reset indicators.",
        )


class DiagnosticEngine:
    """Evaluate normalized events and metrics into lifecycle-aware findings."""

    def __init__(self, event_window=20, metric_window=30, recovery_events=5, rules=None, historical_mode=False):
        self.event_window = event_window
        self.metric_window = metric_window
        self.recovery_events = recovery_events
        self.events = []
        self.metrics = []
        self._active_findings = {}
        self._historical_findings = []
        self._connection_recovery_count = 0
        self._reboot_sequence_active = False
        self.historical_mode = historical_mode
        self.rules = rules or [
            _UnexpectedRebootRule(minimum_previous_uptime=10, startup_uptime=2),
            _MemoryDegradationRule(),
            _ErrorSpikeRule(window_size=event_window),
            _ConnectionInstabilityRule(window_size=event_window),
        ]

    def process(self, event, metrics=None):
        self.events.append(event)
        self.events = self.events[-self.event_window :]
        self.metrics.extend(metrics or [])
        self.metrics = self.metrics[-self.metric_window :]

        new_findings = []
        if self._is_disconnect(event):
            self._connection_recovery_count = 0
            new_finding = self._record_connection_disconnect()
            if new_finding is not None:
                new_findings.append(new_finding)
        elif self._is_connected(event):
            self._connection_recovery_count = 0
            self._mark_connection_recovering()
        elif self._is_valid_telemetry(event):
            self._advance_connection_recovery()

        for rule in self.rules:
            if rule.key == "connection_instability":
                continue
            finding = rule.evaluate(self.events, self.metrics)
            if finding is not None:
                if rule.key == "unexpected_reboot":
                    if self._reboot_sequence_active:
                        continue
                    if self.historical_mode:
                        # In historical analysis, present reboots as INCIDENTs
                        finding.status = "INCIDENT"
                        self._historical_findings.append(finding)
                        new_findings.append(finding)
                        self._reboot_sequence_active = True
                    else:
                        # In live mode, treat reboot detection as a recorded
                        # historical event that is immediately marked resolved
                        finding.status = "RESOLVED"
                        finding.resolved_at = self._now()
                        finding.resolution_reason = "Reboot incident recorded"
                        self._historical_findings.append(finding)
                        new_findings.append(finding)
                        self._reboot_sequence_active = True
                    continue
                existing = self._active_findings.get(rule.key)
                if existing is None:
                    self._active_findings[rule.key] = finding
                    new_findings.append(finding)
                else:
                    existing.evidence = finding.evidence
            elif rule.key in self._active_findings and self._condition_has_cleared(rule.key):
                self._resolve(rule.key, "Condition no longer present in the observation window")
        self._update_reboot_sequence_state()
        return new_findings

    def active_findings(self):
        return list(self._active_findings.values())

    def historical_findings(self):
        return list(self._historical_findings)

    def all_findings(self):
        return self.historical_findings() + self.active_findings()

    def _record_connection_disconnect(self):
        # Decide whether this disconnect should be recorded as a one-off
        # historical interruption or an active instability condition.
        disconnect_count = self._disconnect_count()
        evidence = self._disconnect_evidence(disconnect_count)
        # Find configured instability threshold
        instability_rule = next((r for r in self.rules if r.key == "connection_instability"), None)
        threshold = getattr(instability_rule, "threshold", None)

        # If we already have an active instability finding, update it
        existing = self._active_findings.get("connection_instability")
        if existing is not None:
            existing.status = "ACTIVE"
            existing.resolved_at = None
            existing.resolution_reason = None
            existing.evidence = evidence
            return None

        # Historical mode: record a discrete interruption incident unless the
        # configured threshold is met, in which case create an active instability
        # finding. Live (non-historical) mode should create an active instability
        # finding on disconnect.
        if self.historical_mode:
            if threshold is None or disconnect_count < threshold:
                incident = Finding(
                    severity="WARNING",
                    title="Connection interruption detected",
                    category="connectivity",
                    description="A discrete connection interruption was observed during the session.",
                    evidence=evidence,
                    confidence=1.0,
                    recommended_action="Verify the device connection and monitor for additional disconnects.",
                )
                incident.status = "INCIDENT"
                self._historical_findings.append(incident)
                return incident

            finding = Finding(
                severity="CRITICAL",
                title="Connection instability detected",
                category="connectivity",
                description="The device disconnected and requires stable telemetry to recover.",
                evidence=evidence,
                confidence=1.0,
                recommended_action="Inspect the serial connection, power stability, and device reset indicators.",
            )
            self._active_findings["connection_instability"] = finding
            return finding

        # Live mode: create active instability immediately as before
        finding = Finding(
            severity="CRITICAL",
            title="Connection instability detected",
            category="connectivity",
            description="The device disconnected and requires stable telemetry to recover.",
            evidence=evidence,
            confidence=1.0,
            recommended_action="Inspect the serial connection, power stability, and device reset indicators.",
        )
        self._active_findings["connection_instability"] = finding
        return finding

    def _mark_connection_recovering(self):
        finding = self._active_findings.get("connection_instability")
        if finding is not None:
            finding.status = "RECOVERING"
            finding.evidence = "Device reconnected. Waiting for stable telemetry."

    def _advance_connection_recovery(self):
        finding = self._active_findings.get("connection_instability")
        if finding is None or finding.status != "RECOVERING":
            return
        self._connection_recovery_count += 1
        if self._connection_recovery_count < self.recovery_events:
            finding.evidence = (
                f"{self._connection_recovery_count} consecutive valid telemetry events "
                f"observed; {self.recovery_events} required for recovery."
            )
            return
        finding.status = "RESOLVED"
        finding.resolved_at = self._now()
        finding.resolution_reason = (
            f"{self.recovery_events} consecutive valid telemetry events were observed."
        )
        finding.evidence = self._disconnect_evidence(self._disconnect_count())
        self._historical_findings.append(finding)
        del self._active_findings["connection_instability"]
        self._connection_recovery_count = 0

    def _condition_has_cleared(self, key):
        if key == "memory_degradation":
            values = [metric.value for metric in self.metrics if metric.name == "free_memory"]
            if len(values) < 10:
                return False
            recent = values[-10:]
            return not all(recent[index] > recent[index + 1] for index in range(9))
        if key == "error_spike":
            recent = self.events[-self.event_window :]
            return sum(1 for event in recent if event.get("level") == "ERROR") < 5
        return False

    def _resolve(self, key, reason):
        finding = self._active_findings.pop(key)
        finding.status = "RESOLVED"
        finding.resolved_at = self._now()
        finding.resolution_reason = reason
        self._historical_findings.append(finding)

    def _disconnect_count(self):
        return sum(1 for event in self.events if self._is_disconnect(event))

    @staticmethod
    def _disconnect_evidence(count):
        noun = "disconnect incident" if count == 1 else "disconnect incidents"
        return f"{count} {noun} occurred within the observation window."

    def _update_reboot_sequence_state(self):
        uptime_rule = next(
            rule for rule in self.rules if rule.key == "unexpected_reboot"
        )
        uptimes = [metric.value for metric in self.metrics if metric.name == "uptime"]
        if uptimes and uptimes[-1] > uptime_rule.startup_uptime:
            self._reboot_sequence_active = False

    @staticmethod
    def _now():
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _is_disconnect(event):
        return (
            event.get("event_type") == "connection"
            and "disconnected" in event.get("message", "").lower()
        )

    @staticmethod
    def _is_connected(event):
        return (
            event.get("event_type") == "connection"
            and event.get("message") == "Device connected"
        )

    @staticmethod
    def _is_valid_telemetry(event):
        return (
            event.get("event_type", "log") == "log"
            and event.get("level") != "ERROR"
            and "disconnected" not in event.get("message", "").lower()
        )