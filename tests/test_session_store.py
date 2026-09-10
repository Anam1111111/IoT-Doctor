import os
import tempfile
import unittest
from pathlib import Path
from core.storage.session import SessionStore

class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_construct_does_not_create_file(self):
        store = SessionStore(self.base)
        # no file should be created just by constructing the store
        files = list(Path(self.base, "sessions").glob("*.log"))
        self.assertEqual(len(files), 0)

    def test_list_does_not_create_file_and_excludes_empty(self):
        store = SessionStore(self.base)
        # create an empty file that would previously be created by init
        session_dir = Path(self.base, "sessions")
        session_dir.mkdir(parents=True, exist_ok=True)
        empty = session_dir / "session_empty.log"
        empty.write_bytes(b"")
        # create a valid file with content
        valid = session_dir / "session_valid.log"
        valid.write_text("[12:00:00] SYMBOL level=INFO | message=ok | count=1\n")
        listed = store.list_sessions()
        self.assertIn(valid.name, listed)
        self.assertNotIn(empty.name, listed)

    def test_load_does_not_create_file(self):
        store = SessionStore(self.base)
        session_dir = Path(self.base, "sessions")
        session_dir.mkdir(parents=True, exist_ok=True)
        valid = session_dir / "session_valid.log"
        valid.write_text("[12:00:00] S level=INFO | message=hi | count=1\n")
        # loading should not create any additional files
        events = store.load_events(valid.name)
        files = list(session_dir.glob("*.log"))
        self.assertEqual(len(files), 1)
        self.assertEqual(events[0]["message"], "hi")

    def test_start_creates_live_session_and_save_works(self):
        store = SessionStore(self.base)
        store.start()
        self.assertIsNotNone(store.filename)
        # save an event
        store.save({"timestamp": "12:00:01", "symbol": "S", "level": "INFO", "message": "hello", "count": "1"})
        self.assertTrue(os.path.getsize(store.filename) > 0)
        # listing should include the new file
        names = store.list_sessions()
        self.assertIn(os.path.basename(store.filename), names)

if __name__ == "__main__":
    unittest.main()
