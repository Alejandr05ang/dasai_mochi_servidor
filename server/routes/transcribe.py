from fastapi import APIRouter
import os
from server.services.stt import transcribe_audio_file

router = APIRouter()


@router.get('/transcribe')
async def transcribe(file: str):
    # file is a path relative to /files, e.g. /files/device_session_timestamp.raw
    # map to storage dir
    # sanitize
    if '..' in file:
        return {"error": "invalid path"}
    # strip leading slash
    file = file.lstrip('/')
    base = os.path.join(os.path.dirname(__file__), '..', 'storage')
    path = os.path.normpath(os.path.join(base, os.path.basename(file)))
    if not os.path.exists(path):
        return {"error": "file not found"}
    return transcribe_audio_file(path)
