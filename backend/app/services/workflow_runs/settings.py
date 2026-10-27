"""Where workflow runs keep worktrees and run directories (paths only; decisions live in policy_defaults.json)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import ENV_FILES


class WorkflowRunSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_HUB_WORKFLOW_",
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # <root>/<run_id>/{worktree,run}; created on first use.
    runs_root: Path = Path.home() / ".local/state/agent-hub/workflow-runs"


@lru_cache
def get_workflow_run_settings() -> WorkflowRunSettings:
    return WorkflowRunSettings()
