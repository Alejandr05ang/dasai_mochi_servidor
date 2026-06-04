from typing import Dict, List, Optional
import json

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []
        self.device_connections: Dict[str, WebSocket] = {}  # device_id → ws

    async def connect(self, websocket: WebSocket, device_id: Optional[str] = None) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        if device_id:
            old_ws = self.device_connections.get(device_id)
            if old_ws and old_ws in self.active_connections:
                self.active_connections.remove(old_ws)
            self.device_connections[device_id] = websocket
        print(json.dumps({"event": "ws_connect", "device_id": device_id, "total": len(self.active_connections)}))

    def disconnect(self, websocket: WebSocket) -> Optional[str]:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        device_id = None
        for did, ws in list(self.device_connections.items()):
            if ws is websocket:
                del self.device_connections[did]
                device_id = did
                break
        print(json.dumps({"event": "ws_disconnect", "device_id": device_id, "total": len(self.active_connections)}))
        return device_id

    def connected_devices(self) -> List[str]:
        return list(self.device_connections.keys())

    async def broadcast(self, message: dict) -> None:
        print(json.dumps({
            "event": "ws_broadcast",
            "type": message.get("type", "unknown"),
            "active_connections": len(self.active_connections),
        }))
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        if disconnected:
            print(json.dumps({
                "event": "ws_broadcast_disconnected",
                "type": message.get("type", "unknown"),
                "disconnected": len(disconnected),
            }))

        for connection in disconnected:
            if connection in self.active_connections:
                self.active_connections.remove(connection)
            for did, ws in list(self.device_connections.items()):
                if ws is connection:
                    del self.device_connections[did]

    async def broadcast_to(self, device_id: str, message: dict) -> bool:
        ws = self.device_connections.get(device_id)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            print(json.dumps({"event": "ws_broadcast_to", "device_id": device_id, "type": message.get("type")}))
            return True
        except Exception:
            if ws in self.active_connections:
                self.active_connections.remove(ws)
            del self.device_connections[device_id]
            return False

    def cleanup(self) -> int:
        removed = 0
        for conn in list(self.active_connections):
            try:
                if getattr(conn, 'client_state', None) is not None:
                    if conn.client_state != WebSocketState.CONNECTED:
                        self.active_connections.remove(conn)
                        for did, ws in list(self.device_connections.items()):
                            if ws is conn:
                                del self.device_connections[did]
                        removed += 1
            except Exception:
                try:
                    self.active_connections.remove(conn)
                    removed += 1
                except Exception:
                    pass
        if removed:
            print(json.dumps({"event": "ws_cleanup", "removed": removed, "total": len(self.active_connections)}))
        return removed


manager = ConnectionManager()
