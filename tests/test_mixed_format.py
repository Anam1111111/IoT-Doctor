from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader


def test_mixed_format_handles_sections(tmp_path):
    PROFILE = ProfileLoader('.').load()
    service = FileAnalysisService(None, PROFILE)
    p = tmp_path / "mixed.log"
    content = "2026-09-11 12:00:00 [INFO] component: Started\nRandom garbage line\nError: boom\n    at foo\n"
    p.write_text(content)
    res = service.analyze(str(p))
    # Ensure some events parsed and unrecognized lines don't abort
    assert res['statistics']['lines_total'] == 4
    assert res['statistics']['events_parsed'] >= 1