# Timestamp Consistency Fixes

## Background

A previous session discovered that naive datetime usage (`datetime.now()` and `datetime.utcnow()`) was causing timezone-related bugs across the codebase. The memory system was partially fixed, but many other files still have issues.

**Root Cause:** Python's `datetime.now()` and `datetime.utcnow()` return naive (timezone-unaware) datetime objects. When these are stored to databases or compared with timezone-aware datetimes, bugs occur.

**Correct Patterns:**
- `datetime.now(UTC)` - timezone-aware UTC datetime (requires `from datetime import UTC`)
- `utc_now()` from `graphiti_core.utils.datetime_utils` - Graphiti's helper (used in memory service)

## Your Tasks

### 1. EXPLORE: Find All Remaining Issues

Search the entire backend codebase for:
- `datetime.now()` without UTC
- `datetime.utcnow()` (deprecated in Python 3.12+)
- Any other naive datetime patterns

Categorize each finding:
- **Critical:** Stored to database/Neo4j/Redis
- **Medium:** Used in comparisons or API responses
- **Low:** Local timing calculations only (delta between two calls)

### 2. FIX: Apply Consistent Patterns

For each critical/medium issue:
- Add `from datetime import UTC, datetime` import
- Replace `datetime.now()` with `datetime.now(UTC)`
- Replace `datetime.utcnow()` with `datetime.now(UTC)`

### 3. TEST: Verify Nothing Broke

Run the test suite:
```bash
cd backend && source .venv/bin/activate
pytest tests/ -v --tb=short
```

Manually verify key endpoints:
```bash
# Memory system
curl -s "http://localhost:8003/api/memory/health" | jq
curl -s "http://localhost:8003/api/memory/list?limit=3" | jq '.episodes[0].created_at'
curl -s "http://localhost:8003/api/memory/stats" | jq '.last_updated'

# API keys (if auth system uses timestamps)
curl -s "http://localhost:8003/api/api-keys" -H "Authorization: Bearer ..." | jq

# Admin kill switch (if applicable)
curl -s "http://localhost:8003/api/admin/clients" | jq '.[0].disabled_at'
```

### 4. VALIDATE: Ensure Nothing Was Missed

After fixes, run comprehensive searches:
```bash
# Should return ZERO results (excluding tests and acceptable patterns)
grep -rn "datetime\.now()" backend/app/ | grep -v "datetime.now(UTC)" | grep -v "\.pyc"
grep -rn "datetime\.utcnow()" backend/app/ | grep -v "\.pyc"
```

Check imports are correct:
```bash
# All files using datetime should import UTC
grep -l "datetime\.now(UTC)" backend/app/ -r | xargs -I {} sh -c 'grep -L "from datetime import.*UTC" {} && echo "MISSING UTC IMPORT: {}"'
```

### 5. DOCUMENT: Update Findings

Update this file or create a summary of:
- Files modified
- Any issues that couldn't be fixed (and why)
- Any new patterns discovered

## Known Issues from Previous Session

These were identified but NOT fixed:

| File | Lines | Issue |
|------|-------|-------|
| `app/tasks/session_cleanup.py` | 44, 90 | `datetime.utcnow()` |
| `app/storage/feedback.py` | 80 | `datetime.utcnow()` |
| `app/services/response_cache.py` | 239 | `datetime.utcnow().isoformat()` |
| `app/services/api_key_auth.py` | 91, 100 | `datetime.utcnow()` |
| `app/services/stream_registry.py` | 97, 116, 202 | `datetime.utcnow().isoformat()` |
| `app/api/analytics.py` | 93, 443 | `datetime.utcnow()` |
| `app/api/admin.py` | 119, 206, 215, 341, 350, 461, 470 | `datetime.utcnow()` (7 instances) |
| `app/api/api_keys.py` | 95 | `datetime.utcnow()` |
| `scripts/migrate_rules_to_graphiti.py` | 789 | `datetime.now()` |

Also check:
- `app/services/orchestration/parallel.py` - timing results
- `app/services/orchestration/subagent.py` - timing results
- Any new files created since the last audit

## Additional Cleanup (Optional)

If time permits:
1. Dead code in `services/memory/service.py` - `_map_episode_type()` has unreachable `EpisodeType.message` condition
2. Hardcoded `group_ids=["global"]` in `services/memory/promotion.py` ignores user scope
3. Consider adding a pre-commit hook or linting rule to prevent future naive datetime usage

## Success Criteria

- [ ] All `datetime.utcnow()` calls replaced with `datetime.now(UTC)`
- [ ] All `datetime.now()` calls (stored to DB) replaced with `datetime.now(UTC)`
- [ ] Test suite passes
- [ ] Key API endpoints return timezone-aware timestamps
- [ ] Grep searches return zero results for naive datetime patterns
- [ ] No import errors when starting the application
