import tempfile
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def write_and_analyze(lines, parser_pattern=r"^NO_MATCH$"):
    with tempfile.NamedTemporaryFile(suffix=".log", mode="w", encoding="utf-8") as f:
        for l in lines:
            f.write(l + "\n")
        f.flush()
        parser = RegexParser(parser_pattern)
        svc = FileAnalysisService(parser, {"name": "test-device", "level_symbols": {}})
        return svc.analyze(f.name)


def test_supported_timestamp_formats_and_raw_preservation():
    lines = [
        "2026-09-10 22:14:20 [ERROR] component: command acknowledgement timeout",
        "2026-09-10 22:14:20.224 [WARN] network: reconnect attempt 1 failed",
        "2026-09-10T22:14:20Z [INFO] system: boot complete",
        "2026-09-10T22:14:20+01:00 [ERROR] protocol: timeout occurred",
        "this line is unstructured and should be preserved as raw",
    ]

    result = write_and_analyze(lines)

    assert result["statistics"]["lines_total"] == 5
    # Four structured timestamped lines expected
    assert result["statistics"]["events_parsed"] == 4
    assert result["statistics"]["unrecognized_lines"] == 1
    # raw_lines should preserve the exact original lines
    assert result["raw_lines"][4] == "this line is unstructured and should be preserved as raw"
    # ensure parsed events include timestamps and messages
    assert any(e.get("timestamp") and "timeout" in (e.get("message") or "") for e in result["events"]) or any("timeout" in (r or "") for r in result["raw_lines"]) 
