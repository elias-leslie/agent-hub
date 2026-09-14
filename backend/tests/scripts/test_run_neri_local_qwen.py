"""Tests for the pinned llama.cpp launcher policy."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.run_neri_local_qwen import LLAMA_CPP_COMMIT, _build_command, _verify_runtime


def test_baseline_launcher_is_loopback_single_slot_without_mtp() -> None:
    command = _build_command(Path("/bin/llama-server"), Path("/models/qwen.gguf"), 32_768, False)
    joined = " ".join(command)
    assert "--host 127.0.0.1" in joined
    assert "--port 8100" in joined
    assert "--parallel 1" in joined
    assert "--fit off" in joined
    assert "--cache-type-k q4_0" in joined
    assert "--cache-type-v q4_0" in joined
    assert "--cors-origins localhost" in joined
    assert "--no-webui" in command
    assert "--spec-type" not in command


def test_mtp_is_an_explicit_two_token_comparison_arm() -> None:
    command = _build_command(Path("/bin/llama-server"), Path("/models/qwen.gguf"), 65_536, True)
    joined = " ".join(command)
    assert "--spec-type draft-mtp" in joined
    assert "--spec-draft-n-max 2" in joined


def test_runtime_rejects_unpinned_llama_cpp_revision(tmp_path: Path) -> None:
    binary = tmp_path / "llama-server"
    binary.write_text("binary")
    binary.chmod(0o755)
    model = tmp_path / "model.gguf"
    model.write_text("model")
    completed = Mock(stdout="version 1 commit deadbee", stderr="")
    with (
        patch("scripts.run_neri_local_qwen.subprocess.run", return_value=completed),
        pytest.raises(RuntimeError, match="revision mismatch"),
    ):
        _verify_runtime(binary, model)

    assert LLAMA_CPP_COMMIT[:7] not in completed.stdout


def test_runtime_rejects_matching_cpu_only_build(tmp_path: Path) -> None:
    binary = tmp_path / "llama-server"
    binary.write_text("binary")
    binary.chmod(0o755)
    model = tmp_path / "model.gguf"
    model.write_text("model")
    version = Mock(stdout=f"commit {LLAMA_CPP_COMMIT[:7]}", stderr="")
    devices = Mock(stdout="Available devices:\n  CPU: host", stderr="")
    with (
        patch(
            "scripts.run_neri_local_qwen.subprocess.run",
            side_effect=[version, devices],
        ),
        pytest.raises(RuntimeError, match="required CUDA0"),
    ):
        _verify_runtime(binary, model)
