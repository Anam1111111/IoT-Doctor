from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader
from core.parser.regex_parser import RegexParser
import tempfile


def test_connection_sequence_produces_historical_incident(tmp_path):
    log_lines = [
        "ERROR disconnected - retrying...",
        "INFO reconnect attempt 1 failed",
        "INFO reconnect attempt 2 failed",
        "INFO reconnect attempt 3 failed",
        "INFO connected",
        "INFO connection recovered",
    ]
    p = tmp_path / "sample.log"
    p.write_text("\n".join(log_lines))
    PROFILE = ProfileLoader('.').load()
    parser = RegexParser(PROFILE['log_pattern'])
    # Use profile loader's minimal profile
    service = FileAnalysisService(parser, PROFILE)
    result = service.analyze(str(p))
    incidents = result.get("incidents", [])
    # Expect one connectivity incident recorded
    assert any(i.get("category") == "connectivity" for i in incidents), f"No connectivity incident found: {incidents}"
    conn = next(i for i in incidents if i.get("category") == "connectivity")
    related = conn.get("related_events", [])
    messages = [e.get("message", "").lower() for e in related]
    assert any("disconnected" in m for m in messages)
    assert any("reconnect attempt" in m or "retry" in m for m in messages)
    # recovered should be True per incident impact
    impact = conn.get("impact") or {}
    assert impact.get("recovered") is True
