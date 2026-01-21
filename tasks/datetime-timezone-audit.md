# Datetime/Timezone Audit - All Projects

## Context

A timezone mismatch bug was discovered in Agent Hub:
- PostgreSQL server runs in `America/New_York` timezone
- Database columns use `TIMESTAMP WITHOUT TIME ZONE` (naive)
- Python code uses `datetime.now(UTC)` (timezone-aware)
- This causes crashes when comparing DB values with Python datetime objects

**Confirmed latent bug:** `agent-hub/backend/app/services/api_key_auth.py:91` will crash when an expired API key is checked.

## Objective

Comprehensive audit of ALL projects to:
1. Identify all datetime/timezone mismatches
2. Document all latent bugs
3. Create a unified migration strategy
4. Ensure consistent timezone handling across the stack

## Scope

### Databases (all in single PostgreSQL instance)
```
AGENT_HUB_DB_URL    -> agent_hub database
DATABASE_URL        -> summitflow database
TERMINAL_DB_URL     -> summitflow database (same as above)
PORTFOLIO_AI_DB_URL -> portfolio_ai database
PORTFOLIO_DB_URL    -> portfolio_ai database (same as above)
```

### Projects to Audit

1. **Agent Hub** (`~/agent-hub`)
   - Backend: `~/agent-hub/backend/app/`
   - Models: `~/agent-hub/backend/app/models.py`
   - DB: `agent_hub`
   - Known issue: `api_key_auth.py:91`, `agent_service.py` (fixed partially)

2. **Portfolio AI** (`~/portfolio-ai`)
   - Backend: `~/portfolio-ai/backend/app/`
   - Models in: `watchlist/`, `rules/`, `strategies/`, `portfolio/`, `backtest/`
   - DB: `portfolio_ai`

3. **SummitFlow** (`~/summitflow`)
   - Backend: `~/summitflow/backend/app/`
   - Models: `services/explorer/models.py` and others
   - DB: `summitflow`

4. **Terminal** (`~/terminal`)
   - Backend: `~/terminal/terminal/`
   - Storage: `~/terminal/terminal/storage/`
   - DB: `summitflow` (shared with SummitFlow via DATABASE_URL)
   - Uses `datetime.now(timezone.utc)` in `terminal_lifecycle.py`

5. **Monkey Fight** (`~/monkey-fight`)
   - Type: Frontend/Node.js game (Vite + TypeScript)
   - DB: None (no PostgreSQL usage found)
   - **Skip from audit** - no database

## Audit Checklist

### Per Database
- [ ] Check PostgreSQL timezone setting: `SHOW timezone;`
- [ ] List all `timestamp` columns and their types (with/without timezone)
- [ ] Sample existing data to understand what timezone it represents

### Per Project
- [ ] Find all `DateTime` column definitions in SQLAlchemy models
- [ ] Check if `DateTime(timezone=True)` or `DateTime` (naive)
- [ ] Find all `datetime.now(UTC)` usages
- [ ] Find all `datetime.utcnow()` usages (deprecated)
- [ ] Find all `datetime.now()` usages (local time - problematic)
- [ ] Find all datetime comparisons between DB values and Python code
- [ ] Find all `.isoformat()` calls (API response format)
- [ ] Check frontend datetime parsing

### Search Patterns
```bash
# Find DateTime columns
grep -r "Column(DateTime" --include="*.py"

# Find timezone-aware datetime creation
grep -r "datetime.now(UTC)" --include="*.py"

# Find naive datetime creation
grep -rE "datetime\.(now\(\)|utcnow\(\))" --include="*.py"

# Find datetime comparisons
grep -rE "\.(created_at|updated_at|expires_at).*(<|>|<=|>=)" --include="*.py"

# Find isoformat calls
grep -r "\.isoformat()" --include="*.py"
```

## Deliverables

1. **Audit Report**
   - Table of all datetime columns across all DBs
   - List of all timezone-related bugs found
   - Risk assessment for each

2. **Migration Strategy**
   - Recommended approach (timezone-aware vs naive)
   - Order of operations (which DB/project first)
   - Rollback plan

3. **Implementation Plan**
   - Alembic migrations needed
   - Code changes required
   - Testing approach

## Decision Point

After audit, decide between:
- **Option A:** Migrate all to `TIMESTAMP WITH TIME ZONE` + `datetime.now(UTC)`
- **Option B:** Standardize on naive UTC (use `datetime.now(UTC).replace(tzinfo=None)`)
- **Option C:** Project-by-project based on needs

## Notes

- DB server is `America/New_York`, not UTC - existing naive timestamps represent Eastern time
- Changing to timezone-aware will interpret existing data as Eastern (which is correct)
- Frontend uses `new Date(timestamp)` - will work with either format for date display
