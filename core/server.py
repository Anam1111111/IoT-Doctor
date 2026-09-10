import asyncio
import os
import serial
from datetime import datetime
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

from core.config.profile_loader import ProfileLoader
from core.diagnostics import DiagnosticEngine
from core.health.monitor import HealthMonitor
from core.metrics import MetricExtractor
from core.normalization.normalizer import EventNormalizer
from core.transport.serial_transport import SerialTransport
from core.parser.regex_parser import RegexParser
from core.storage.session import SessionStore

app = FastAPI()
connected_clients = []
broadcast_lock = asyncio.Lock()
health = HealthMonitor()
replay_active = False
connection_state = "DISCONNECTED"
disconnect_incidents = 0
reconnect_attempts = 0

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
profile_loader = ProfileLoader(BASE_DIR)
profile = profile_loader.load(os.environ.get("IOT_PROFILE"))

parser = RegexParser(profile["log_pattern"])
transport = SerialTransport(profile["port"], profile["baud_rate"])
session = SessionStore(BASE_DIR)
normalizer = EventNormalizer(
    device_id=profile.get("device_id", profile.get("name")),
    level_symbols=profile.get("level_symbols"),
    log_file=session.basename(),
)
metric_extractor = MetricExtractor(profile.get("metrics"))
diagnostics = DiagnosticEngine()

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

def build_session_snapshot():
    filename = session.basename()
    session_name = os.path.splitext(filename)[0].removeprefix("session_")
    try:
        started_at = datetime.strptime(
            session_name, "%Y-%m-%d_%H-%M-%S"
        ).isoformat()
    except ValueError:
        started_at = None
    health_data = health.status()
    return {
        "type": "session_snapshot",
        "data": {
            "session": {
                "filename": filename,
                "started_at": started_at,
            },
            "events": session.load_events(filename),
            "health": health_data,
            "findings": health_data.get("findings", []),
        },
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        async with broadcast_lock:
            await websocket.send_json(build_session_snapshot())
        while True:
            await asyncio.sleep(1)
    except:
        connected_clients.remove(websocket)

async def broadcast(event):
    async with broadcast_lock:
        for client in connected_clients:
            try:
                await client.send_json(event)
            except:
                pass

async def handle_transport_failure(error):
    global connection_state, disconnect_incidents
    print(f"Serial transport failure: {error}")
    transport.close()
    if connection_state not in {"CONNECTED", "RECOVERING"}:
        connection_state = "RECONNECTING"
        health.set_connection_metrics(
            connection_state=connection_state,
            disconnect_incidents=disconnect_incidents,
            reconnect_attempts=reconnect_attempts,
        )
        return

    disconnect_incidents += 1
    connection_state = "RECONNECTING"
    disconnected_event = normalizer.normalize(
        {"level": "ERROR", "message": "Device disconnected - retrying...", "count": "-"},
        transport_metadata=transport.metadata(),
        event_type="connection",
    )
    disconnected_event["symbol"] = "🔴"
    findings = diagnostics.process(disconnected_event)
    await broadcast(disconnected_event)
    health.update(
        disconnected_event,
        findings=diagnostics.all_findings(),
        connection_state=connection_state,
        disconnect_incidents=disconnect_incidents,
        reconnect_attempts=reconnect_attempts,
    )
    await broadcast({"type": "health", "data": health.status()})
    for finding in findings:
        await broadcast({"type": "finding", "data": finding.to_dict()})

def record_reconnect_attempt(error):
    global reconnect_attempts, connection_state
    reconnect_attempts += 1
    connection_state = "RECONNECTING"
    health.set_connection_metrics(
        connection_state=connection_state,
        disconnect_incidents=disconnect_incidents,
        reconnect_attempts=reconnect_attempts,
    )
    print(f"Reconnect attempt {reconnect_attempts} failed: {error}")

def process_serial_data(raw_data):
    parsed = parser.parse(raw_data)
    event = normalizer.normalize(
        parsed,
        raw=raw_data,
        transport_metadata=transport.metadata(),
    )
    metrics = metric_extractor.extract(event)
    findings = diagnostics.process(event, metrics)
    session.save(event)
    return event, metrics, findings

async def read_loop():
    global connection_state, reconnect_attempts
    while True:
        reconnecting = connection_state == "RECONNECTING"
        try:
            transport.connect()
            print(f"Connected to {profile['port']}")
        except (serial.SerialException, OSError) as error:
            if reconnecting:
                record_reconnect_attempt(error)
            await asyncio.sleep(2)
            continue

        connection_state = "RECOVERING" if reconnecting else "CONNECTED"
        connected_event = normalizer.normalize(
            {"level": "INFO", "message": "Device connected", "count": "-"},
            transport_metadata=transport.metadata(),
            event_type="connection",
        )
        connected_event["symbol"] = "🟢"
        diagnostics.process(connected_event)
        await broadcast(connected_event)
        health.update(
            connected_event,
            findings=diagnostics.all_findings(),
            connection_state=connection_state,
            disconnect_incidents=disconnect_incidents,
            reconnect_attempts=reconnect_attempts,
        )
        await broadcast({"type": "health", "data": health.status()})

        while True:
            try:
                raw_data = transport.receive()
            except (serial.SerialException, OSError) as error:
                await handle_transport_failure(error)
                break

            if raw_data is None or raw_data == "" or replay_active:
                await asyncio.sleep(0.01)
                continue

            try:
                event, metrics, findings = process_serial_data(raw_data)
                if connection_state == "RECOVERING" and not diagnostics.active_findings():
                    connection_state = "CONNECTED"
                health.update(
                    event,
                    metrics=metrics,
                    findings=diagnostics.all_findings(),
                    connection_state=connection_state,
                    disconnect_incidents=disconnect_incidents,
                    reconnect_attempts=reconnect_attempts,
                )
                await broadcast(event)
                for finding in findings:
                    await broadcast({"type": "finding", "data": finding.to_dict()})
                await broadcast({"type": "health", "data": health.status()})
            except Exception as error:
                print(f"Error processing serial data: {error}")
                continue

            await asyncio.sleep(0.01)

        await asyncio.sleep(2)

@app.on_event("startup")
async def startup_event():
    session_event = normalizer.normalize(
        {"level": "INFO", "message": "Session started", "count": "-"},
        transport_metadata=transport.metadata(),
        event_type="session",
    )
    session_event["symbol"] = "🟢"
    await broadcast(session_event)
    asyncio.create_task(read_loop())
