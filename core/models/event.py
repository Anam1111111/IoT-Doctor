from datetime import datetime
from uuid import uuid4


def make_event(
    level,
    message,
    count="-",
    port=None,
    log_file=None,
    symbol=None,
    raw=None,
    device_id=None,
    transport=None,
    event_type="log",
    metadata=None,
    category=None,
    source=None,
):
    """
    Build the normalized event dict used by health, storage, and the UI.

    The legacy fields remain present for the current session format and
    dashboard while the new fields establish a transport-independent model.
    """
    # Determine timestamp: preserve parsed timestamp when provided.
    if metadata and metadata.get("parsed_timestamp"):
        ts = metadata.get("parsed_timestamp")
    else:
        # For file-imported events we must not invent timestamps.
        if metadata and metadata.get("transport") == "file":
            ts = ""
        else:
            ts = datetime.now().strftime("%H:%M:%S")

    event = {
        "id": str(uuid4()),
        "timestamp": ts,
        "device_id": device_id,
        "transport": transport,
        "level": level if level is not None else "UNKNOWN",
        "event_type": event_type,
        "message": message,
        "count": count,
        "symbol": symbol or "❓",
        "metadata": metadata or {},
    }
    if source:
        event["source"] = source
    if port:
        event["port"] = port
    if log_file:
        event["log_file"] = log_file
    if raw:
        # preserve raw line under both `raw` (legacy) and `raw_line` (explicit)
        event["raw"] = raw
        event["raw_line"] = raw
    if category:
        event["category"] = category
    # If a parsed timestamp was provided, preserve it exactly (do not invent)
    if metadata and metadata.get("parsed_timestamp"):
        event["timestamp"] = metadata.get("parsed_timestamp")
    return event


