"""Session management operations."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

from agent_hub._utils import handle_error
from agent_hub.models import SessionCreate, SessionListResponse, SessionResponse
from agent_hub.models.native_observation import (
    NativeObservationBatch,
    NativeObservationResult,
    NativeProtocolProfileRegistration,
    NativeQuarantineBatch,
    NativeQuarantineRegistration,
    NativeSourceReceipt,
    NativeSourceRegistration,
)


def _event_params(event_type: str | None, turn: int | None, page: int, page_size: int) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if event_type:
        params["event_type"] = event_type
    if turn is not None:
        params["turn"] = turn
    return params


def _list_params(*, page: int, page_size: int, **filters: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    params.update({name: value for name, value in filters.items() if value})
    return params


class SessionOperationsMixin:
    """Mixin providing session management methods."""

    if TYPE_CHECKING:
        # Supplied by the composing client; these declarations have no runtime body.
        def _get_client(self) -> httpx.Client: ...
        def _inject_tracking_headers(self, source: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]: ...

    def register_native_protocol_profile(self, request: NativeProtocolProfileRegistration, *, execution_owner_secret: str | None = None) -> dict[str, Any]:
        response = self._get_client().post("/api/session-ingestion/native-protocol-profiles", json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.register_native_protocol_profile", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None))
        if not response.is_success:
            handle_error(response)
        return response.json()

    def list_native_protocol_profiles(self, *, execution_owner_secret: str | None = None) -> dict[str, Any]:
        response = self._get_client().get("/api/session-ingestion/native-protocol-profiles", headers=self._inject_tracking_headers("sdk.list_native_protocol_profiles", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None))
        if not response.is_success:
            handle_error(response)
        return response.json()

    def register_native_quarantine(self, request: NativeQuarantineRegistration, *, execution_owner_secret: str | None = None) -> NativeSourceReceipt:
        response = self._get_client().post("/api/session-ingestion/native-quarantine", json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.register_native_quarantine", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None))
        if not response.is_success:
            handle_error(response)
        return NativeSourceReceipt.model_validate(response.json())

    def ingest_native_quarantine(self, source_id: str, request: NativeQuarantineBatch, *, execution_owner_secret: str | None = None) -> NativeObservationResult:
        response = self._get_client().post(f"/api/session-ingestion/native-quarantine/{source_id}/observations", json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.ingest_native_quarantine", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None))
        if not response.is_success:
            handle_error(response)
        return NativeObservationResult.model_validate(response.json())

    def register_native_source(self, session_id: str, request: NativeSourceRegistration, *, execution_owner_secret: str | None = None) -> NativeSourceReceipt:
        response = self._get_client().post(
            f"/api/session-ingestion/sessions/{session_id}/native-sources",
            json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.register_native_source", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None),
        )
        if not response.is_success:
            handle_error(response)
        return NativeSourceReceipt.model_validate(response.json())

    def ingest_native_observations(self, session_id: str, source_id: str, request: NativeObservationBatch, *, execution_owner_secret: str | None = None) -> NativeObservationResult:
        response = self._get_client().post(
            f"/api/session-ingestion/sessions/{session_id}/native-sources/{source_id}/observations",
            json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.ingest_native_observations", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None),
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
        *,
        agent_slug: str | None = None,
        parent_session_id: str | None = None,
        external_id: str | None = None,
        session_type: str | None = None,
    ) -> SessionListResponse:
        """List sessions with pagination.

        Args:
            project_id: Filter by project.
            status: Filter by status (also the live aliases ``stale`` and ``reapable``).
            page: Page number.
            page_size: Items per page.
            agent_slug: Filter by agent.
            parent_session_id: Filter to children of one session.
            external_id: Filter by caller-assigned external ID (e.g. a task ID).
            session_type: Filter by session type.

        Returns:
            SessionListResponse with sessions and pagination info.
        """
        client = self._get_client()
        params = _list_params(
            page=page, page_size=page_size, project_id=project_id, status=status, agent_slug=agent_slug,
            parent_session_id=parent_session_id, external_id=external_id, session_type=session_type,
        )
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

    def list_session_events(self, session_id: str, *, event_type: str | None = None, turn: int | None = None, page: int = 1, page_size: int = 100) -> dict[str, Any]:
        """Return one page of a session's events (``GET /api/sessions/{id}/events``)."""
        response = self._get_client().get(f"/api/sessions/{session_id}/events", params=_event_params(event_type, turn, page, page_size), headers=self._inject_tracking_headers("sdk.list_session_events"))
        if not response.is_success:
            handle_error(response)
        return response.json()

    def append_session_event(self, session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """Record one event on a session (``POST /api/sessions/{id}/events``)."""
        response = self._get_client().post(f"/api/sessions/{session_id}/events", json=event, headers=self._inject_tracking_headers("sdk.append_session_event"))
        if not response.is_success:
            handle_error(response)
        return response.json()


class AsyncSessionOperationsMixin:
    """Mixin providing async session management methods."""

    if TYPE_CHECKING:
        async def _get_client(self) -> httpx.AsyncClient: ...
        def _inject_tracking_headers(self, source: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]: ...

    async def register_native_protocol_profile(self, request: NativeProtocolProfileRegistration, *, execution_owner_secret: str | None = None) -> dict[str, Any]:
        response = await (await self._get_client()).post("/api/session-ingestion/native-protocol-profiles", json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.register_native_protocol_profile", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None))
        if not response.is_success:
            handle_error(response)
        return response.json()

    async def list_native_protocol_profiles(self, *, execution_owner_secret: str | None = None) -> dict[str, Any]:
        response = await (await self._get_client()).get("/api/session-ingestion/native-protocol-profiles", headers=self._inject_tracking_headers("sdk.list_native_protocol_profiles", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None))
        if not response.is_success:
            handle_error(response)
        return response.json()

    async def register_native_quarantine(self, request: NativeQuarantineRegistration, *, execution_owner_secret: str | None = None) -> NativeSourceReceipt:
        response = await (await self._get_client()).post("/api/session-ingestion/native-quarantine", json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.register_native_quarantine", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None))
        if not response.is_success:
            handle_error(response)
        return NativeSourceReceipt.model_validate(response.json())

    async def ingest_native_quarantine(self, source_id: str, request: NativeQuarantineBatch, *, execution_owner_secret: str | None = None) -> NativeObservationResult:
        response = await (await self._get_client()).post(f"/api/session-ingestion/native-quarantine/{source_id}/observations", json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.ingest_native_quarantine", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None))
        if not response.is_success:
            handle_error(response)
        return NativeObservationResult.model_validate(response.json())

    async def register_native_source(self, session_id: str, request: NativeSourceRegistration, *, execution_owner_secret: str | None = None) -> NativeSourceReceipt:
        client = await self._get_client()
        response = await client.post(
            f"/api/session-ingestion/sessions/{session_id}/native-sources",
            json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.register_native_source", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None),
        )
        if not response.is_success:
            handle_error(response)
        return NativeSourceReceipt.model_validate(response.json())

    async def ingest_native_observations(self, session_id: str, source_id: str, request: NativeObservationBatch, *, execution_owner_secret: str | None = None) -> NativeObservationResult:
        client = await self._get_client()
        response = await client.post(
            f"/api/session-ingestion/sessions/{session_id}/native-sources/{source_id}/observations",
            json=request.model_dump(mode="json"), headers=self._inject_tracking_headers("sdk.ingest_native_observations", {"X-Agent-Hub-Internal": execution_owner_secret} if execution_owner_secret else None),
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
        *,
        agent_slug: str | None = None,
        parent_session_id: str | None = None,
        external_id: str | None = None,
        session_type: str | None = None,
    ) -> SessionListResponse:
        """List sessions with pagination asynchronously."""
        client = await self._get_client()
        params = _list_params(
            page=page, page_size=page_size, project_id=project_id, status=status, agent_slug=agent_slug,
            parent_session_id=parent_session_id, external_id=external_id, session_type=session_type,
        )
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

    async def list_session_events(self, session_id: str, *, event_type: str | None = None, turn: int | None = None, page: int = 1, page_size: int = 100) -> dict[str, Any]:
        """Return one page of a session's events (``GET /api/sessions/{id}/events``)."""
        client = await self._get_client()
        response = await client.get(f"/api/sessions/{session_id}/events", params=_event_params(event_type, turn, page, page_size), headers=self._inject_tracking_headers("sdk.list_session_events"))
        if not response.is_success:
            handle_error(response)
        return response.json()

    async def append_session_event(self, session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """Record one event on a session (``POST /api/sessions/{id}/events``)."""
        client = await self._get_client()
        response = await client.post(f"/api/sessions/{session_id}/events", json=event, headers=self._inject_tracking_headers("sdk.append_session_event"))
        if not response.is_success:
            handle_error(response)
        return response.json()
