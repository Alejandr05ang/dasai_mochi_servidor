from fastapi import APIRouter
from pydantic import BaseModel
import os

from server.services.stt import transcribe_audio_file
from server.services.intents import detect_intent, build_response

router = APIRouter()


class TextPayload(BaseModel):
    text: str


@router.post("/transcribe")
async def transcribe_text(payload: TextPayload):
    intent = detect_intent(payload.text)
    return build_response(intent, payload.text)


@router.get("/transcribe")
async def transcribe_file(file: str):
    if ".." in file:
        return {"error": "invalid path"}
    file = file.lstrip("/")
    base = os.path.join(os.path.dirname(__file__), "..", "storage")
    path = os.path.normpath(os.path.join(base, os.path.basename(file)))
    if not os.path.exists(path):
        return {"error": "file not found"}
    return transcribe_audio_file(path)
