"""Format-independent sanitization boundary for future external analysis."""

from dataclasses import dataclass
import json
import re

REDACTION = "[REDACTED]"
_SECRET_PATTERNS = [
    ("AUTHORIZATION_HEADER", re.compile(r"(?i)(\b(?:authorization|proxy-authorization)\s*[:=]\s*bearer\s+)[^\s,;]+")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S)),
    ("COOKIE", re.compile(r"(?i)(\b(?:cookie|set-cookie)\s*[:=]\s*)[^\r\n]+")),
    ("CREDENTIAL", re.compile(r"(?i)(\b(?:password|passphrase|psk|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|credentials?)\s*[=:]\s*[\"']?)[^\s,;\"']+")),
]


@dataclass(frozen=True)
class SanitizedEvidencePackage:
    schema_version: str
    analysis_id: str | None
    events: list
    findings: list
    incidents: list
    completeness: object
    confidence: object
    redactions: list
    omitted_counts: dict

    def to_dict(self):
        return {
            "schema_version": self.schema_version,
            "analysis_id": self.analysis_id,
            "events": self.events,
            "findings": self.findings,
            "incidents": self.incidents,
            "completeness": self.completeness,
            "confidence": self.confidence,
            "redactions": self.redactions,
            "omitted_counts": self.omitted_counts,
        }


def serialize_for_external_analysis(package: SanitizedEvidencePackage) -> dict:
    """The only supported boundary for a future external analysis consumer."""
    if not isinstance(package, SanitizedEvidencePackage):
        raise TypeError("external analysis requires SanitizedEvidencePackage")
    return package.to_dict()


def serialize_sanitized_evidence(package: SanitizedEvidencePackage) -> str:
    """Return the canonical bounded serialization used for size accounting."""
    if not isinstance(package, SanitizedEvidencePackage):
        raise TypeError("sanitized evidence serialization requires SanitizedEvidencePackage")
    return json.dumps(package.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sanitize_text(value, location, redactions):
    text = str(value)
    for secret_type, pattern in _SECRET_PATTERNS:
        def replace(match):
            prefix = match.group(1) if match.lastindex else ""
            redactions.append({"type": secret_type, "location": location, "replacement": REDACTION})
            return prefix + REDACTION
        text = pattern.sub(replace, text)
    return text


def _sanitize(value, location, redactions, max_chars, max_nested_items, omitted):
    if isinstance(value, str):
        return sanitize_text(value[:max_chars], location, redactions)
    if isinstance(value, list):
        values = value[:max_nested_items]
        omitted["nested_items"] += max(0, len(value) - len(values))
        return [_sanitize(item, f"{location}[{index}]", redactions, max_chars, max_nested_items, omitted) for index, item in enumerate(values)]
    if isinstance(value, dict):
        sanitized = {}
        sensitive_keys = {"password", "passphrase", "psk", "api_key", "apikey", "access_token", "refresh_token", "client_secret", "credentials", "authorization", "proxy-authorization", "cookie", "set-cookie", "private_key"}
        for key, item in value.items():
            key_text = str(key)
            item_location = f"{location}.{key_text}"
            normalized_key = key_text.lower().replace("-", "_")
            if normalized_key in sensitive_keys and isinstance(item, str):
                redactions.append({"type": normalized_key.upper(), "location": item_location, "replacement": REDACTION})
                sanitized[key_text] = REDACTION
            else:
                sanitized[key_text] = _sanitize(item, item_location, redactions, max_chars, max_nested_items, omitted)
        return sanitized
    return value


def build_sanitized_evidence_package(result, *, max_events=100, max_findings=100, max_incidents=100, max_message_chars=2000, max_nested_items=100, max_total_chars=100_000):
    def select(item, fields):
        return {field: item[field] for field in fields if field in item}

    source_events = [select(item, ("event_id", "timestamp", "level", "message", "source_class", "event_type", "category", "parse_format", "parse_confidence", "trust_state", "source_line_start", "source_line_end")) for item in (result.get("events") or [])]
    source_findings = [select(item, ("id", "title", "category", "severity", "description", "evidence", "confidence", "status", "supporting_event_ids", "supporting_source_lines", "evidence_claims")) for item in (result.get("findings") or [])]
    source_incidents = [select(item, ("incident_id", "id", "title", "category", "severity", "evidence", "status", "impact", "supporting_event_ids", "supporting_source_lines", "evidence_claims")) for item in (result.get("incidents") or [])]

    def build(events, findings, incidents, string_limit, nested_limit):
        redactions = []
        omitted = {"events": max(0, len(source_events) - len(events)), "findings": max(0, len(source_findings) - len(findings)), "incidents": max(0, len(source_incidents) - len(incidents)), "characters": 0, "nested_items": 0}
        package = SanitizedEvidencePackage(
            schema_version=str(result.get("schema_version", "3H-C.1")),
            analysis_id=result.get("analysis_id"),
            events=_sanitize(events, "events", redactions, string_limit, nested_limit, omitted),
            findings=_sanitize(findings, "findings", redactions, string_limit, nested_limit, omitted),
            incidents=_sanitize(incidents, "incidents", redactions, string_limit, nested_limit, omitted),
            completeness=result.get("analysis", {}).get("completeness"),
            confidence=result.get("analysis", {}).get("confidence"),
            redactions=redactions,
            omitted_counts=omitted,
        )
        serialized = json.dumps(package.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return package, serialized

    events, findings, incidents = source_events[:max_events], source_findings[:max_findings], source_incidents[:max_incidents]
    string_limit, nested_limit = max_message_chars, max_nested_items
    package, serialized = build(events, findings, incidents, string_limit, nested_limit)
    while len(serialized.encode("utf-8")) > max_total_chars and events:
        events = events[:-1]
        package, serialized = build(events, findings, incidents, string_limit, nested_limit)
    while len(serialized.encode("utf-8")) > max_total_chars and string_limit > 32:
        string_limit = max(32, string_limit // 2)
        package, serialized = build(events, findings, incidents, string_limit, nested_limit)
    while len(serialized.encode("utf-8")) > max_total_chars and nested_limit > 1:
        nested_limit = max(1, nested_limit // 2)
        package, serialized = build(events, findings, incidents, string_limit, nested_limit)
    while len(serialized.encode("utf-8")) > max_total_chars and incidents:
        incidents = incidents[:-1]
        package, serialized = build(events, findings, incidents, string_limit, nested_limit)
    while len(serialized.encode("utf-8")) > max_total_chars and findings:
        findings = findings[:-1]
        package, serialized = build(events, findings, incidents, string_limit, nested_limit)
    if len(serialized.encode("utf-8")) > max_total_chars:
        package, serialized = build([], [], [], 1, 1)
    package.omitted_counts["characters"] = max(0, len(serialized.encode("utf-8")) - max_total_chars)
    return package
