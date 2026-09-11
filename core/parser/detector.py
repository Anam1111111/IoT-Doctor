import re
from typing import List, Tuple


def detect_format(line: str) -> List[Tuple[str, float]]:
    """Return list of (format_name, confidence) candidates."""
    candidates = []
    s = line.strip()
    # JSON Lines
    if s.startswith('{') and s.endswith('}'):
        candidates.append(("jsonl", 0.9))
    # Logcat signature: MM-DD HH:MM:SS.mmm  PID  TID L tag: msg
    if re.match(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3}\s+\d+\s+\d+\s+[VDIWEF]\s+[^:]+:\s+", s):
        candidates.append(("logcat", 0.95))
    # bracketed [LEVEL] pattern
    if re.match(r"^\[\w+\]\s", s):
        candidates.append(("regex", 0.8))

    return sorted(candidates, key=lambda x: -x[1])
