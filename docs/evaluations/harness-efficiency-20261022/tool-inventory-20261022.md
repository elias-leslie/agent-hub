# Native tool use, 15–22 October 2026

Window: `2026-10-15T21:37:43Z` through `2026-10-22T21:37:43Z` (seven days). This is a direct-tool inventory from native Codex, Claude Code, and Pi transcripts, counted by event time and unique native call ID. Case-only `Bash`/`bash`, `Read`/`read`, `Write`/`write`, and `Edit`/`edit` names are grouped. Distinct APIs remain distinct.

**88,990 calls**, **88,987 matched results**, **270.29 MiB returned text**, and **45 tool names**. Sources: 431 Codex files, 1,231 Claude Code files, and 29 Pi files; all scanned without parse errors. Three calls had no matched result by the cutoff.

Returned-text size counts UTF-8 text result blocks only. It excludes images and other nontext payloads, is not a token count, and does not establish how much stayed in a model's active context. `exec` is a Codex wrapper that can invoke nested tools: do not add Agent Hub's nested child-call projections to these direct call counts or text sizes. Tool names alone do not establish whether work was administrative or productive. The source files were read for this aggregate only; raw prompts, tool results, and credentials are not reproduced here.

## All tools, sorted by call frequency

The first 25 rows are the top 25 by frequency. `Output rank` identifies the separate output-size ranking below.

| Call rank | Tool | Calls | Matched results | Returned text | Output rank |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | `Bash` | 63,533 | 63,533 | 156.09 MiB | 1 |
| 2 | `exec` | 15,974 | 15,973 | 96.70 MiB | 2 |
| 3 | `Read` | 3,321 | 3,321 | 12.68 MiB | 3 |
| 4 | `Write` | 1,135 | 1,134 | 187.7 KiB | 10 |
| 5 | `StructuredOutput` | 704 | 704 | 29.1 KiB | 16 |
| 6 | `send_message` | 546 | 546 | 0 B | 44 |
| 7 | `Edit` | 534 | 533 | 71.3 KiB | 14 |
| 8 | `SendMessage` | 489 | 489 | 103.9 KiB | 12 |
| 9 | `sleep` | 373 | 373 | 16.0 KiB | 18 |
| 10 | `js` | 279 | 279 | 2.11 MiB | 4 |
| 11 | `ToolSearch` | 244 | 244 | 0 B | 45 |
| 12 | `Skill` | 236 | 236 | 7.5 KiB | 21 |
| 13 | `wait_agent` | 218 | 218 | 10.7 KiB | 19 |
| 14 | `Agent` | 217 | 217 | 216.7 KiB | 9 |
| 15 | `wait` | 198 | 198 | 554.5 KiB | 6 |
| 16 | `WebFetch` | 183 | 183 | 603.9 KiB | 5 |
| 17 | `Monitor` | 155 | 155 | 50.4 KiB | 15 |
| 18 | `WebSearch` | 121 | 121 | 388.0 KiB | 7 |
| 19 | `spawn_agent` | 100 | 100 | 4.3 KiB | 23 |
| 20 | `TaskStop` | 97 | 97 | 74.1 KiB | 13 |
| 21 | `Workflow` | 96 | 96 | 122.2 KiB | 11 |
| 22 | `followup_task` | 64 | 64 | 46 B | 40 |
| 23 | `list_agents` | 64 | 64 | 290.8 KiB | 8 |
| 24 | `AskUserQuestion` | 33 | 33 | 21.3 KiB | 17 |
| 25 | `request_user_input_async` | 18 | 18 | 306 B | 35 |
| 26 | `mcp__claude-in-chrome__computer` | 15 | 15 | 5.1 KiB | 22 |
| 27 | `mcp__claude-in-chrome__tabs_context_mcp` | 6 | 6 | 2.7 KiB | 25 |
| 28 | `ExitPlanMode` | 5 | 5 | 10.6 KiB | 20 |
| 29 | `mcp__claude-in-chrome__list_connected_browsers` | 4 | 4 | 8 B | 43 |
| 30 | `interrupt_agent` | 3 | 3 | 87 B | 38 |
| 31 | `ListAgents` | 3 | 3 | 1.2 KiB | 28 |
| 32 | `mcp__claude-in-chrome__browser_batch` | 3 | 3 | 1.1 KiB | 29 |
| 33 | `mcp__claude-in-chrome__navigate` | 3 | 3 | 1.7 KiB | 27 |
| 34 | `ScheduleWakeup` | 3 | 3 | 716 B | 31 |
| 35 | `Artifact` | 2 | 2 | 2.1 KiB | 26 |
| 36 | `mcp__claude-in-chrome__tabs_close_mcp` | 2 | 2 | 554 B | 32 |
| 37 | `bash_placeholder` | 1 | 1 | 80 B | 39 |
| 38 | `CronCreate` | 1 | 1 | 169 B | 37 |
| 39 | `CronDelete` | 1 | 1 | 23 B | 42 |
| 40 | `mcp__claude-in-chrome__find` | 1 | 1 | 369 B | 34 |
| 41 | `mcp__claude-in-chrome__get_page_text` | 1 | 1 | 402 B | 33 |
| 42 | `mcp__claude-in-chrome__javascript_tool` | 1 | 1 | 2.9 KiB | 24 |
| 43 | `mcp__claude-in-chrome__read_page` | 1 | 1 | 909 B | 30 |
| 44 | `RemoteTrigger` | 1 | 1 | 37 B | 41 |
| 45 | `SendFeedback` | 1 | 1 | 179 B | 36 |

## Top 25 by returned text size

| Output rank | Tool | Returned text | Calls |
| ---: | --- | ---: | ---: |
| 1 | `Bash` | 156.09 MiB | 63,533 |
| 2 | `exec` | 96.70 MiB | 15,974 |
| 3 | `Read` | 12.68 MiB | 3,321 |
| 4 | `js` | 2.11 MiB | 279 |
| 5 | `WebFetch` | 603.9 KiB | 183 |
| 6 | `wait` | 554.5 KiB | 198 |
| 7 | `WebSearch` | 388.0 KiB | 121 |
| 8 | `list_agents` | 290.8 KiB | 64 |
| 9 | `Agent` | 216.7 KiB | 217 |
| 10 | `Write` | 187.7 KiB | 1,135 |
| 11 | `Workflow` | 122.2 KiB | 96 |
| 12 | `SendMessage` | 103.9 KiB | 489 |
| 13 | `TaskStop` | 74.1 KiB | 97 |
| 14 | `Edit` | 71.3 KiB | 534 |
| 15 | `Monitor` | 50.4 KiB | 155 |
| 16 | `StructuredOutput` | 29.1 KiB | 704 |
| 17 | `AskUserQuestion` | 21.3 KiB | 33 |
| 18 | `sleep` | 16.0 KiB | 373 |
| 19 | `wait_agent` | 10.7 KiB | 218 |
| 20 | `ExitPlanMode` | 10.6 KiB | 5 |
| 21 | `Skill` | 7.5 KiB | 236 |
| 22 | `mcp__claude-in-chrome__computer` | 5.1 KiB | 15 |
| 23 | `spawn_agent` | 4.3 KiB | 100 |
| 24 | `mcp__claude-in-chrome__javascript_tool` | 2.9 KiB | 1 |
| 25 | `mcp__claude-in-chrome__tabs_context_mcp` | 2.7 KiB | 6 |

## Interpretation

`Bash` and `exec` together account for 79,507 direct calls (89.3%) and 252.78 MiB of returned text (93.5%). That is the largest context-output review opportunity; it is not an estimate of wasted tokens. The seven-day source coverage contains direct tool-using Codex, Claude Code, and Pi transcripts. It does not support a separate Agent Hub or Antigravity native-tool ranking.

