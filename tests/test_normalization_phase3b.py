from core.parser.regex_parser import RegexParser
from core.normalization.normalizer import EventNormalizer


def test_normalize_preserve_timestamp_and_raw():
    parser = RegexParser(r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(?P<level>INFO|WARN|ERROR)\] (?P<message>.+)$")
    parsed = parser.parse("2026-09-11 12:00:00 [INFO] Device started")
    normalizer = EventNormalizer(device_id="dev1")
    evt = normalizer.normalize(parsed, raw="2026-09-11 12:00:00 [INFO] Device started", transport_metadata={})
    assert evt["timestamp"] == "2026-09-11 12:00:00"
    assert evt["raw_line"] == "2026-09-11 12:00:00 [INFO] Device started"
    assert evt["level"] == "INFO"
    assert evt["message"] == "Device started"


def test_missing_timestamp_not_invented_and_level_normalization():
    parser = RegexParser(r"^(?P<level>INFO|WARN|ERROR) (?P<message>.+)$")
    parsed = parser.parse("WARN Low battery")
    normalizer = EventNormalizer()
    evt = normalizer.normalize(parsed, raw="WARN Low battery", transport_metadata={})
    # For non-file transports, a timestamp may be assigned (current time)
    assert evt.get("timestamp") not in (None, "")
    assert evt["level"] == "WARN"
    assert "WARN" not in evt["message"]
    assert evt["raw_line"] == "WARN Low battery"


def test_file_transport_without_parsed_timestamp_has_empty_timestamp():
    # When importing from file, missing parsed timestamp must not be replaced
    parser = RegexParser(r"^(?P<level>INFO|WARN|ERROR) (?P<message>.+)$")
    parsed = parser.parse("ERROR Crash")
    normalizer = EventNormalizer()
    evt = normalizer.normalize(parsed, raw="ERROR Crash", transport_metadata={"transport": "file"})
    # For file transport with no parsed timestamp, timestamp must be empty string
    assert evt.get("timestamp") == ""
    assert evt["level"] == "ERROR"
    assert evt["raw_line"] == "ERROR Crash"


def test_unrecognized_line_becomes_unknown_event():
    normalizer = EventNormalizer()
    parsed = {}
    evt = normalizer.normalize(parsed, raw="nonsense line", transport_metadata={})
    assert evt["level"] == "UNKNOWN" or evt["level"] is None
    assert evt["raw_line"] == "nonsense line"
