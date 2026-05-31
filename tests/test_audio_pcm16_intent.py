"""
Tests de integración para verificar que el endpoint /audio/pcm16
incluye intent y mood_id en la respuesta cuando recibe audio válido.
Usa un WAV PCM16 sintético generado en memoria (sin ESP32 real).
"""
import struct
import wave
import io
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)

DEVICE_ID  = "test_device"
SESSION_ID = "test_session_001"


def _make_pcm16_bytes(duration_s: float = 1.0, sample_rate: int = 8000) -> bytes:
    """Genera silencio PCM16 mono de la duración indicada."""
    n_samples = int(sample_rate * duration_s)
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


def _post_audio(pcm_bytes: bytes, end: str = "true") -> dict:
    r = client.post(
        "/audio/pcm16",
        content=pcm_bytes,
        headers={
            "Content-Type": "application/octet-stream",
            "device-id": DEVICE_ID,
            "session-id": SESSION_ID,
            "end": end,
        },
    )
    assert r.status_code == 200
    return r.json()


@patch(
    "server.routes.audio_pcm16.transcribe_audio_file_async",
    new_callable=AsyncMock,
    return_value={"text": "duerme un rato"},
)
def test_response_includes_mood_id(mock_stt):
    pcm = _make_pcm16_bytes(1.0)
    data = _post_audio(pcm, end="true")
    assert data.get("intent") == "MOOD_SLEEPY"
    assert data.get("mood_id") == 3
    assert data.get("text") == "duerme un rato"


@patch(
    "server.routes.audio_pcm16.transcribe_audio_file_async",
    new_callable=AsyncMock,
    return_value={"text": "hola mundo"},
)
def test_unknown_intent_mood_minus_one(mock_stt):
    pcm = _make_pcm16_bytes(1.0)
    data = _post_audio(pcm, end="true")
    assert data.get("intent") == "UNKNOWN"
    assert data.get("mood_id") == -1


@patch(
    "server.routes.audio_pcm16.transcribe_audio_file_async",
    new_callable=AsyncMock,
    return_value={"text": ""},
)
def test_empty_transcription_unknown(mock_stt):
    pcm = _make_pcm16_bytes(1.0)
    data = _post_audio(pcm, end="true")
    assert data.get("intent") == "UNKNOWN"
    assert data.get("mood_id") == -1
