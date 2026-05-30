from __future__ import annotations

import json
import os
import asyncio
import audioop
import wave
try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except Exception:
    VOSK_AVAILABLE = False

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vosk import Model, KaldiRecognizer


_VOSK_MODEL = None


def _resolve_model_path() -> str | None:
    # Model path should be configured or placed in server/models/
    # Try the default small model path first, otherwise look for any
    # folder under server/models that looks like a vosk model.
    base_models_dir = os.path.join(os.path.dirname(__file__), '..', 'models')
    model_path = os.path.join(base_models_dir, 'vosk-model-small')

    if os.path.exists(model_path):
        return model_path

    try:
        for name in os.listdir(base_models_dir):
            candidate = os.path.join(base_models_dir, name)
            if os.path.isdir(candidate) and name.startswith('vosk-model'):
                return candidate
    except Exception:
        pass

    return None


def _get_vosk_model() -> tuple[Model | None, dict | None]:
    global _VOSK_MODEL

    if not VOSK_AVAILABLE:
      return None, {"error": "Vosk not installed"}

    if _VOSK_MODEL is not None:
        return _VOSK_MODEL, None

    model_path = _resolve_model_path()
    if not model_path:
        base_models_dir = os.path.join(os.path.dirname(__file__), '..', 'models')
        return None, {"error": f"Model not found in {base_models_dir}. Download a Vosk model and place it there (e.g. vosk-model-small-es-0.42)."}

    _VOSK_MODEL = Model(model_path)
    return _VOSK_MODEL, None


def transcribe_audio_file(path: str) -> dict:
    model, error = _get_vosk_model()
    if error:
        return error

    rec = KaldiRecognizer(model, 16000)
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        data = wf.readframes(wf.getnframes())

    if channels != 1 or sample_width != 2:
        return {
            "error": f"Unsupported WAV format: channels={channels}, sample_width={sample_width}. Expected mono 16-bit PCM.",
        }

    if sample_rate != 16000 and data:
        data, _ = audioop.ratecv(data, 2, 1, sample_rate, 16000, None)

    if rec.AcceptWaveform(data):
        res = rec.Result()
    else:
        res = rec.FinalResult()
    return json.loads(res)


async def transcribe_audio_file_async(path: str) -> dict:
    return await asyncio.to_thread(transcribe_audio_file, path)
