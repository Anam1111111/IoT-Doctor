import os
from datetime import datetime

from core.diagnostics import DiagnosticEngine
from core.health.monitor import HealthMonitor
from core.ingestion.file_reader import FileReader
from core.metrics import MetricExtractor
from core.normalization.normalizer import EventNormalizer


class FileAnalysisService:
    """Run LOG/TXT input through the same normalized diagnostic pipeline."""

    def __init__(self, parser, profile, max_bytes=5 * 1024 * 1024):
        self.parser = parser
        self.profile = profile
        self.max_bytes = max_bytes

    def analyze(self, path, metadata=None):
        metadata = dict(metadata or {})
        filename = metadata.get("source_filename", os.path.basename(path))
        normalizer = EventNormalizer(
            device_id=metadata.get("device_name", self.profile.get("name")),
            level_symbols=self.profile.get("level_symbols"),
        )
        extractor = MetricExtractor(self.profile.get("metrics"))
        diagnostics = DiagnosticEngine(historical_mode=True)
        health = HealthMonitor()
        health.connected = True
        events = []
        metrics = []
        lines_total = 0
        unrecognized_lines = 0
        parsed_lines = 0
        raw_lines = []
        # Generic timestamp patterns to support:
        # - YYYY-MM-DD HH:MM:SS
        # - YYYY-MM-DD HH:MM:SS.sss
        # - ISO-8601 e.g. 2026-09-10T22:14:20, with optional fractional seconds
        # - ISO-8601 with timezone Z or ±hh:mm
        generic_ts_re = (
            r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
            r"\s*\[(?P<level>\w+)\]\s*(?:(?P<component>[^:]+):\s*)?(?P<message>.+)$"
        )
        for raw_line in FileReader(path, self.max_bytes).lines():
            lines_total += 1
            line = raw_line.rstrip("\r\n")
            raw_lines.append(line)
            if not line:
                continue
            parsed = None
            structured = False
            try:
                parsed = self.parser.parse(line)
                if parsed is not None:
                    structured = True
            except Exception:
                parsed = None

            if parsed is None:
                # Attempt a generic timestamped-line parse
                import re

                m = re.match(generic_ts_re, line)
                if m:
                    parsed = {k: v for k, v in m.groupdict().items() if v is not None}
                    structured = True
                else:
                    # Unrecognized but preserve raw line as an event
                    unrecognized_lines += 1
                    parsed = {"message": line, "raw": line, "level": "UNKNOWN"}
            event_type = self._event_type(parsed)
            event = normalizer.normalize(
                parsed,
                raw=line,
                transport_metadata={
                    "transport": "file",
                    "source": "file",
                    "filename": filename,
                },
                event_type=event_type,
            )
            try:
                event_metrics = extractor.extract(event)
                diagnostics.process(event, event_metrics)
            except Exception:
                # If metric extraction/diagnostics fail, still keep the event
                event_metrics = []

            events.append(event)
            metrics.extend(event_metrics)
            # Count as parsed for health only if it was structured (parser or generic)
            if structured:
                parsed_lines += 1

            health.update(
                event,
                metrics=event_metrics,
                findings=diagnostics.all_findings(),
                connection_state="CONNECTED",
            )

        health_data = health.status()
        # If we parsed zero structured events, mark overall health UNKNOWN
        if parsed_lines == 0:
            health_data["status"] = "UNKNOWN"
            health_data["reason"] = "Insufficient parsed events"
        # Build incident summaries from diagnostics
        incidents = []
        for f in diagnostics.historical_findings():
            incidents.append(
                {
                    "category": f.category,
                    "title": f.title,
                    "severity": f.severity,
                    "evidence": f.evidence,
                    "status": getattr(f, "status", "INCIDENT"),
                }
            )

        # If final health is HEALTHY but there were historical findings or transient WARN/ERROR events, provide explanation
        health_explanation = None
        if health_data.get("status") == "HEALTHY":
            warning_count = sum(1 for i in incidents if i.get("severity") in ("WARNING", "CRITICAL"))
            transient_count = sum(1 for e in events if (e.get("level") or "").upper() in ("WARN", "WARNING", "ERROR"))
            if warning_count > 0 or transient_count > 0:
                # Build a slightly richer explanation based on incident categories
                parts = []
                if warning_count:
                    parts.append(f"{warning_count} warning(s) observed")
                if transient_count and transient_count > warning_count:
                    parts.append(f"{transient_count} transient warning/error events observed")
                # Summarize incident categories
                categories = sorted({i.get("category") for i in incidents if i.get("category")})
                cat_text = f" in categories: {', '.join(categories)}" if categories else ""
                health_explanation = (
                    f"{'; '.join(parts)}{cat_text}. The conditions recovered and no persistent failure pattern was detected."
                )

        # Executive summary: one-line headline + short sentence
        executive_summary = None
        if health_explanation:
            executive_summary = (
                ("WARNING observed" if health_data.get("status") != "HEALTHY" else "No persistent failures detected")
                + ": " + health_explanation
            )

        return {
            "source": {
                "type": "file",
                "filename": filename,
                "device": metadata.get("device_name", self.profile.get("name", "UNKNOWN")),
            },
            "session": {
                "id": f"file-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                "source_type": "file",
                "filename": filename,
                "started_at": datetime.now().isoformat(),
                "lines_analyzed": lines_total,
                "events_analyzed": len(events),
            },
            "statistics": {
                "lines_total": lines_total,
                "events_parsed": parsed_lines,
                "unrecognized_lines": unrecognized_lines,
            },
            "events": events,
            # Preserve original raw log lines for inspection in the UI
            "raw_lines": raw_lines,
            "metrics": [metric.to_dict() for metric in metrics],
            "health": health_data,
            "findings": [finding.to_dict() for finding in diagnostics.all_findings()],
            "incidents": incidents,
            "health_explanation": health_explanation,
            "executive_summary": executive_summary,
        }

    @staticmethod
    def _event_type(parsed):
        message = parsed.get("message", "").lower()
        if message == "device connected":
            return "connection"
        if "device disconnected" in message:
            return "connection"
        return "log"