import os
import re
from datetime import datetime
from uuid import uuid4

from core.diagnostics import DiagnosticEngine
from core.analysis_summary import build_analysis_interpretation
from core.schema import SCHEMA_VERSION
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
        # remember whether a parser instance was explicitly provided (legacy)
        self._explicit_parser_provided = parser is not None

    def analyze(self, path, metadata=None):
        metadata = dict(metadata or {})
        analysis_id = str(uuid4())
        filename = metadata.get("source_filename", os.path.basename(path))
        normalizer = EventNormalizer(
            device_id=metadata.get("device_name", self.profile.get("name")),
            level_symbols=self.profile.get("level_symbols"),
        )
        extractor = MetricExtractor(self.profile.get("metrics"))
        diagnostics = DiagnosticEngine(historical_mode=True)
        # Allow diagnostics to be aware whether this service was provided an explicit parser
        diagnostics._allow_legacy_parser = True if getattr(self, '_explicit_parser_provided', False) else False
        health = HealthMonitor()
        events = []
        metrics = []
        lines_total = 0
        unrecognized_lines = 0
        parsed_lines = 0
        raw_lines = []
        source_byte_offsets = []
        source_byte_cursor = 0
        # Generic timestamp patterns to support:
        # - YYYY-MM-DD HH:MM:SS
        # - YYYY-MM-DD HH:MM:SS.sss
        # - ISO-8601 e.g. 2026-09-10T22:14:20, with optional fractional seconds
        # - ISO-8601 with timezone Z or ±hh:mm
        generic_ts_re = (
            r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
            r"\s*\[(?P<level>\w+)\]\s*(?:(?P<component>[^:]+):\s*)?(?P<message>.+)$"
        )
        generic_level_re = re.compile(r"^(?P<level>INFO|WARN|WARNING|ERROR|ERR|DEBUG|TRACE)\s+(?P<message>.+)$", re.IGNORECASE)
        # Parser registry + detector
        from core.parser import registry as parser_registry
        from core.parser import detector

        preferred_parser_name = None
        # if profile explicitly provides parser hint use it
        if self.profile.get("parser"):
            preferred_parser_name = self.profile.get("parser")

        # Read all lines first (FileReader enforces upload limits). Then apply multiline coalescing.
        all_lines = []
        for raw_line in FileReader(path, self.max_bytes).lines():
            lines_total += 1
            all_lines.append(raw_line)
            raw_lines.append(raw_line)
            source_byte_offsets.append(source_byte_cursor)
            source_byte_cursor += len(raw_line.encode("utf-8"))

        from core.parser.multiline import coalesce
        groups = coalesce([l.rstrip("\r\n") for l in all_lines])

        # Large-file safety defaults (can be overridden by profile)
        max_return_events = int(self.profile.get("max_return_events", 10000))
        max_return_raw_lines = int(self.profile.get("max_return_raw_lines", 20000))
        max_key_events = int(self.profile.get("max_key_events", 200))
        omitted_counts = {"events": 0, "raw_lines": 0, "key_events": 0}

        if len(groups) > max_return_events:
            omitted_counts["events"] = len(groups) - max_return_events
            groups = groups[:max_return_events]
        if len(raw_lines) > max_return_raw_lines:
            omitted_counts["raw_lines"] = len(raw_lines) - max_return_raw_lines
            raw_lines = raw_lines[:max_return_raw_lines]

        source_line_cursor = 0
        # Now iterate grouped events (each group is one or more raw lines)
        for group in groups:
            line = "\n".join(group)
            raw_lines_for_event = group
            source_line_start = source_line_cursor + 1
            source_line_cursor += len(group)
            source_byte_start = source_byte_offsets[source_line_start - 1] if source_byte_offsets else 0
            # Detect best parser
            parsed = None
            structured = False
            parse_result = None
            try:
                parser = None
                if preferred_parser_name:
                    parser = parser_registry.get(preferred_parser_name)
                if not parser:
                    parser = getattr(self, 'parser', None)
                if not parser:
                    candidates = detector.detect_format(line)
                    if candidates:
                        parser = parser_registry.get(candidates[0][0])

                if parser:
                    parse_result = parser.parse(group)
                    if parse_result is None:
                        try:
                            legacy = parser.parse(line)
                            if isinstance(legacy, dict):
                                parsed = legacy
                                structured = True
                        except Exception:
                            pass
            except Exception:
                parse_result = None

            if parse_result is None:
                m = re.match(generic_ts_re, line)
                if m:
                    parsed = {k: v for k, v in m.groupdict().items() if v is not None}
                    ts = parsed.get("timestamp")
                    if ts:
                        from datetime import datetime as _dt
                        try:
                            parsed_ts = _dt.fromisoformat(ts)
                        except Exception:
                            try:
                                _dt.strptime(ts, "%H:%M:%S")
                            except Exception:
                                parsed.pop("timestamp", None)
                    structured = True
                    parse_result = None
                else:
                    level_match = generic_level_re.match(line)
                    if level_match:
                        parsed = {k: v for k, v in level_match.groupdict().items() if v is not None}
                        structured = True
                    else:
                        parsed = {"message": line, "raw": line, "level": "UNKNOWN"}
                    try:
                        temp_event = normalizer.normalize(
                            parsed,
                            raw=line,
                            transport_metadata={
                                "transport": "file",
                                "source": "file",
                                "filename": filename,
                            },
                            event_type=self._event_type(parsed),
                        )
                        temp_metrics = extractor.extract(temp_event)
                    except Exception:
                        temp_metrics = []

                    if temp_metrics:
                        structured = True
                    elif not structured:
                        unrecognized_lines += 1
                        parse_result = None

            if parse_result:
                trust_state = "PARSED" if parse_result.confidence >= 0.8 else "PARTIALLY_PARSED"
                event = normalizer.normalize(
                    parse_result.fields,
                    raw=line,
                    transport_metadata={
                        "transport": "file",
                        "source": parse_result.format,
                        "filename": filename,
                        "analysis_id": analysis_id,
                        "source_line_start": source_line_start,
                        "source_line_end": source_line_start + len(group) - 1,
                        "source_byte_start": source_byte_start,
                        "trust_state": trust_state,
                        "normalization_confidence": parse_result.confidence,
                    },
                    event_type=self._event_type(parse_result.fields),
                )
                parsed_lines += 1
                event["parse_format"] = parse_result.format
                event["parse_confidence"] = parse_result.confidence
                event["raw_lines"] = raw_lines_for_event
                event["source_line_start"] = source_line_start
                event["source_line_end"] = source_line_start + len(group) - 1
                event["source_byte_start"] = source_byte_start
                event["source_byte_offset"] = source_byte_start
                event["trust_state"] = trust_state

                try:
                    event_metrics = extractor.extract(event)
                    if trust_state == "PARSED":
                        diagnostics.process(event, event_metrics)
                except Exception:
                    event_metrics = []
            else:
                fallback_trust = "PARSED" if structured and parsed.get("message") and parsed.get("level") else ("PARTIALLY_PARSED" if structured else "PRESERVED_ONLY")
                event = normalizer.normalize(
                    parsed,
                    raw=line,
                    transport_metadata={
                        "transport": "file",
                        "source": "file",
                        "filename": filename,
                        "analysis_id": analysis_id,
                        "source_line_start": source_line_start,
                        "source_line_end": source_line_start + len(group) - 1,
                        "source_byte_start": source_byte_start,
                        "trust_state": fallback_trust,
                        "normalization_confidence": 0.8 if fallback_trust == "PARSED" else 0.3,
                    },
                    event_type=self._event_type(parsed),
                )
                try:
                    event_metrics = extractor.extract(event)
                except Exception:
                    event_metrics = []
                event["source_line_start"] = source_line_start
                event["source_line_end"] = source_line_start + len(group) - 1
                event["source_byte_start"] = source_byte_start
                event["source_byte_offset"] = source_byte_start
                event["raw_lines"] = raw_lines_for_event
                event["trust_state"] = fallback_trust
                if structured and event["trust_state"] == "PARSED":
                    parsed_lines += 1
                    try:
                        diagnostics.process(event, event_metrics)
                    except Exception:
                        pass
                elif not structured:
                    event["trust_state"] = "PRESERVED_ONLY"

            events.append(event)
            metrics.extend(event_metrics)

            health.update(
                event,
                metrics=event_metrics,
                findings=diagnostics.all_findings(),
                connection_state=None,
            )

        # Report omitted counts in statistics
        coverage = (parsed_lines / lines_total) if lines_total else 0
        analysis_status = None
        analysis_explanation = None
        min_coverage = float(self.profile.get("min_parse_coverage", 0.5))
        if coverage < min_coverage:
            analysis_status = "LIMITED_ANALYSIS"
            analysis_explanation = (
                f"Only {parsed_lines} of {lines_total} lines were parsed ({coverage:.0%}); analysis may be incomplete."
            )


        # For file-imported analysis, be conservative: only mark CONNECTED when
        # the file contains explicit evidence of successful connection/active
        # communication (e.g., "connected", "connection established",
        # "verification passed", "provisioning completed", "acknowledged",
        # or explicit success/completion messages). Do NOT infer connected
        # simply because there is no "disconnected" message.
        def _has_positive_connection_evidence(ev_list):
            import re

            positive_patterns = [
                r"\bconnected\b",
                r"(connection|link) established",
                r"handshake",
                r"status\s*=\s*ready",
                r"heartbeat received",
                r"verification\s*(=|is)?\s*pass(ed)?",
                r"verification (complete|completed|succeeded)",
                r"provisioning\s*(=|is)?\s*(complete|completed|success|succeeded)",
                r"acknowledg(e|ed|ement) (received|ok|success|succeeded)",
                r"ack (received|ok|success)",
                r"completed successfully",
                r"successfully (connected|provisioned|verified)",
                r"session closed cleanly",
            ]
            prog = re.compile("|".join(positive_patterns), re.IGNORECASE)
            for e in ev_list:
                msg = (e.get("message") or "")
                # skip messages that explicitly contain timeout/fail
                if "timeout" in msg.lower() or "failed" in msg.lower():
                    continue
                if prog.search(msg):
                    return True
            return False

        if parsed_lines > 0 and _has_positive_connection_evidence(events):
            health.connected = True
            health.connection_state = "CONNECTED"

        health_data = health.status()
        # If we parsed zero structured events, mark overall health UNKNOWN
        # only when there are no diagnostic findings; if diagnostics found
        # evidence (e.g., reboot via metrics), prefer diagnostic-driven status.
        if parsed_lines == 0:
            if not diagnostics.all_findings():
                health_data["status"] = "UNKNOWN"
                health_data["reason"] = "Insufficient parsed events"
                notable_events = []  # Initialize notable_events list
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
                # Try ISO first; normalize to naive so relative comparisons
                # between mixed timestamp formats never raise TypeError.
                parsed = _dt.fromisoformat(ts_str)
                return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
            except Exception:
                pass
            # Try time-only HH:MM:SS
            try:
                return _dt.strptime(ts_str, "%H:%M:%S")
            except Exception:
                return None

        used_blocks_by_category = {}
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

            # Group locally related events. When timestamps are present, allow
            # intervening telemetry only inside a short, deterministic window.
            blocks = []
            block = []
            for i in candidate_indices:
                if not block:
                    block = [i]
                    continue
                previous = block[-1]
                previous_ts = _parse_ts(events[previous].get("timestamp"))
                current_ts = _parse_ts(events[i].get("timestamp"))
                close_in_time = (
                    previous_ts is not None
                    and current_ts is not None
                    and 0 <= (current_ts - previous_ts).total_seconds() <= 60
                )
                if i == previous + 1 or close_in_time:
                    block.append(i)
                else:
                    blocks.append(block)
                    block = [i]
            if block:
                blocks.append(block)

            block_index = used_blocks_by_category.get(f.category, 0)
            chosen_block = blocks[block_index] if block_index < len(blocks) else []
            used_blocks_by_category[f.category] = block_index + 1

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
                # Consider a variety of recovery messages as evidence: not just
                # the literal "Device connected" but any message mentioning
                # "connected" or indicating recovery.
                recovered = any(
                    "connected" in (e.get("message") or "").lower()
                    or "recovered" in (e.get("message") or "").lower()
                    for e in related
                )
                impact = {
                    "reconnect_attempts": reconnect_attempts,
                    "recovered": recovered,
                }

            incidents.append(
                {
                    "id": getattr(f, "id", None),
                    "incident_id": str(uuid4()),
                    "category": f.category,
                    "title": f.title,
                    "severity": f.severity,
                    "evidence": f.evidence,
                    "status": getattr(f, "status", "INCIDENT"),
                    "recommended_action": getattr(f, "recommended_action", None),
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "related_events": related,
                    "impact": impact,
                }
            )

        # A timeout becomes an incident only when the file contains explicit
        # later recovery evidence; isolated timeout events remain notable events.
        recovery_terms = (
            "acknowledgement received",
            "acknowledgment received",
            "acknowledged",
            "retry succeeded",
            "recovered",
            "verification passed",
            "provisioning completed",
            "completed successfully",
        )
        timeout_starts = set()
        for start_index, event in enumerate(events):
            message = (event.get("message") or "").lower()
            if "timeout" not in message or start_index in timeout_starts:
                continue

            recovery_index = None
            start_ts = _parse_ts(event.get("timestamp"))
            for candidate_index in range(start_index + 1, len(events)):
                candidate = events[candidate_index]
                candidate_msg = (candidate.get("message") or "").lower()
                if "timeout" in candidate_msg:
                    break
                candidate_ts = _parse_ts(candidate.get("timestamp"))
                if (
                    start_ts is not None
                    and candidate_ts is not None
                    and (candidate_ts - start_ts).total_seconds() > 60
                ):
                    break
                if any(term in candidate_msg for term in recovery_terms):
                    recovery_index = candidate_index
                    break

            if recovery_index is None:
                continue

            timeout_starts.add(start_index)
            related = events[start_index : recovery_index + 1]
            start_time = related[0].get("timestamp")
            end_time = related[-1].get("timestamp")
            start_dt = _parse_ts(start_time)
            end_dt = _parse_ts(end_time)
            duration = (
                (end_dt - start_dt).total_seconds()
                if start_dt is not None and end_dt is not None
                else None
            )
            # Derive a neutral but specific title from the observed timeout
            first_msg = (related[0].get("message") or "").lower()
            if "command" in first_msg and "ack" in first_msg or "command acknowledgement" in first_msg:
                title_text = "Command acknowledgement timeout recovered"
                recommendation_text = "Check endpoint responsiveness and investigate repeated acknowledgement timeouts."
            elif "sensor" in first_msg or "sensor" in first_msg.split():
                title_text = "Sensor response timeout recovered"
                recommendation_text = "Investigate sensor responsiveness and read/response timing; monitor sensor endpoints for repeated timeouts."
            else:
                # Preserve as a generic timeout but echo the observed phrase
                observed = related[0].get("message") or "timeout"
                title_text = f"Timeout recovered: {observed}"
                recommendation_text = "Check endpoint responsiveness and investigate repeated timeouts for the affected subsystem."

            incidents.append(
                {
                    "id": None,
                    "incident_id": str(uuid4()),
                    "category": "timeout",
                    "title": title_text,
                    "severity": "WARNING",
                    "evidence": (
                        f"Timeout observed: {related[0].get('message')}. "
                        f"Recovery observed: {related[-1].get('message')}."
                    ),
                    "status": "RESOLVED",
                    "recommended_action": recommendation_text,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "related_events": related,
                    "impact": {"recovered": True},
                }
            )

        for incident in incidents:
            related = incident.get("related_events") or []
            incident["supporting_event_ids"] = [event.get("event_id", event.get("id")) for event in related]
            incident["supporting_source_lines"] = [line_number for event in related for line_number in range(event.get("source_line_start", 0), event.get("source_line_end", 0) + 1)]
            incident["evidence_claims"] = [{
                "claim": incident.get("title"),
                "supporting_event_ids": incident["supporting_event_ids"],
                "supporting_source_lines": incident["supporting_source_lines"],
                "evidence_text": incident.get("evidence"),
                "confidence": 1.0,
            }]

        finding_incident_index = {}
        for incident in incidents:
            finding_incident_index.setdefault((incident.get("category"), incident.get("title")), []).append(incident)

        # Build notable events summary (WARN/ERROR) deterministically from parsed events
        notable_events = []
        # Include WARN/ERROR plus explicit reboot-related events regardless of level
        # include 'uptime' to capture lines like 'Uptime=0s' as key events
        reboot_keywords = ("reboot", "restarted", "restart", "uptime reset", "uptime", "reset", "started after reset")
        for ev in events:
            lvl = (ev.get("level") or "").upper()
            msg = (ev.get("message") or "").lower()
            include = lvl in ("WARN", "WARNING", "ERROR") or any(k in msg for k in reboot_keywords)
            if include:
                # If this event was included solely because it matched reboot
                # keywords and has unknown level (parser didn't provide one),
                # mark it INFO so Key Events (UI) displays it as telemetry.
                out_level = lvl
                if out_level in (None, "", "UNKNOWN") and any(k in msg for k in reboot_keywords):
                    out_level = "INFO"
                notable_events.append(
                    {
                        "timestamp": ev.get("timestamp"),
                        "level": out_level,
                        "message": ev.get("message"),
                        "raw_line": ev.get("raw_line") or ev.get("raw"),
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

        # Adjust health for file-imported analysis: don't mark CRITICAL solely because the
        # file shows no live connection evidence. If the monitor reported CRITICAL due
        # to not connected, prefer diagnostic findings' severities for the file import.
        if health_data.get("status") == "CRITICAL" and health_data.get("reason") == "Device not connected":
            # Determine highest severity among findings
            def _sev(f):
                return f.severity if hasattr(f, "severity") else f.get("severity") if f else None

            findings_list = diagnostics.all_findings() or []
            # If a reboot finding exists, prefer WARNING health for file imports
            if any((getattr(f, "category", None) == "reboot") or (isinstance(f, dict) and f.get("category") == "reboot") for f in findings_list):
                health_data["status"] = "WARNING"
                health_data["reason"] = "Reboot observed in imported log"
            finding_severities = [s for s in (_sev(f) for f in findings_list) if s]
            if any(s == "CRITICAL" for s in finding_severities):
                # keep CRITICAL
                pass
            elif any(s == "WARNING" for s in finding_severities):
                health_data["status"] = "WARNING"
                health_data["reason"] = "Warning findings present in imported log"
            else:
                health_data["status"] = "UNKNOWN"
                health_data["reason"] = "Insufficient connection evidence in imported log"
                health_data["connection_state"] = "UNKNOWN"

        all_finding_objects = diagnostics.all_findings()
        for finding in all_finding_objects:
            related = [event for event in events if event.get("category") == finding.category or (finding.category == "connectivity" and event.get("event_type") == "connection")]
            matching_incidents = finding_incident_index.get((finding.category, finding.title), [])
            if matching_incidents and matching_incidents[0].get("supporting_event_ids"):
                related_ids = set(matching_incidents[0]["supporting_event_ids"])
                related = [event for event in events if event.get("event_id") in related_ids]
                matching_incidents.pop(0)
            finding.supporting_event_ids = [event["event_id"] for event in related]
            finding.supporting_source_lines = [line_number for event in related for line_number in range(event.get("source_line_start", 0), event.get("source_line_end", 0) + 1)]
            finding.evidence_claims = [{
                "claim": finding.title,
                "supporting_event_ids": finding.supporting_event_ids,
                "supporting_source_lines": finding.supporting_source_lines,
                "evidence_text": finding.evidence,
                "confidence": finding.confidence,
            }]
        findings_dict = [finding.to_dict() for finding in all_finding_objects]
        interpretation = build_analysis_interpretation(
            health=health_data,
            incidents=incidents,
            findings=findings_dict,
            events=events,
            statistics={
                "lines_total": lines_total,
                "events_parsed": parsed_lines,
                "unrecognized_lines": unrecognized_lines,
            },
        )
        executive_summary = interpretation["summary"]
        analysis_summary = interpretation["summary"]

        return {
            "source": {
                "type": "file",
                "filename": filename,
                "device": metadata.get("device_name", self.profile.get("name", "UNKNOWN")),
            },
            "schema_version": SCHEMA_VERSION,
            "analysis_id": analysis_id,
            "analysis_metadata": {
                "schema_version": SCHEMA_VERSION,
                "parser_versions": sorted({event.get("parse_format") for event in events if event.get("parse_format")}),
                "profile_name": self.profile.get("name"),
                "profile_path": self.profile.get("profile_path"),
                "diagnostic_engine_version": "current",
                "summary_builder_version": "current",
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
            "findings": findings_dict,
            "incidents": incidents,
            "notable_events": notable_events,
            "health_explanation": health_explanation,
            "executive_summary": executive_summary,
            # Human-readable structured report for each incident
            "report": self._build_report(incidents, events),
            "analysis_summary": analysis_summary,
            "what_happened": interpretation["what_happened"],
            "analysis": interpretation,
            "analysis_status": analysis_status,
            "analysis_explanation": analysis_explanation,
            "omitted_counts": omitted_counts,
        }

    def _build_report(self, incidents, events):
        """
        Convert correlated incidents into a deterministic, structured,
        human-readable report suitable for UI presentation.
        """
        reports = []
        for inc in incidents:
            title = inc.get("title")
            category = inc.get("category")
            severity = inc.get("severity")
            start = inc.get("start_time")
            end = inc.get("end_time")
            duration = inc.get("duration")
            related = inc.get("related_events") or []
            impact = inc.get("impact") or {}
            evidence = inc.get("evidence")

            # Build a concise narrative
            what_happened = title
            recovered = False
            if impact and isinstance(impact, dict):
                recovered = bool(impact.get("recovered"))

            possible_cause = None
            if category == "reboot":
                possible_cause = "uptime reset observed; investigate watchdogs, crashes, or power interruptions"
            elif category == "connectivity":
                if impact and impact.get("reconnect_attempts", 0) > 0:
                    possible_cause = "intermittent connection loss; check cabling, power, and serial stability"

            reports.append(
                {
                    "id": inc.get("id"),
                    "incident_id": inc.get("incident_id"),
                    "title": title,
                    "category": category,
                    "severity": severity,
                    "what_happened": what_happened,
                    "start_time": start,
                    "end_time": end,
                    "duration": duration,
                    "recovered": recovered,
                    "impact": impact,
                    "evidence": evidence,
                    "related_events": related,
                    "possible_cause": possible_cause,
                    "recommended_action": inc.get("recommended_action") or "Review the related events and monitor for recurrence.",
                }
            )
        # If no incidents but insufficient data, return an explanatory entry
        if not reports and events:
            return []
        return reports

    @staticmethod
    def _event_type(parsed):
        message = parsed.get("message", "").lower()
        # Treat any parsed line that mentions a connection state as a
        # connection event so diagnostic rules can inspect it. Keep the
        # matching conservative (word containment) to avoid reclassifying
        # unrelated messages.
        if "device connected" == message or "connected" in message:
            return "connection"
        if "device disconnected" in message or "disconnected" in message:
            return "connection"
        return "log"