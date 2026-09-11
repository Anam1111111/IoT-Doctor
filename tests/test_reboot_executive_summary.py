from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader
from core.parser.regex_parser import RegexParser
from pathlib import Path


def test_reboot_executive_summary_and_notable_count(tmp_path):
    lines = [
        "[INFO] Uptime=123s",
        "[INFO] Uptime=0s",
        "[INFO] device started after reset",
    ]
    p = tmp_path / "reboot3.log"
    p.write_text("\n".join(lines))
    PROFILE = ProfileLoader('.').load()
    parser = RegexParser(PROFILE['log_pattern'])
    service = FileAnalysisService(parser, PROFILE)
    result = service.analyze(str(p))
    # Notable events should include reboot lines but executive summary should
    # count only WARN/ERROR events (zero in this case) and prioritize reboot finding
    notable = result.get('notable_events', [])
    # confirm INFO events are present in notable_events
    assert any('uptime' in (e.get('message') or '').lower() for e in notable)
    exec_sum = result.get('executive_summary')
    assert exec_sum is not None
    assert 'Unexpected device reboot detected' in exec_sum
    assert 'Uptime reset' in exec_sum or 'uptime' in exec_sum.lower()
    # executive summary should NOT say 'notable warning/error event(s)'
    assert 'notable warning/error' not in exec_sum.lower()
