import os
import re
from datetime import datetime

class SessionStore:
    def __init__(self, base_dir):
        self.sessions_dir = os.path.join(base_dir, "sessions")
        self.filename = None
        self.file = None

    def start(self):
        """
        Create and open a live session file. This is a deliberate side
        effect invoked when a live run actually begins (e.g. on
        application startup / transport connect). Listing or loading
        historical sessions should not call this.
        """
        if self.file:
            return
        os.makedirs(self.sessions_dir, exist_ok=True)
        stem = datetime.now().strftime("session_%Y-%m-%d_%H-%M-%S")
        for suffix in ("", *[f"-{index}" for index in range(1, 1000)]):
            filename = os.path.join(self.sessions_dir, f"{stem}{suffix}.log")
            try:
                self.file = open(filename, "x")
                self.filename = filename
                return
            except FileExistsError:
                continue
        raise RuntimeError("Unable to create a unique session file")

    def basename(self):
        return os.path.basename(self.filename) if self.filename else ""

    def save(self, event):
        if not self.file:
            raise RuntimeError("Session has not been started")
        # Use safe lookups to avoid KeyErrors if callers omit fields
        ts = event.get("timestamp", "")
        sym = event.get("symbol", "")
        lvl = event.get("level", "UNKNOWN")
        msg = event.get("message", "")
        cnt = event.get("count", "-")
        line = f"[{ts}] {sym} level={lvl} | message={msg} | count={cnt}\n"
        self.file.write(line)
        self.file.flush()

    def list_sessions(self):
        if not os.path.isdir(self.sessions_dir):
            return []
        files = []
        for f in os.listdir(self.sessions_dir):
            if not f.endswith(".log"):
                continue
            path = os.path.join(self.sessions_dir, f)
            try:
                if os.path.getsize(path) == 0:
                    # skip empty files — they are not valid historical sessions
                    continue
            except OSError:
                continue
            files.append(f)
        return sorted(files, reverse=True)

    def validate_filename(self, filename):
        if not filename or os.path.basename(filename) != filename or not filename.endswith(".log"):
            raise ValueError("Invalid session filename")
        path = os.path.join(self.sessions_dir, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(filename)
        return path

    def load_events(self, filename):
        """
        Reads a saved session file back into a list of event dicts,
        so it can be replayed through the same dashboard pipeline.
        """
        path = self.validate_filename(filename)
        events = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Parse timestamp in brackets
                if not line.startswith("["):
                    # Fallback: include raw line as message
                    events.append({
                        "timestamp": None,
                        "symbol": "",
                        "level": "INFO",
                        "message": line,
                        "count": "-",
                    })
                    continue
                try:
                    ts_end = line.index("]")
                    timestamp = line[1:ts_end]
                    rest = line[ts_end + 1 :].strip()
                except ValueError:
                    timestamp = None
                    rest = line

                # symbol is first token
                parts = rest.split(None, 1)
                symbol = parts[0] if parts else ""
                remainder = parts[1] if len(parts) > 1 else ""

                # attempt to extract count via ' | count=' delimiter from the right
                count = "-"
                message = remainder
                if "| count=" in remainder:
                    try:
                        before, count_part = remainder.rsplit("| count=", 1)
                        count = count_part.strip()
                        # remove trailing separators and labels from message
                        if "| message=" in before:
                            _, message = before.split("| message=", 1)
                        else:
                            message = before.strip()
                    except Exception:
                        message = remainder

                message = message.strip()

                events.append({
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "level": (re.match(r"level=(\w+)", remainder) and re.match(r"level=(\w+)", remainder).group(1)) if "level=" in remainder else ("INFO" if symbol else "INFO"),
                    "message": message,
                    "count": count,
                })
        return events
