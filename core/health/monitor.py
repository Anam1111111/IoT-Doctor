import re

class HealthMonitor:
    """
    Watches the stream of events and derives a live health picture:
    connection state, error rate, and simple rule-based status.
    Uses only real data already flowing through the system.
    """

    def __init__(self, window_size=20):
        self.window_size = window_size
        self.recent_events = []
        self.connected = False
        self.reconnect_count = 0
        self.last_free_ram = None
        self.ram_history = []

    def update(self, event):
        self.recent_events.append(event)
        if len(self.recent_events) > self.window_size:
            self.recent_events.pop(0)

        if event["message"] == "Device connected":
            self.connected = True
        elif "disconnected" in event["message"].lower():
            self.connected = False
            self.reconnect_count += 1

        # Extract FreeRAM if present in the message, to track trend
        match = re.search(r"FreeRAM=(\d+)b", event["message"])
        if match:
            ram = int(match.group(1))
            self.last_free_ram = ram
            self.ram_history.append(ram)
            if len(self.ram_history) > 30:
                self.ram_history.pop(0)

    def status(self):
        error_count = sum(1 for e in self.recent_events if e["level"] == "ERROR")
        warn_count = sum(1 for e in self.recent_events if e["level"] == "WARN")

        # Rule-based status, not an arbitrary score
        if not self.connected:
            level = "CRITICAL"
            reason = "Device not connected"
        elif self._ram_decreasing_steadily():
            level = "WARNING"
            reason = "Free RAM decreasing continuously — possible memory leak"
        elif error_count >= 5:
            level = "WARNING"
            reason = f"{error_count} errors in last {self.window_size} events"
        else:
            level = "HEALTHY"
            reason = "Normal operation"

        return {
            "connected": self.connected,
            "reconnect_count": self.reconnect_count,
            "free_ram": self.last_free_ram,
            "errors_recent": error_count,
            "warnings_recent": warn_count,
            "status": level,
            "reason": reason,
        }

    def _ram_decreasing_steadily(self):
        if len(self.ram_history) < 10:
            return False
        # Check if the last 10 readings are strictly decreasing
        recent = self.ram_history[-10:]
        return all(recent[i] > recent[i + 1] for i in range(len(recent) - 1))
