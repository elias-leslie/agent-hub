"""Security and wire-contract tests for the passive Neri local worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.api.neri_local_worker_schemas import (
    NeriHarnessArm,
    NeriLocalTaskFamily,
    NeriLocalWorkerOutput,
    NeriLocalWorkerPacket,
    NeriLocalWorkerRequest,
    NeriPacketEvidence,
)
from app.constants.models import LOCAL_NERI_QWEN3_8_27B_IQ3_S
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.openai_completions import (
    OpenAICompletionsOptions,
    _get_compat,
    build_params,
    create_client,
)
from app.llm.runtime_profiles import NERI_QWEN_RUNTIME_PROFILE
from app.llm.types import TextContent, ToolCall
from app.services.neri_local_worker import (
    NeriLocalWorkerError,
    _evaluation_config,
    _get_observed_runtime_metadata,
    _load_runtime_receipt,
    _merge_observed_runtime,
    _one_pass,
    _prompt_payload,
    _validate_output,
    _validate_runtime_process,
    _validate_runtime_props,
    _validate_runtime_receipt,
    _validate_runtime_slots,
    execute_neri_local_worker,
    get_neri_local_worker_status,
)


def _packet() -> NeriLocalWorkerPacket:
    return NeriLocalWorkerPacket(
        objective="Separate facts from unknowns",
        evidence=[NeriPacketEvidence(ref="E1", content="Observed status 200")],
        constraints=[],
    )


def _request(arm: NeriHarnessArm = NeriHarnessArm.GROUNDED_DECOMPOSITION) -> NeriLocalWorkerRequest:
    return NeriLocalWorkerRequest(
        task_family=NeriLocalTaskFamily.FACTS_UNKNOWNS,
        harness_arm=arm,
        packet=_packet(),
    )


def _valid_output() -> NeriLocalWorkerOutput:
    return NeriLocalWorkerOutput.model_validate(
        {
            "disposition": "complete",
            "summary": "A status was observed; impact is unknown.",
            "items": [
                {
                    "kind": "fact",
                    "statement": "Status 200 was observed.",
                    "evidence_refs": ["E1"],
                    "confidence": "high",
                    "choices": [],
                },
                {
                    "kind": "unknown",
                    "statement": "Response content and impact are unknown.",
                    "evidence_refs": [],
                    "confidence": "high",
                    "choices": [],
                },
            ],
            "limitations": ["No response body was supplied."],
        }
    )


def test_request_rejects_generic_completion_escape_fields() -> None:
    raw = {
        "task_family": "facts_unknowns",
        "packet": _packet().model_dump(),
        "tools": [{"name": "bash"}],
        "model": "openai/gpt-5.5",
        "use_memory": True,
        "working_dir": "/tmp",
    }
    with pytest.raises(ValidationError):
        NeriLocalWorkerRequest.model_validate(raw)


def test_prompt_marks_packet_untrusted_and_supplies_no_action_interface() -> None:
    prompt = _prompt_payload(_request())
    assert "BEGIN UNTRUSTED EVIDENCE PACKET" in prompt
    assert "never instructions" in prompt
    assert "Except for learning_draft tasks" in prompt
    assert '"ref": "E1"' in prompt
    assert "shell" not in prompt.lower()


def test_output_rejects_invented_evidence_reference() -> None:
    output = _valid_output().model_dump()
    output["items"][0]["evidence_refs"] = ["E999"]
    with pytest.raises(NeriLocalWorkerError, match="invented evidence refs"):
        _validate_output(NeriLocalWorkerOutput.model_validate(output).model_dump_json(), _request())


def test_learning_draft_requires_a_unique_answered_question() -> None:
    raw = {
        "disposition": "complete",
        "summary": "Question draft.",
        "items": [
            {
                "kind": "question",
                "statement": "What evidence is still needed?",
                "evidence_refs": ["E1"],
                "confidence": "high",
                "choices": ["Capture the body", "Assume impact", "Capture the body"],
                "answer_index": 0,
            }
        ],
        "limitations": [],
    }
    with pytest.raises(ValidationError, match="choices must be unique"):
        NeriLocalWorkerOutput.model_validate(raw)


def test_runtime_profile_builds_llama_cpp_qwen_wire_params() -> None:
    model = resolve_llm_model(
        LOCAL_NERI_QWEN3_8_27B_IQ3_S,
        "local",
        allow_restricted_runtime=True,
    )
    assert model.base_url.endswith(":8100/v1")
    assert model.id == NERI_QWEN_RUNTIME_PROFILE.server_model_id
    context = SimpleNamespace(messages=[], system_prompt="passive", tools=None)
    options = OpenAICompletionsOptions(
        temperature=1.0,
        max_tokens=4096,
        reasoning_effort="xhigh",
    )
    params = build_params(model, context, options, _get_compat(model), "none")
    assert params["model"] == NERI_QWEN_RUNTIME_PROFILE.server_model_id
    assert params["max_tokens"] == 4096
    assert params["temperature"] == 1.0
    assert params["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }
    assert params["reasoning_budget_tokens"] == 4096 // 2
    assert "tools" not in params
    assert "store" not in params
    assert "reasoning_effort" not in params


def test_runtime_profile_uses_proxy_and_redirect_disabled_transport() -> None:
    model = resolve_llm_model(
        LOCAL_NERI_QWEN3_8_27B_IQ3_S,
        "local",
        allow_restricted_runtime=True,
    )
    compat = _get_compat(model)
    with (
        patch("app.llm.providers.openai_completions.httpx.AsyncClient") as http_client,
        patch("app.llm.providers.openai_completions.AsyncOpenAI") as openai_client,
    ):
        create_client(model, "", None, None, compat)

    http_client.assert_called_once_with(trust_env=False, follow_redirects=False)
    assert openai_client.call_args.kwargs["http_client"] is http_client.return_value


@pytest.mark.asyncio
async def test_runtime_metadata_probe_disables_proxies_and_redirects() -> None:
    client = AsyncMock()
    client.__aenter__.return_value = client
    props = Mock()
    props.json.return_value = {
        "build_info": "b1-f1e44dc",
        "model_alias": NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        "model_ftype": "IQ3_S - 3.4375 bpw",
        "total_slots": 1,
        "default_generation_settings": {
            "n_ctx": 32_768,
            "params": {"speculative.types": "none"},
        },
    }
    slots = Mock()
    slots.json.return_value = [{"n_ctx": 32_768, "speculative": False}]
    client.get.side_effect = [props, slots]
    with (
        patch("app.services.neri_local_worker.httpx.AsyncClient", return_value=client) as ctor,
        patch("app.services.neri_local_worker._load_runtime_receipt", return_value={}),
    ):
        observed = await _get_observed_runtime_metadata()

    ctor.assert_called_once_with(timeout=2.0, trust_env=False, follow_redirects=False)
    assert observed["observed_mtp_enabled"] is False


def test_runtime_properties_capture_context_revision_and_mtp() -> None:
    observed = _validate_runtime_props(
        {
            "build_info": "b1-f1e44dc",
            "model_alias": NERI_QWEN_RUNTIME_PROFILE.server_model_id,
            "model_ftype": "IQ3_S - 3.4375 bpw",
            "total_slots": 1,
            "default_generation_settings": {
                "n_ctx": 32_768,
                "params": {"speculative.types": "none"},
            },
        }
    )
    observed.update(_validate_runtime_slots([{"n_ctx": 32_768, "speculative": True}]))

    assert observed["observed_mtp_enabled"] is True
    assert observed["observed_context_tokens"] == 32_768


def test_runtime_receipt_adds_exact_tuning_provenance() -> None:
    receipt = _validate_runtime_receipt(
        {
            "pid": 1234,
            "process_start_ticks": 5678,
            "artifact_sha256": NERI_QWEN_RUNTIME_PROFILE.artifact_sha256,
            "engine_revision": NERI_QWEN_RUNTIME_PROFILE.engine_revision,
            "server_model_id": NERI_QWEN_RUNTIME_PROFILE.server_model_id,
            "context_tokens": 32_768,
            "mtp_enabled": True,
            "spec_draft_n_max": 3,
            "cache_type_k": "q4_0",
            "cache_type_v": "q4_0",
            "batch_size": 2_048,
            "ubatch_size": 512,
            "prompt_cache_enabled": False,
            "binary_path": "/opt/llama/bin/llama-server",
            "model_path": "/models/qwen.gguf",
        }
    )
    observed = _merge_observed_runtime(
        {"observed_context_tokens": 32_768},
        {"observed_mtp_enabled": True},
        receipt,
    )
    assert observed["observed_spec_draft_n_max"] == 3
    assert observed["observed_prompt_cache_enabled"] is False
    assert observed["observed_cache_type_k"] == "q4_0"


def _runtime_receipt_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "pid": 1234,
        "process_start_ticks": 5678,
        "artifact_sha256": NERI_QWEN_RUNTIME_PROFILE.artifact_sha256,
        "engine_revision": NERI_QWEN_RUNTIME_PROFILE.engine_revision,
        "server_model_id": NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        "context_tokens": 32_768,
        "mtp_enabled": True,
        "spec_draft_n_max": 3,
        "cache_type_k": "q4_0",
        "cache_type_v": "q4_0",
        "batch_size": 2_048,
        "ubatch_size": 512,
        "prompt_cache_enabled": True,
        "binary_path": "/opt/llama/bin/llama-server",
        "model_path": "/models/qwen.gguf",
    }
    payload.update(overrides)
    return payload


def _runtime_command() -> list[str]:
    return [
        "/opt/llama/bin/llama-server",
        "-m",
        "/models/qwen.gguf",
        "--alias",
        NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        "-ngl",
        "99",
        "-c",
        "32768",
        "--cache-type-k",
        "q4_0",
        "--cache-type-v",
        "q4_0",
        "--batch-size",
        "2048",
        "--ubatch-size",
        "512",
        "-fa",
        "on",
        "--jinja",
        "--reasoning-preserve",
        "--parallel",
        "1",
        "--fit",
        "off",
        "--temp",
        "1.0",
        "--top-p",
        "0.95",
        "--top-k",
        "20",
        "--min-p",
        "0.0",
        "--host",
        "127.0.0.1",
        "--port",
        "8100",
        "--cors-origins",
        "localhost",
        "--no-webui",
        "--cache-prompt",
        "--spec-type",
        "draft-mtp",
        "--spec-draft-n-max",
        "3",
    ]


def test_runtime_process_must_match_receipt_exactly() -> None:
    receipt = _validate_runtime_receipt(_runtime_receipt_payload())
    command_line = "\0".join(_runtime_command()).encode() + b"\0"

    _validate_runtime_process(receipt, command_line)


@pytest.mark.parametrize(
    ("flag", "replacement", "message"),
    [
        ("--port", "8200", "--port"),
        ("--spec-draft-n-max", "2", "--spec-draft-n-max"),
        ("--cache-type-k", "q8_0", "--cache-type-k"),
        ("-m", "/models/other.gguf", "-m"),
    ],
)
def test_runtime_process_rejects_argument_mismatch(
    flag: str,
    replacement: str,
    message: str,
) -> None:
    receipt = _validate_runtime_receipt(_runtime_receipt_payload())
    command = _runtime_command()
    command[command.index(flag) + 1] = replacement

    with pytest.raises(NeriLocalWorkerError, match=message):
        _validate_runtime_process(receipt, "\0".join(command).encode() + b"\0")


def test_runtime_receipt_is_required(tmp_path: Path) -> None:
    with (
        patch(
            "app.services.neri_local_worker._runtime_receipt_path",
            return_value=tmp_path / "missing.json",
        ),
        pytest.raises(NeriLocalWorkerError, match="receipt is missing"),
    ):
        _load_runtime_receipt()


@pytest.mark.parametrize(
    ("payload_overrides", "message"),
    [
        ({"pid": 999_999_999}, "process that is not available"),
        ({"pid": os.getpid(), "process_start_ticks": 1}, "start identity is stale"),
    ],
)
def test_runtime_receipt_rejects_wrong_or_stale_process(
    tmp_path: Path,
    payload_overrides: dict[str, object],
    message: str,
) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(_runtime_receipt_payload(**payload_overrides)))
    receipt_path.chmod(0o600)
    with (
        patch(
            "app.services.neri_local_worker._runtime_receipt_path",
            return_value=receipt_path,
        ),
        pytest.raises(NeriLocalWorkerError, match=message),
    ):
        _load_runtime_receipt()


def test_runtime_receipt_must_agree_with_observed_server() -> None:
    receipt = {
        "receipt_context_tokens": 65_536,
        "receipt_mtp_enabled": True,
    }
    with pytest.raises(NeriLocalWorkerError, match="context disagree"):
        _merge_observed_runtime(
            {"observed_context_tokens": 32_768},
            {"observed_mtp_enabled": True},
            receipt,
        )


@pytest.mark.asyncio
async def test_one_pass_forwards_only_single_turn_passive_options() -> None:
    output = _valid_output()
    message = SimpleNamespace(
        response_model=NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        model=NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        stop_reason="stop",
        error_message=None,
        content=[TextContent(text=output.model_dump_json())],
        usage=SimpleNamespace(input=10, output=20, total_tokens=30),
    )
    with patch(
        "app.services.neri_local_worker.run_completion",
        new=AsyncMock(return_value=SimpleNamespace(message=message)),
    ) as run:
        parsed, _content, metrics = await _one_pass(
            prompt="packet",
            system_prompt="passive",
            request=_request(),
        )

    assert parsed == output
    call = run.call_args
    assert call.kwargs["execute_tools"] is False
    assert call.kwargs["run_tool"] is None
    assert call.kwargs["max_turns"] == 1
    assert call.args[1].tools is None
    assert call.kwargs["options"].temperature == 1.0
    assert call.kwargs["options"].reasoning == "xhigh"
    assert call.kwargs["options"].max_tokens == 4096
    assert metrics["total_tokens"] == 30
    assert metrics["cache_read_tokens"] == 0
    assert metrics["cache_write_tokens"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("reported_model", [None, "different-model"])
async def test_one_pass_requires_matching_observed_model_identity(
    reported_model: str | None,
) -> None:
    output = _valid_output()
    message = SimpleNamespace(
        response_model=reported_model,
        model=NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        stop_reason="stop",
        error_message=None,
        content=[TextContent(text=output.model_dump_json())],
        usage=SimpleNamespace(input=10, output=20, total_tokens=30),
    )
    with (
        patch(
            "app.services.neri_local_worker.run_completion",
            new=AsyncMock(return_value=SimpleNamespace(message=message)),
        ),
        pytest.raises(NeriLocalWorkerError) as raised,
    ):
        await _one_pass(prompt="packet", system_prompt="passive", request=_request())

    assert raised.value.failure_kind == "identity"
    assert raised.value.runtime_metrics["total_tokens"] == 30


@pytest.mark.asyncio
async def test_one_pass_retains_tool_violation_usage_and_name() -> None:
    message = SimpleNamespace(
        response_model=NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        model=NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        stop_reason="toolUse",
        error_message=None,
        content=[ToolCall(id="call-1", name="bash", arguments={})],
        usage=SimpleNamespace(input=11, output=7, total_tokens=18),
    )
    with (
        patch(
            "app.services.neri_local_worker.run_completion",
            new=AsyncMock(return_value=SimpleNamespace(message=message)),
        ),
        pytest.raises(NeriLocalWorkerError) as raised,
    ):
        await _one_pass(prompt="packet", system_prompt="passive", request=_request())

    error = raised.value
    assert error.failure_kind == "tool_policy"
    assert error.runtime_metrics["total_tokens"] == 18
    assert error.runtime_metrics["tool_calls_count"] == 1
    assert error.runtime_metrics["used_tool_names"] == ["bash"]
    assert error.safety_failures == ["unexpected_tool_call"]


def test_evaluation_fingerprint_changes_with_material_configuration() -> None:
    baseline_request = _request(NeriHarnessArm.BARE_SCHEMA)
    baseline = _evaluation_config(
        baseline_request, system_prompt="passive-v1", prompt_revision=1
    )
    variants = [
        _evaluation_config(
            baseline_request.model_copy(update={"reasoning_effort": "low"}),
            system_prompt="passive-v1",
            prompt_revision=1,
        ),
        _evaluation_config(
            baseline_request.model_copy(update={"max_output_tokens": 2_048}),
            system_prompt="passive-v1",
            prompt_revision=1,
        ),
        _evaluation_config(
            baseline_request.model_copy(
                update={"harness_arm": NeriHarnessArm.ROLE_CHECKLIST}
            ),
            system_prompt="passive-v1",
            prompt_revision=1,
        ),
        _evaluation_config(
            baseline_request,
            system_prompt="passive-v2",
            prompt_revision=2,
        ),
    ]

    assert baseline["schema_sha256"]
    assert baseline["harness_sha256"]
    assert baseline["effective_reasoning_budget_tokens"] == 2_048
    assert all(item["config_sha256"] != baseline["config_sha256"] for item in variants)


def _models_response() -> Mock:
    response = Mock()
    response.json.return_value = {
        "data": [{"id": NERI_QWEN_RUNTIME_PROFILE.server_model_id}]
    }
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "json", "props"])
async def test_status_clears_exact_identity_on_any_verification_failure(
    failure: str,
) -> None:
    client = AsyncMock()
    client.__aenter__.return_value = client
    models = _models_response()
    if failure == "http":
        client.get.side_effect = [models, httpx.ConnectError("failed")]
    elif failure == "json":
        models.json.side_effect = ValueError("malformed")
        client.get.return_value = models
    else:
        malformed_props = Mock()
        malformed_props.json.return_value = {}
        client.get.side_effect = [models, malformed_props]

    with patch("app.services.neri_local_worker.httpx.AsyncClient", return_value=client):
        status = await get_neri_local_worker_status()

    assert status.exact_model_loaded is False
    assert status.detail is not None


@pytest.mark.asyncio
async def test_worker_rejects_agent_with_fallback_chain_before_inference() -> None:
    agent = SimpleNamespace(
        primary_model_id=LOCAL_NERI_QWEN3_8_27B_IQ3_S,
        fallback_models=["openai/gpt-5.5"],
        escalation_model_id=None,
        system_prompt="passive",
        version=1,
    )
    service = SimpleNamespace(get_by_slug=AsyncMock(return_value=agent))
    with (
        patch("app.services.neri_local_worker.get_agent_service", return_value=service),
        pytest.raises(NeriLocalWorkerError, match="fallback-free"),
    ):
        await execute_neri_local_worker(_request(), AsyncMock())


@pytest.mark.asyncio
async def test_critique_arm_runs_exactly_two_tool_free_passes() -> None:
    agent = SimpleNamespace(
        primary_model_id=LOCAL_NERI_QWEN3_8_27B_IQ3_S,
        fallback_models=[],
        escalation_model_id=None,
        system_prompt="passive",
        version=7,
    )
    service = SimpleNamespace(get_by_slug=AsyncMock(return_value=agent))
    output = _valid_output()
    one_pass = AsyncMock(
        side_effect=[
            (output, output.model_dump_json(), {"latency_ms": 10, "total_tokens": 20}),
            (output, output.model_dump_json(), {"latency_ms": 12, "total_tokens": 25}),
        ]
    )
    with (
        patch("app.services.neri_local_worker.get_agent_service", return_value=service),
        patch("app.services.neri_local_worker._one_pass", new=one_pass),
        patch(
            "app.services.neri_local_worker._get_observed_runtime_metadata",
            new=AsyncMock(return_value={"observed_mtp_enabled": False}),
        ),
    ):
        result = await execute_neri_local_worker(
            _request(NeriHarnessArm.CRITIQUE_REPAIR), AsyncMock()
        )

    assert one_pass.await_count == 2
    assert result.runtime_metrics["passes"] == 2
    assert result.runtime_metrics["latency_ms"] == 22
    assert result.prompt_revision == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arm", [NeriHarnessArm.ROLE_CHECKLIST, NeriHarnessArm.CRITIQUE_REPAIR]
)
async def test_structured_arms_repair_first_pass_schema_failure(
    arm: NeriHarnessArm,
) -> None:
    agent = SimpleNamespace(
        primary_model_id=LOCAL_NERI_QWEN3_8_27B_IQ3_S,
        fallback_models=[],
        escalation_model_id=None,
        system_prompt="passive",
        version=8,
    )
    service = SimpleNamespace(get_by_slug=AsyncMock(return_value=agent))
    output = _valid_output()
    first_failure = NeriLocalWorkerError(
        "invalid JSON",
        failure_kind="schema",
        runtime_metrics={"latency_ms": 10, "total_tokens": 20},
        effective_model=NERI_QWEN_RUNTIME_PROFILE.server_model_id,
        failed_content="{bad-json",
    )
    one_pass = AsyncMock(
        side_effect=[
            first_failure,
            (output, output.model_dump_json(), {"latency_ms": 12, "total_tokens": 25}),
        ]
    )
    with (
        patch("app.services.neri_local_worker.get_agent_service", return_value=service),
        patch("app.services.neri_local_worker._one_pass", new=one_pass),
        patch(
            "app.services.neri_local_worker._get_observed_runtime_metadata",
            new=AsyncMock(return_value={"observed_mtp_enabled": True}),
        ),
    ):
        result = await execute_neri_local_worker(
            _request(arm), AsyncMock()
        )

    assert one_pass.await_count == 2
    assert result.runtime_metrics["passes"] == 2
    assert result.runtime_metrics["repair_triggered"] is True
    assert result.runtime_metrics["first_pass_validated"] is False
    assert result.runtime_metrics["first_pass_failure_kind"] == "schema"
    assert result.runtime_metrics["latency_ms"] == 22


@pytest.mark.asyncio
async def test_critique_arm_never_retries_tool_policy_failure() -> None:
    agent = SimpleNamespace(
        primary_model_id=LOCAL_NERI_QWEN3_8_27B_IQ3_S,
        fallback_models=[],
        escalation_model_id=None,
        system_prompt="passive",
        version=8,
    )
    service = SimpleNamespace(get_by_slug=AsyncMock(return_value=agent))
    one_pass = AsyncMock(
        side_effect=NeriLocalWorkerError(
            "unexpected tool call",
            failure_kind="tool_policy",
            failed_content='{"tool":"bash"}',
        )
    )
    with (
        patch("app.services.neri_local_worker.get_agent_service", return_value=service),
        patch("app.services.neri_local_worker._one_pass", new=one_pass),
        patch(
            "app.services.neri_local_worker._get_observed_runtime_metadata",
            new=AsyncMock(return_value={"observed_mtp_enabled": True}),
        ),
        pytest.raises(NeriLocalWorkerError) as raised,
    ):
        await execute_neri_local_worker(
            _request(NeriHarnessArm.CRITIQUE_REPAIR), AsyncMock()
        )

    assert one_pass.await_count == 1
    assert raised.value.failure_kind == "tool_policy"
