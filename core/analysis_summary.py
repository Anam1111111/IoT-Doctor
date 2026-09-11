"""Build deterministic, evidence-based interpretation text for analysis results."""


def _category_items(incidents, findings, category):
    return [item for item in [*(incidents or []), *(findings or [])]
            if item.get("category") == category]


def _recovered(item):
    impact = item.get("impact") or {}
    return bool(item.get("recovered") or impact.get("recovered") or item.get("status") in {"RESOLVED", "RECOVERED"})


def _source_classes(incidents, events):
    classes = set()
    for item in incidents:
        for event in item.get("related_events") or []:
            classes.add(event.get("source_class") or (event.get("metadata") or {}).get("source_class"))
    for event in events or []:
        classes.add(event.get("source_class") or (event.get("metadata") or {}).get("source_class"))
    return {source for source in classes if source}


def build_analysis_interpretation(*, health, incidents, findings, events, statistics):
    incidents = incidents or []
    findings = findings or []
    statistics = statistics or {}
    categories = {item.get("category") for item in [*incidents, *findings]}
    recovered_count = sum(1 for item in incidents if _recovered(item))
    active_count = max(0, len(incidents) - recovered_count)
    total_lines = statistics.get("lines_total", 0)
    parsed_lines = statistics.get("events_parsed", 0)
    completeness = (parsed_lines / total_lines) if total_lines else None
    status = (health or {}).get("status", "UNKNOWN")
    recommendations = [item.get("recommended_action") for item in [*incidents, *findings] if item.get("recommended_action")]
    source_classes = _source_classes(incidents, events)
    system_only = bool(source_classes) and source_classes <= {"BLUETOOTH_SYSTEM", "WIFI_SYSTEM", "ANDROID_SYSTEM", "VENDOR_SYSTEM", "UNKNOWN"}

    if "connectivity" in categories:
        connection_items = _category_items(incidents, findings, "connectivity")
        attempts = sum(int((item.get("impact") or {}).get("reconnect_attempts", 0) or 0) for item in connection_items)
        if system_only:
            state = " Some connection activity remains unresolved." if active_count else " The available logs do not show an ongoing issue."
            what_happened = f"Bluetooth connection activity was observed.{state} The available logs do not provide enough evidence to confirm a physical device-level failure."
        elif active_count:
            issue_word = "issue" if active_count == 1 else "issues"
            verb = "remains" if active_count == 1 else "remain"
            what_happened = f"Connection interruptions were detected. {recovered_count} recovered, but {active_count} {issue_word} {verb} unresolved in the captured logs."
        elif recovered_count:
            detail = f" The logs show {attempts} reconnect attempt{'s' if attempts != 1 else ''} before the connection came back." if attempts else " The connection came back in the captured logs."
            what_happened = f"The device temporarily lost its connection.{detail} The available logs do not show an ongoing failure."
        else:
            what_happened = "The device lost its connection in the captured logs. The logs do not show that it came back, so check whether the problem is still happening."
    elif "memory" in categories:
        what_happened = "Memory use changed steadily in the captured logs. Review the memory finding and monitor whether the trend continues."
    elif "timeout" in categories:
        what_happened = "The device did not receive an expected response in time. Review whether this happens again and check the related response timing."
    elif "reboot" in categories:
        reboot_item = next((item for item in [*incidents, *findings] if item.get("category") == "reboot"), {})
        reboot_title = reboot_item.get("title") or "The device restarted"
        reboot_evidence = reboot_item.get("evidence")
        evidence_text = f" {reboot_evidence}" if reboot_evidence else ""
        what_happened = f"{reboot_title}.{evidence_text} The logs do not determine the exact cause."
    elif "communication" in categories or "errors" in categories:
        what_happened = "The logs contain repeated errors that may still affect the device. Review the findings and surrounding events."
    elif not events or status in {"UNKNOWN", "LIMITED ANALYSIS"}:
        what_happened = "There is not enough readable information in the logs to reach a confident conclusion."
    elif status == "HEALTHY":
        what_happened = "The device appears to be working normally in the captured logs. No ongoing problem is shown."
    else:
        what_happened = "The logs show a condition that may need attention. Review the findings and check whether it happens again."

    notable_count = sum(1 for event in (events or []) if (event.get("level") or "").upper() in {"WARN", "WARNING", "ERROR"})
    summary = what_happened
    if notable_count:
        summary = f"{summary} {notable_count} notable warning/error event(s) were recorded."
    confidence = "high" if completeness is not None and completeness >= 0.8 else "limited"
    return {
        "what_happened": what_happened,
        "summary": summary,
        "confidence": confidence,
        "completeness": completeness,
        "recovered_count": recovered_count,
        "active_count": active_count,
        "recommended_action": recommendations[0] if recommendations else None,
    }
