import yaml
import asyncio
import os
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from core.health.monitor import HealthMonitor

from core.transport.serial_transport import SerialTransport
from core.parser.regex_parser import RegexParser
from core.models.event import make_event
from core.storage.session import SessionStore
from core.health.monitor import HealthMonitor

app = FastAPI()
connected_clients = []
health = HealthMonitor()
replay_active = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE_DIR, "profiles", "arduino_uno.yaml"), "r") as f:
    profile = yaml.safe_load(f)

symbols = profile["level_symbols"]
parser = RegexParser(profile["log_pattern"])
transport = SerialTransport(profile["port"], profile["baud_rate"])
session = SessionStore(BASE_DIR)

@app.get("/")
async def get_dashboard():
    with open(os.path.join(BASE_DIR, "ui", "dashboard.html"), "r") as f:
        return HTMLResponse(f.read())

@app.get("/health")
async def get_health():
    return health.status()

@app.get("/sessions")
async def list_sessions():
    return {"sessions": session.list_sessions()}

@app.post("/replay/{filename}")
async def replay_session(filename: str, speed: float = 1.0):
    if replay_active:
        return {"status": "already replaying, ignored"}
    events = session.load_events(filename)
    asyncio.create_task(run_replay(events, speed))
    return {"status": "replay started", "event_count": len(events)}

async def run_replay(events, speed):
    global replay_active
    replay_active = True
    try:
        await broadcast({"type": "replay_start", "count": len(events)})
        for event in events:
            replay_event = dict(event)
            replay_event["replay"] = True
            await broadcast(replay_event)
            await asyncio.sleep(1.0 / speed)
        await broadcast({"type": "replay_end"})
    finally:
        replay_active = False

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except:
        connected_clients.remove(websocket)

async def broadcast(event):
    for client in connected_clients:
        try:
            await client.send_json(event)
        except:
            pass

async def read_loop():
    while True:
        try:
            transport.connect()
            print(f"Connected to {profile['port']}")

            connected_event = make_event("INFO", "Device connected", "-",
                                          port=profile["port"], log_file=session.basename(),
                                          symbol="🟢")
            await broadcast(connected_event)
            health.update(connected_event)

            while True:
                line = transport.read_line()
                if not line or replay_active:
                 await asyncio.sleep(0.01)
                 continue

                parsed = parser.parse(line)
                if parsed:
                    level, message, count = parsed
                    symbol = symbols.get(level, "❓")
                else:
                    level, message, count = "?", line, "?"
                    symbol = "❓"

                event = make_event(level, message, count, port=profile["port"], symbol=symbol,
                                    raw=line, log_file=session.basename())
                session.save(event)
                health.update(event)
                await broadcast(event)
                await broadcast({"type": "health", "data": health.status()})
                await asyncio.sleep(0.01)

        except Exception as e:
            print(f"Error in read loop: {e}")
            print("Retrying in 2s...")
            disconnected_event = make_event("ERROR", "Device disconnected — retrying...", "-", symbol="🔴")
            await broadcast(disconnected_event)
            await broadcast({"type": "health", "data": health.status()})
            health.update(disconnected_event)
            await asyncio.sleep(2)

@app.on_event("startup")
async def startup_event():
    session_event = make_event("INFO", "Session started", "-", log_file=session.basename(), symbol="🟢")
    await broadcast(session_event)
    asyncio.create_task(read_loop())
