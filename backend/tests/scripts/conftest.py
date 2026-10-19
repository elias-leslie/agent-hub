import pytest


@pytest.fixture(autouse=True)
def _no_agent_tether(monkeypatch):
    """codex-session-sync tests never ask the host's agent Tether or read the agent user's rollouts."""
    monkeypatch.setenv("AGENT_HUB_TETHER_SOCKETS", "")
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", str(__import__("pathlib").Path.home() / ".codex" / "sessions"))
