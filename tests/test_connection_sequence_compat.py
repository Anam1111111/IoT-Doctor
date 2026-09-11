from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader
from core.parser.regex_parser import RegexParser


def test_connection_sequence_produces_historical_incident_compat(tmp_path):
    log_lines = [
        "ERROR disconnected - retrying...",
        "INFO reconnect attempt 1 failed",
        "INFO reconnect attempt 2 failed",
        "INFO reconnect attempt 3 failed",
        "INFO connected",
        "INFO connection recovered",
    ]
    p = tmp_path / "sample2.log"
    p.write_text("\n".join(log_lines))
    PROFILE = ProfileLoader('.').load()
    parser = RegexParser(PROFILE['log_pattern'])
    service = FileAnalysisService(parser, PROFILE)
    result = service.analyze(str(p))
    incidents = result.get("incidents", [])
    assert any(i.get("category") == "connectivity" for i in incidents), f"No connectivity incident found: {incidents}"