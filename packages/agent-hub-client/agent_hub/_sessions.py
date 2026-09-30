"""Session management operations."""

from typing import Any

from agent_hub.models.native_observation import (
    NativeObservationBatch, NativeObservationResult, NativeSourceReceipt, NativeSourceRegistration,
)
from agent_hub._utils import handle_error
from agent_hub.models import SessionCreate, SessionListResponse, SessionResponse


class SessionOperationsMixin:
    """Mixin providing session management methods."""

    def register_native_source(self, session_id: str, request: NativeSourceRegistration) -> NativeSourceReceipt:
        response = self._get_client().post(
            f"/api/session-ingestion/sessions/{session_id}/native-sources",
            json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.register_native_source"),
        )
        if not response.is_success:
            handle_error(response)
        return NativeSourceReceipt.model_validate(response.json())

    def ingest_native_observations(self, session_id: str, source_id: str, request: NativeObservationBatch) -> NativeObservationResult:
        response = self._get_client().post(
            f"/api/session-ingestion/sessions/{session_id}/native-sources/{source_id}/observations",
            json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.ingest_native_observations"),
        )
        if not response.is_success:
            handle_error(response)
        return NativeObservationResult.model_validate(response.json())

    def create_session(
        self,
        project_id: str,
        provider: str,
        model: str,
    ) -> SessionResponse:
        """Create a new conversation session.

        Args:
            project_id: Project identifier.
            provider: Provider name ("claude" or "gemini").
            model: Model identifier.

        Returns:
            SessionResponse with session details.
        """
        client = self._get_client()
        payload = SessionCreate(
            project_id=project_id,
            provider=provider,
            model=model,
        )
        headers = self._inject_tracking_headers("sdk.create_session")
        response = client.post(
            "/api/sessions", json=payload.model_dump(), headers=headers
        )
        if not response.is_success:
            handle_error(response)
        return SessionResponse.model_validate(response.json())

    def get_session(self, session_id: str) -> SessionResponse:
        """Get a session by ID with all messages.

        Args:
            session_id: Session identifier.

        Returns:
            SessionResponse with session details and messages.
        """
        client = self._get_client()
        headers = self._inject_tracking_headers("sdk.get_session")
        response = client.get(f"/api/sessions/{session_id}", headers=headers)
        if not response.is_success:
            handle_error(response)
        return SessionResponse.model_validate(response.json())

    def list_sessions(
        self,
        project_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SessionListResponse:
        """List sessions with pagination.

        Args:
            project_id: Filter by project.
            status: Filter by status.
            page: Page number.
            page_size: Items per page.

        Returns:
            SessionListResponse with sessions and pagination info.
        """
        client = self._get_client()
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if project_id:
            params["project_id"] = project_id
        if status:
            params["status"] = status
        headers = self._inject_tracking_headers("sdk.list_sessions")
        response = client.get("/api/sessions", params=params, headers=headers)
        if not response.is_success:
            handle_error(response)
        return SessionListResponse.model_validate(response.json())

    def delete_session(self, session_id: str) -> None:
        """Delete/archive a session.

        Args:
            session_id: Session identifier.
        """
        client = self._get_client()
        headers = self._inject_tracking_headers("sdk.delete_session")
        response = client.delete(f"/api/sessions/{session_id}", headers=headers)
        if not response.is_success:
            handle_error(response)

    def close_session(self, session_id: str) -> dict[str, Any]:
        """Explicitly close a session.

        Marks the session as completed. Use for clean session termination.
        This is idempotent - calling on an already-completed session is safe.

        Args:
            session_id: Session identifier.

        Returns:
            Dict with id, status, and message.
        """
        client = self._get_client()
        headers = self._inject_tracking_headers("sdk.close_session")
        response = client.post(f"/api/sessions/{session_id}/close", headers=headers)
        if not response.is_success:
            handle_error(response)
        return response.json()


class AsyncSessionOperationsMixin:
    """Mixin providing async session management methods."""

    async def register_native_source(self, session_id: str, request: NativeSourceRegistration) -> NativeSourceReceipt:
        client = await self._get_client()
        response = await client.post(
            f"/api/session-ingestion/sessions/{session_id}/native-sources",
            json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.register_native_source"),
        )
        if not response.is_success:
            handle_error(response)
        return NativeSourceReceipt.model_validate(response.json())

    async def ingest_native_observations(self, session_id: str, source_id: str, request: NativeObservationBatch) -> NativeObservationResult:
        client = await self._get_client()
        response = await client.post(
            f"/api/session-ingestion/sessions/{session_id}/native-sources/{source_id}/observations",
            json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.ingest_native_observations"),
        )
        if not response.is_success:
            handle_error(response)
        return NativeObservationResult.model_validate(response.json())

    async def create_session(
        self,
        project_id: str,
        provider: str,
        model: str,
    ) -> SessionResponse:
        """Create a new conversation session asynchronously."""
        client = await self._get_client()
        payload = SessionCreate(
            project_id=project_id,
            provider=provider,
            model=model,
        )
        headers = self._inject_tracking_headers("sdk.create_session")
        response = await client.post(
            "/api/sessions", json=payload.model_dump(), headers=headers
        )
        if not response.is_success:
            handle_error(response)
        return SessionResponse.model_validate(response.json())

    async def get_session(self, session_id: str) -> SessionResponse:
        """Get a session by ID with all messages asynchronously."""
        client = await self._get_client()
        headers = self._inject_tracking_headers("sdk.get_session")
        response = await client.get(f"/api/sessions/{session_id}", headers=headers)
        if not response.is_success:
            handle_error(response)
        return SessionResponse.model_validate(response.json())

    async def list_sessions(
        self,
        project_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SessionListResponse:
        """List sessions with pagination asynchronously."""
        client = await self._get_client()
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if project_id:
            params["project_id"] = project_id
        if status:
            params["status"] = status
        headers = self._inject_tracking_headers("sdk.list_sessions")
        response = await client.get("/api/sessions", params=params, headers=headers)
        if not response.is_success:
            handle_error(response)
        return SessionListResponse.model_validate(response.json())

    async def delete_session(self, session_id: str) -> None:
        """Delete/archive a session asynchronously."""
        client = await self._get_client()
        headers = self._inject_tracking_headers("sdk.delete_session")
        response = await client.delete(f"/api/sessions/{session_id}", headers=headers)
        if not response.is_success:
            handle_error(response)

    async def close_session(self, session_id: str) -> dict[str, Any]:
        """Explicitly close a session asynchronously."""
        client = await self._get_client()
        headers = self._inject_tracking_headers("sdk.close_session")
        response = await client.post(
            f"/api/sessions/{session_id}/close", headers=headers
        )
        if not response.is_success:
            handle_error(response)
        return response.json()

