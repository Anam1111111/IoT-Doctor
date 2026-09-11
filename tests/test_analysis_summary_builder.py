from core.analysis_summary import build_analysis_interpretation
from pathlib import Path


def interpret(*, device_name="Device", incidents=None, findings=None, events=None, status="WARNING"):
    return build_analysis_interpretation(
        health={"status": status},
        incidents=incidents or [],
        findings=findings or [],
        events=events or [],
        statistics={"lines_total": 10, "events_parsed": 10, "unrecognized_lines": 0},
    )


def test_same_connectivity_facts_have_same_interpretation_for_different_names():
    facts = [{"category": "connectivity", "title": "Connection interruption", "impact": {"recovered": True, "reconnect_attempts": 2}}]
    assert interpret(device_name="Alpha", incidents=facts) == interpret(device_name="Beta", incidents=facts)


def test_same_name_with_different_evidence_changes_interpretation():
    assert "connection" in interpret(device_name="Same", incidents=[{"category": "connectivity", "impact": {"recovered": True}}])["what_happened"].lower()
    assert "response" in interpret(device_name="Same", incidents=[{"category": "timeout", "status": "RESOLVED", "impact": {"recovered": True}}])["what_happened"].lower()


def test_memory_timeout_reboot_and_unknown_are_fact_driven():
    assert "memory" in interpret(findings=[{"category": "memory"}])["what_happened"].lower()
    assert "response" in interpret(incidents=[{"category": "timeout"}])["what_happened"].lower()
    assert "restarted" in interpret(findings=[{"category": "reboot"}])["what_happened"].lower()
    assert "enough" in interpret(events=[], status="UNKNOWN")["what_happened"].lower()


def test_names_and_raw_text_do_not_cause_diagnosis():
    result = interpret(device_name="Vendor Product", events=[{"level": "INFO", "message": "Vendor Product is online"}], status="HEALTHY")
    assert "normally" in result["what_happened"].lower()
    assert "vendor product" not in result["what_happened"].lower()


def test_ui_renders_backend_interpretation_without_diagnosing():
    html = (Path(__file__).parents[1] / "ui" / "dashboard.html").read_text()
    assert "result.what_happened || result.analysis?.what_happened" in html
    assert "const connectionObserved" not in html


def test_all_recovered_connectivity_uses_recovered_wording():
    incidents = [{"category": "connectivity", "impact": {"recovered": True, "reconnect_attempts": 1}}]
    summary = interpret(incidents=incidents)["what_happened"]
    assert "came back" in summary
    assert "ongoing failure" in summary


def test_active_and_recovered_connectivity_prioritizes_unresolved_state():
    incidents = [
        {"category": "connectivity", "impact": {"recovered": True}},
        {"category": "connectivity", "impact": {"recovered": False}, "status": "INCIDENT"},
    ]
    summary = interpret(incidents=incidents)["what_happened"]
    assert "1 recovered" in summary
    assert "1 issue remains unresolved" in summary
    assert "do not show that the problem continued" not in summary


def test_bluetooth_only_connectivity_uses_cautious_source_wording():
    incidents = [{
        "category": "connectivity",
        "impact": {"recovered": True},
        "related_events": [{"source_class": "BLUETOOTH_SYSTEM"}],
    }]
    summary = interpret(incidents=incidents)["what_happened"]
    assert "Bluetooth connection activity" in summary
    assert "physical device-level failure" in summary


def test_insufficient_evidence_uses_uncertainty_wording():
    summary = interpret(events=[], status="UNKNOWN")["what_happened"]
    assert "not enough" in summary
    assert "confident conclusion" in summary
