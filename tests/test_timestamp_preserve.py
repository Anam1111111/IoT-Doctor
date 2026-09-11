import tempfile
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def test_preserve_parsed_timestamp_generic():
    # Use a simple profile with no special level_symbols
    profile = {"level_symbols": {}}
    # RegexParser won't match generic timestamp lines, FileAnalysisService uses fallback generic regex
    parser = RegexParser(r"^(?P<level>\w+)\s+(?P<message>.+)$")
    service = FileAnalysisService(parser, profile)

    line = "2026-09-11 12:34:56 [INFO] Test message"
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".log") as f:
        f.write(line + "\n")
        path = f.name

    result = service.analyze(path, metadata={})
    events = result.get("events", [])
    assert len(events) >= 1
    # The timeline event should preserve the parsed timestamp string
    assert any(e.get("timestamp") == "2026-09-11 12:34:56" or e.get("timestamp") == "2026-09-11 12:34:56" for e in events)
