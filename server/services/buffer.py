from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Dict, Tuple


@dataclass
class AudioSession:
    device_id: str
    session_id: str
    chunks: list[bytes] = field(default_factory=list)
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)

    def add_chunk(self, chunk: bytes) -> None:
        self.chunks.append(chunk)
        self.updated_at = time()

    def build_audio(self) -> bytes:
        return b"".join(self.chunks)


class AudioBufferManager:
    def __init__(self) -> None:
        self.sessions: Dict[Tuple[str, str], AudioSession] = {}

    def add_chunk(self, device_id: str, session_id: str, chunk: bytes) -> AudioSession:
        key = (device_id, session_id)
        session = self.sessions.get(key)
        if session is None:
            session = AudioSession(device_id=device_id, session_id=session_id)
            self.sessions[key] = session

        session.add_chunk(chunk)
        return session

    def finalize_session(self, device_id: str, session_id: str) -> bytes:
        key = (device_id, session_id)
        session = self.sessions.pop(key, None)
        if session is None:
            return b""
        return session.build_audio()

    def cleanup_stale_sessions(self, max_age_seconds: int) -> int:
        now = time()
        expired_keys = [
            key
            for key, session in self.sessions.items()
            if now - session.updated_at > max_age_seconds
        ]

        for key in expired_keys:
            self.sessions.pop(key, None)

        return len(expired_keys)


buffer_manager = AudioBufferManager()
