import json
from pathlib import Path

from core.ingestion.file_analysis import FileAnalysisService
from core.models.event import make_event
from core.models.finding import Finding
from core.parser.logcat_parser import LogcatParser
from core.parser.regex_parser import RegexParser
from core.schema import SCHEMA_VERSION


ROOT = Path(__file__).parents[1]
PROFILE = {
    "name": "Generic profile",
    "level_symbols": {},
    "metrics": {},
    "min_parse_coverage": 0.5,
}


def analyze(tmp_path, lines, parser=None):
    path = tmp_path / "input.log"
    path.write_text("\n".join(lines), encoding="utf-8")
    return FileAnalysisService(parser, PROFILE).analyze(path)


def test_trust_states_are_explicit_and_preserved_only_has_no_findings(tmp_path):
    result = analyze(tmp_path, [
        "2026-09-12 10:00:00 [INFO] service: ready",
        "unclassified content",
    ])
    states = [event["trust_state"] for event in result["events"]]
    assert states == ["PARSED", "PRESERVED_ONLY"]
    assert all(event["trust_state"] != "PRESERVED_ONLY" for event in result["findings"])


def test_partial_parser_result_is_not_diagnosed(tmp_path):
    result = analyze(tmp_path, ["2026-09-12 10:00:00 [INFO] service: ready"], parser=LogcatParser())
    assert result["events"][0]["trust_state"] == "PARTIALLY_PARSED"
    assert result["findings"] == []


def test_canonical_fields_unknown_fields_and_line_provenance(tmp_path):
    result = analyze(tmp_path, [
        "2026-09-12 10:00:00 [INFO] service: ready",
        "unclassified content",
    ])
    event = result["events"][0]
    assert event["event_id"] == event["id"]
    assert event["timestamp_original"] == "2026-09-12 10:00:00"
    assert event["timestamp_kind"] == "absolute"
    assert event["source_line_start"] == 1
    assert event["source_line_end"] == 1
    assert event["raw_line"]
    assert event.get("parse_confidence") in (0.0, None)
    assert result["events"][1]["source_line_start"] == 2


def test_finding_provenance_links_events_and_source_lines(tmp_path):
    result = analyze(tmp_path, [
        "ERROR disconnected - retrying",
        "INFO reconnect attempt 1 failed",
        "INFO connected",
    ], parser=RegexParser(r"^(?P<level>INFO|ERROR)\s+(?P<message>.+)$"))
    assert result["findings"]
    finding = result["findings"][0]
    assert finding["supporting_event_ids"]
    assert finding["supporting_source_lines"]
    assert finding["evidence_claims"][0]["supporting_event_ids"] == finding["supporting_event_ids"]
    event_ids = {event["event_id"] for event in result["events"]}
    assert set(finding["supporting_event_ids"]).issubset(event_ids)
    for incident in result["incidents"]:
        assert incident["incident_id"] not in event_ids
        assert incident["evidence_claims"][0]["supporting_event_ids"] == incident["supporting_event_ids"]


def test_response_schema_analysis_identity_and_reproducibility_metadata(tmp_path):
    result = analyze(tmp_path, ["2026-09-12 10:00:00 [INFO] service: ready"])
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["analysis_id"]
    assert result["analysis_metadata"]["schema_version"] == result["schema_version"]
    assert "parser_versions" in result["analysis_metadata"]
    assert "diagnostic_engine_version" in result["analysis_metadata"]
    assert "summary_builder_version" in result["analysis_metadata"]


def test_legacy_event_and_finding_serialization_remain_json_compatible():
    event = make_event("INFO", "ready", transport="file", metadata={"transport": "file"})
    finding = Finding("WARNING", "Test", "test", "description", "evidence", 1.0, "review")
    json.dumps(event)
    json.dumps(finding.to_dict())
    assert event["id"]
    assert finding.to_dict()["recommended_action"] == "review"


def test_provenance_rejects_unknown_supporting_event_id(tmp_path):
    result = analyze(tmp_path, ["2026-09-12 10:00:00 [INFO] service: ready"])
    event_ids = {event["event_id"] for event in result["events"]}
    for finding in result["findings"]:
        assert set(finding["supporting_event_ids"]).issubset(event_ids)


def test_multiline_event_keeps_original_line_range_and_raw_lines(tmp_path):
    result = analyze(tmp_path, [
        "2026-09-12 10:00:00 [ERROR] service: failure",
        "  detail: first continuation",
        "  detail: second continuation",
    ])
    event = result["events"][0]
    assert event["source_line_start"] == 1
    assert event["source_line_end"] == 3
    assert len(event["raw_lines"]) == 3
