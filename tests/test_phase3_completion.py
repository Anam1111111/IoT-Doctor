from core.ingestion.file_analysis import FileAnalysisService
from core.normalization.normalizer import EventNormalizer
from core.parser.regex_parser import RegexParser


def test_timeout_with_explicit_recovery_becomes_resolved_incident(tmp_path):
    path = tmp_path / "timeout.log"
    path.write_text(
        "2026-09-11 12:00:00 [ERROR] command acknowledgement timeout\n"
        "2026-09-11 12:00:02 [INFO] retry succeeded\n"
    )
    service = FileAnalysisService(RegexParser(r"^$"), {"name": "Test"})

    result = service.analyze(str(path))

    incident = next(item for item in result["incidents"] if item["category"] == "timeout")
    assert incident["status"] == "RESOLVED"
    assert incident["impact"]["recovered"] is True
    assert incident["duration"] == 2
    assert "Timeout observed" in incident["evidence"]


def test_explicit_positive_signals_produce_healthy_import(tmp_path):
    path = tmp_path / "healthy.log"
    path.write_text(
        "2026-09-11 12:00:00 [INFO] network: link established\n"
        "2026-09-11 12:00:01 [INFO] device status=READY\n"
        "2026-09-11 12:00:02 [INFO] heartbeat received\n"
        "2026-09-11 12:00:03 [INFO] verification=PASS\n"
        "2026-09-11 12:00:04 [INFO] provisioning complete\n"
        "2026-09-11 12:00:05 [INFO] session closed cleanly\n"
    )
    service = FileAnalysisService(RegexParser(r"^$"), {"name": "Test"})

    result = service.analyze(str(path))

    assert result["health"]["status"] == "HEALTHY"
    assert result["health"]["connected"] is True
    assert result["health"]["reason"] == "Normal operation"
    assert result["findings"] == []


def test_normalized_file_event_has_category_source_and_unchanged_raw_line():
    event = EventNormalizer().normalize(
        {"timestamp": "2026-09-11T12:00:00Z", "level": "ERR", "message": "Sensor response timeout"},
        raw="2026-09-11T12:00:00Z [ERR] Sensor response timeout",
        transport_metadata={"transport": "file", "source": "file"},
    )

    assert event["level"] == "ERROR"
    assert event["message"] == "Sensor response timeout"
    assert event["timestamp"] == "2026-09-11T12:00:00Z"
    assert event["category"] == "log"
    assert event["source"] == "file"
    assert event["raw_line"] == "2026-09-11T12:00:00Z [ERR] Sensor response timeout"


def test_raw_lines_preserve_original_line_endings(tmp_path):
    path = tmp_path / "source.log"
    path.write_bytes(b"[INFO] first\r\n[INFO] second\n")
    result = FileAnalysisService(RegexParser(r"^$"), {}).analyze(str(path))

    assert result["raw_lines"] == ["[INFO] first\r\n", "[INFO] second\n"]