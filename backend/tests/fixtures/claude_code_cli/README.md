# Claude Code CLI stream-json fixtures

Sanitized to protocol fields only (no conversation content, cwd, paths or ids; request ids replaced by `req_FIXTURE`).

- `success_continuation_turn.jsonl`: a continuation turn of one persistent process, from a real probe run (claude 2.1.312, claude-haiku-5-5; answer text replaced).
- `refusal_assistant.jsonl`: synthetic refusal assistant turn (`model "<synthetic>"`, `stop_reason "refusal"`, `Details: [cyber]`); derived from transcript record (a ~/.claude/projects `isApiErrorMessage` assistant record, Claude Code 2.1.311) wrapped as a stream-json `assistant` event.
- `model_refusal_fallback.jsonl`: `system` event `model_refusal_fallback` (opus-5-5 to opus-4-8, cyber); derived from transcript record (Claude Code 2.1.299), followed by the fallback model's answer.
- `safeguards_informational.jsonl`: "safeguards stopped the response" `system`/`informational` notice; derived from transcript record (Claude Code 2.1.311).
- `usage_limit.jsonl`: `rate_limit_event` from the real probe stream with `status` changed to `rejected`, plus an error result (no real rejected record was available; derived).
