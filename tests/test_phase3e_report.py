import pytest
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def test_end_to_end_report_reboot_and_connectivity(tmp_path):
    lines = [
        "2026-09-11 12:00:00 [INFO] Uptime=120s",
        "2026-09-11 12:00:01 [INFO] Uptime=121s",
        "2026-09-11 12:00:02 [INFO] Uptime=122s",
        "2026-09-11 12:00:03 [INFO] Uptime=0s",
        "2026-09-11 12:05:00 [ERROR] Device disconnected - retrying...",
        "2026-09-11 12:05:05 [INFO] Reconnect attempt 1 failed",
        "2026-09-11 12:05:10 [INFO] Device connected",
    ]
    p = tmp_path / "report.log"
    p.write_text("\n".join(lines))

    parser = RegexParser(r"^$")
    profile = {
        "name": "TestDevice",
        "level_symbols": {},
        "metrics": {
            "uptime": {"source": "message", "pattern": r"Uptime=(?P<value>\d+)s", "unit": "seconds"}
        },
    }
    svc = FileAnalysisService(parser, profile)
    result = svc.analyze(str(p), metadata={"device_name": "TestDevice", "source_filename": "report.log"})

    report = result.get("report")
    assert isinstance(report, list)
    # Should contain at least one reboot and one connectivity report
    titles = [r.get("title", "") for r in report]
    assert any(("reboot" in (r.get("title", "")).lower()) or ("reboot" in (r.get("evidence") or "").lower()) for r in report)
    assert any(r.get("category") == "connectivity" for r in report)
    # Check preserved events in report entries
    for r in report:
        assert "related_events" in r
        for ev in r.get("related_events", []):
            assert "message" in ev


def test_insufficient_data_reports_empty_report(tmp_path):
    lines = ["just some random line without structure"]
    p = tmp_path / "sparse.log"
    p.write_text("\n".join(lines))
    parser = RegexParser(r"^$")
    profile = {"name": "TestDevice", "level_symbols": {}, "metrics": {}}
    svc = FileAnalysisService(parser, profile)
    result = svc.analyze(str(p), metadata={"device_name": "TestDevice"})
    report = result.get("report")
    # No structured report when parsed events are insufficient
    assert report == []
