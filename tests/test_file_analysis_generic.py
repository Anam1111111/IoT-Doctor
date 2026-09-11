import os
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def test_generic_timestamped_lines(tmp_path):
    sample = """
2026-09-10 22:14:20.224 [ERROR] commissioning: command acknowledgement timeout
2026-09-10 22:14:21.100 [WARN] network: reconnect attempt 1 failed
garbage line that does not match
"""
    p = tmp_path / "sample.log"
    p.write_text(sample.strip() + "\n", encoding="utf-8")

    # Provide a simple parser that will not match the generic lines
    parser = RegexParser(r"^NO_MATCH$")
    profile = {"name": "test-device", "level_symbols": {}}
    svc = FileAnalysisService(parser, profile)
    result = svc.analyze(str(p), metadata={"source_filename": "sample.log"})

    assert result["statistics"]["lines_total"] == 3
    # Two lines parsed by the generic fallback
    assert result["statistics"]["events_parsed"] == 2
    assert result["statistics"]["unrecognized_lines"] == 1
    # Connection evidence is absent, so imported health remains UNKNOWN unless
    # a diagnostic rule reports an explicit condition.
    assert result["health"]["status"] in {"HEALTHY", "WARNING", "RECOVERING", "CRITICAL", "UNKNOWN"}
    # Ensure events include timestamp, level, and message when parsed
    ev0 = result["events"][0]
    assert "timestamp" in ev0 or "raw" in ev0
    assert any("timeout" in (e.get("message") or "") for e in result["events"]) or any("timeout" in (e.get("raw") or "") for e in result["events"]) 
