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
            raw_lines.append(raw_line)
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
                    # Validate parsed timestamp: reject impossible calendar/time
                    ts = parsed.get("timestamp")
                    if ts:
                        from datetime import datetime as _dt
                        try:
                            # Accept ISO-like and space-separated timestamps
                            parsed_ts = _dt.fromisoformat(ts)
                            # If parsed successfully, keep as-is
                        except Exception:
                            # Try common time-only HH:MM:SS patterns as fallback
                            try:
                                _dt.strptime(ts, "%H:%M:%S")
                            except Exception:
                                # Invalid timestamp — treat as missing so the
                                # event is still parsed but without a valid timestamp
                                parsed.pop("timestamp", None)
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
                connection_state=None,
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
            elif "sensor" in first_msg or "sensor" in first_msg.split():
                title_text = "Sensor response timeout recovered"
            else:
                # Preserve as a generic timeout but echo the observed phrase
                observed = related[0].get("message") or "timeout"
                title_text = f"Timeout recovered: {observed}"

            incidents.append(
                {
                    "id": None,
                    "category": "timeout",
                    "title": title_text,
                    "severity": "WARNING",
                    "evidence": (
                        f"Timeout observed: {related[0].get('message')}. "
                        f"Recovery observed: {related[-1].get('message')}."
                    ),
                    "status": "RESOLVED",
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "related_events": related,
                    "impact": {"recovered": True},
                }
            )

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

        # Executive summary: one-line headline + short sentence
        executive_summary = None
        if health_explanation:
            executive_summary = (
                ("WARNING observed" if health_data.get("status") != "HEALTHY" else "No persistent failures detected")
                + ": " + health_explanation
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

        # Build a human-readable analysis summary regardless of whether
        # correlated incidents exist, so the UI always has something to show.
        parts = []
        # Count only actual warning/error notable events (levels WARN/ERROR)
        warning_error_events = [ev for ev in notable_events if (ev.get("level") or "").upper() in ("WARN", "WARNING", "ERROR")]
        if warning_error_events:
            parts.append(f"{len(warning_error_events)} notable warning/error event(s) occurred")
            first = warning_error_events[0]
            parts.append(f"first notable: {first.get('timestamp')} {first.get('level')} — {first.get('message')}")

        status = health_data.get("status")
        if status == "UNKNOWN":
            parts.append("Final health: UNKNOWN (insufficient parsed events or evidence)")
        else:
            parts.append(f"Final health: {status}")

        # If a reboot diagnostic was detected, prioritize it in the executive summary
        reboot_findings = [f for f in diagnostics.historical_findings() if getattr(f, "category", None) == "reboot" or (isinstance(f, dict) and f.get("category") == "reboot")]
        if reboot_findings:
            rf = reboot_findings[0]
            if isinstance(rf, dict):
                evidence = rf.get("evidence")
                title = rf.get("title")
            else:
                evidence = getattr(rf, "evidence", None)
                title = getattr(rf, "title", None)
            executive_summary = f"{title or 'Reboot detected'}. {evidence or ''}".strip()
            parts = [executive_summary]
        else:
            if executive_summary and "recovered" in (executive_summary or "").lower():
                parts.append("Conditions recovered; no persistent failure detected.")

        rec = "Review the notable events and monitor the device; collect more logs if recurrence occurs."
        parts.append(f"Recommended action: {rec}")

        analysis_summary = " ".join(parts) if parts else None

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
            "notable_events": notable_events,
            "health_explanation": health_explanation,
            "executive_summary": executive_summary,
            # Human-readable structured report for each incident
            "report": self._build_report(incidents, events),
            "analysis_summary": analysis_summary,
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

            # Generate a concise, evidence-based recommendation per category
            if category == "reboot":
                recommendation = (
                    "Inspect power, watchdog, reset, and crash indicators around the reboot timestamp."
                )
            elif category == "connectivity":
                recommendation = (
                    "Check connection stability and investigate repeated disconnects or reconnect failures."
                )
            elif category == "timeout":
                    # Make timeout recommendations specific to the observed timeout
                    first_msg = (related[0].get("message") or "").lower() if related else (title or "").lower()
                    if "command" in first_msg or "ack" in first_msg or "acknowledg" in first_msg:
                        recommendation = (
                            "Check endpoint responsiveness and investigate repeated acknowledgement timeouts."
                        )
                    elif "sensor" in first_msg:
                        recommendation = (
                            "Investigate sensor responsiveness and read/response timing; monitor sensor endpoints for repeated timeouts."
                        )
                    else:
                        recommendation = (
                            "Check endpoint responsiveness and investigate repeated timeouts for the affected subsystem."
                        )
            elif category == "memory":
                recommendation = (
                    "Investigate possible memory growth or leak behavior and monitor FreeRAM over a longer run."
                )
            elif category == "errors":
                recommendation = (
                    "Inspect error messages and affected subsystems; collect surrounding logs to determine persistence."
                )
            else:
                recommendation = (
                    "Review the related events and monitor for recurrence."
                )

            reports.append(
                {
                    "id": inc.get("id"),
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
                    "recommended_action": recommendation,
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