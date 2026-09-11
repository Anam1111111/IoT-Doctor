from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader
from core.parser.regex_parser import RegexParser
import tempfile


def test_reboot_in_key_events_and_health(tmp_path):
    lines = [
        "[INFO] Uptime=123s",
        "[INFO] Uptime=0s",
        "[INFO] device started after reset",
    ]
    p = tmp_path / "reboot.log"
    p.write_text("\n".join(lines))
    PROFILE = ProfileLoader('.').load()
    parser = RegexParser(PROFILE['log_pattern'])
    service = FileAnalysisService(parser, PROFILE)
    result = service.analyze(str(p))
    # Key events should include reboot/start messages
    key = result.get('notable_events', [])
    messages = [e.get('message','').lower() for e in key]
    assert any('uptime' in m or 'reboot' in m or 'started after reset' in m for m in messages), f"No reboot key events: {messages}"
    # Findings should include a reboot finding
    findings = result.get('findings', [])
    assert any(f.get('category') == 'reboot' for f in findings), f"No reboot finding: {findings}"
    # Health should not be CRITICAL just because connection evidence is absent; expect WARNING due to reboot finding
    health = result.get('health', {})
    assert health.get('status') in ('WARNING', 'RECOVERING', 'HEALTHY', 'UNKNOWN'), f"Unexpected health: {health}"
    # If there's a reboot finding, prefer WARNING
    if any(f.get('category') == 'reboot' for f in findings):
        assert health.get('status') == 'WARNING'
