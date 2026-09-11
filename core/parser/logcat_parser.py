import re
from core.parser.base import Parser, ParseResult
from datetime import datetime


LOGCAT_RE = re.compile(r"^(?P<month>\d{2})-(?P<day>\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2}\.\d{3})\s+(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<level>[VDIWEF])\s+(?P<tag>[^:]+):\s*(?P<message>.*)$")


class LogcatParser(Parser):
    def parse(self, raw_lines):
        # Backwards-compat: if called with a single string, return legacy dict
        if isinstance(raw_lines, str):
            line = raw_lines
            called_with_str = True
        else:
            line = raw_lines[0] if isinstance(raw_lines, list) else raw_lines
            called_with_str = False
        m = LOGCAT_RE.match(line.strip())
        if not m:
            # low confidence unstructured
            result = ParseResult(fields={"message": line}, raw_lines=[line], format="logcat", confidence=0.1, is_multiline=False)
            return result.fields if called_with_str else result

        g = m.groupdict()
        # Build a conservative timestamp using current year
        year = datetime.now().year
        ts_str = f"{year}-{g['month']}-{g['day']} {g['time']}"
        try:
            parsed_ts = datetime.fromisoformat(ts_str)
            ts = parsed_ts.isoformat()
            confidence = 0.95
        except Exception:
            ts = None
            confidence = 0.8

        level_map = {"V": "DEBUG", "D": "DEBUG", "I": "INFO", "W": "WARN", "E": "ERROR", "F": "ERROR"}

        fields = {
            "timestamp": ts,
            "pid": int(g["pid"]),
            "tid": int(g["tid"]),
            "level": level_map.get(g["level"], "INFO"),
            "tag": g["tag"].strip(),
            "message": g["message"].strip(),
        }

        result = ParseResult(fields=fields, raw_lines=[line], format="logcat", confidence=confidence, is_multiline=False)
        return result.fields if called_with_str else result
