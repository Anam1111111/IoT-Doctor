import asyncio
import tempfile
import unittest
from pathlib import Path

from core import server
from core.models.event import make_event
from core.storage.session import SessionStore


class SessionPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SessionStore(self.tmpdir.name)
        self.store.start()
        self.original_session = server.session
        self.original_broadcast = server.broadcast
        server.session = self.store
        self.broadcasted = []

        async def capture(event):
            self.broadcasted.append(event)

        server.broadcast = capture

    def tearDown(self):
        server.session = self.original_session
        server.broadcast = self.original_broadcast
        if self.store.file:
            self.store.file.close()
        self.tmpdir.cleanup()

    def event(self, message, level="INFO", count="-"):
        return make_event(
            level=level,
            message=message,
            count=count,
            symbol="S",
            event_type="connection" if "Device" in message or "Reconnect" in message else "log",
        )

    def publish_all(self, events):
        async def run():
            for event in events:
                await server.publish_live_event(event)

        asyncio.run(run())

    def test_complete_live_event_stream_is_persisted_once_in_order(self):
        events = [
            self.event("Uptime=1s", count="1"),
            self.event("Device disconnected - retrying...", level="ERROR"),
            self.event("Reconnect attempt 1 failed - retrying...", count="1"),
            self.event("Device connected"),
            self.event("Device started"),
            self.event("Uptime=2s", count="2"),
        ]

        self.publish_all(events)
        stored = self.store.load_events(Path(self.store.filename).name)

        self.assertEqual([event["message"] for event in self.broadcasted], [
            event["message"] for event in events
        ])
        self.assertEqual([event["message"] for event in stored], [
            event["message"] for event in events
        ])
        lines = Path(self.store.filename).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), len(events))
        # ensure disconnect message persisted
        self.assertIn("Device disconnected", "\n".join(lines))

    def test_telemetry_is_persisted_at_publish_boundary_without_duplicate_save(self):
        event = self.event("Uptime=42s", count="42")

        self.publish_all([event])
        self.store.file.flush()
        lines = Path(self.store.filename).read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        # broadcasted events may be marked with an internal `_persisted`
        # flag; compare by user-visible `message` instead.
        self.assertEqual([e["message"] for e in self.broadcasted], [event["message"]])
        stored = self.store.load_events(Path(self.store.filename).name)[0]
        self.assertIsNotNone(stored.get("level"))
        self.assertNotEqual(stored.get("level"), "null")
        self.assertEqual(stored["message"], "Uptime=42s")

    def test_new_live_session_does_not_reuse_existing_timestamped_file(self):
        second_store = SessionStore(self.tmpdir.name)
        try:
            second_store.start()
            self.assertNotEqual(self.store.filename, second_store.filename)
        finally:
            if second_store.file:
                second_store.file.close()

    def test_broadcast_call_also_persists_event(self):
        # restore real broadcast to test persistence-on-broadcast
        server.broadcast = self.original_broadcast
        ev = self.event("Broadcast persistence test")
        # call broadcast directly; it should persist the event before sending
        asyncio.run(server.broadcast(ev))
        self.store.file.flush()
        lines = open(self.store.filename, encoding="utf-8").read().splitlines()
        self.assertTrue(any("Broadcast persistence test" in l for l in lines))

    def test_no_duplicate_persistence_when_event_already_saved(self):
        ev = self.event("Dedup persistence test")
        # publish_live_event saves then marks event; broadcasting same object should not double-save
        asyncio.run(server.publish_live_event(ev))
        asyncio.run(server.broadcast(ev))
        self.store.file.flush()
        lines = open(self.store.filename, encoding="utf-8").read().splitlines()
        occurrences = sum(1 for l in lines if "Dedup persistence test" in l)
        self.assertEqual(occurrences, 1)


if __name__ == "__main__":
    unittest.main()
