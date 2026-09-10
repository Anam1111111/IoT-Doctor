import asyncio
import unittest
from pathlib import Path

from core import server
from core.storage.session import SessionStore


class ReplaySession:
    def __init__(self):
        self.loaded = []

    def load_events(self, filename):
        self.loaded.append(filename)
        return [
            {
                "timestamp": "15:00:00",
                "symbol": "⚪",
                "level": "INFO",
                "message": f"event from {filename}",
                "count": "1",
            }
        ]


class ReplayTests(unittest.TestCase):
    def test_replay_state_does_not_copy_live_findings(self):
        original_health = server.health
        original_diagnostics = server.diagnostics
        try:
            server.health = type("LiveHealth", (), {
                "status": lambda self: {
                    "status": "CRITICAL",
                    "findings": [{"title": "LIVE ONLY"}],
                }
            })()
            replay_state = server.build_replay_state(
                "session_old.log",
                [{"level": "INFO", "message": "historical", "count": "1"}],
            )
        finally:
            server.health = original_health
            server.diagnostics = original_diagnostics

        self.assertEqual(replay_state["health"]["status"], "UNKNOWN")
        self.assertEqual(replay_state["findings"], [])
        self.assertNotIn("LIVE ONLY", str(replay_state))

    def test_replay_does_not_save_events_to_current_session(self):
        messages = []
        original_broadcast = server.broadcast
        original_session = server.session

        class SessionWithoutReplayWrites:
            def save(self, event):
                messages.append(event)

        async def capture(message):
            pass

        async def run():
            server.broadcast = capture
            server.session = SessionWithoutReplayWrites()
            try:
                await server.run_replay(
                    [{"level": "INFO", "message": "historical", "count": "1"}],
                    speed=1000,
                    filename="session_old.log",
                )
            finally:
                server.broadcast = original_broadcast
                server.session = original_session

        asyncio.run(run())
        self.assertEqual(messages, [])

    def test_selected_filename_is_loaded_and_returned(self):
        session = ReplaySession()
        original_session = server.session
        original_replay_active = server.replay_active
        original_run_replay = server.run_replay
        captured = {}
        async def fake_run(events, speed, filename, replay_state):
            captured["events"] = events
            captured["speed"] = speed
            captured["filename"] = filename
            captured["state"] = replay_state
        async def run():
            server.session = session
            server.replay_active = False
            server.run_replay = fake_run
            try:
                response = await server.replay_session("session_old.log", speed=3)
            finally:
                server.session = original_session
                server.replay_active = original_replay_active
                server.run_replay = original_run_replay
            return response
        response = asyncio.run(run())
        self.assertEqual(session.loaded, ["session_old.log"])
        self.assertEqual(response["filename"], "session_old.log")
        self.assertEqual(captured["filename"], "session_old.log")
        self.assertEqual(captured["speed"], 3)
        self.assertEqual(captured["events"][0]["message"], "event from session_old.log")
        self.assertEqual(captured["state"]["session"]["filename"], "session_old.log")

    def test_replay_messages_identify_selected_filename(self):
        messages = []
        original_broadcast = server.broadcast
        async def capture(message):
            messages.append(message)
        async def run():
            server.broadcast = capture
            try:
                await server.run_replay(
                    [{"level": "INFO", "message": "historical", "count": "1"}],
                    speed=1000,
                    filename="session_old.log",
                )
            finally:
                server.broadcast = original_broadcast
        asyncio.run(run())
        self.assertEqual(messages[0]["type"], "replay_start")
        self.assertEqual(messages[0]["filename"], "session_old.log")
        self.assertEqual(messages[0]["count"], 1)
        self.assertEqual(messages[0]["state"]["session"]["filename"], "session_old.log")
        self.assertIn("health", messages[0]["state"])
        self.assertIn("findings", messages[0]["state"])
        self.assertIn("metrics", messages[0]["state"])
        self.assertEqual(messages[-1], {
            "type": "replay_end",
            "filename": "session_old.log",
        })
        # Replay no longer streams per-event messages; UI receives a single
        # `replay_start` with full state followed by `replay_end`.

    def test_session_store_rejects_traversal_and_missing_files(self):
        store = SessionStore(str(Path("tests")))
        with self.assertRaises(ValueError):
            store.validate_filename("../../outside.log")
        with self.assertRaises(FileNotFoundError):
            store.validate_filename("missing.log")

    def test_dashboard_keeps_replay_mode_until_back_to_live(self):
        html = Path("ui/dashboard.html").read_text(encoding="utf-8")
        self.assertIn('data.type === "replay_end"', html)
        self.assertIn('id="backLiveButton"', html)
        self.assertIn('async function backToLive()', html)
        self.assertIn('let restoringLive = false;', html)
        self.assertIn('pendingLiveMessages.push(data);', html)
        self.assertIn('displayedEventKeys.has(eventKey(data))', html)
        self.assertIn('if (replayMode && !data.replay)', html)
        self.assertIn('applySessionSnapshot(snapshot.data || {}, true);', html)
        self.assertIn('Historical session remains visible.', html)
        self.assertIn('document.querySelectorAll(".toolbar .filter-btn")', html)
        self.assertNotIn('document.getElementById("totalCount").textContent = "0";\n    document.getElementById("replayStatus").textContent = "Back to live view.";', html)


if __name__ == "__main__":
    unittest.main()
