from pathlib import Path


def test_analysis_modal_has_required_sections_in_order():
    html = (Path(__file__).parents[1] / "ui" / "dashboard.html").read_text()
    modal = html.split('id="analysisModal"', 1)[1].split("<script>", 1)[0]

    labels = [
        "EXECUTIVE SUMMARY",
        "HEALTH / ASSESSMENT",
        "FINDINGS / INCIDENTS",
        "KEY EVENTS",
        "RECOMMENDED ACTION",
        "EVENT TIMELINE",
        "UNRECOGNIZED LINES",
        "RAW LOG / ORIGINAL SOURCE",
    ]
    positions = [modal.index(label) for label in labels]

    assert positions == sorted(positions)
    assert 'id="analysisRaw" class="raw-log"' in modal
    assert 'id="analysisUnrecognizedList" class="raw-log"' in modal


def test_analysis_ui_renders_exact_raw_lines_and_required_key_event_terms():
    html = (Path(__file__).parents[1] / "ui" / "dashboard.html").read_text()

    assert "raw.textContent = (result.raw_lines || []).join('');" in html
    assert "timeout|disconnect|reconnect|reboot|restart|reset|recover|complet|verif" in html
    assert "#analysisTimeline { max-height: 330px; overflow-y: auto; }" in html