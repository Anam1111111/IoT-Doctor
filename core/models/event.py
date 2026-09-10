from datetime import datetime



def make_event(level, message, count, port=None, log_file=None, symbol=None, raw=None):
    """
    Builds a normalized event dict. Every transport and parser
    produces data in this same shape, so the rest of the app
    (dashboard, session storage) never needs to know where the
    data came from.
    """
    event = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": message,
        "count": count,
        "symbol": symbol or "❓",
    }
    if port:
        event["port"] = port
    if log_file:
        event["log_file"] = log_file
    if raw:
        event["raw"] = raw
    return event


