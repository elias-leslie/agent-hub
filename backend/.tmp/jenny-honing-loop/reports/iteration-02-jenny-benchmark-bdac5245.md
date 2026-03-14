# Jenny Model Benchmark

**Benchmark ID:** `jenny-benchmark-bdac5245`
**Project ID:** `agent-hub`
**Models:** `codex/gpt-5.4`, `codex/gpt-5.3-codex`, `codex/gpt-5.3-codex-spark`, `codex/gpt-5.2`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`
**Cases:** `ready_task_dispatch`, `same_task_overlap`, `same_task_recent_progress`, `cleanup_blocks_closeout`, `session_patience_quiet`, `session_patience_recent_progress`, `stalled_session_reconcile`, `workspace_inspection_gate`, `precision_search_architecture`, `precision_search_live_lookup`, `review_request_routes_to_reviewer`, `dead_code_cleanup_followthrough`, `feedback_triage_hotspot`, `performance_review_honing`, `model_config_reconsideration`
**Runs per case:** 1
**Started:** 2026-03-14T18:53:31.925244+00:00
**Completed:** 2026-03-14T18:53:32.111866+00:00

## Ranking

| Rank | Model | Avg Score | Pass Rate | Infra Failures | Model Failures | Avg Latency (ms) | Avg Tokens | Avg Turns | Avg Tool Calls |
|------|-------|-----------|-----------|----------------|----------------|------------------|------------|-----------|----------------|
| 1 | `codex/gpt-5.4` | 0.0 | 0.0% | 0 | 15 | 1 | 0 | 0.0 | 0.0 |
| 2 | `codex/gpt-5.2` | 0.0 | 0.0% | 0 | 15 | 1 | 0 | 0.0 | 0.0 |
| 3 | `codex/gpt-5.3-codex` | 0.0 | 0.0% | 0 | 15 | 1 | 0 | 0.0 | 0.0 |
| 4 | `claude-sonnet-4-6` | 0.0 | 0.0% | 0 | 15 | 1 | 0 | 0.0 | 0.0 |
| 5 | `codex/gpt-5.3-codex-spark` | 0.0 | 0.0% | 0 | 15 | 1 | 0 | 0.0 | 0.0 |
| 6 | `claude-haiku-4-5` | 0.0 | 0.0% | 0 | 15 | 1 | 0 | 0.0 | 0.0 |
| 7 | `claude-opus-4-6` | 0.0 | 0.0% | 0 | 15 | 2 | 0 | 0.0 | 0.0 |

## Attempt Details

| Model | Case | Run | Score | Latency (ms) | Tokens | Turns | Tool Calls | Used Tools | Outcome | Detail |
|-------|------|-----|-------|--------------|--------|-------|------------|------------|---------|--------|
| claude-haiku-4-5 | cleanup_blocks_closeout | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | dead_code_cleanup_followthrough | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | feedback_triage_hotspot | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | model_config_reconsideration | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | performance_review_honing | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | precision_search_architecture | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | precision_search_live_lookup | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | ready_task_dispatch | 1 | 0.0 | 3 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | review_request_routes_to_reviewer | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | same_task_overlap | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | same_task_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | session_patience_quiet | 1 | 0.0 | 4 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | session_patience_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | stalled_session_reconcile | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-haiku-4-5 | workspace_inspection_gate | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | cleanup_blocks_closeout | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | dead_code_cleanup_followthrough | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | feedback_triage_hotspot | 1 | 0.0 | 18 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | model_config_reconsideration | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | performance_review_honing | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | precision_search_architecture | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | precision_search_live_lookup | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | ready_task_dispatch | 1 | 0.0 | 0 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | review_request_routes_to_reviewer | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | same_task_overlap | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | same_task_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | session_patience_quiet | 1 | 0.0 | 0 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | session_patience_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | stalled_session_reconcile | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-opus-4-6 | workspace_inspection_gate | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | cleanup_blocks_closeout | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | dead_code_cleanup_followthrough | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | feedback_triage_hotspot | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | model_config_reconsideration | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | performance_review_honing | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | precision_search_architecture | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | precision_search_live_lookup | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | ready_task_dispatch | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | review_request_routes_to_reviewer | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | same_task_overlap | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | same_task_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | session_patience_quiet | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | session_patience_recent_progress | 1 | 0.0 | 0 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | stalled_session_reconcile | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| claude-sonnet-4-6 | workspace_inspection_gate | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | cleanup_blocks_closeout | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | dead_code_cleanup_followthrough | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | feedback_triage_hotspot | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | model_config_reconsideration | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | performance_review_honing | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | precision_search_architecture | 1 | 0.0 | 0 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | precision_search_live_lookup | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | ready_task_dispatch | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | review_request_routes_to_reviewer | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | same_task_overlap | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | same_task_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | session_patience_quiet | 1 | 0.0 | 0 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | session_patience_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | stalled_session_reconcile | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.2 | workspace_inspection_gate | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | cleanup_blocks_closeout | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | dead_code_cleanup_followthrough | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | feedback_triage_hotspot | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | model_config_reconsideration | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | performance_review_honing | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | precision_search_architecture | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | precision_search_live_lookup | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | ready_task_dispatch | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | review_request_routes_to_reviewer | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | same_task_overlap | 1 | 0.0 | 0 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | same_task_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | session_patience_quiet | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | session_patience_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | stalled_session_reconcile | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex | workspace_inspection_gate | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | cleanup_blocks_closeout | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | dead_code_cleanup_followthrough | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | feedback_triage_hotspot | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | model_config_reconsideration | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | performance_review_honing | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | precision_search_architecture | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | precision_search_live_lookup | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | ready_task_dispatch | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | review_request_routes_to_reviewer | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | same_task_overlap | 1 | 0.0 | 2 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | same_task_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | session_patience_quiet | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | session_patience_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | stalled_session_reconcile | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.3-codex-spark | workspace_inspection_gate | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | cleanup_blocks_closeout | 1 | 0.0 | 0 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | dead_code_cleanup_followthrough | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | feedback_triage_hotspot | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | model_config_reconsideration | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | performance_review_honing | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | precision_search_architecture | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | precision_search_live_lookup | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | ready_task_dispatch | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | review_request_routes_to_reviewer | 1 | 0.0 | 0 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | same_task_overlap | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | same_task_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | session_patience_quiet | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | session_patience_recent_progress | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | stalled_session_reconcile | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
| codex/gpt-5.4 | workspace_inspection_gate | 1 | 0.0 | 1 | 0 | 0 | 0 |  | MODEL | All connection attempts failed |
