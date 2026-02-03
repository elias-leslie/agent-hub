# AGENTS.md

This repository is a full-stack AI application managed by autonomous coding agents.
It consists of a Python backend (FastAPI) and a TypeScript frontend (Next.js).

## 🚀 Workflow & Tools

This environment includes specialized CLI tools to streamline development. **Prefer these tools over raw commands.**

### 🏔️ SummitFlow CLI (`st`)
Project management and task execution. SummitFlow acts as the "manager" that delegates execution to Agent Hub.
- **Find Work:** `st ready` (lists unblocked tasks)
- **Start Task:** `st claim <id>` (creates git branch, updates DB)
- **Get Context:** `st context <id>` (dumps full task context/plan)
- **Finish:** `st done <id>` (squash merges to main, closes task)
- **Checkpoints:** `st checkpoints` (list active work)
- **Auto-Code:** `st autocode <id>` (queues task for autonomous execution via Agent Hub subagents)

### 🛠️ Dev Tools (`dt`)
Cross-project quality assurance wrapper.
- **Full Check:** `dt --check` (runs lint, types, tests for all projects)
- **Quick Check:** `dt --quick` (runs lint/types only)
- **Frontend Only:** `dt --frontend-only` (runs Biome/TSC)
- **Auto-Fix:** `dt --fix` (fixes formatting/linting issues)

### 📦 Commit Tool (`scripts/sf-commit.sh`)
Streamlined commit workflow that runs quality gates and formats messages.
- **Commit:** `scripts/sf-commit.sh --msg "Commit message"`
- **Commit & Push:** `scripts/sf-commit.sh --push --msg "Commit message"`
- **Commit for Task:** `scripts/sf-commit.sh --task <id> --msg "Commit message"`
- **Skip Checks:** `scripts/sf-commit.sh --skip-checks --msg "WIP"` (use sparingly)

---

## 📁 Repository Structure

- `backend/`: Python API server, database models, and background tasks.
- `frontend/`: Next.js application, UI components, and client-side logic.
- `packages/`: Shared libraries (`agent-hub-client` for Python, `passport-client` for TS).
- `AGENTS.md`: This file. Read it before starting any task.

---

## 🐍 Backend (Python)

**Location:** `/backend`
**Stack:** Python 3.13, FastAPI, SQLAlchemy (Async), Pydantic v2, Celery.

### 🛠 Build & Environment
- **Dependency Management:** Uses `uv` (or standard pip).
- **Install Dependencies:**
  ```bash
  cd backend && uv sync
  ```
- **Run Dev Server:**
  ```bash
  # From /backend
  fastapi dev app/main.py
  ```
- **Database Migrations:**
  ```bash
  cd backend
  alembic upgrade head
  ```

### 🧪 Testing & Quality (via `dt` or manual)
**Recommended:** `dt --check` (runs everything)

**Manual Commands:**
- **Run All Tests:** `pytest`
- **Run Single Test File:** `pytest tests/api/test_sessions.py`
- **Run Single Test Case:** `pytest tests/api/test_sessions.py::TestSessions::test_create_session`
- **Debug Output:** `pytest -vv -s`
- **Lint/Format:** `ruff check . --fix` / `ruff format .`
- **Type Check:** `mypy .`

### 🐛 Debugging
Use the `app.core.debug` module for logging, NOT `print()`.
```python
from app.core.debug import debug, debug_timer
debug("Processing item", item_id=123)
with debug_timer("db_query"):
    await db.execute(...)
```

### 📝 Python Style Guidelines
- **Naming:** `snake_case` for variables/functions, `PascalCase` for classes.
- **Typing:** Strict type hints are REQUIRED. Use `typing.Optional`, `typing.List` or standard collections.
- **Async:** Prefer async IO. Await DB calls.
- **Pydantic:** Use `BaseModel` for API schemas.
- **Imports:** Absolute imports preferred (`from app.services import ...`).

---

## ⚛️ Frontend (TypeScript)

**Location:** `/frontend`
**Stack:** Next.js 16 (App Router), React 19, Tailwind CSS v4, Biome.

### 🛠 Build & Environment
- **Install Dependencies:**
  ```bash
  cd frontend && npm install
  ```
- **Run Dev Server:**
  ```bash
  npm run dev
  ```

### 🧪 Testing & Quality (via `dt` or manual)
**Recommended:** `dt --check` or `dt --frontend-only`

**Manual Commands:**
- **Unit/Integration:** `npm run test`
- **Single Test:** `npx vitest src/components/chat/message-list.test.tsx`
- **E2E Tests:** `npm run test:e2e`
- **Lint/Format:** `npm run lint:fix` (Biome)

### 📝 TypeScript Style Guidelines
- **Components:** Functional components using `interface` for props.
- **Imports:** Use `@/` alias for `src/` (e.g., `import { Button } from '@/components/ui/button'`).
- **Styling:** Tailwind utility classes.
- **Naming:**
  - **Components:** `PascalCase` (e.g., `MessageBubble.tsx`).
  - **Files:** Mostly `kebab-case` (e.g., `message-utils.ts`), check neighbors for consistency.
  - **Hooks:** `usePascalCase` (e.g., `useSessionStream`).

---

## 🌐 Common Operational Mandates

### 1. Safety & Validation
- **Read First:** Always `read` a file before modifying it to understand imports and context.
- **No Assumptions:** Do not assume a library is installed. Check `pyproject.toml` or `package.json`.
- **Absolute Paths:** Tools require absolute paths (e.g., `/home/kasadis/agent-hub/backend/app/main.py`).

### 2. File Operations
- **New Files:** Place them in the correct directory (e.g., `backend/app/api/endpoints/` for new routes).
- **Cleanup:** If you create temporary files, delete them.
- **Structure:** Follow the existing project structure. Do not create new top-level directories without strong reason.

### 3. Git Protocol
- **Commits:** Only commit when explicitly asked.
- **Messages:** Use conventional commits (`feat:`, `fix:`, `chore:`, `refactor:`).
- **Branches:** Create feature branches if complex changes are requested.

### 4. Agent Persona
- **Direct Action:** Do not chat about what you *will* do. Just plan, then execute.
- **Concise Output:** Keep responses short. Use tool outputs to convey success/failure.
- **Proactive Fixes:** If a test fails, fix it immediately. Do not ask for permission to fix your own broken code.

### 5. Shared Packages
- **Location:** `/packages`
- **Clients:** `agent-hub-client` (Python) and `passport-client` (TS) are shared libraries.
- **Versioning:** Be careful when changing these as they affect both ends of the stack.

---

## 🔍 Context & Rules
- **Cursor/Copilot:** No specific rule files found (`.cursor/rules` or `.github/copilot-instructions.md`).
- **CLAUDE.md:** Check this file for memory system context if needed.
- **System Prompt:** Adhere to "Core Mandates" regarding strictly mimicking existing style and conventions.
