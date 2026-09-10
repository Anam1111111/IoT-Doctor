import os
import re
from datetime import datetime

class SessionStore:
    def __init__(self, base_dir):
        self.sessions_dir = os.path.join(base_dir, "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)

        self.filename = os.path.join(
            self.sessions_dir,
            datetime.now().strftime("session_%Y-%m-%d_%H-%M-%S.log")
        )
        self.file = open(self.filename, "a")

    def basename(self):
        return os.path.basename(self.filename)

    def save(self, event):
        line = f"[{event['timestamp']}] {event['symbol']} level={event['level']} | message={event['message']} | count={event['count']}\n"
        self.file.write(line)
        self.file.flush()

    def list_sessions(self):
        files = [f for f in os.listdir(self.sessions_dir) if f.endswith(".log")]
        return sorted(files, reverse=True)

    def load_events(self, filename):
        """
        Reads a saved session file back into a list of event dicts,
        so it can be replayed through the same dashboard pipeline.
        """
        path = os.path.join(self.sessions_dir, filename)
        pattern = r'\[(?P<timestamp>[\d:]+)\]\s(?P<symbol>\S+)\slevel=(?P<level>\w+)\s\|\smessage=(?P<message>.+)\s\|\scount=(?P<count>\S+)'

        events = []
        with open(path, "r") as f:
            for line in f:
                match = re.match(pattern, line.strip())
                if match:
                    events.append({
                        "timestamp": match.group("timestamp"),
                        "symbol": match.group("symbol"),
                        "level": match.group("level"),
                        "message": match.group("message"),
                        "count": match.group("count"),
                    })
        return events
