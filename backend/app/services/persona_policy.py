"""Shared persona policy wording and command checks."""

from __future__ import annotations

import shlex
from pathlib import PurePath

PERSONA_BLOCKED_GIT_SUBCOMMANDS = frozenset({"commit", "push"})
# git global options that take the next argument as their value (git -C DIR commit).
_GIT_OPTIONS_WITH_VALUE = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env",
})
_SHELL_PUNCTUATION = frozenset(";&|()<>")


def _tokens(command: str) -> list[str] | None:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _git_subcommand(args: list[str]) -> str | None:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg and set(arg) <= _SHELL_PUNCTUATION:
            return None
        if arg in _GIT_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return arg.lower().rstrip("`)")
    return None


def command_hits_persona_git_publish_policy(command: str, _depth: int = 0) -> bool:
    """Return True when a command runs git commit or git push anywhere in it.

    The command is split into shell words, so global options (``git -C . commit``),
    wrappers (``env``, ``sudo``, ``xargs``), separators and quoted nested shells
    (``bash -c "git push"``) do not hide the subcommand. Unparseable input falls
    back to a plain substring check.
    """
    tokens = _tokens(command)
    if tokens is None:
        lowered = command.lower()
        return any(f"git {name}" in lowered for name in PERSONA_BLOCKED_GIT_SUBCOMMANDS)
    for index, token in enumerate(tokens):
        name = PurePath(token.lstrip("`$({")).name.lower() if token else ""
        if name == "git" and _git_subcommand(tokens[index + 1:]) in PERSONA_BLOCKED_GIT_SUBCOMMANDS:
            return True
        if _depth < 3 and any(ch.isspace() for ch in token) and command_hits_persona_git_publish_policy(token, _depth + 1):
            return True
    return False


def get_persona_git_publish_block_reason() -> str:
    """Return the canonical persona git-publish policy message."""
    return (
        "The persona must not use raw git commit/push from Bash. "
        "Use the canonical commit.sh publish flow after validation when direct code "
        "intervention is operationally required."
    )
