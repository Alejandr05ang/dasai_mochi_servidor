import sys
import asyncio
import logging
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from routes.audio import router as audio_router
from routes.audio_pcm16 import router as audio_pcm16_router
from routes.transcribe import router as transcribe_router
from ws.manager import manager
from services.buffer import buffer_manager


LOG = logging.getLogger("voiceiot")
LOG.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
LOG.addHandler(handler)


app = FastAPI(title="Voice IoT Monitor")
app.include_router(audio_router)
app.include_router(audio_pcm16_router)
app.include_router(transcribe_router)

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

ENABLE_MOCK_EVENTS = os.getenv("ENABLE_MOCK_EVENTS", "false").lower() == "true"


@app.on_event("startup")
async def startup_event() -> None:
    LOG.info(json.dumps({"event": "startup"}))
    if ENABLE_MOCK_EVENTS:
        asyncio.create_task(mock_broadcaster())
    asyncio.create_task(periodic_maintenance())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
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
