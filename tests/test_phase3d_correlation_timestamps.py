import pytest
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def test_timestamps_start_end_duration_and_unrelated_do_not_merge(tmp_path):
    lines = [
        "2026-09-11 12:00:00 [ERROR] Device disconnected - retrying...",
        "2026-09-11 12:00:05 [INFO] Reconnect attempt 1 failed",
        "2026-09-11 12:00:10 [INFO] Reconnect attempt 2 failed",
        "2026-09-11 12:00:15 [INFO] Device connected",
        # unrelated event in between separate incidents
        "2026-09-11 12:05:00 [ERROR] Some other error",
        "2026-09-11 12:10:00 [ERROR] Device disconnected - retrying...",
        "2026-09-11 12:10:05 [INFO] Reconnect attempt 1 failed",
        "2026-09-11 12:10:10 [INFO] Device connected",
    ]
    p = tmp_path / "conn2.log"
    p.write_text("\n".join(lines))

    parser = RegexParser(r"^$")
    profile = {"name": "TestDevice", "level_symbols": {}, "metrics": {}}
    svc = FileAnalysisService(parser, profile)
    result = svc.analyze(str(p), metadata={"device_name": "TestDevice", "source_filename": "conn2.log"})

    incidents = [i for i in result.get("incidents", []) if i.get("category") == "connectivity"]
    # Should have two separate connectivity incidents
    assert len(incidents) == 2
    first = incidents[0]
    second = incidents[1]
    assert first.get("start_time") is not None
    assert first.get("end_time") is not None
    assert first.get("duration") is not None and first.get("duration") >= 0
    # Ensure related events preserved and unchanged
    assert any(e.get("message") == "Device connected" for e in first.get("related_events", []))
    # Unrelated error should not be included in related_events
    assert all("some other error" not in (e.get("message") or "").lower() for e in first.get("related_events", []))

