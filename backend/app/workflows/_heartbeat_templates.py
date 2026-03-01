"""Heartbeat prompt string constants and model-review text."""

from __future__ import annotations

HEARTBEAT_PROMPT_TEMPLATE = """\
Run your regular heartbeat check. Current time: {timestamp} ({local_time})

{project_access_summary}

## Model Review ({model_review_status})
{model_review_instructions}

## Journal Diversity (REQUIRED)
Write at least ONE journal entry this heartbeat. Your recent journal types: {recent_journal_types}.
Rotate types across heartbeats — use a type you haven't used recently:
- observation, decision, learning, user_insight, evolution

## Memory Curation
Review injected memories in your context. Use `mark_memory_relevant` for memories \
useful to your ongoing operations. Use `mark_memory_irrelevant` for noise/outdated ones.

## Available Tools ({tool_count} total)
Beyond bash/read_file/write_file, you have: {persona_tool_list}

Follow your <heartbeat_instructions> from your system context.

Your FINAL message must start with either `HEARTBEAT_OK` or `HEARTBEAT_ACTION`, \
followed by a 1-2 sentence summary. Also include a `[[S:completed:summary here]]` \
or `[[S:partial:summary here]]` tag so the session gets a searchable summary.

If approaching your turn limit, prioritize journaling findings before doing more work.\
"""

MODEL_REVIEW_DO = (
    "Due — run `review_agent_performance` + `manage_model_config(action=get_benchmarks)` + "
    "`manage_model_config(action=list_agents)`. Check `synced_at` — if benchmark data >60 days old, "
    "`send_push` to flag stale benchmarks. Evaluate model assignments. Log via `log_agent_performance`."
)
MODEL_REVIEW_SKIP = "Not due — skip model review this heartbeat."

__all__ = [
    "HEARTBEAT_PROMPT_TEMPLATE",
    "MODEL_REVIEW_DO",
    "MODEL_REVIEW_SKIP",
]
