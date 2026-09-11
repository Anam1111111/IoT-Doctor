from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader
from core.parser.regex_parser import RegexParser
from pathlib import Path


def test_reboot_keyevents_contains_uptime(tmp_path):
    lines = [
        "[INFO] Uptime=123s",
        "[INFO] Uptime=0s",
        "[INFO] device started after reset",
    ]
    p = tmp_path / "reboot2.log"
    p.write_text("\n".join(lines))
    PROFILE = ProfileLoader('.').load()
    parser = RegexParser(PROFILE['log_pattern'])
    service = FileAnalysisService(parser, PROFILE)
    result = service.analyze(str(p))
    key = result.get('notable_events', [])
    messages = [e.get('message','') for e in key]
    assert any('Uptime' in m or 'uptime' in m.lower() for m in messages), f"Uptime not in key events: {messages}"
