import json
from pathlib import Path

from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def _run_analysis(lines, profile=None):
    p = Path("test_log.txt")
    p.write_text("\n".join(lines))
    parser = RegexParser(r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?) \[(?P<level>\w+)\] (?P<message>.+)$")
    svc = FileAnalysisService(parser, profile or {})
    return svc.analyze(str(p), metadata={"source_filename": p.name, "device_name": "TEST"})


def test_transient_warning_error_produces_summary(tmp_path, monkeypatch):
    # transient WARN/ERROR with successful recovery should produce analysis_summary
    lines = [
        "2026-09-10 22:14:12.334 [WARN] network: response latency=842ms",
        "2026-09-10 22:14:20.224 [ERROR] commissioning: command acknowledgement timeout endpoint=0x22",
        "2026-09-10 22:14:20.500 [INFO] commissioning: acknowledgement received",
        "2026-09-10 22:14:26.010 [WARN] network: packet retry count=2",
        "2026-09-10 22:15:00.000 [INFO] provisioning: completed successfully",
    ]
    # run
    res = _run_analysis(lines)
    timeout_incident = next(
        item for item in res.get("incidents", []) if item.get("category") == "timeout"
    )
    assert timeout_incident["status"] == "RESOLVED"
    assert res.get("analysis_summary") is not None
    assert "notable" in res.get("analysis_summary") or "Final health" in res.get("analysis_summary")


def test_explicit_connection_evidence_marks_connected(tmp_path):
    lines = [
        "2026-09-10 22:10:00.000 [INFO] device: connection established",
        "2026-09-10 22:11:00.000 [INFO] provisioning: completed successfully",
    ]
    res = _run_analysis(lines)
    assert res.get("health", {}).get("connected") is True


def test_absence_of_connection_evidence_marks_unknown(tmp_path):
    lines = [
        "2026-09-10 22:14:12.334 [WARN] network: response latency=842ms",
        "Some unstructured line without timestamps",
    ]
    res = _run_analysis(lines)
    # Parsed data without connection or disconnect evidence is insufficient.
    assert res.get("health", {}).get("connected") in (False, None)
    assert res.get("health", {}).get("status") == "UNKNOWN"
    assert "Insufficient connection evidence" in res.get("health", {}).get("reason", "")
