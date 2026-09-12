import json
from pathlib import Path

import pytest

from core.security.sanitization import (
    REDACTION,
    SanitizedEvidencePackage,
    build_sanitized_evidence_package,
    serialize_for_external_analysis,
)
from core.storage.session import SessionStore


SECRET_CASES = [
    ("password", "password=synthetic-password"),
    ("passphrase", "passphrase=synthetic-passphrase"),
    ("psk", "psk=synthetic-psk"),
    ("api_key", "api_key=synthetic-api-key"),
    ("access_token", "access_token=synthetic-access-token"),
    ("refresh_token", "refresh_token=synthetic-refresh-token"),
    ("client_secret", "client_secret=synthetic-client-secret"),
    ("credentials", "credentials=synthetic-credentials"),
    ("bearer", "Authorization: Bearer synthetic-bearer"),
    ("proxy_bearer", "Proxy-Authorization: Bearer synthetic-proxy-bearer"),
    ("cookie", "Cookie: session=synthetic-cookie"),
    ("private_key", "-----BEGIN PRIVATE KEY-----\nsynthetic-private-key\n-----END PRIVATE KEY-----"),
]


def result_with(value):
    return {
        "schema_version": "3H-B.1",
        "analysis_id": "analysis-p0",
        "events": [{"event_id": "event-p0", "message": value, "raw_line": value}],
        "findings": [], "incidents": [],
        "analysis": {"completeness": 1.0, "confidence": "high"},
    }


@pytest.mark.parametrize("secret_type,input_text", SECRET_CASES, ids=[case[0] for case in SECRET_CASES])
def test_each_supported_secret_class_is_redacted_and_original_is_unchanged(secret_type, input_text):
    result = result_with(input_text)
    package = build_sanitized_evidence_package(result)
    output = json.dumps(package.to_dict())
    assert REDACTION in output
    assert input_text not in output
    assert input_text == result["events"][0]["message"]
    assert all("original_value" not in metadata for metadata in package.redactions)


def test_nested_structured_json_is_recursively_sanitized_without_mutation():
    original = {
        "headers": {"Authorization": "Bearer synthetic-json-bearer"},
        "credentials": {"password": "synthetic-json-password", "api_key": "synthetic-json-key"},
        "items": [{"refresh_token": "synthetic-json-refresh"}],
    }
    result = result_with(original)
    package = build_sanitized_evidence_package(result)
    output = json.dumps(package.to_dict())
    for secret in ("synthetic-json-bearer", "synthetic-json-password", "synthetic-json-key", "synthetic-json-refresh"):
        assert secret not in output
    assert result["events"][0]["message"] == original


def test_external_boundary_accepts_only_sanitized_package():
    package = build_sanitized_evidence_package(result_with("password=synthetic-password"))
    exported = serialize_for_external_analysis(package)
    assert "raw_lines" not in json.dumps(exported)
    assert "raw_line" not in json.dumps(exported)
    assert "metadata" not in exported
    with pytest.raises(TypeError):
        serialize_for_external_analysis(result_with("password=synthetic-password"))


def test_allowlist_excludes_dashboard_session_parser_and_arbitrary_metadata():
    result = result_with("safe")
    result["events"][0].update({"metadata": {"secret": "synthetic-hidden"}, "raw_lines": ["raw"]})
    result.update({"session": {"internal": "state"}, "dashboard": {"html": "state"}, "parser": {"internals": True}})
    exported = serialize_for_external_analysis(build_sanitized_evidence_package(result))
    serialized = json.dumps(exported)
    assert "synthetic-hidden" not in serialized
    assert "session" not in serialized
    assert "dashboard" not in serialized
    assert "parser" not in serialized
    assert "raw_lines" not in serialized
    assert "raw_line" not in serialized


def test_filename_path_traversal_is_rejected(tmp_path):
    store = SessionStore(tmp_path)
    for filename in ("../../evil.log", "..\\..\\evil.log", "/absolute/path.log", "C:\\Windows\\evil.log"):
        with pytest.raises((ValueError, FileNotFoundError)):
            store.validate_filename(filename)


def test_xss_values_are_not_present_in_html_interpolation_paths():
    html = Path("ui/dashboard.html").read_text(encoding="utf-8")
    assert "summary.innerHTML" not in html
    assert "overviewStats.innerHTML = metricItems.map" not in html
    assert "<script>alert" not in html
    assert "onerror=alert" not in html
    assert "textContent" in html
