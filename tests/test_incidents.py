from core.ingestion.file_analysis import FileAnalysisService
from core.parser.regex_parser import RegexParser
import tempfile


def test_detect_disconnect_incident():
    profile = {"level_symbols": {}, "metrics": {}}
    parser = RegexParser(r"^(?P<level>\w+)\s+(?P<message>.+)$")
    service = FileAnalysisService(parser, profile)

    lines = [
        "2026-09-11 12:00:00 [INFO] Device connected",
        "2026-09-11 12:01:00 [ERROR] device disconnected unexpectedly",
        "2026-09-11 12:01:05 [INFO] Device connected",
    ]

    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".log") as f:
        for l in lines:
            f.write(l + "\n")
        path = f.name

    result = service.analyze(path, metadata={})
    incidents = result.get("incidents", [])
    assert any(i.get("category") == "connectivity" for i in incidents)


def test_detect_reboot_incident():
    profile = {"level_symbols": {}, "metrics": {"uptime":{"pattern": r"uptime=(?P<value>\d+)", "unit":"s"}}}
    parser = RegexParser(r"^(?P<level>\w+)\s+(?P<message>.+)$")
    service = FileAnalysisService(parser, profile)

    lines = [
        "2026-09-11 12:00:00 [INFO] uptime=120",
        "2026-09-11 12:05:00 [INFO] uptime=1",
    ]

    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".log") as f:
        for l in lines:
            f.write(l + "\n")
        path = f.name

    result = service.analyze(path, metadata={})
    incidents = result.get("incidents", [])
    # Reboot detection may be in findings; ensure either incidents or findings mention reboot
    assert any("reboot" in (i.get("title") or "").lower() for i in incidents) or any("reboot" in (f.get("title") or "").lower() for f in result.get("findings", []))
