"""
WebSocket manager for live session streaming.

Agent execution sends progress events via callback, which are broadcast
to all connected WebSocket clients for a given session.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages WebSocket connections for live session streaming."""

    def __init__(self) -> None:
        # session_id → set of connected WebSocket clients
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection for a session."""
        await websocket.accept()
        if session_id not in self._connections:
            self._connections[session_id] = set()
        self._connections[session_id].add(websocket)
        logger.info("WebSocket connected for session %s (%d clients)",
                     session_id, len(self._connections[session_id]))

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection."""
        if session_id in self._connections:
            self._connections[session_id].discard(websocket)
            if not self._connections[session_id]:
                del self._connections[session_id]
        logger.info("WebSocket disconnected for session %s", session_id)

    async def broadcast(self, session_id: str, message: dict) -> None:
        """Broadcast a message to all connected clients for a session."""
        if session_id not in self._connections:
            return

        payload = json.dumps(message)
        dead_connections = set()

        for ws in self._connections[session_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead_connections.add(ws)

        # Clean up dead connections
        for ws in dead_connections:
            self._connections[session_id].discard(ws)

    def has_clients(self, session_id: str) -> bool:
        """Check if any clients are connected for a session."""
        return bool(self._connections.get(session_id))

    def get_callback(self, session_id: str) -> "Callable":
        """Create a synchronous callback that queues messages for async broadcast.

        This is used to bridge the synchronous agent execution with async WebSocket.
        """
        loop = asyncio.get_event_loop()

        def callback(event: dict) -> None:
            if self.has_clients(session_id):
                asyncio.run_coroutine_threadsafe(
                    self.broadcast(session_id, event), loop
                )

        return callback


# Global session manager instance
session_manager = SessionManager()
