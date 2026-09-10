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
        diagnostics = DiagnosticEngine()
        health = HealthMonitor()
        health.connected = True
        events = []
        metrics = []
        lines_total = 0
        unrecognized_lines = 0
        for raw_line in FileReader(path, self.max_bytes).lines():
            lines_total += 1
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            try:
                parsed = self.parser.parse(line)
            except Exception:
                unrecognized_lines += 1
                continue
            if parsed is None:
                unrecognized_lines += 1
                continue
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
                unrecognized_lines += 1
                continue
            events.append(event)
            metrics.extend(event_metrics)
            health.update(
                event,
                metrics=event_metrics,
                findings=diagnostics.all_findings(),
                connection_state="CONNECTED",
            )

        health_data = health.status()
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
                "events_parsed": len(events),
                "unrecognized_lines": unrecognized_lines,
            },
            "events": events,
            "metrics": [metric.to_dict() for metric in metrics],
            "health": health_data,
            "findings": [finding.to_dict() for finding in diagnostics.all_findings()],
        }

    @staticmethod
    def _event_type(parsed):
        message = parsed.get("message", "").lower()
        if message == "device connected":
            return "connection"
        if "device disconnected" in message:
            return "connection"
        return "log"