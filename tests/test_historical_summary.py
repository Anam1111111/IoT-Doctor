import unittest
from core import server
from core.storage.session import SessionStore

class HistoricalSummaryTests(unittest.TestCase):
    def setUp(self):
        # sample session events matching the user's report
        self.events = [
            {"timestamp":"t1","symbol":"🔴","level":"ERROR","message":"Device disconnected - retrying...","count":"-"},
            {"timestamp":"t2","symbol":"⚪","level":"INFO","message":"Reconnect attempt 1 failed - retrying...","count":"1"},
            {"timestamp":"t3","symbol":"⚪","level":"INFO","message":"Reconnect attempt 2 failed - retrying...","count":"2"},
            {"timestamp":"t4","symbol":"⚪","level":"INFO","message":"Reconnect attempt 3 failed - retrying...","count":"3"},
            {"timestamp":"t5","symbol":"⚪","level":"INFO","message":"Reconnect attempt 4 failed - retrying...","count":"4"},
            {"timestamp":"t6","symbol":"🟢","level":"INFO","message":"Device connected","count":"-"},
            {"timestamp":"t7","symbol":"🟢","level":"INFO","message":"Device started","count":"-"},
            {"timestamp":"t8","symbol":"🟢","level":"INFO","message":"Device started","count":"-"},
        ]

    def test_historical_reconnect_count_matches_persisted(self):
        state = server.build_replay_state("session_old.log", list(self.events))
        self.assertEqual(state["health"]["reconnect_attempts"], 4)
        self.assertEqual(state["health"]["reconnect_count"], 4)

    def test_historical_disconnect_count_matches_persisted(self):
        state = server.build_replay_state("session_old.log", list(self.events))
        self.assertEqual(state["health"]["disconnect_incidents"], 1)

    def test_historical_level_counts_from_session(self):
        state = server.build_replay_state("session_old.log", list(self.events))
        self.assertEqual(state["health"]["errors_recent"], 1)
        self.assertEqual(state["health"]["warnings_recent"], 0)
        self.assertEqual(state["health"]["events_total"], len(self.events))

    def test_historical_independent_of_live_state(self):
        # mutate live health and global counters
        orig_health = server.health
        try:
            server.health = type("LiveHealth", (), {"status": lambda self: {"status":"CRITICAL","findings":[]}})()
            state = server.build_replay_state("session_old.log", list(self.events))
            # still uses persisted counts
            self.assertEqual(state["health"]["reconnect_attempts"], 4)
            self.assertEqual(state["health"]["disconnect_incidents"], 1)
        finally:
            server.health = orig_health

    def test_duplicate_device_started_events_detected(self):
        # Ensure both "Device started" events are preserved in the replay events
        state = server.build_replay_state("session_old.log", list(self.events))
        started = [e for e in state["events"] if e.get("message") == "Device started"]
        self.assertEqual(len(started), 2)

    def test_live_summary_unchanged(self):
        # building replay state should not alter live health monitor counters
        orig_reconnect = server.reconnect_attempts
        orig_disconnect = server.disconnect_incidents
        _ = server.build_replay_state("session_old.log", list(self.events))
        self.assertEqual(server.reconnect_attempts, orig_reconnect)
        self.assertEqual(server.disconnect_incidents, orig_disconnect)

if __name__ == "__main__":
    unittest.main()
