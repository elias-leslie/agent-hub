# Datetime/Timezone Audit Report

**Date:** 2026-01-20
**Auditor:** Claude Code with Gemini Pro consultation
**Scope:** agent-hub, portfolio-ai, summitflow, terminal

## Executive Summary

**PostgreSQL Server Timezone:** `America/New_York` (NOT UTC)

| Project | Schema Type | Python Pattern | Critical Bugs | Risk Level |
|---------|-------------|----------------|---------------|------------|
| **Agent Hub** | TIMESTAMP (naive) | `func.now()` + `datetime.now(UTC)` | **2 confirmed** | **CRITICAL** |
| **Portfolio AI** | TIMESTAMPTZ | Mixed naive/aware | 3 potential | HIGH |
| **SummitFlow** | TIMESTAMPTZ | Mixed naive/aware | 2 potential | MEDIUM |
| **Terminal** | TIMESTAMPTZ | `datetime.now(timezone.utc)` | 0 | LOW |

**Recommended Strategy:** Option A - Migrate all to TIMESTAMPTZ + `datetime.now(UTC)`

---

## Database Schema Analysis

### Agent Hub (32 columns - ALL NAIVE)
```
api_keys: created_at, expires_at, last_used_at
sessions: created_at, updated_at
messages: created_at
... (all timestamp without time zone)
```
**Risk:** All timestamps stored as NY time. Python code uses UTC. Comparisons WILL crash.

### Portfolio AI (80+ columns - ALL TIMESTAMPTZ)
Database correctly uses `timestamp with time zone`. Python code has inconsistent patterns.

### SummitFlow (60+ columns - MOSTLY TIMESTAMPTZ)
Database correctly configured except `celery_taskmeta` (third-party, OK to ignore).

### Terminal (5 columns - ALL TIMESTAMPTZ)
Fully compliant. Uses `datetime.now(timezone.utc)` consistently.

---

## Critical Bugs Identified

### 1. Agent Hub: api_key_auth.py:91 (CONFIRMED CRASH)
```python
# WILL CRASH: TypeError: can't compare offset-naive and offset-aware datetimes
if key_record.expires_at and key_record.expires_at < datetime.now(UTC):
```
- `expires_at` from DB is naive (NY time)
- `datetime.now(UTC)` is timezone-aware
- **Any expired API key check crashes the service**

### 2. Agent Hub: api_key_auth.py:100 (DATA CORRUPTION)
```python
await db.execute(...values(last_used_at=datetime.now(UTC)))
```
- Writing UTC-aware to naive column
- SQLAlchemy strips timezone, stores UTC value as if it were NY time
- **last_used_at is 4-5 hours wrong relative to other timestamps**

### 3. Portfolio AI: backtest/storage.py (Multiple locations)
Lines 64, 98, 182, 240, 295 use `datetime.now()` (naive) with TIMESTAMPTZ columns.
May cause psycopg3 conversion issues or silent timezone assumption.

### 4. Portfolio AI: market/sentiment.py:318 (Deprecated)
```python
last_updated=datetime.utcnow().isoformat()  # Deprecated in Python 3.12+
```

### 5. SummitFlow: storage/qa_issues.py:150, 194 (Deprecated)
```python
datetime.utcnow()  # Deprecated, returns naive datetime
```

---

## Gemini Pro Recommendation

> **Option A (TIMESTAMPTZ + datetime.now(UTC)) is the "Gold Standard"** for PostgreSQL + SQLAlchemy.
>
> Key reasons:
> 1. TIMESTAMPTZ stores UTC internally, converts on display
> 2. Your NY server timezone makes Option B dangerous (func.now() = NY, Python = UTC)
> 3. Only TIMESTAMPTZ handles DST transitions correctly
> 4. Shared databases mandate consistency across all 4 projects

---

## Migration Strategy

### Phase 1: Agent Hub Schema Migration (CRITICAL)

**Alembic migration needed:**
```sql
-- Interpret existing naive timestamps as NY time (which they are)
ALTER TABLE api_keys
  ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'America/New_York';

ALTER TABLE api_keys
  ALTER COLUMN expires_at TYPE TIMESTAMPTZ USING expires_at AT TIME ZONE 'America/New_York';

-- etc for all 32 columns
```

**SQLAlchemy model changes:**
```python
# Before
created_at = Column(DateTime, default=func.now(), nullable=False)

# After
created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### Phase 2: Python Code Standardization

**All projects must use:**
```python
from datetime import UTC, datetime

# Correct
now = datetime.now(UTC)
cutoff = datetime.now(UTC) - timedelta(days=7)

# Wrong - remove all of these:
datetime.now()        # Naive local time
datetime.utcnow()     # Deprecated, returns naive
```

### Phase 3: Add Linting Rules

Create custom ruff rule or pre-commit hook to catch:
- `datetime.now()` without timezone
- `datetime.utcnow()` (deprecated)
- `Column(DateTime)` without `timezone=True`

---

## Files Requiring Changes

### Agent Hub (CRITICAL - Fix First)
| File | Lines | Issue |
|------|-------|-------|
| `models.py` | All DateTime columns | Add `timezone=True` |
| `api_key_auth.py` | 14, 91, 100 | Already uses UTC, but comparing with naive DB |
| `agent_service.py` | Multiple | Review all datetime usage |

### Portfolio AI (HIGH)
| File | Lines | Issue |
|------|-------|-------|
| `backtest/storage.py` | 64, 98, 182, 240, 295 | `datetime.now()` → `datetime.now(UTC)` |
| `market/sentiment.py` | 318 | `utcnow()` → `now(UTC)` |
| `api/backup.py` | 165, 172, 238, 257, 263, 365 | Naive datetime usage |
| `tasks/artifact_tasks.py` | 87, 108, 114 | Naive cutoff comparisons |
| `portfolio/models.py` | 20-21, 34-35, 50 | Naive defaults |

### SummitFlow (MEDIUM)
| File | Lines | Issue |
|------|-------|-------|
| `storage/qa_issues.py` | 150, 194 | `utcnow()` → `now(UTC)` |
| `storage/backups.py` | 91 | Naive datetime in naming |
| `services/evidence/capture_orchestrator.py` | 82, 137, 276 | Naive datetime |
| `tasks/evidence_tasks.py` | 97, 111 | Naive cutoff/mtime |

### Terminal (LOW - Already Compliant)
No changes needed. Uses `datetime.now(timezone.utc)` consistently.

---

## PostgreSQL Tool Recommendations

For ongoing database quality, add to `dt` (dev-tools.sh):

### 1. sqlfluff (SQL Linting)
- Lint SQL migrations for consistent TIMESTAMPTZ usage
- Auto-format SQL files
- Can enforce dialect-specific rules

```bash
# Install
pip install sqlfluff

# Usage in dt
dt sqlfluff              # Lint migrations
sqlfluff lint --dialect postgres ./migrations/
```

### 2. squawk (Migration Safety)
- Catches unsafe migration patterns
- Validates zero-downtime migrations
- Prevents common PostgreSQL anti-patterns

```bash
# Install
pip install squawk-cli

# Usage in dt
dt squawk                # Check migrations
squawk ./migrations/*.sql
```

### Integration with dev-tools.sh

Add to `TOOL_DEFS`:
```bash
TOOL_DEFS[sqlfluff]='SQLFLUFF|sqlfluff|lint --dialect postgres|wc_l|root|1|1'
TOOL_DEFS[squawk]='SQUAWK|squawk||wc_l|root|1|1'
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| API key check crash | HIGH | Service down | Fix api_key_auth.py first |
| Data interpretation wrong in migration | MEDIUM | Silent data corruption | Test migration on staging first |
| DST bugs in date arithmetic | LOW | Incorrect time calculations | Use UTC consistently |
| Third-party library incompatibility | LOW | Build failures | Test all integrations |

---

## Acceptance Criteria for Remediation

1. **Zero naive datetime comparisons** - grep for `datetime.now()` returns 0
2. **All Agent Hub columns TIMESTAMPTZ** - schema introspection confirms
3. **All datetime.utcnow() removed** - grep returns 0
4. **dt sqlfluff passes** - SQL linting clean
5. **dt squawk passes** - Migration safety verified
6. **Integration tests pass** - Existing test suite green

---

## Rollback Procedure

**Migration ID:** `cd269ebb1e0d`

If the TIMESTAMPTZ migration causes issues, rollback with:

```bash
# Navigate to agent-hub backend
cd ~/agent-hub

# Downgrade to previous migration
ALEMBIC_CONFIG=backend/alembic.ini backend/.venv/bin/alembic downgrade e5f6g7h8i9j0
```

This will:
1. Convert all 32 TIMESTAMPTZ columns back to TIMESTAMP
2. Use `AT TIME ZONE 'America/New_York'` to preserve time values
3. Leave timestamps in naive NY local time (original state)

**Post-rollback changes needed:**
1. Revert `models.py` - change `DateTime(timezone=True)` back to `DateTime`
2. Revert `api_key_auth.py` - the comparison bug will return

**Note:** Rollback should only be used in emergencies. The TIMESTAMPTZ migration fixes critical timezone bugs.

---

## Implementation Status

| Item | Status |
|------|--------|
| Alembic migration for Agent Hub schema | ✅ DONE |
| Fix api_key_auth.py bug | ✅ DONE |
| Standardize Python code - Portfolio AI | ✅ DONE |
| Standardize Python code - SummitFlow | ✅ DONE |
| Add sqlfluff/squawk to dev-tools.sh | ✅ DONE |
| Custom pre-commit hook for datetime patterns | ✅ DONE |
| Memory mandate added | ✅ DONE |

---

## Next Steps

1. ~~Create Alembic migration for Agent Hub schema~~ ✅
2. ~~Fix api_key_auth.py bug (highest priority)~~ ✅
3. ~~Standardize Python code across all projects~~ ✅
4. ~~Add sqlfluff/squawk to dev-tools.sh~~ ✅
5. ~~Add custom linting rule for datetime patterns~~ ✅
6. ~~Update memory system with timezone policy~~ ✅
