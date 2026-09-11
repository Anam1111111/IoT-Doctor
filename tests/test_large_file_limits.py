from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader


def test_large_file_limits_applied(tmp_path):
    PROFILE = ProfileLoader('.').load()
    PROFILE['max_return_events'] = 2
    PROFILE['max_return_raw_lines'] = 3
    service = FileAnalysisService(None, PROFILE)
    p = tmp_path / "big.log"
    content = "\n".join([f"Line {i}" for i in range(10)])
    p.write_text(content)
    res = service.analyze(str(p))
    assert res['statistics']['lines_total'] == 10
    assert res['statistics']['events_parsed'] <= 2
    assert res['omitted_counts']['events'] >= 0
    assert res['omitted_counts']['raw_lines'] == max(0, 10 - 3)