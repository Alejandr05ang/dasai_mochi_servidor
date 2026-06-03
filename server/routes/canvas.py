import base64
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ws.manager import manager

LOG = logging.getLogger("voiceiot")
router = APIRouter()


class CanvasPayload(BaseModel):
    bitmap: Optional[str] = None
    exit: bool = False


@router.post("/canvas")
async def receive_canvas(payload: CanvasPayload):
    if payload.exit:
        await manager.broadcast({"type": "canvas_exit"})
        LOG.info(json.dumps({"event": "canvas_exit"}))
        return {"ok": True, "action": "exit"}

    if not payload.bitmap:
        raise HTTPException(status_code=400, detail="bitmap required when exit=false")

    try:
        raw = base64.b64decode(payload.bitmap)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 in bitmap")

    if len(raw) != 1024:
        raise HTTPException(status_code=400, detail=f"Expected 1024 bytes, got {len(raw)}")

    await manager.broadcast({"type": "canvas_update", "bitmap": payload.bitmap})
    LOG.info(json.dumps({"event": "canvas_update", "bytes": 1024}))
    return {"ok": True, "bytes": 1024}
