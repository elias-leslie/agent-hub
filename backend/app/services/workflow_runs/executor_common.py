"""Shared plumbing of the native-harness executors (codex, pi): settings, process lifecycle, handoff, usage.

Decisions (sandbox, binaries, provider maps, timeouts) live in ``executor_defaults.json``; nothing here names a
model. A harness runs unmodified, in the run's worktree, with a minimal environment and its own credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

from app.llm.utils.outcomes import ProviderOutcome
from app.utils.safe_subprocess import create_process

from .packet import HandoffPacket, normalize_handoff, parse_handoff
from .processes import TrackedProcess, start_tracked

DEFAULTS_FILE = Path(__file__).with_name("executor_defaults.json")
FALLBACK_NOTE = "fallback handoff: built by the executor from the final message and git diff --stat"


def load_defaults(path: Path = DEFAULTS_FILE) -> dict[str, Any]:
    return json.loads(path.read_text())


def child_env(defaults: Mapping[str, Any]) -> dict[str, str]:
    """Only the variables the harness needs to find its login; backend secrets never reach the agent."""

    env = {k: os.environ[k] for k in defaults["env_passthrough"] if k in os.environ}
    # `codex`/`claude` on PATH may be Agent Hub's context launchers; the packet already carries the context.
    env["AGENT_HUB_CONTEXT_BYPASS"] = "1"
    return env


def thinking_level(packet: HandoffPacket, model: Any, defaults: Mapping[str, Any]) -> str:
    """The agent's thinking level when the packet carries it, else the catalog-capable default.

    ``xhigh`` is clamped to ``high`` for models that do not support it; the catalog's own level map applies last.
    """

    level = str(getattr(packet, "thinking_level", None) or defaults["default_thinking_level"])
    caps = getattr(model, "capabilities", None)
    if level == "xhigh" and caps is not None and not caps.supports_xhigh:
        level = "high"
    mapped = ((caps.thinking_level_map or {}) if caps is not None else {}).get(level, level)
    return str(mapped or defaults["default_thinking_level"])


@dataclass
class Progress:
    """Whole output/action items of the attempt, oldest first, bounded by count."""

    limit: int
    items: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        text = text.strip()
        if text:
            self.items.append(text)
            del self.items[: -self.limit]


@dataclass
class Usage:
    """Disjoint token counts: ``input_tokens`` excludes what was read from or written to the cache."""

    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0  # already inside output_tokens

    def add(self, input_: int, cache_read: int, cache_write: int, output: int, reasoning: int) -> None:
        self.input_tokens += max(0, input_)
        self.cache_read_tokens += max(0, cache_read)
        self.cache_write_tokens += max(0, cache_write)
        self.output_tokens += max(0, output)
        self.reasoning_tokens += max(0, reasoning)

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.input_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
            + self.output_tokens,
        }


def argv_tools(argv: Sequence[str]) -> tuple[str, ...] | None:
    """The tool names a harness command line limits the attempt to (``--tools A,B``); None when it names none."""

    for flag, value in pairwise(argv):
        if flag == "--tools":
            return tuple(name for name in value.split(",") if name)
    return None


def catalog_served(requested: str, served: Sequence[str]) -> list[str]:
    """Served model ids as catalog ids, so one model is never shown as a switch because of how it was spelled.

    A served id that is the requested model (same upstream id, provider prefix, case or dated snapshot: the rule
    ``is_model_switch`` applies) becomes the requested catalog id. A different model becomes its catalog id when the
    catalog knows it (as reported, or under the requested model's provider), else it stays as reported.
    """

    from app.constants.catalog import MODEL_CATALOG_BY_ID, get_model_entry
    from app.llm.utils.outcomes import is_model_switch

    entry = get_model_entry(requested)
    provider = entry.provider if entry is not None else requested.partition("/")[0]
    out: list[str] = []
    for name in served:
        if not is_model_switch(requested, name):
            out.append(requested)
            continue
        out.append(next((key for key in (name, f"{provider}/{name}") if key in MODEL_CATALOG_BY_ID), name))
    return list(dict.fromkeys(out))


def as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + " [truncated]"


# --- failures ------------------------------------------------------------------------------------------

_USAGE_LIMIT_CODES = {"usagelimitexceeded", "usagelimitreached", "ratelimitexceeded", "sessionbudgetexceeded"}
_USAGE_LIMIT_TEXT = re.compile(r"usage limit|hit your .*limit|quota (?:exceeded|reached)|rate limit", re.I)


def _norm(value: Any) -> str:
    return str(value).replace("_", "").replace("-", "").lower() if value is not None else ""


def _json_in(text: str) -> dict[str, Any]:
    """The JSON object in ``text``: the whole string, or the braces of an error such as ``400 {...}``."""

    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        with contextlib.suppress(ValueError):
            value = json.loads(text[start : end + 1])
            if isinstance(value, dict):
                return value
    return {}


def _find_key(value: Any, names: set[str], depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in names and item not in (None, ""):
                return item
        for item in value.values():
            found = _find_key(item, names, depth + 1)
            if found is not None:
                return found
    return None


def classify_failure(
    model: str, message: str, info: Any = None, *, now: float | None = None
) -> ProviderOutcome | None:
    """A refusal or usage-limit outcome for a provider error, from its code, JSON body or text; else None.

    ``info`` is the provider's error code (``codex_error_info`` / error type) as a string or ``{code: ...}``.
    """

    from app.llm.utils.refusal_codes import codex_refusal_category

    body = _json_in(message)
    codes: list[Any] = [next(iter(info), None) if isinstance(info, Mapping) else info]
    codes += [_find_key(body, {"codex_error_info", "codexErrorInfo", "code", "type"})]
    for code in codes:
        category = codex_refusal_category(code)
        if category:
            return ProviderOutcome("refused", model, category=category, explanation=clip(message, 500))
    inner: Mapping[str, Any] = body["error"] if isinstance(body.get("error"), Mapping) else body
    kind = inner.get("type")
    text = str(inner.get("message") or message)
    limited = any(_norm(code) in _USAGE_LIMIT_CODES for code in (*codes, kind)) or (
        not body and bool(_USAGE_LIMIT_TEXT.search(text))
    )
    if limited:
        resets_at = _find_key(body, {"resets_at", "resetsAt"})
        if not isinstance(resets_at, int):
            seconds = _find_key(body, {"resets_in_seconds", "resetsInSeconds"})
            resets_at = int((now or time.time()) + seconds) if isinstance(seconds, (int, float)) else None
        window = _find_key(body, {"window", "limit_window", "plan_type"})
        return ProviderOutcome(
            "usage_limit",
            model,
            window=str(window) if window else None,
            resets_at=resets_at,
            explanation=clip(text, 500),
        )
    return None


# --- handoff ------------------------------------------------------------------------------------------


async def diff_stat(worktree: Path) -> str:
    try:
        for args in (("add", "-A"), ("diff", "--cached", "--stat", "HEAD")):
            process = await create_process(
                "git", *args, working_dir=worktree, stdin=asyncio.subprocess.DEVNULL
            )
            out, _ = await asyncio.wait_for(process.communicate(), 30)
            if process.returncode != 0:
                return ""
        return out.decode(errors="replace").strip()
    except Exception:
        return ""


async def build_handoff(final_text: str, worktree: Path) -> dict[str, Any] | None:
    """Parsed handoff when the final message carries one, else a minimal fallback note (marked as such)."""

    note = parse_handoff(final_text)
    if note is not None:
        return note
    stat = await diff_stat(worktree)
    files = [
        line.split("|")[0].strip()
        for line in stat.splitlines()
        if "|" in line and line.split("|")[0].strip()
    ]
    summary = final_text.strip() or (f"Changed files:\n{stat}" if stat else "")
    return normalize_handoff(
        {
            "summary": clip(summary, 4000),
            "decisions": [FALLBACK_NOTE],
            "files": files,
            "open_questions": [],
        }
    )


# --- process ------------------------------------------------------------------------------------------


class HarnessProcess:
    """One harness child in its own process group: LF-framed stdout, bounded stderr tail, hard cleanup."""

    def __init__(self, tracked: TrackedProcess, stderr_tail: int) -> None:
        self.tracked = tracked
        self.process = tracked.process
        self._stderr = bytearray()
        self._tail = stderr_tail
        self._drain = asyncio.create_task(self._drain_stderr())

    @classmethod
    async def start(
        cls, argv: Sequence[str], cwd: Path, env: dict[str, str], stderr_tail: int, *, stdin: bool
    ) -> HarnessProcess:
        # Registered with the attempt (when there is one) and killed by the kernel if the worker dies.
        tracked = await start_tracked(
            *argv,
            kind="harness",
            working_dir=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
            limit=2**24,
        )
        return cls(tracked, stderr_tail)

    async def _drain_stderr(self) -> None:
        stream = self.process.stderr
        while stream is not None and (chunk := await stream.read(8192)):
            self._stderr += chunk
            del self._stderr[: -self._tail]

    @property
    def stderr_text(self) -> str:
        return self._stderr.decode(errors="replace").strip()

    async def write(self, payload: bytes, *, close: bool = False) -> None:
        stdin = self.process.stdin
        if stdin is None:
            return
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            stdin.write(payload)
            await stdin.drain()
            if close:
                stdin.close()

    async def records(self) -> AsyncIterator[dict[str, Any]]:
        """JSON objects from stdout, split on LF only; non-JSON lines are skipped."""

        stream = self.process.stdout
        while stream is not None and (line := await stream.readline()):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record

    async def stop(self, grace: float) -> int | None:
        """End the whole process group (harness and its tool children) and reap it.

        SIGTERM first, SIGKILL after ``grace`` seconds, and also when only a grandchild outlived the harness.
        """

        await self.tracked.stop(grace)
        # Not cancelled on timeout: stop() may run twice (the executor's cleanup and the engine's).
        await asyncio.wait({self._drain}, timeout=2)
        return self.process.returncode
