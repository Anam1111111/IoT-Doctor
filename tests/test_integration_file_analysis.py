import pytest
import tempfile
from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser


def test_file_analysis_reboot_integration(tmp_path):
    # Create a tiny log with uptime that resets to 0 -> should detect reboot
    lines = [
        "2026-09-11 12:00:00 [INFO] Uptime=120s",
        "2026-09-11 12:00:01 [INFO] Uptime=121s",
        "2026-09-11 12:00:02 [INFO] Uptime=122s",
        "2026-09-11 12:00:03 [INFO] Uptime=0s",
    ]
    p = tmp_path / "reboot.log"
    p.write_text("\n".join(lines))

    # Use a parser that doesn't match to let generic parser handle timestamped lines
    parser = RegexParser(r"^$")
    profile = {
        "name": "TestDevice",
        "level_symbols": {},
        "metrics": {
            "uptime": {
                "source": "message",
                "pattern": r"Uptime=(?P<value>\d+)s",
                "unit": "seconds",
            }
        },
    }

    svc = FileAnalysisService(parser, profile)
    result = svc.analyze(str(p), metadata={"device_name": "TestDevice", "source_filename": "reboot.log"})

    # There should be at least one historical incident indicating reboot
    incidents = result.get("incidents", [])
    assert any("reboot" in inc.get("title", "").lower() or "reboot" in inc.get("evidence", "").lower() or "Unexpected device reboot" in inc.get("title", "") for inc in incidents)
    # And findings should include a reboot finding
    findings = result.get("findings", [])
    assert any("Unexpected device reboot detected" in f.get("title", "") for f in findings)
