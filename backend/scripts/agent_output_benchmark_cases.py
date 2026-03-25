"""Benchmark cases for helper-agent output contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentOutputBenchmarkCase:
    """One reproducible helper-agent output contract scenario."""

    case_id: str
    agent_slug: str
    name: str
    description: str
    prompt: str
    required_prefix: str | None = None
    required_terms: tuple[str, ...] = field(default_factory=tuple)
    forbidden_terms: tuple[str, ...] = field(default_factory=tuple)
    min_lines: int | None = None
    max_lines: int | None = None


_DEFAULT_FORBIDDEN_TERMS = ("[[P:", "[[S:", "Applied:", "```")

_CASES: tuple[AgentOutputBenchmarkCase, ...] = (
    AgentOutputBenchmarkCase(
        case_id="note_titler_plain_title",
        agent_slug="note-titler",
        name="Note Titler Plain Title",
        description="Return a single TITLE line without observability or wrapper prose.",
        prompt=(
            "Return ONLY a concise title for this note:\n"
            "JWT auth migration deadline is Q2 because the old tokens expire on June 30 "
            "and rotation must finish before then."
        ),
        required_prefix="TITLE:",
        required_terms=("jwt", "q2"),
        forbidden_terms=_DEFAULT_FORBIDDEN_TERMS,
        max_lines=1,
    ),
    AgentOutputBenchmarkCase(
        case_id="note_formatter_bare_json",
        agent_slug="note-formatter",
        name="Note Formatter Bare JSON",
        description="Return only structured note JSON with preserved content terms.",
        prompt=(
            "Format this note and return ONLY the formatted note body.\n\n"
            "project: agent-hub\n"
            "owner: jenny\n"
            "status: in progress\n"
            "items:\n"
            "- rotate keys\n"
            "- rerun benchmark\n"
            "- verify heartbeat"
        ),
        required_prefix="{",
        required_terms=('"title"', '"content"', "rotate keys", "rerun benchmark", "verify heartbeat"),
        forbidden_terms=_DEFAULT_FORBIDDEN_TERMS,
        min_lines=2,
    ),
    AgentOutputBenchmarkCase(
        case_id="prompt_builder_raw_prompt",
        agent_slug="prompt-builder",
        name="Prompt Builder Raw Prompt",
        description="Return prompt text directly without narration tags or explanatory wrapper prose.",
        prompt=(
            "Build a concise system prompt for a specialist that summarizes billing incidents "
            "in calm, factual language. Return ONLY the prompt text."
        ),
        required_prefix="You ",
        required_terms=("billing", "incident", "factual"),
        forbidden_terms=(*_DEFAULT_FORBIDDEN_TERMS, "Here is", "Here's", "Prompt:"),
        min_lines=3,
    ),
)


def get_agent_output_benchmark_cases(agent_slug: str | None = None) -> list[AgentOutputBenchmarkCase]:
    """Return all helper-agent output benchmark cases, optionally scoped to one agent."""
    if not agent_slug:
        return list(_CASES)
    return [case for case in _CASES if case.agent_slug == agent_slug]


def get_default_case_ids(agent_slug: str) -> list[str]:
    """Return the default case ids for one helper agent."""
    return [case.case_id for case in get_agent_output_benchmark_cases(agent_slug)]


def get_case_by_id(agent_slug: str, case_id: str) -> AgentOutputBenchmarkCase:
    """Resolve one helper-agent output benchmark case."""
    for case in get_agent_output_benchmark_cases(agent_slug):
        if case.case_id == case_id:
            return case
    raise KeyError(f"Unknown agent output benchmark case for {agent_slug}: {case_id}")
