from core.models.event import make_event


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
        parsed_data = parsed_data or {}
        transport_metadata = dict(transport_metadata or {})
        level = parsed_data.get("level", "?")
        message = parsed_data.get("message")
        if message is None:
            message = raw if isinstance(raw, str) else str(raw or "")

        return make_event(
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
            metadata=transport_metadata,
        )