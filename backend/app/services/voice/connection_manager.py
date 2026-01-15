import logging

from fastapi import WebSocket

logger = logging.getLogger("agent_hub.voice.websocket")


class ConnectionManager:
    def __init__(self):
        # Maps user_id -> List[WebSocket]
        self.active_connections: dict[str, list[WebSocket]] = {}
        # Maps session_id -> WebSocket (for specific voice sessions)
        self.session_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str, session_id: str | None = None):
        await websocket.accept()

        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

        if session_id:
            self.session_connections[session_id] = websocket

        logger.info(
            f"User {user_id} connected via WebSocket"
            + (f" (Session: {session_id})" if session_id else "")
        )

    def disconnect(self, websocket: WebSocket, user_id: str, session_id: str | None = None):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

        if session_id and session_id in self.session_connections:
            del self.session_connections[session_id]

        logger.info(
            f"User {user_id} disconnected" + (f" (Session: {session_id})" if session_id else "")
        )

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(message)


manager = ConnectionManager()
