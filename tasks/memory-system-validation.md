# Memory System Validation & Consolidation Review

## Context

A fix was applied to the memory system on 2026-01-20 to resolve an issue where golden standards weren't appearing in the Memory dashboard. The changes were:

1. **`backend/app/services/memory/service.py`**:
   - Changed from `datetime.now()` to Graphiti's `utc_now()` for timezone-aware timestamps
   - Changed `EpisodeType.message` to `EpisodeType.text` per `episode-format-decision.md`

2. **Data migration**: `backend/scripts/fix_episode_timestamps.py` was run to convert existing `localdatetime` values to `datetime` with UTC timezone in Neo4j

## Validation Tasks

### 1. Verify the Fix Works End-to-End

- [ ] `/api/memory/list` returns ALL episodes (not just a subset)
- [ ] Golden standards appear in the Memory dashboard at `/memory`
- [ ] `/api/memory/golden-standards` and `/api/memory/list` return consistent data
- [ ] New episodes created via `/api/memory/save-learning` are retrievable
- [ ] New golden standards created via `/api/memory/golden-standards` (POST) appear in list
- [ ] Progressive context (`/api/memory/progressive-context`) includes golden standards in mandates

### 2. Check for Consistency Across All Memory Code

Review these files for consistent timestamp handling (should all use `utc_now()` or `datetime.now(timezone.utc)`):

- [ ] `backend/app/services/memory/service.py`
- [ ] `backend/app/services/memory/golden_standards.py`
- [ ] `backend/app/services/memory/episode_formatter.py`
- [ ] `backend/app/services/memory/context_injector.py`
- [ ] `backend/app/services/memory/learning_extractor.py`
- [ ] `backend/app/services/memory/promotion.py`
- [ ] `backend/app/services/memory/tools.py`
- [ ] `backend/app/api/memory.py`

### 3. Check Hooks/Scripts That Use Memory

- [ ] `~/.claude/hooks/SessionStart.sh` - Does it call memory APIs correctly?
- [ ] Any session end hooks that save learnings
- [ ] `backend/scripts/fix_episode_timestamps.py` - Should this be kept or removed?

### 4. Validate Frontend Memory Dashboard

- [ ] `/memory` page loads without errors
- [ ] Episodes display with correct categories, scopes, timestamps
- [ ] Search works
- [ ] Delete works
- [ ] Stats display correctly

## Consolidation & Optimization Opportunities

### Known Issues to Review

1. **Duplicate Endpoints**: We have BOTH:
   - `/api/memory/list` - uses Graphiti's `retrieve_episodes()`
   - `/api/memory/golden-standards` (GET) - queries Neo4j directly

   **Question**: Should these be consolidated? Can `/api/memory/list` handle everything with proper filtering?

2. **Episode Storage Methods**: We have:
   - `service.add_episode()` - for general episodes
   - `store_golden_standard()` - for golden standards
   - Episode formatter for structured formatting

   **Question**: Is there unnecessary duplication? Should all storage go through a single method?

3. **Category Inference**: `_infer_category()` in service.py infers category from source_description

   **Question**: Should category be explicitly stored/passed instead of inferred?

### Review Checklist

- [ ] Are there any other endpoints that do similar things that could be consolidated?
- [ ] Are there any unused memory endpoints that should be removed?
- [ ] Is the `EpisodeType` usage consistent across all storage paths?
- [ ] Is there dead code related to the old `EpisodeType.message` usage?
- [ ] Are the memory API response schemas consistent and complete?
- [ ] Is error handling consistent across all memory endpoints?

## Expected Outcome

1. Confirmation that the memory system works correctly end-to-end
2. List of any remaining inconsistencies or bugs found
3. Recommendations for consolidation with specific action items
4. Updated code if any quick fixes are needed

## Files Changed in Previous Session

For reference, these files were modified:
- `backend/app/services/memory/service.py` (timestamp and episode type fixes)
- `backend/scripts/fix_episode_timestamps.py` (new migration script)
