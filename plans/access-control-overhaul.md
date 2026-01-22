# Access Control Overhaul Plan

## Overview

Replace the fragmented "kill switch" + "API keys" system with a unified **Access Control** system featuring:
- Mandatory client authentication (secret-based)
- Full request attribution (client + source location)
- Single unified UI
- No honor system - cryptographic verification

---

## Phase 1: Database Schema

### New Tables

```sql
-- Primary client registry
CREATE TABLE clients (
    id VARCHAR(100) PRIMARY KEY,           -- "portfolio-ai-backend"
    display_name VARCHAR(200) NOT NULL,    -- "Portfolio AI Backend"
    client_type VARCHAR(20) NOT NULL,      -- "service", "test", "external", "dashboard"
    secret_hash VARCHAR(128) NOT NULL,     -- argon2/bcrypt hash of client secret
    secret_prefix VARCHAR(12) NOT NULL,    -- "ahc_7f8a9b2c" for identification
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- "active", "suspended", "blocked"

    -- Rate limits
    rate_limit_rpm INT NOT NULL DEFAULT 60,
    rate_limit_tpm INT NOT NULL DEFAULT 100000,

    -- Metadata
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) NOT NULL,
    last_seen_at TIMESTAMP,
    last_request_source VARCHAR(255),

    -- Blocking info (when status != active)
    status_reason TEXT,
    status_changed_at TIMESTAMP,
    status_changed_by VARCHAR(100)
);

-- Request audit log (persistent, not in-memory)
CREATE TABLE request_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    client_id VARCHAR(100) NOT NULL,       -- FK to clients or "<rejected>"
    request_source VARCHAR(255) NOT NULL,  -- "services/strategy.py:generate"
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL,           -- "allowed", "rejected", "blocked"
    rejection_reason VARCHAR(255),         -- why rejected (if applicable)
    response_code INT,
    tokens_used INT,
    latency_ms INT,

    -- Request metadata
    user_agent VARCHAR(500),
    client_ip VARCHAR(45),

    INDEX idx_request_log_client (client_id),
    INDEX idx_request_log_timestamp (timestamp),
    INDEX idx_request_log_status (status)
);
```

### Modify Sessions Table

```sql
ALTER TABLE sessions
    ADD COLUMN client_id VARCHAR(100) NOT NULL,
    ADD COLUMN request_source VARCHAR(255) NOT NULL,
    ADD CONSTRAINT fk_sessions_client FOREIGN KEY (client_id) REFERENCES clients(id);

CREATE INDEX idx_sessions_client ON sessions(client_id);
```

### Tables to Remove (After Migration)

- `client_controls` → replaced by `clients`
- `purpose_controls` → removed (use client_type + status instead)
- `client_purpose_controls` → removed
- `api_keys` → merged into `clients` (external type)

---

## Phase 2: Backend Implementation

### 2.1 Client Authentication Service

**File:** `backend/app/services/client_auth.py`

```python
class ClientAuthService:
    """Handles client registration and authentication."""

    async def register_client(
        self,
        client_id: str,
        display_name: str,
        client_type: str,
        created_by: str,
    ) -> tuple[Client, str]:
        """
        Register a new client.
        Returns (client, secret) - secret shown only once.
        """
        # Generate secret: ahc_<32 random bytes>
        secret = f"ahc_{secrets.token_urlsafe(32)}"
        secret_hash = self._hash_secret(secret)
        secret_prefix = secret[:12]

        client = Client(
            id=client_id,
            display_name=display_name,
            client_type=client_type,
            secret_hash=secret_hash,
            secret_prefix=secret_prefix,
            created_by=created_by,
        )
        # Save to DB
        return client, secret  # Secret returned ONCE

    async def authenticate(
        self,
        client_id: str,
        client_secret: str,
    ) -> Client:
        """
        Authenticate a client by ID + secret.
        Raises AuthenticationError if invalid.
        """
        client = await self._get_client(client_id)
        if not client:
            raise AuthenticationError("Unknown client")
        if not self._verify_secret(client_secret, client.secret_hash):
            raise AuthenticationError("Invalid client secret")
        if client.status != "active":
            raise AuthenticationError(f"Client {client.status}: {client.status_reason}")
        return client

    async def rotate_secret(self, client_id: str, rotated_by: str) -> str:
        """Generate new secret for client. Returns new secret (shown once)."""
        ...
```

### 2.2 Access Control Middleware

**File:** `backend/app/middleware/access_control.py`

Replace `kill_switch.py` with:

```python
REQUIRED_HEADERS = ["X-Client-Id", "X-Client-Secret", "X-Request-Source"]

class AccessControlMiddleware(BaseHTTPMiddleware):
    """Enforce client authentication on all API requests."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Exempt paths (health, docs, access-control admin)
        if self._is_exempt(path):
            return await call_next(request)

        # Extract required headers
        client_id = request.headers.get("X-Client-Id")
        client_secret = request.headers.get("X-Client-Secret")
        request_source = request.headers.get("X-Request-Source")

        # Validate ALL headers present
        missing = []
        if not client_id:
            missing.append("X-Client-Id")
        if not client_secret:
            missing.append("X-Client-Secret")
        if not request_source:
            missing.append("X-Request-Source")

        if missing:
            await self._log_rejection(request, "missing_headers", missing)
            return JSONResponse(
                status_code=400,
                content={
                    "error": "missing_required_headers",
                    "missing": missing,
                    "message": "All requests require X-Client-Id, X-Client-Secret, and X-Request-Source headers",
                },
            )

        # Authenticate client
        try:
            client = await self.auth_service.authenticate(client_id, client_secret)
        except AuthenticationError as e:
            await self._log_rejection(request, "auth_failed", str(e))
            return JSONResponse(
                status_code=403,
                content={
                    "error": "authentication_failed",
                    "message": str(e),
                },
            )

        # Attach client to request state for downstream use
        request.state.client = client
        request.state.request_source = request_source

        # Update last_seen
        await self._update_last_seen(client, request_source)

        # Log and proceed
        response = await call_next(request)
        await self._log_request(request, client, request_source, response)
        return response
```

### 2.3 Access Control Admin API

**File:** `backend/app/api/access_control.py`

```python
router = APIRouter(prefix="/api/access-control", tags=["access-control"])

# Client management
@router.post("/clients")
async def register_client(data: ClientCreate) -> ClientWithSecret:
    """Register new client. Returns secret ONCE."""

@router.get("/clients")
async def list_clients(status: str = None, client_type: str = None) -> ClientList:
    """List all registered clients."""

@router.get("/clients/{client_id}")
async def get_client(client_id: str) -> ClientDetail:
    """Get client details including recent activity."""

@router.patch("/clients/{client_id}")
async def update_client(client_id: str, data: ClientUpdate) -> Client:
    """Update client display name, rate limits, etc."""

@router.post("/clients/{client_id}/suspend")
async def suspend_client(client_id: str, reason: str) -> Client:
    """Suspend a client (temporary block)."""

@router.post("/clients/{client_id}/activate")
async def activate_client(client_id: str) -> Client:
    """Re-activate a suspended client."""

@router.post("/clients/{client_id}/block")
async def block_client(client_id: str, reason: str) -> Client:
    """Permanently block a client."""

@router.post("/clients/{client_id}/rotate-secret")
async def rotate_secret(client_id: str) -> SecretRotateResponse:
    """Generate new secret. Returns new secret ONCE."""

@router.delete("/clients/{client_id}")
async def delete_client(client_id: str) -> None:
    """Permanently delete a client."""

# Request log
@router.get("/request-log")
async def get_request_log(
    client_id: str = None,
    status: str = None,
    limit: int = 100,
) -> RequestLogResponse:
    """Get request audit log with filtering."""

# Stats
@router.get("/stats")
async def get_stats() -> AccessControlStats:
    """Get access control statistics."""
```

### 2.4 Session Creation Updates

**File:** `backend/app/api/complete.py`

Update session creation to use authenticated client:

```python
@router.post("/complete")
async def complete(
    request: Request,
    data: CompletionRequest,
    db: AsyncSession = Depends(get_db),
):
    # Client already authenticated by middleware
    client = request.state.client
    request_source = request.state.request_source

    # Create session with full attribution
    session = Session(
        id=str(uuid4()),
        client_id=client.id,           # FROM AUTHENTICATED CLIENT
        request_source=request_source,  # FROM REQUIRED HEADER
        project_id=data.project_id,
        provider=data.provider,
        model=data.model,
        ...
    )
```

---

## Phase 3: Frontend Implementation

### 3.1 New Access Control Section

**Location:** `/access-control` (replaces `/admin` and `/settings/api-keys`)

```
/access-control
├── /access-control              # Dashboard overview
├── /access-control/clients      # Client list with status filters
├── /access-control/clients/new  # Register new client
├── /access-control/clients/[id] # Client detail + activity
├── /access-control/requests     # Request log viewer
└── /access-control/settings     # Global settings
```

### 3.2 Components

**ClientList:** Table of all clients with:
- ID, display name, type, status
- Last seen, request count (24h)
- Quick actions: suspend/activate/block

**ClientDetail:** Single client view with:
- Basic info and status
- Recent requests from this client
- Rotate secret button
- Activity graph

**RequestLog:** Searchable/filterable log with:
- Timestamp, client, source, endpoint
- Status (allowed/rejected/blocked)
- Expandable detail rows

**RegisterClient:** Form with:
- Client ID (validated format)
- Display name
- Type selection
- Shows secret ONCE after creation with copy button

### 3.3 Navigation Update

**File:** `frontend/src/components/layout/app-shell.tsx`

```tsx
// Remove:
{ name: "Settings", href: "/settings" }
{ name: "Admin", href: "/admin" }

// Add:
{ name: "Access Control", href: "/access-control", icon: Shield }
```

---

## Phase 4: Project Audit & Updates

### 4.1 Projects to Update

| Project | Files to Update | Client ID |
|---------|-----------------|-----------|
| portfolio-ai backend | API calls to agent-hub | `portfolio-ai-backend` |
| portfolio-ai tests | Test fixtures | `portfolio-ai-tests` |
| summitflow backend | API calls to agent-hub | `summitflow-backend` |
| summitflow tests | Test fixtures | `summitflow-tests` |
| agent-hub frontend | Internal API calls | `agent-hub-dashboard` |
| agent-hub tests | Test fixtures | `agent-hub-tests` |
| Any cron jobs | Scheduled tasks | `<project>-cron` |

### 4.2 Update Pattern

Each project needs:

**1. Environment variable:**
```bash
# .env.local
AGENT_HUB_CLIENT_ID=portfolio-ai-backend
AGENT_HUB_CLIENT_SECRET=ahc_xxxxxxxxxxxxxxxx
```

**2. HTTP client wrapper:**
```python
# lib/agent_hub.py
import os
import httpx

class AgentHubClient:
    def __init__(self):
        self.client_id = os.environ["AGENT_HUB_CLIENT_ID"]
        self.client_secret = os.environ["AGENT_HUB_CLIENT_SECRET"]
        self.base_url = os.environ.get("AGENT_HUB_URL", "http://localhost:8003")

    def _headers(self, request_source: str) -> dict:
        return {
            "X-Client-Id": self.client_id,
            "X-Client-Secret": self.client_secret,
            "X-Request-Source": request_source,
        }

    async def complete(self, request_source: str, **kwargs):
        async with httpx.AsyncClient() as client:
            return await client.post(
                f"{self.base_url}/api/complete",
                headers=self._headers(request_source),
                json=kwargs,
            )
```

**3. Usage with source attribution:**
```python
# services/strategy.py
from lib.agent_hub import AgentHubClient

hub = AgentHubClient()

async def generate_strategy(...):
    response = await hub.complete(
        request_source="services/strategy.py:generate_strategy",
        model="claude-sonnet-4-5",
        messages=[...],
    )
```

### 4.3 Test Fixtures

```python
# conftest.py
import os
os.environ["AGENT_HUB_CLIENT_ID"] = "portfolio-ai-tests"
os.environ["AGENT_HUB_CLIENT_SECRET"] = "ahc_test_secret_for_ci"

@pytest.fixture
def agent_hub_client():
    return AgentHubClient()
```

---

## Phase 5: Migration & Rollout

### 5.1 Migration Steps

```
1. Deploy database schema changes (new tables)
2. Deploy backend with NEW middleware (but in bypass mode initially)
3. Deploy frontend with new Access Control UI
4. Register all known clients via UI/API
5. Update all projects with client credentials
6. Enable enforcement mode
7. Monitor for rejections
8. Remove old tables after 1 week stable
```

### 5.2 Bypass Mode (Temporary)

During migration, middleware supports bypass:

```python
# environment variable
ACCESS_CONTROL_MODE=bypass  # bypass, audit, enforce

# bypass: Log but allow all (for deployment)
# audit: Log and allow, but flag missing headers
# enforce: Full enforcement (production)
```

### 5.3 Client Registration Order

```
1. agent-hub-dashboard (internal, auto-created)
2. agent-hub-tests (test)
3. portfolio-ai-backend (service)
4. portfolio-ai-tests (test)
5. summitflow-backend (service)
6. summitflow-tests (test)
7. Any other discovered callers
```

---

## Phase 6: Cleanup

### 6.1 Remove Old Code

- `backend/app/middleware/kill_switch.py` → deleted
- `backend/app/api/admin.py` → deleted (replaced by access_control.py)
- `frontend/src/app/admin/` → deleted
- `frontend/src/app/settings/api-keys/` → deleted

### 6.2 Remove Old Tables

```sql
DROP TABLE client_controls;
DROP TABLE purpose_controls;
DROP TABLE client_purpose_controls;
DROP TABLE api_keys;
```

### 6.3 Update Documentation

- CLAUDE.md - update API access instructions
- README - document access control system

---

## Acceptance Criteria

- [ ] All API requests require X-Client-Id, X-Client-Secret, X-Request-Source
- [ ] Unknown/unauthenticated requests return 400/403
- [ ] All sessions have client_id and request_source (NOT NULL)
- [ ] Single Access Control UI replaces Admin + Settings/API Keys
- [ ] All projects updated with client credentials
- [ ] Request log shows full attribution for all requests
- [ ] Can suspend/block clients and see immediate effect
- [ ] Secret rotation works without downtime

---

## Estimated Effort

| Phase | Work |
|-------|------|
| Phase 1: Database | 1 hour |
| Phase 2: Backend | 3 hours |
| Phase 3: Frontend | 3 hours |
| Phase 4: Project Audit | 2 hours |
| Phase 5: Migration | 1 hour |
| Phase 6: Cleanup | 30 min |
| **Total** | ~10 hours |

---

## Open Questions

1. Should external API keys (OpenAI-compatible) be separate or merged into clients?
2. Rate limiting: per-client or keep current per-key approach?
3. Should we support IP allowlisting as additional security layer?
4. Retention policy for request_log table?
