from typing import List
import json

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        print(json.dumps({"event": "ws_connect", "total": len(self.active_connections)}))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(json.dumps({"event": "ws_disconnect", "total": len(self.active_connections)}))

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

    def cleanup(self) -> int:
        # Remove connections that are not in CONNECTED state
        removed = 0
        for conn in list(self.active_connections):
            try:
                if getattr(conn, 'client_state', None) is not None:
                    if conn.client_state != WebSocketState.CONNECTED:
                        self.active_connections.remove(conn)
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
