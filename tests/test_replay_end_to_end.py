import os
from core.storage.session import SessionStore
from core.server import build_replay_state


def write_session_file(tmp_path, lines, name="session_test.log"):
    sessions_dir = tmp_path
    os.makedirs(sessions_dir, exist_ok=True)
    path = os.path.join(sessions_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        for l in lines:
            f.write(l + "\n")
    return path


def test_load_and_build_replay_state(tmp_path, monkeypatch):
    # Create a fake base dir with a sessions/ subdirectory and a sample session file
    base_dir = str(tmp_path)
    sessions_dir = os.path.join(base_dir, "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    monkeypatch.setenv("BASE_DIR", base_dir)
    store = SessionStore(base_dir)

    lines = [
        "[2026-01-01T00:00:00Z] 🟢 level=INFO | message=Device connected | count=-",
        "[2026-01-01T00:00:01Z] 🔍 level=INFO | message=Some info | count=1",
        "[2026-01-01T00:00:02Z] ⚠️ level=WARN | message=Warning occurred | count=2",
    ]

    path = write_session_file(sessions_dir, lines, name="session_sample.log")

    # Ensure list_sessions sees the file
    listed = store.list_sessions()
    assert "session_sample.log" in listed

    events = store.load_events("session_sample.log")
    assert len(events) == 3
    assert events[0]["message"].startswith("Device connected")

    # build_replay_state should accept the filename and events
    replay = build_replay_state("session_sample.log", events)
    assert replay["session"]["filename"] == "session_sample.log"
    assert replay["events"] and len(replay["events"]) == 3
    assert replay["health"]["events_total"] == 3
