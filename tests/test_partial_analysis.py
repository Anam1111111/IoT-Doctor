from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader


def test_partial_analysis_reports_limited(tmp_path):
    PROFILE = ProfileLoader('.').load()
    PROFILE['min_parse_coverage'] = 0.9
    service = FileAnalysisService(None, PROFILE)
    p = tmp_path / "partial.log"
    # only one parseable line
    content = "Good line\nbad junk\nbad junk\n"
    p.write_text(content)
    res = service.analyze(str(p))
    assert res.get('analysis_status') == 'LIMITED_ANALYSIS'
    assert 'analysis may be incomplete' in (res.get('analysis_explanation') or '').lower()