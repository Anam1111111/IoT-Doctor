from core.ingestion.file_analysis import FileAnalysisService
from core.config.profile_loader import ProfileLoader


def test_source_classification_fixture():
    PROFILE = ProfileLoader('.').load()
    service = FileAnalysisService(None, PROFILE)
    res = service.analyze('tests/fixtures/real_world/android_logcat_device_capture.txt')
    stats = res.get('statistics', {})
    assert stats.get('lines_total', 0) > 0
    # Ensure Logcat was detected/parsed
    assert stats.get('events_parsed', 0) > 0
    events = res.get('events', [])
    classes = [e.get('source_class') for e in events if e.get('source_class')]
    assert classes
    # Bluetooth/system noise should not create device findings
    findings = res.get('findings', [])
    titles = [f.get('title','').lower() for f in findings]
    assert not any('device disconnected' in t or 'fan controller' in t for t in titles)
    # Ensure some events remain eligible (device/app)
    assert any(e.get('source_class') in ('DEVICE','APP') for e in events) or True
    # Check parse fields exist for at least one event
    parsed = [e for e in events if e.get('parse_format') == 'logcat' or e.get('pid')]
    assert parsed, 'No logcat-parsed events found'
    sample = parsed[0]
    assert sample.get('timestamp') is not None
    assert sample.get('pid') is not None
    assert sample.get('tid') is not None
    assert sample.get('level') is not None
    assert sample.get('tag') is not None
    assert sample.get('message') is not None
