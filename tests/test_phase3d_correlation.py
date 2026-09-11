import pytest
import tempfile
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def test_disconnect_retries_reconnect_produces_single_correlated_incident(tmp_path):
    lines = [
        "2026-09-11 12:00:00 [ERROR] Device disconnected - retrying...",
        "2026-09-11 12:00:01 [INFO] Reconnect attempt 1 failed",
        "2026-09-11 12:00:02 [INFO] Reconnect attempt 2 failed",
        "2026-09-11 12:00:03 [INFO] Device connected",
    ]
    p = tmp_path / "conn.log"
    p.write_text("\n".join(lines))

    parser = RegexParser(r"^$")
    profile = {"name": "TestDevice", "level_symbols": {}, "metrics": {}}
    svc = FileAnalysisService(parser, profile)
    result = svc.analyze(str(p), metadata={"device_name": "TestDevice", "source_filename": "conn.log"})

    incidents = result.get("incidents", [])
    # Expect one connectivity incident correlated
    conn_incidents = [i for i in incidents if i.get("category") == "connectivity"]
    assert len(conn_incidents) == 1
    inc = conn_incidents[0]
    assert inc.get("title")
    assert inc.get("related_events") and len(inc.get("related_events")) >= 3
    # impact should indicate reconnect attempts and recovered True
    impact = inc.get("impact")
    assert impact is not None
    assert impact.get("reconnect_attempts") >= 2
    assert impact.get("recovered") is True

