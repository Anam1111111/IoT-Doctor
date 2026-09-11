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
        # Correlate historical findings into richer incident summaries
        incidents = []
        hist = diagnostics.historical_findings()
        # Helper to parse timestamps from event or finding
        from datetime import datetime as _dt

        def _parse_ts(ts_str):
            if not ts_str:
                return None
            try:
                # Try ISO first
                return _dt.fromisoformat(ts_str)
            except Exception:
                pass
            # Try time-only HH:MM:SS
            try:
                return _dt.strptime(ts_str, "%H:%M:%S")
            except Exception:
                return None

        for f in hist:
            # Choose keywords by category
            if f.category == "connectivity":
                keywords = ["disconnected", "reconnect", "connected", "retry", "attempt"]
            elif f.category == "reboot":
                keywords = ["uptime", "reset"]
            elif f.category == "errors":
                keywords = ["error", "failed"]
            else:
                keywords = []

            # Find candidate related event indices preserving order
            candidate_indices = []
            for idx, ev in enumerate(events):
                msg = (ev.get("message") or "").lower()
                if any(k in msg for k in keywords):
                    candidate_indices.append(idx)

            # Group contiguous candidate indices into correlation blocks
            blocks = []
            block = []
            for i in candidate_indices:
                if not block:
                    block = [i]
                    continue
                if i == block[-1] + 1:
                    block.append(i)
                else:
                    blocks.append(block)
                    block = [i]
            if block:
                blocks.append(block)

            # Prefer the largest block that likely corresponds to the finding
            chosen_block = blocks[0] if blocks else []
            if blocks:
                chosen_block = max(blocks, key=lambda b: len(b))

            related = [events[i] for i in chosen_block]

            # Determine start/end timestamps from related events if available
            start_time = None
            end_time = None
            parsed_times = [
                _parse_ts(e.get("timestamp")) for e in related if e.get("timestamp")
            ]
            if parsed_times:
                start_dt = parsed_times[0]
                end_dt = parsed_times[-1]
                start_time = start_dt.isoformat() if start_dt else None
                end_time = end_dt.isoformat() if end_dt else None
            else:
                # Fall back to finding timestamps
                start_time = getattr(f, "created_at", None)
                end_time = getattr(f, "resolved_at", None)

            duration = None
            if start_time and end_time:
                try:
                    duration = (
                        _parse_ts(end_time) - _parse_ts(start_time)
                    ).total_seconds()
                except Exception:
                    duration = None

            impact = None
            if f.category == "connectivity":
                reconnect_attempts = sum(
                    1
                    for e in related
                    if any(k in (e.get("message") or "").lower() for k in ("retry", "reconnect", "attempt", "failed"))
                    and "connected" not in (e.get("message") or "").lower()
                )
                recovered = any((e.get("message") or "").lower() == "device connected" for e in related)
                impact = {
                    "reconnect_attempts": reconnect_attempts,
                    "recovered": recovered,
                }

            incidents.append(
                {
                    "id": getattr(f, "id", None),
                    "category": f.category,
                    "title": f.title,
                    "severity": f.severity,
                    "evidence": f.evidence,
                    "status": getattr(f, "status", "INCIDENT"),
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "related_events": related,
                    "impact": impact,
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