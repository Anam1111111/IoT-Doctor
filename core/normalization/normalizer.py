from core.models.event import make_event
from core.parser.base import ParseResult
from core.parser.source_classifier import classify as classify_source


class EventNormalizer:
    """Convert parser output and transport metadata into normalized events."""

    def __init__(self, device_id=None, level_symbols=None, log_file=None):
        self.device_id = device_id
        self.level_symbols = level_symbols or {}
        self.log_file = log_file

    def normalize(
        self,
        parsed_data=None,
        raw=None,
        transport_metadata=None,
        event_type="log",
    ):
        # Accept either legacy dict or new ParseResult
        if isinstance(parsed_data, ParseResult):
            pdata = parsed_data.fields or {}
            # preserve parse metadata
            parse_format = parsed_data.format
            parse_confidence = parsed_data.confidence
            raw_lines = parsed_data.raw_lines
            is_multiline = parsed_data.is_multiline
        else:
            pdata = parsed_data or {}
            parse_format = None
            parse_confidence = None
            raw_lines = None
            is_multiline = False
        parsed_data = pdata
        transport_metadata = dict(transport_metadata or {})
        # Normalize level to canonical set: INFO, WARN, ERROR, UNKNOWN
        raw_level = (parsed_data.get("level") or "").strip()
        lvl = raw_level.upper()
        if lvl in ("INFO", "INFORMATION"):
            level = "INFO"
        elif lvl in ("WARN", "WARNING"):
            level = "WARN"
        elif lvl in ("ERROR", "ERR"):
            level = "ERROR"
        elif raw_level == "":
            level = None
        else:
            level = "UNKNOWN"
        message = parsed_data.get("message")
        if message is None:
            message = raw if isinstance(raw, str) else str(raw or "")
        # If parser provided a timestamp field, pass it through via metadata
        meta = dict(transport_metadata or {})
        if parsed_data.get("timestamp"):
            meta["parsed_timestamp"] = parsed_data.get("timestamp")
            meta["timestamp_original"] = parsed_data.get("timestamp")
            meta["timestamp_kind"] = "absolute"
            meta["timestamp_confidence"] = 1.0
        else:
            meta["timestamp_kind"] = "unknown"
            meta["timestamp_confidence"] = 0.0

        # attach parser metadata
        if parse_format:
            meta["parse_format"] = parse_format
        if parse_confidence is not None:
            meta["parse_confidence"] = parse_confidence
        if raw_lines:
            meta["raw_lines"] = raw_lines
        # source classification (conservative)
        source_tag = parsed_data.get("tag") if isinstance(parsed_data, dict) else None
        package = parsed_data.get("package") if isinstance(parsed_data, dict) else None
        src_class = classify_source(source_tag, package, message or "", parse_format=parse_format)
        meta["source_class"] = src_class
        meta["source_confidence"] = 1.0 if src_class != "UNKNOWN" else 0.0
        meta["source_evidence"] = []

        category = (
            parsed_data.get("category")
            or parsed_data.get("component")
            or event_type
        )

        evt = make_event(
            level=level,
            message=message,
            count=parsed_data.get("count", "?"),
            port=transport_metadata.get("port"),
            log_file=self.log_file,
            symbol=self.level_symbols.get(level, "❓"),
            raw=raw,
            device_id=self.device_id,
            transport=transport_metadata.get("transport"),
            event_type=event_type,
            metadata=meta,
            category=category,
            source=transport_metadata.get("source"),
        )
        # add parse metadata/top-level fields expected by consumers
        if parse_format:
            evt["parse_format"] = parse_format
        if parse_confidence is not None:
            evt["parse_confidence"] = parse_confidence
        if meta.get("source_class"):
            evt["source_class"] = meta.get("source_class")
        # optional fields from parser
        if parsed_data.get("tag"):
            evt["tag"] = parsed_data.get("tag")
        if parsed_data.get("pid"):
            evt["pid"] = parsed_data.get("pid")
        if parsed_data.get("tid"):
            evt["tid"] = parsed_data.get("tid")
        for key, value in parsed_data.items():
            if key not in {"timestamp", "level", "message", "count", "tag", "pid", "tid", "package", "process", "component", "category"}:
                evt.setdefault("structured_fields", {})[key] = value
        return evt