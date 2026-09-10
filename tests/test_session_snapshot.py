import asyncio
import unittest

from core import server


class SnapshotSession:
    def basename(self):
        return "session_2026-09-10_15-51-43.log"

    def load_events(self, filename):
        self.loaded_filename = filename
        return [
            {
                "timestamp": "15:52:00",
                "symbol": "⚪",
                "level": "INFO",
                "message": "Uptime=17s, FreeRAM=1778b",
                "count": "17",
            }
        ]


class SnapshotHealth:
    def status(self):
        return {
            "connected": True,
            "reconnect_count": 2,
            "free_ram": 1778,
            "errors_recent": 0,
            "warnings_recent": 0,
            "status": "HEALTHY",
            "reason": "Normal operation",
            "findings": [
                {
                    "title": "Previous incident",
                    "status": "RESOLVED",
                }
            ],
        }


class SnapshotWebSocket:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_json(self, payload):
        self.sent.append(payload)
        raise RuntimeError("stop test endpoint")


class SessionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.original_session = server.session
        self.original_health = server.health
        self.original_clients = server.connected_clients
        server.session = SnapshotSession()
        server.health = SnapshotHealth()
        server.connected_clients = []

    def tearDown(self):
        server.session = self.original_session
        server.health = self.original_health
        server.connected_clients = self.original_clients

    def test_snapshot_contains_current_session_metadata_events_health_and_findings(self):
        snapshot = server.build_session_snapshot()
        data = snapshot["data"]

        self.assertEqual(snapshot["type"], "session_snapshot")
        self.assertEqual(data["session"]["filename"], "session_2026-09-10_15-51-43.log")
        self.assertEqual(data["session"]["started_at"], "2026-09-10T15:51:43")
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["health"]["status"], "HEALTHY")
        self.assertEqual(data["findings"][0]["status"], "RESOLVED")

    def test_websocket_sends_snapshot_without_creating_a_session(self):
        websocket = SnapshotWebSocket()
        asyncio.run(server.websocket_endpoint(websocket))

        self.assertEqual(len(websocket.sent), 1)
        self.assertEqual(websocket.sent[0]["type"], "session_snapshot")
        self.assertEqual(server.session.basename(), "session_2026-09-10_15-51-43.log")

    def test_repeated_snapshot_builds_use_the_same_current_session(self):
        first = server.build_session_snapshot()
        second = server.build_session_snapshot()

        self.assertEqual(
            first["data"]["session"]["filename"],
            second["data"]["session"]["filename"],
        )
        self.assertEqual(first["data"]["events"], second["data"]["events"])

    def test_back_to_live_endpoint_returns_current_session_snapshot(self):
        snapshot = asyncio.run(server.current_session_snapshot())
        self.assertEqual(snapshot["type"], "session_snapshot")
        self.assertEqual(
            snapshot["data"]["session"]["filename"],
            "session_2026-09-10_15-51-43.log",
        )


if __name__ == "__main__":
    unittest.main()
