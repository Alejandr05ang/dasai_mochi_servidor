"""
Ruta para recibir audio PCM16 (16-bit, mono) directamente del ESP32
y guardarlo como WAV.  Si INPUT != OUTPUT se usa scipy.resample_poly.
"""
from fastapi import APIRouter, Request
from starlette.requests import ClientDisconnect
import os
import wave
import json
from datetime import datetime

import numpy as np
try:
    from scipy.signal import resample_poly as _resample_poly
    _HAVE_SCIPY = True
except ImportError:
    _HAVE_SCIPY = False

from server.ws.manager import manager
from server.services.stt import transcribe_audio_file_async

router = APIRouter()

STORAGE_DIR = os.path.join(os.path.dirname(__file__), '..', 'storage')
os.makedirs(STORAGE_DIR, exist_ok=True)

# ESP32 captura a 8 kHz; Vosk funciona mejor a 16 kHz.
# La diferencia se cubre con scipy.resample_poly.
INPUT_SAMPLE_RATE = 8000
OUTPUT_SAMPLE_RATE = 16000

# Duración mínima (segundos) para guardar y transcribir una sesión.
MIN_DURATION_S = 1.0

# Buffer temporal para acumular muestras
audio_sessions = {}


@router.post("/audio/pcm16")
async def receive_audio_pcm16(request: Request) -> dict:
    """
    Recibe audio PCM16 (16-bit, mono, 16kHz) del ESP32.
    
    Headers requeridos:
    - device-id: identificador del dispositivo
    - session-id: ID de la sesión
    - end: "true" para finalizar la sesión y guardar WAV
    
    Body:
    - Audio PCM16 binario (2 bytes por muestra)
    """
    device_id = request.headers.get("device-id", "unknown")
    session_id = request.headers.get("session-id", "unknown")
    end = request.headers.get("end", "false").lower() == "true"

    # Clave de sesión única
    session_key = f"{device_id}_{session_id}"
    
    # Obtener o crear sesión
    if session_key not in audio_sessions:
        audio_sessions[session_key] = {
            "samples": bytearray(),
            "start_time": datetime.utcnow()
        }
    
    session = audio_sessions[session_key]
    try:
        body = await request.body()
    except ClientDisconnect:
        print(json.dumps({"event": "client_disconnected", "device_id": device_id, "session_id": session_id}))
        return {"status": "disconnected", "device_id": device_id, "session_id": session_id}

    print(json.dumps({
        "event": "pcm16_request",
        "device_id": device_id,
        "session_id": session_id,
        "end": end,
        "body_bytes": len(body),
        "active_ws": len(manager.active_connections),
    }))
    
    # Agregar muestras
    session["samples"].extend(body)
    
    num_samples = len(session["samples"]) // 2  # 2 bytes por muestra
    
    manager_log = {
        "event": "pcm16_chunk_received",
        "device_id": device_id,
        "session_id": session_id,
        "bytes": len(body),
        "total_samples": num_samples,
        "total_bytes": len(session["samples"]),
        "time": datetime.utcnow().isoformat() + 'Z'
    }
    print(json.dumps(manager_log))

    await manager.broadcast({
        "type": "status",
        "message": f"Audio PCM16 recibido de {device_id} ({len(body)} bytes, {num_samples} muestras)",
    })

    response = {
        "status": "ok",
        "device_id": device_id,
        "session_id": session_id,
        "total_samples": num_samples,
        "total_bytes": len(session["samples"]),
    }

    if end:
        input_audio_bytes = bytes(session["samples"])

        # Descartar sesiones de reinicios inesperados (WAVs cortos)
        input_duration = (len(input_audio_bytes) / 2) / INPUT_SAMPLE_RATE
        if input_duration < MIN_DURATION_S:
            del audio_sessions[session_key]
            print(json.dumps({
                "event": "session_too_short",
                "device_id": device_id,
                "session_id": session_id,
                "duration_seconds": round(input_duration, 3),
                "min_required": MIN_DURATION_S,
            }))
            response["finalized"] = True
            response["skipped"] = True
            response["reason"] = f"Sesión demasiado corta ({input_duration:.2f}s < {MIN_DURATION_S}s)"
            return response

        # Resampleo con scipy si las tasas difieren; bypass si son iguales
        if INPUT_SAMPLE_RATE != OUTPUT_SAMPLE_RATE:
            from math import gcd
            g = gcd(OUTPUT_SAMPLE_RATE, INPUT_SAMPLE_RATE)
            up, down = OUTPUT_SAMPLE_RATE // g, INPUT_SAMPLE_RATE // g
            arr = np.frombuffer(input_audio_bytes, dtype=np.int16)
            if _HAVE_SCIPY:
                audio_bytes = _resample_poly(arr, up, down).astype(np.int16).tobytes()
            else:
                audio_bytes = np.repeat(arr, up).astype(np.int16).tobytes()
        else:
            audio_bytes = input_audio_bytes
        
        print(json.dumps({
            "event": "session_finalized_pcm16",
            "device_id": device_id,
            "session_id": session_id,
            "input_samples": len(input_audio_bytes) // 2,
            "input_bytes": len(input_audio_bytes),
            "output_samples": len(audio_bytes) // 2,
            "output_bytes": len(audio_bytes),
            "input_duration_seconds": (len(input_audio_bytes) / 2) / INPUT_SAMPLE_RATE,
            "output_duration_seconds": (len(audio_bytes) / 2) / OUTPUT_SAMPLE_RATE
        }))

        # Guardar WAV raw a la tasa de entrada (original sin procesar)
        raw_filename = f"{device_id}_{session_id}_{int(datetime.utcnow().timestamp())}_raw.wav"
        raw_filepath = os.path.join(STORAGE_DIR, raw_filename)
        try:
            with wave.open(raw_filepath, 'wb') as wf_raw:
                wf_raw.setnchannels(1)
                wf_raw.setsampwidth(2)
                wf_raw.setframerate(INPUT_SAMPLE_RATE)
                wf_raw.writeframes(input_audio_bytes)
        except Exception as e:
            print(json.dumps({
                "event": "error_saving_raw_wav",
                "error": str(e),
                "raw_filename": raw_filename
            }))

        # Guardar WAV resampleado (16 kHz) para reproducción y STT
        filename = f"{device_id}_{session_id}_{int(datetime.utcnow().timestamp())}.wav"
        filepath = os.path.join(STORAGE_DIR, filename)
        try:
            with wave.open(filepath, 'wb') as wf:
                wf.setnchannels(1)           # Mono
                wf.setsampwidth(2)           # 16 bits (2 bytes)
                wf.setframerate(OUTPUT_SAMPLE_RATE)       # 16 kHz para playback/STT
                wf.writeframes(audio_bytes)
            
            print(json.dumps({
                "event": "wav_saved_pcm16",
                "filename": filename,
                "wav_bytes": len(audio_bytes),
                "duration_seconds": (len(audio_bytes) / 2) / OUTPUT_SAMPLE_RATE
            }))

            await manager.broadcast({
                "type": "status",
                "message": f"Sesión cerrada para {device_id} ({len(audio_bytes)} bytes PCM16 → WAV)",
            })

            # Notificar archivo disponible
            transcription = await transcribe_audio_file_async(filepath)
            response["transcription"] = transcription

            print(json.dumps({
                "event": "pcm16_transcription_result",
                "device_id": device_id,
                "session_id": session_id,
                "file": filename,
                "transcription": transcription,
            }))

            await manager.broadcast({
                "type": "session_result",
                "device_id": device_id,
                "session_id": session_id,
                "file": f"/files/{filename}",
                "duration_seconds": (len(audio_bytes) / 2) / OUTPUT_SAMPLE_RATE,
                "transcription": transcription,
            })

            await manager.broadcast({
                "type": "audio_file",
                "url": f"/files/{filename}",
                "device_id": device_id,
                "session_id": session_id,
                "duration_seconds": (len(audio_bytes) / 2) / OUTPUT_SAMPLE_RATE
            })

            text = (transcription.get("text") or "").strip()
            if text:
                await manager.broadcast({
                    "type": "transcription",
                    "text": text,
                    "device_id": device_id,
                    "session_id": session_id,
                    "file": f"/files/{filename}"
                })
            else:
                await manager.broadcast({
                    "type": "status",
                    "message": f"Transcripción vacía para {device_id} / {session_id}",
                    "file": f"/files/{filename}",
                })

            print(json.dumps({
                "event": "pcm16_session_result_sent",
                "device_id": device_id,
                "session_id": session_id,
                "active_ws": len(manager.active_connections),
            }))

        except Exception as e:
            print(json.dumps({
                "event": "error_saving_wav",
                "error": str(e),
                "filename": filename
            }))
            response["error"] = f"Error guardando WAV: {str(e)}"

        # Limpiar sesión
        del audio_sessions[session_key]
        response["finalized"] = True
        response["file"] = f"/files/{filename}"
    else:
        response["finalized"] = False

    return response
