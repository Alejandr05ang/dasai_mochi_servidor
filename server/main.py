import sys
import asyncio
import logging
import os
import json
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from routes.audio import router as audio_router
from routes.audio_pcm16 import router as audio_pcm16_router
from routes.transcribe import router as transcribe_router
from routes.canvas import router as canvas_router
from ws.manager import manager
from services.buffer import buffer_manager
from services.stt import download_model_if_missing


LOG = logging.getLogger("voiceiot")
LOG.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
LOG.addHandler(handler)


app = FastAPI(title="Voice IoT Monitor")
app.include_router(audio_router)
app.include_router(audio_pcm16_router)
app.include_router(transcribe_router)
app.include_router(canvas_router)

# CORS para permitir que la web estática en otro puerto llame a la API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SAVE_AUDIO = os.getenv("SAVE_AUDIO", "false").lower() == "true"
if SAVE_AUDIO:
    FILES_DIR = os.path.join(os.path.dirname(__file__), 'storage')
    os.makedirs(FILES_DIR, exist_ok=True)
    LOG.info(json.dumps({"event": "files_dir", "path": FILES_DIR}))
    app.mount("/files", StaticFiles(directory=FILES_DIR), name="files")

# Carpeta web — debe definirse antes del startup pero el mount va al final
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')

ENABLE_MOCK_EVENTS = os.getenv("ENABLE_MOCK_EVENTS", "false").lower() == "true"


@app.on_event("startup")
async def startup_event() -> None:
    LOG.info(json.dumps({"event": "startup"}))
    await asyncio.to_thread(download_model_if_missing)
    if ENABLE_MOCK_EVENTS:
        asyncio.create_task(mock_broadcaster())
    asyncio.create_task(periodic_maintenance())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, device_id: Optional[str] = None) -> None:
    await manager.connect(websocket, device_id)
    if device_id:
        await manager.broadcast({"type": "device_connected", "device_id": device_id})
        await manager.broadcast({"type": "devices", "list": manager.connected_devices()})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        disconnected_id = manager.disconnect(websocket)
        if disconnected_id:
            await manager.broadcast({"type": "device_disconnected", "device_id": disconnected_id})
            await manager.broadcast({"type": "devices", "list": manager.connected_devices()})
    except Exception as e:
        print(f"WS ERROR: {e}")
        manager.disconnect(websocket)


async def mock_broadcaster() -> None:
    index = 0
    while True:
        await asyncio.sleep(3)
        if manager.active_connections:
            event = [
                {"type": "status", "message": "ESP32_01 conectado"},
                {"type": "status", "message": "Recibiendo audio..."},
                {"type": "status", "message": "Procesando..."},
                {"type": "transcription", "text": "enciende la luz"},
                {"type": "intent", "intent": "LUZ_ON"},
                {"type": "devices", "list": ["esp32_01"]},
            ][index % 6]
            await manager.broadcast(event)
        index += 1


async def periodic_maintenance() -> None:
    # Limpieza cada 30s: sesiones huérfanas y conexiones WS muertas
    while True:
        await asyncio.sleep(30)
        removed = buffer_manager.cleanup_stale_sessions(max_age_seconds=60)
        ws_removed = manager.cleanup()
        LOG.info(json.dumps({"event": "maintenance", "stale_sessions_removed": removed, "ws_removed": ws_removed}))


# ── Páginas web ─────────────────────────────────────────────────────────────
# Las rutas explícitas se registran antes del mount, por lo que tienen prioridad.

@app.get("/")
async def index_page() -> FileResponse:
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/canvas")
async def canvas_page() -> FileResponse:
    return FileResponse(os.path.join(WEB_DIR, "canvas.html"))


# Archivos estáticos (styles.css, app.js, etc.) — debe ser el último mount
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR), name="web_static")
