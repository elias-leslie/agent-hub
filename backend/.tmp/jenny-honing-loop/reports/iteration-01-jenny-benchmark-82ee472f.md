# Jenny Model Benchmark

**Benchmark ID:** `jenny-benchmark-82ee472f`
**Project ID:** `agent-hub`
**Models:** `codex/gpt-5.4`, `codex/gpt-5.3-codex`, `codex/gpt-5.3-codex-spark`, `codex/gpt-5.2`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`
**Cases:** `ready_task_dispatch`, `same_task_overlap`, `same_task_recent_progress`, `cleanup_blocks_closeout`, `session_patience_quiet`, `session_patience_recent_progress`, `stalled_session_reconcile`, `workspace_inspection_gate`, `precision_search_architecture`, `precision_search_live_lookup`, `review_request_routes_to_reviewer`, `dead_code_cleanup_followthrough`, `feedback_triage_hotspot`, `performance_review_honing`, `model_config_reconsideration`
**Runs per case:** 1
**Started:** 2026-03-14T18:12:24.637351+00:00
**Completed:** 2026-03-14T18:27:32.492533+00:00

## Ranking

| Rank | Model | Avg Score | Pass Rate | Infra Failures | Model Failures | Avg Latency (ms) | Avg Tokens | Avg Turns | Avg Tool Calls |
|------|-------|-----------|-----------|----------------|----------------|------------------|------------|-----------|----------------|
| 1 | `codex/gpt-5.4` | 100.0 | 100.0% | 0 | 0 | 4012 | 1910 | 1.3 | 0.7 |
| 2 | `codex/gpt-5.3-codex` | 100.0 | 100.0% | 0 | 0 | 4151 | 1921 | 1.3 | 0.6 |
| 3 | `codex/gpt-5.2` | 98.3 | 86.7% | 0 | 2 | 4904 | 1923 | 1.8 | 1.1 |
| 4 | `claude-haiku-4-5` | 97.7 | 86.7% | 0 | 2 | 17523 | 818 | 2.0 | 1.4 |
| 5 | `claude-sonnet-4-6` | 97.2 | 86.7% | 0 | 2 | 10619 | 187 | 1.3 | 0.7 |
| 6 | `claude-opus-4-6` | 97.2 | 73.3% | 0 | 4 | 13015 | 203 | 1.3 | 0.9 |
| 7 | `codex/gpt-5.3-codex-spark` | 91.1 | 80.0% | 0 | 3 | 6279 | 2166 | 2.7 | 2.0 |

## Attempt Details

| Model | Case | Run | Score | Latency (ms) | Tokens | Turns | Tool Calls | Used Tools | Outcome | Detail |
|-------|------|-----|-------|--------------|--------|-------|------------|------------|---------|--------|
| claude-haiku-4-5 | cleanup_blocks_closeout | 1 | 100.0 | 12542 | 1123 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | dead_code_cleanup_followthrough | 1 | 100.0 | 26063 | 1602 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | feedback_triage_hotspot | 1 | 100.0 | 18739 | 265 | 2 | 2 | mcp__agent-hub__manage_feedback | PASS |  |
| claude-haiku-4-5 | model_config_reconsideration | 1 | 83.0 | 36500 | 392 | 3 | 3 | mcp__agent-hub__manage_model_config, mcp__agent-hub__review_agent_performance | MODEL | summary_terms_missing: model, benchmark |
| claude-haiku-4-5 | performance_review_honing | 1 | 100.0 | 16484 | 353 | 1 | 2 | mcp__agent-hub__review_agent_performance, mcp__agent-hub__read_heartbeat_instructions | PASS |  |
| claude-haiku-4-5 | precision_search_architecture | 1 | 100.0 | 13731 | 1131 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | precision_search_live_lookup | 1 | 100.0 | 34209 | 158 | 8 | 8 | mcp__agent-hub__precision_code_search | PASS |  |
| claude-haiku-4-5 | ready_task_dispatch | 1 | 100.0 | 13533 | 1074 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | review_request_routes_to_reviewer | 1 | 100.0 | 15696 | 1052 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | same_task_overlap | 1 | 100.0 | 13520 | 1084 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | same_task_recent_progress | 1 | 100.0 | 9504 | 777 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | session_patience_quiet | 1 | 100.0 | 12688 | 1132 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | session_patience_recent_progress | 1 | 83.0 | 11445 | 974 | 1 | 0 |  | MODEL | summary_terms_missing: progress, wait |
| claude-haiku-4-5 | stalled_session_reconcile | 1 | 100.0 | 15421 | 1070 | 1 | 0 |  | PASS |  |
| claude-haiku-4-5 | workspace_inspection_gate | 1 | 100.0 | 12774 | 90 | 6 | 6 | Read | PASS |  |
| claude-opus-4-6 | cleanup_blocks_closeout | 1 | 100.0 | 9813 | 232 | 1 | 0 |  | PASS |  |
| claude-opus-4-6 | dead_code_cleanup_followthrough | 1 | 100.0 | 12705 | 300 | 1 | 0 |  | PASS |  |
| claude-opus-4-6 | feedback_triage_hotspot | 1 | 100.0 | 16254 | 149 | 3 | 3 | ToolSearch, mcp__agent-hub__manage_feedback | PASS |  |
| claude-opus-4-6 | model_config_reconsideration | 1 | 100.0 | 17738 | 94 | 2 | 3 | ToolSearch, mcp__agent-hub__manage_model_config, mcp__agent-hub__review_agent_performance | PASS |  |
| claude-opus-4-6 | performance_review_honing | 1 | 91.5 | 16633 | 92 | 2 | 3 | ToolSearch, mcp__agent-hub__review_agent_performance, mcp__agent-hub__read_heartbeat_instructions | MODEL | summary_terms_missing: performance |
| claude-opus-4-6 | precision_search_architecture | 1 | 100.0 | 12389 | 298 | 1 | 0 |  | PASS |  |
| claude-opus-4-6 | precision_search_live_lookup | 1 | 83.0 | 18223 | 241 | 2 | 3 | ToolSearch, mcp__agent-hub__precision_code_search | MODEL | summary_terms_missing: shared |
| claude-opus-4-6 | ready_task_dispatch | 1 | 100.0 | 12451 | 176 | 1 | 0 |  | PASS |  |
| claude-opus-4-6 | review_request_routes_to_reviewer | 1 | 91.5 | 11241 | 222 | 1 | 0 |  | MODEL | summary_terms_missing: findings |
| claude-opus-4-6 | same_task_overlap | 1 | 100.0 | 8341 | 180 | 1 | 0 |  | PASS |  |
| claude-opus-4-6 | same_task_recent_progress | 1 | 100.0 | 11485 | 186 | 1 | 0 |  | PASS |  |
| claude-opus-4-6 | session_patience_quiet | 1 | 100.0 | 10263 | 294 | 1 | 0 |  | PASS |  |
| claude-opus-4-6 | session_patience_recent_progress | 1 | 91.5 | 14390 | 243 | 1 | 0 |  | MODEL | summary_terms_missing: wait |
| claude-opus-4-6 | stalled_session_reconcile | 1 | 100.0 | 11492 | 257 | 1 | 0 |  | PASS |  |
| claude-opus-4-6 | workspace_inspection_gate | 1 | 100.0 | 11811 | 75 | 1 | 1 | Bash | PASS |  |
| claude-sonnet-4-6 | cleanup_blocks_closeout | 1 | 100.0 | 12451 | 270 | 1 | 0 |  | PASS |  |
| claude-sonnet-4-6 | dead_code_cleanup_followthrough | 1 | 100.0 | 9023 | 189 | 1 | 0 |  | PASS |  |
| claude-sonnet-4-6 | feedback_triage_hotspot | 1 | 100.0 | 14847 | 81 | 2 | 2 | ToolSearch, mcp__agent-hub__manage_feedback | PASS |  |
| claude-sonnet-4-6 | model_config_reconsideration | 1 | 100.0 | 18628 | 97 | 3 | 3 | ToolSearch, mcp__agent-hub__manage_model_config, mcp__agent-hub__review_agent_performance | PASS |  |
| claude-sonnet-4-6 | performance_review_honing | 1 | 100.0 | 15963 | 104 | 2 | 3 | ToolSearch, mcp__agent-hub__review_agent_performance, mcp__agent-hub__read_heartbeat_instructions | PASS |  |
| claude-sonnet-4-6 | precision_search_architecture | 1 | 100.0 | 8260 | 263 | 1 | 0 |  | PASS |  |
| claude-sonnet-4-6 | precision_search_live_lookup | 1 | 100.0 | 13120 | 168 | 2 | 2 | ToolSearch, mcp__agent-hub__precision_code_search | PASS |  |
| claude-sonnet-4-6 | ready_task_dispatch | 1 | 100.0 | 5979 | 180 | 1 | 0 |  | PASS |  |
| claude-sonnet-4-6 | review_request_routes_to_reviewer | 1 | 100.0 | 6922 | 233 | 1 | 0 |  | PASS |  |
| claude-sonnet-4-6 | same_task_overlap | 1 | 100.0 | 5648 | 175 | 1 | 0 |  | PASS |  |
| claude-sonnet-4-6 | same_task_recent_progress | 1 | 66.0 | 7442 | 184 | 1 | 0 |  | MODEL | wrong_fields: primary_action |
| claude-sonnet-4-6 | session_patience_quiet | 1 | 100.0 | 11446 | 380 | 1 | 0 |  | PASS |  |
| claude-sonnet-4-6 | session_patience_recent_progress | 1 | 91.5 | 6795 | 194 | 1 | 0 |  | MODEL | summary_terms_missing: wait |
| claude-sonnet-4-6 | stalled_session_reconcile | 1 | 100.0 | 11595 | 196 | 1 | 0 |  | PASS |  |
| claude-sonnet-4-6 | workspace_inspection_gate | 1 | 100.0 | 11172 | 84 | 1 | 1 | Bash | PASS |  |
| codex/gpt-5.2 | cleanup_blocks_closeout | 1 | 100.0 | 2921 | 2833 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | dead_code_cleanup_followthrough | 1 | 100.0 | 2191 | 2837 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | feedback_triage_hotspot | 1 | 100.0 | 4647 | 87 | 1 | 1 | manage_feedback | PASS |  |
| codex/gpt-5.2 | model_config_reconsideration | 1 | 91.5 | 15662 | 94 | 6 | 6 | manage_model_config, review_agent_performance | MODEL | summary_terms_missing: benchmark |
| codex/gpt-5.2 | performance_review_honing | 1 | 100.0 | 5683 | 106 | 2 | 2 | read_heartbeat_instructions, review_agent_performance | PASS |  |
| codex/gpt-5.2 | precision_search_architecture | 1 | 100.0 | 2323 | 2916 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | precision_search_live_lookup | 1 | 83.0 | 19029 | 100 | 5 | 5 | precision_code_search | MODEL | summary_terms_missing: shared |
| codex/gpt-5.2 | ready_task_dispatch | 1 | 100.0 | 2467 | 2841 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | review_request_routes_to_reviewer | 1 | 100.0 | 2278 | 2822 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | same_task_overlap | 1 | 100.0 | 2318 | 2825 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | same_task_recent_progress | 1 | 100.0 | 2114 | 2841 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | session_patience_quiet | 1 | 100.0 | 2363 | 2811 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | session_patience_recent_progress | 1 | 100.0 | 2163 | 2833 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | stalled_session_reconcile | 1 | 100.0 | 2239 | 2820 | 1 | 0 |  | PASS |  |
| codex/gpt-5.2 | workspace_inspection_gate | 1 | 100.0 | 5167 | 76 | 3 | 3 | read_file | PASS |  |
| codex/gpt-5.3-codex | cleanup_blocks_closeout | 1 | 100.0 | 2864 | 2832 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | dead_code_cleanup_followthrough | 1 | 100.0 | 2426 | 2843 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | feedback_triage_hotspot | 1 | 100.0 | 6645 | 89 | 1 | 1 | manage_feedback | PASS |  |
| codex/gpt-5.3-codex | model_config_reconsideration | 1 | 100.0 | 7792 | 97 | 2 | 2 | manage_model_config, review_agent_performance | PASS |  |
| codex/gpt-5.3-codex | performance_review_honing | 1 | 100.0 | 8365 | 88 | 2 | 2 | review_agent_performance, read_heartbeat_instructions | PASS |  |
| codex/gpt-5.3-codex | precision_search_architecture | 1 | 100.0 | 2541 | 2919 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | precision_search_live_lookup | 1 | 100.0 | 7091 | 91 | 1 | 1 | precision_code_search | PASS |  |
| codex/gpt-5.3-codex | ready_task_dispatch | 1 | 100.0 | 2496 | 2831 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | review_request_routes_to_reviewer | 1 | 100.0 | 2582 | 2830 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | same_task_overlap | 1 | 100.0 | 2321 | 2828 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | same_task_recent_progress | 1 | 100.0 | 2729 | 2842 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | session_patience_quiet | 1 | 100.0 | 2302 | 2810 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | session_patience_recent_progress | 1 | 100.0 | 3497 | 2837 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | stalled_session_reconcile | 1 | 100.0 | 2528 | 2813 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex | workspace_inspection_gate | 1 | 100.0 | 6088 | 71 | 3 | 3 | read_file | PASS |  |
| codex/gpt-5.3-codex-spark | cleanup_blocks_closeout | 1 | 100.0 | 1734 | 3086 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | dead_code_cleanup_followthrough | 1 | 100.0 | 1432 | 3336 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | feedback_triage_hotspot | 1 | 91.5 | 3664 | 87 | 1 | 1 | manage_feedback | MODEL | summary_terms_missing: triage |
| codex/gpt-5.3-codex-spark | model_config_reconsideration | 1 | 100.0 | 8443 | 108 | 4 | 4 | manage_model_config, review_agent_performance | PASS |  |
| codex/gpt-5.3-codex-spark | performance_review_honing | 1 | 100.0 | 3005 | 102 | 2 | 2 | read_heartbeat_instructions, review_agent_performance | PASS |  |
| codex/gpt-5.3-codex-spark | precision_search_architecture | 1 | 100.0 | 1158 | 3349 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | precision_search_live_lookup | 1 | 0.0 | 57305 | 82 | 20 | 20 | precision_code_search | MODEL | invalid_json: Expecting value: line 1 column 1 (char 0) |
| codex/gpt-5.3-codex-spark | ready_task_dispatch | 1 | 100.0 | 1128 | 3084 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | review_request_routes_to_reviewer | 1 | 100.0 | 1045 | 3134 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | same_task_overlap | 1 | 100.0 | 1072 | 3085 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | same_task_recent_progress | 1 | 100.0 | 1232 | 3042 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | session_patience_quiet | 1 | 100.0 | 2108 | 3021 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | session_patience_recent_progress | 1 | 74.5 | 1475 | 3748 | 1 | 0 |  | MODEL | wrong_fields: primary_action |
| codex/gpt-5.3-codex-spark | stalled_session_reconcile | 1 | 100.0 | 1259 | 3139 | 1 | 0 |  | PASS |  |
| codex/gpt-5.3-codex-spark | workspace_inspection_gate | 1 | 100.0 | 8125 | 81 | 3 | 3 | read_file | PASS |  |
| codex/gpt-5.4 | cleanup_blocks_closeout | 1 | 100.0 | 1939 | 2813 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | dead_code_cleanup_followthrough | 1 | 100.0 | 1957 | 2824 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | feedback_triage_hotspot | 1 | 100.0 | 4995 | 80 | 1 | 1 | manage_feedback | PASS |  |
| codex/gpt-5.4 | model_config_reconsideration | 1 | 100.0 | 14991 | 81 | 3 | 3 | manage_model_config, review_agent_performance | PASS |  |
| codex/gpt-5.4 | performance_review_honing | 1 | 100.0 | 5388 | 88 | 2 | 2 | review_agent_performance, read_heartbeat_instructions | PASS |  |
| codex/gpt-5.4 | precision_search_architecture | 1 | 100.0 | 3065 | 2911 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | precision_search_live_lookup | 1 | 100.0 | 5118 | 94 | 1 | 1 | precision_code_search | PASS |  |
| codex/gpt-5.4 | ready_task_dispatch | 1 | 100.0 | 2063 | 2816 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | review_request_routes_to_reviewer | 1 | 100.0 | 2315 | 2810 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | same_task_overlap | 1 | 100.0 | 1917 | 2812 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | same_task_recent_progress | 1 | 100.0 | 2489 | 2842 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | session_patience_quiet | 1 | 100.0 | 2050 | 2791 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | session_patience_recent_progress | 1 | 100.0 | 1938 | 2818 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | stalled_session_reconcile | 1 | 100.0 | 3450 | 2793 | 1 | 0 |  | PASS |  |
| codex/gpt-5.4 | workspace_inspection_gate | 1 | 100.0 | 6512 | 72 | 3 | 3 | read_file | PASS |  |
