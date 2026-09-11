import asyncio
import os
import re
import serial
import tempfile
from datetime import datetime
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket
from fastapi.responses import HTMLResponse

from core.config.profile_loader import ProfileLoader
from core.diagnostics import DiagnosticEngine
from core.health.monitor import HealthMonitor
from core.ingestion.file_analysis import FileAnalysisService
from core.ingestion.file_reader import FileReaderError
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
file_analysis = FileAnalysisService(parser, profile)

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

@app.post("/analyze/file")
async def analyze_file(file: UploadFile = File(...)):
    filename = file.filename or ""
    if os.path.splitext(filename)[1].lower() not in {".log", ".txt"}:
        await file.close()
        raise HTTPException(status_code=415, detail="Only .log and .txt files are supported")

    temp_path = None
    total_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as temp_file:
            temp_path = temp_file.name
            while chunk := await file.read(64 * 1024):
                total_bytes += len(chunk)
                if total_bytes > file_analysis.max_bytes:
                    raise HTTPException(status_code=413, detail="Input file exceeds the maximum allowed size")
                temp_file.write(chunk)
        return file_analysis.analyze(
            temp_path,
            metadata={"source_filename": filename},
        )
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="Input file is not valid UTF-8") from error
    except FileReaderError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

@app.post("/replay/{filename}")
async def replay_session(filename: str, speed: float = 1.0):
    if replay_active:
        return {"status": "already replaying, ignored"}
    try:
        events = session.load_events(filename)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error
    replay_state = build_replay_state(filename, events)
    asyncio.create_task(run_replay(events, speed, filename, replay_state))
    return {"status": "replay started", "filename": filename, "event_count": len(events)}

def build_replay_state(filename, events):
    # Use an isolated diagnostic engine in historical mode so we do not
    # mutate or borrow live findings when analyzing a stored session.
    replay_diagnostics = DiagnosticEngine(historical_mode=True)
    replay_health = HealthMonitor()
    replay_metrics = []
    replay_events = []
    has_connection_evidence = False
    for stored_event in events:
        event = dict(stored_event)
        message = event.get("message", "")
        if message == "Device connected" or "disconnected" in message.lower():
            event["event_type"] = "connection"
            has_connection_evidence = True
        event_metrics = metric_extractor.extract(event)
        replay_metrics.extend(event_metrics)
        replay_events.append(event)
        replay_diagnostics.process(event, event_metrics)
        replay_health.update(
            event,
            metrics=event_metrics,
            findings=replay_diagnostics.all_findings(),
            connection_state="CONNECTED" if has_connection_evidence else None,
        )

    if not has_connection_evidence:
        replay_health.connected = False
        replay_health.connection_state = "UNKNOWN"
    # Compute deterministic historical summary counts from the persisted events
    # Do NOT rely on HealthMonitor live counters (reconnect_attempts, etc.).
    info_count = sum(1 for e in events if (e.get("level") or "INFO") == "INFO")
    warn_count = sum(1 for e in events if (e.get("level") or "INFO") == "WARN")
    error_count = sum(1 for e in events if (e.get("level") or "INFO") == "ERROR")
    total_count = len(events)
    # disconnect incidents: count events that contain 'disconnected' in the message
    disconnect_incidents = sum(1 for e in events if "disconnected" in (e.get("message") or "").lower())
    # reconnect attempts: count informational events that look like reconnect attempt messages
    reconnect_attempts = sum(1 for e in events if (e.get("level") == "INFO") and re.match(r"Reconnect attempt \d+ failed", (e.get("message") or "")))

    health_data = replay_health.status()
    # Override connection metrics with historical values derived only from the stored events
    health_data["errors_recent"] = error_count
    health_data["warnings_recent"] = warn_count
    health_data["reconnect_count"] = reconnect_attempts
    health_data["disconnect_incidents"] = disconnect_incidents
    health_data["reconnect_attempts"] = reconnect_attempts
    # Total events is useful for the UI
    health_data["events_total"] = total_count
    if not has_connection_evidence:
        health_data["connection_state"] = "UNKNOWN"
        health_data["status"] = "UNKNOWN"
        health_data["reason"] = "Historical connection state unavailable"
    # Try to infer the session start from the first event timestamp if present
    started_at = None
    if events:
        first_ts = events[0].get("timestamp")
        if first_ts:
            started_at = first_ts
    return {
        "session": {"filename": filename, "started_at": started_at},
        "events": replay_events,
        "health": health_data,
        "findings": [finding.to_dict() for finding in replay_diagnostics.all_findings()],
        "metrics": [metric.to_dict() for metric in replay_metrics],
    }

async def run_replay(events, speed, filename, replay_state=None):
    global replay_active
    replay_active = True
    try:
        # Broadcast a single replay_start, then send an explicit
        # replay_snapshot message containing the full historical state
        # so the UI can load events in one shot.
        # Ensure the start message includes the full state (for backward
        # compatibility with clients/tests that expect state.session.filename).
        state = replay_state or build_replay_state(filename, events)
        await broadcast({
            "type": "replay_start",
            "filename": filename,
            "count": len(events),
            "state": state,
        })

        # Also send an explicit snapshot message; UI may prefer this
        # dedicated message type to load events in one shot.
        await broadcast({
            "type": "replay_snapshot",
            "data": state,
        })
        # Immediately signal completion: the UI should remain in REPLAY MODE
        # until the user clicks Back to Live.
        await broadcast({"type": "replay_end", "filename": filename})
    finally:
        replay_active = False

def build_session_snapshot():
    filename = session.basename()
    session_name = os.path.splitext(filename)[0].removeprefix("session_")
    try:
        timestamp_match = re.fullmatch(
            r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:-\d+)?",
            session_name,
        )
        started_at = datetime.strptime(
            timestamp_match.group(1) if timestamp_match else session_name,
            "%Y-%m-%d_%H-%M-%S",
        ).isoformat()
    except ValueError:
        started_at = None
    health_data = health.status()
    # Build incidents from diagnostics historical findings
    incidents = [
        {
            "category": f.category,
            "title": f.title,
            "severity": f.severity,
            "evidence": f.evidence,
            "status": getattr(f, "status", "INCIDENT"),
        }
        for f in diagnostics.historical_findings()
    ]

    # health_explanation for live snapshot when HEALTHY but warnings observed
    health_explanation = None
    if health_data.get("status") == "HEALTHY" and incidents:
        warning_count = sum(1 for i in incidents if i.get("severity") in ("WARNING", "CRITICAL"))
        health_explanation = (
            f"{warning_count} warning(s) observed during live session. The conditions recovered and no persistent failure pattern was detected."
        )

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
            "incidents": incidents,
            "health_explanation": health_explanation,
        },
    }

@app.get("/session/snapshot")
async def current_session_snapshot():
    return build_session_snapshot()

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
    """Broadcast to connected clients. Persist any user-visible event
    that has not yet been saved so there is no path that shows an
    event to the UI without it being stored.
    """
    # If this looks like a live user-visible event and hasn't been
    # persisted yet, persist it exactly once before broadcasting.
    try:
        is_dict = isinstance(event, dict)
        looks_like_event = is_dict and event.get("message") is not None and event.get("id") is not None
        already_persisted = is_dict and event.get("_persisted")
        if looks_like_event and not already_persisted and session.filename:
            # Persist once and mark so subsequent broadcasts skip saving.
            session.save(event)
            if is_dict:
                event["_persisted"] = True
    except Exception:
        # Never let persistence issues break broadcasting.
        pass

    async with broadcast_lock:
        for client in connected_clients:
            try:
                await client.send_json(event)
            except:
                pass

async def publish_live_event(event):
    """Persist a live event before making it visible to connected clients."""
    # Ensure event has required fields and no None values that become JSON null
    evt = dict(event)
    evt.setdefault("id", evt.get("id") or None)
    evt["timestamp"] = evt.get("timestamp") or ""
    if evt.get("level") is None:
        evt["level"] = "UNKNOWN"
    evt["message"] = evt.get("message") or ""
    evt["count"] = evt.get("count") or "-"
    evt["symbol"] = evt.get("symbol") or "❓"
    # Persist if a live session file exists. Mark the event so other
    # callers do not persist a duplicate when broadcast() also enforces
    # persistence for safety.
    if session.filename:
        session.save(evt)
        evt["_persisted"] = True
    await broadcast(evt)

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
    await publish_live_event(disconnected_event)
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
    return normalizer.normalize(
        {
            "level": "INFO",
            "message": f"Reconnect attempt {reconnect_attempts} failed - retrying...",
            "count": str(reconnect_attempts),
        },
        transport_metadata=transport.metadata(),
        event_type="connection",
    )

def process_serial_data(raw_data):
    parsed = parser.parse(raw_data)
    event = normalizer.normalize(
        parsed,
        raw=raw_data,
        transport_metadata=transport.metadata(),
    )
    metrics = metric_extractor.extract(event)
    findings = diagnostics.process(event, metrics)
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
                retry_event = record_reconnect_attempt(error)
                await publish_live_event(retry_event)
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
        await publish_live_event(connected_event)
        health.update(
            connected_event,
            findings=diagnostics.all_findings(),
            connection_state=connection_state,
            disconnect_incidents=disconnect_incidents,
            reconnect_attempts=reconnect_attempts,
        )
        await broadcast({"type": "health", "data": health.status()})

        started_event = normalizer.normalize(
            {"level": "INFO", "message": "Device started", "count": "-"},
            transport_metadata=transport.metadata(),
            event_type="connection",
        )
        started_event["symbol"] = "🟢"
        await publish_live_event(started_event)
        health.update(
            started_event,
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

            if raw_data is None or raw_data == "":
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
                await publish_live_event(event)
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
    # Open a live session file now that the app is starting.
    session.start()

    session_event = normalizer.normalize(
        {"level": "INFO", "message": "Session started", "count": "-"},
        transport_metadata=transport.metadata(),
        event_type="session",
    )
    session_event["symbol"] = "🟢"
    await publish_live_event(session_event)
    asyncio.create_task(read_loop())
