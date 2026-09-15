"""Tests for the pinned llama.cpp launcher policy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.run_neri_local_qwen import (
    LLAMA_CPP_COMMIT,
    RUNTIME_RECEIPT_NAME,
    NeriQwenRuntimeConfig,
    _build_command,
    _verify_runtime,
    _write_runtime_receipt,
)


def _config(**overrides: object) -> NeriQwenRuntimeConfig:
    values: dict[str, object] = {
        "context_tokens": 32_768,
        "mtp_enabled": False,
        "spec_draft_n_max": 2,
        "cache_type_k": "q4_0",
        "cache_type_v": "q4_0",
        "batch_size": 2_048,
        "ubatch_size": 512,
        "prompt_cache_enabled": True,
        "idle_sleep_seconds": 300,
    }
    values.update(overrides)
    return NeriQwenRuntimeConfig(**values)


def test_baseline_launcher_is_loopback_single_slot_without_mtp() -> None:
    command = _build_command(
        Path("/bin/llama-server"), Path("/models/qwen.gguf"), _config()
    )
    joined = " ".join(command)
    assert "--host 127.0.0.1" in joined
    assert "--port 8100" in joined
    assert "--parallel 1" in joined
    assert "--fit off" in joined
    assert "--cache-type-k q4_0" in joined
    assert "--cache-type-v q4_0" in joined
    assert "--batch-size 2048" in joined
    assert "--ubatch-size 512" in joined
    assert "--cache-prompt" in command
    assert "--cors-origins localhost" in joined
    assert "--no-webui" in command
    assert "--sleep-idle-seconds 300" in joined
    assert "--spec-type" not in command


def test_mtp_draft_length_is_an_explicit_comparison_arm() -> None:
    command = _build_command(
        Path("/bin/llama-server"),
        Path("/models/qwen.gguf"),
        _config(context_tokens=65_536, mtp_enabled=True, spec_draft_n_max=3),
    )
    joined = " ".join(command)
    assert "--spec-type draft-mtp" in joined
    assert "--spec-draft-n-max 3" in joined


def test_runtime_profile_can_disable_cache_and_use_q8_kv() -> None:
    command = _build_command(
        Path("/bin/llama-server"),
        Path("/models/qwen.gguf"),
        _config(
            cache_type_k="q8_0",
            cache_type_v="q8_0",
            batch_size=1_024,
            ubatch_size=256,
            prompt_cache_enabled=False,
        ),
    )
    joined = " ".join(command)
    assert "--cache-type-k q8_0" in joined
    assert "--cache-type-v q8_0" in joined
    assert "--batch-size 1024" in joined
    assert "--ubatch-size 256" in joined
    assert "--no-cache-prompt" in command


def test_runtime_profile_rejects_unbounded_experiment_values() -> None:
    with pytest.raises(RuntimeError, match="draft length"):
        _config(spec_draft_n_max=9).validate()
    with pytest.raises(RuntimeError, match="K cache type"):
        _config(cache_type_k="f16").validate()
    with pytest.raises(RuntimeError, match="idle sleep"):
        _config(idle_sleep_seconds=0).validate()


def test_runtime_receipt_preserves_exact_non_secret_profile(tmp_path: Path) -> None:
    config = _config(mtp_enabled=True, spec_draft_n_max=3)
    _write_runtime_receipt(
        tmp_path,
        config,
        binary=Path("/opt/llama/bin/llama-server"),
        model=Path("/models/qwen.gguf"),
    )

    receipt_path = tmp_path / RUNTIME_RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text())
    assert receipt["process_start_ticks"] > 0
    assert receipt["mtp_enabled"] is True
    assert receipt["spec_draft_n_max"] == 3
    assert receipt["cache_type_k"] == "q4_0"
    assert receipt["idle_sleep_seconds"] == 300
    assert receipt["binary_path"] == "/opt/llama/bin/llama-server"
    assert receipt["model_path"] == "/models/qwen.gguf"
    assert receipt_path.stat().st_mode & 0o777 == 0o600


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
