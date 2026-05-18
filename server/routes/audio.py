from fastapi import APIRouter, Request
import os
import json
from datetime import datetime

from server.services.buffer import buffer_manager
from server.services.audio_converter import convert_i2s32_to_pcm16_wav
from server.services.stt import transcribe_audio_file_async
from server.ws.manager import manager

router = APIRouter()

STORAGE_DIR = os.path.join(os.path.dirname(__file__), '..', 'storage')
os.makedirs(STORAGE_DIR, exist_ok=True)


@router.post("/audio")
async def receive_audio(request: Request) -> dict:
    device_id = request.headers.get("device-id", "unknown")
    session_id = request.headers.get("session-id", "unknown")
    end = request.headers.get("end", "false").lower() == "true"

    body = await request.body()
    session = buffer_manager.add_chunk(device_id, session_id, body)

    manager_log = {
        "event": "chunk_received",
        "device_id": device_id,
        "session_id": session_id,
        "bytes": len(body),
        "chunk_count": len(session.chunks),
        "time": datetime.utcnow().isoformat() + 'Z'
    }
    print(json.dumps(manager_log))

    await manager.broadcast(
        {
            "type": "status",
            "message": f"Audio recibido de {device_id} ({len(body)} bytes)",
        }
    )

    response = {
        "status": "ok",
        "device_id": device_id,
        "session_id": session_id,
        "chunk_count": len(session.chunks),
    }

    if end:
        audio_bytes = buffer_manager.finalize_session(device_id, session_id)

        # DEBUG: Ver cuántos bytes se acumularon
        print(json.dumps({
            "event": "session_finalized",
            "device_id": device_id,
            "session_id": session_id,
            "total_bytes": len(audio_bytes),
            "total_samples_32bit": len(audio_bytes) // 4
        }))

        # Convertir 32-bit I2S a PCM16 WAV
        wav_bytes = convert_i2s32_to_pcm16_wav(audio_bytes)

        # Guardar en disco como WAV
        filename = f"{device_id}_{session_id}_{int(datetime.utcnow().timestamp())}.wav"
        filepath = os.path.join(STORAGE_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(wav_bytes)

        print(json.dumps({
            "event": "wav_saved",
            "filename": filename,
            "wav_bytes": len(wav_bytes),
            "raw_bytes": len(audio_bytes)
        }))

        await manager.broadcast(
            {
                "type": "status",
                "message": f"Sesión cerrada para {device_id} ({len(audio_bytes)} bytes brutos → {len(wav_bytes)} bytes WAV)",
            }
        )

        # Notificar archivo disponible
        await manager.broadcast({"type": "audio_file", "url": f"/files/{filename}", "device_id": device_id, "session_id": session_id})

        transcription = await transcribe_audio_file_async(filepath)
        response["transcription"] = transcription

        text = (transcription.get("text") or "").strip()
        if text:
            await manager.broadcast({
                "type": "transcription",
                "text": text,
                "device_id": device_id,
                "session_id": session_id,
                "file": f"/files/{filename}"
            })

        response["finalized"] = True
        response["audio_bytes"] = len(audio_bytes)
        response["file"] = f"/files/{filename}"
    else:
        response["finalized"] = False

    return response
