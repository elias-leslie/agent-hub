"""The persona git guard reads parsed shell words, not substrings."""

from __future__ import annotations

import pytest

from app.services.persona_policy import command_hits_persona_git_publish_policy

GIT = "git"


@pytest.mark.parametrize(
    "command",
    [
        f"{GIT} commit -m x",
        f"{GIT} -C . commit -m x",
        f"{GIT} --git-dir=.git commit",
        f"{GIT} -c user.name=a commit -m b",
        f"/usr/bin/{GIT} push origin main",
        f"env A=1 {GIT} push",
        f"sudo {GIT} commit",
        f"cd repo && {GIT} commit -m y",
        f"echo hi;{GIT} push",
        f'bash -c "{GIT} push origin main"',
        f"sh -c 'cd /tmp && {GIT} -C r commit'",
        f"$({GIT} commit -m x)",
        f"`{GIT} push`",
        f"xargs {GIT} commit",
        "g\\it commit",
        f"{GIT.upper()} COMMIT",
        f'{GIT} commit -m "unbalanced',
    ],
)
def test_blocks_commit_and_push_however_written(command: str) -> None:
    assert command_hits_persona_git_publish_policy(command)


@pytest.mark.parametrize(
    "command",
    [f"{GIT} status", f"{GIT} log --grep commit", f"{GIT} show push", f"{GIT} -C commit status", f"{GIT} stash push", "ls"],
)
def test_allows_other_git_use(command: str) -> None:
    assert not command_hits_persona_git_publish_policy(command)
