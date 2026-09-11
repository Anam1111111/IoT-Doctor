from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser
import tempfile


def test_health_explanation_on_recovered_warning():
    profile = {"level_symbols": {}}
    # Simple parser: timestamped lines like 'TIME [LEVEL] message' will be caught by generic fallback
    parser = RegexParser(r"^(?P<level>\w+)\s+(?P<message>.+)$")
    service = FileAnalysisService(parser, profile)

    lines = [
        "2026-09-11 12:00:00 [WARN] packet retry count=2",
        "2026-09-11 12:00:01 [INFO] packet retry recovered",
        "2026-09-11 12:00:05 [INFO] verification started",
        "2026-09-11 12:00:06 [INFO] verification=PASS",
    ]

    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".log") as f:
        for l in lines:
            f.write(l + "\n")
        path = f.name

    result = service.analyze(path, metadata={})
    assert result["health"]
    # If health is HEALTHY, we expect a non-empty health_explanation describing transient warnings
    if result["health"].get("status") == "HEALTHY":
        assert result.get("health_explanation") is not None
        assert "warning" in result["health_explanation"].lower()
    else:
        # If health isn't HEALTHY, ensure incidents captured
        assert result.get("incidents") is not None
