"""Retained, tool-denied Codex app-server runtimes for delta-context completions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from app.utils.safe_subprocess import create_process

_DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "remote_plugin",
    "hooks",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "in_app_browser",
    "image_generation",
    "multi_agent",
    "multi_agent_v2",
    "view_image",
    "memories",
    "skill_search",
    "skill_mcp_dependency_install",
    "code_mode",
    "code_mode_host",
    "goals",
)
_TOOL_POLICY = {
    "version": 1,
    "tools": "deny",
    "network": False,
    "filesystem": "minimal-runtime-only",
    "features": _DISABLED_FEATURES,
}
NATIVE_TOOL_POLICY_HASH = hashlib.sha256(
    json.dumps(_TOOL_POLICY, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


class NativeRuntimeError(RuntimeError):
    """Safe, classified native-runtime failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        self.observation: NativeTurnObservation | None = None
        super().__init__(message)


class NativeRuntimeLost(NativeRuntimeError):
    """The logical generation no longer has a live process/thread owner."""

    def __init__(self) -> None:
        super().__init__(
            "native_generation_unavailable",
            "The retained native generation is unavailable. Start a higher generation with a fresh snapshot; the uncertain turn was not replayed.",
        )


@dataclass(frozen=True, slots=True)
class NativeRuntimeKey:
    session_id: str
    generation: int
    client_id: str
    project_id: str
    role: str
    controller_generation: str
    instruction_hash: str
    tool_policy_hash: str
    model: str
    reasoning_effort: str
    cyber_access_program: str | None = None


@dataclass(slots=True)
class NativeTurnUsage:
    input_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    known: bool = False


@dataclass(slots=True)
class NativeTurnObservation:
    answer_text: str
    thread_id: str
    turn_id: str | None
    observed_model: str
    usage: NativeTurnUsage
    runtime: str | None


def _runtime_binary() -> Path:
    executable = shutil.which("codex")
    if not executable:
        raise NativeRuntimeError("native_unavailable", "Codex CLI is not installed.")
    resolved = Path(executable).resolve()
    if resolved.suffix != ".js":
        entries = [Path(part) / "codex" for part in os.get_exec_path()]
        npm_entries = {
            entry.resolve()
            for entry in entries
            if entry.is_file() and entry.resolve().suffix == ".js"
        }
        if len(npm_entries) == 1:
            resolved = npm_entries.pop()
    if resolved.suffix == ".js":
        candidates = list(
            resolved.parent.parent.glob("node_modules/@openai/codex-linux-*/vendor/*/bin/codex")
        )
        if len(candidates) != 1:
            raise NativeRuntimeError(
                "native_unavailable", "Cannot uniquely identify the installed native Codex binary."
            )
        resolved = candidates[0].resolve()
    return resolved


def _profile_config(binary: Path) -> str:
    return "\n".join(
        [
            'default_permissions = "agent_hub_native"',
            'approval_policy = "on-request"',
            'forced_login_method = "chatgpt"',
            'cli_auth_credentials_store = "file"',
            'web_search = "disabled"',
            "project_doc_max_bytes = 0",
            "[history]",
            'persistence = "none"',
            "[features]",
            *(f"{feature} = false" for feature in _DISABLED_FEATURES),
            "[tools]",
            "view_image = false",
            "[permissions.agent_hub_native.filesystem]",
            '":minimal" = "read"',
            f"{json.dumps(str(binary.parent))} = \"read\"",
            "[permissions.agent_hub_native.network]",
            "enabled = false",
            "",
        ]
    )


async def _sandbox_preflight(
    binary: Path, home: Path, work: Path, env: dict[str, str]
) -> None:
    canary = home / "canary"
    canary.write_text("synthetic-canary")
    script = """import errno,os,socket,sys
assert all(not os.access(p,os.R_OK) for p in sys.argv[1:])
try:
    socket.socket()
except OSError as error:
    assert error.errno in (errno.EPERM, errno.EACCES)
    print("DENIED")
else:
    raise AssertionError("network socket creation permitted")
"""
    process = await create_process(
        str(binary),
        "sandbox",
        "-P",
        "agent_hub_native",
        "-C",
        str(work),
        "/usr/bin/python3",
        "-c",
        script,
        str(canary),
        str(home / "auth.json"),
        str((home / "auth.json").resolve()),
        str(Path(__file__).resolve()),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 20)
        if process.returncode or stdout.strip() != b"DENIED":
            raise NativeRuntimeError(
                "native_isolation_unavailable",
                "Native filesystem/network sandbox preflight failed.",
            )
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class _Protocol:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self.sequence = 0
        self.notifications: list[dict[str, Any]] = []

    async def send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise NativeRuntimeLost()
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def receive(self) -> dict[str, Any]:
        if self.process.stdout is None:
            raise NativeRuntimeLost()
        line = await self.process.stdout.readline()
        if not line:
            raise NativeRuntimeLost()
        message = json.loads(line)
        if "method" in message and "id" in message:
            await self.send(
                {
                    "id": message["id"],
                    "error": {
                        "code": -32601,
                        "message": "Native continuation does not permit tools or approvals.",
                    },
                }
            )
            raise NativeRuntimeError(
                "native_tool_denied", "Native reasoning requested a denied tool or approval."
            )
        return message

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        request_id = self.sequence
        await self.send({"id": request_id, "method": method, "params": params})
        while True:
            message = await self.receive()
            if message.get("id") == request_id:
                if "error" in message:
                    raise _safe_provider_error(message["error"])
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            self.notifications.append(message)


def _safe_provider_error(error: object) -> NativeRuntimeError:
    value = cast(dict[str, Any], error) if isinstance(error, dict) else {}
    raw_data = value.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    fallback_info = data.get("codexErrorInfo", value.get("code"))
    info = value.get("codexErrorInfo", fallback_info)
    code = next(iter(info), None) if isinstance(info, dict) else info
    known = {
        "cyberPolicy": ("native_provider_refusal", "The native provider declined this request."),
        "misalignmentPolicyViolation": (
            "native_provider_refusal",
            "The native provider declined this request.",
        ),
        "usageLimitExceeded": (
            "native_quota_exceeded",
            "The native provider reported a usage limit.",
        ),
        "rateLimitExceeded": (
            "native_quota_exceeded",
            "The native provider reported a rate limit.",
        ),
        "unauthorized": (
            "native_auth_unavailable",
            "The native provider reported an authentication failure.",
        ),
        "contextWindowExceeded": (
            "native_context_limit",
            "The retained native context window was exceeded.",
        ),
    }
    safe_code, message = known.get(
        code, ("native_provider_error", "The native provider did not complete the request.")
    )
    return NativeRuntimeError(safe_code, message)


def _usage_int(value: object, *keys: str) -> int:
    if not isinstance(value, dict):
        return 0
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return max(0, candidate)
    return 0


def _turn_usage(
    token_usage: object, previous_total: dict[str, int]
) -> tuple[NativeTurnUsage, dict[str, int]]:
    payload = token_usage if isinstance(token_usage, dict) else {}
    last = payload.get("last")
    total = payload.get("total")
    total = total if isinstance(total, dict) else {}
    current_total = {
        "input": _usage_int(total, "inputTokens", "input_tokens"),
        "cache": _usage_int(total, "cachedInputTokens", "cached_input_tokens"),
        "output": _usage_int(total, "outputTokens", "output_tokens"),
        "reasoning": _usage_int(total, "reasoningOutputTokens", "reasoning_output_tokens"),
    }
    if isinstance(last, dict):
        usage = NativeTurnUsage(
            input_tokens=_usage_int(last, "inputTokens", "input_tokens"),
            cache_read_tokens=_usage_int(last, "cachedInputTokens", "cached_input_tokens"),
            output_tokens=_usage_int(last, "outputTokens", "output_tokens"),
            reasoning_tokens=_usage_int(
                last, "reasoningOutputTokens", "reasoning_output_tokens"
            ),
            known=True,
        )
    elif current_total:
        usage = NativeTurnUsage(
            input_tokens=max(0, current_total["input"] - previous_total.get("input", 0)),
            cache_read_tokens=max(0, current_total["cache"] - previous_total.get("cache", 0)),
            output_tokens=max(0, current_total["output"] - previous_total.get("output", 0)),
            reasoning_tokens=max(
                0, current_total["reasoning"] - previous_total.get("reasoning", 0)
            ),
            known=bool(total),
        )
    else:
        usage = NativeTurnUsage()
    return usage, current_total or previous_total


@dataclass(slots=True)
class _RetainedRuntime:
    key: NativeRuntimeKey
    tempdir: tempfile.TemporaryDirectory[str]
    process: asyncio.subprocess.Process
    protocol: _Protocol
    thread_id: str
    observed_model: str
    runtime_name: str | None
    total_usage: dict[str, int] = field(default_factory=dict)

    def _attach_observation(
        self,
        failure: NativeRuntimeError,
        *,
        answer: str,
        turn_id: str | None,
        usage: NativeTurnUsage,
    ) -> NativeRuntimeError:
        failure.observation = NativeTurnObservation(
            answer_text=answer,
            thread_id=self.thread_id,
            turn_id=turn_id,
            observed_model=self.observed_model,
            usage=usage,
            runtime=self.runtime_name,
        )
        return failure

    async def turn(
        self, prompt: str, output_schema: dict[str, Any] | None
    ) -> NativeTurnObservation:
        params: dict[str, Any] = {
            "threadId": self.thread_id,
            "input": [{"type": "text", "text": prompt}],
            "effort": self.key.reasoning_effort,
        }
        if self.key.cyber_access_program:
            params["cyberAccessProgram"] = self.key.cyber_access_program
        if output_schema:
            params["outputSchema"] = output_schema
        started = await self.protocol.request("turn/start", params)
        turn_id = (started.get("turn") or {}).get("id")
        answer = ""
        usage = NativeTurnUsage()
        turn_baseline = dict(self.total_usage)
        latest_total = dict(self.total_usage)
        while True:
            message = (
                self.protocol.notifications.pop(0)
                if self.protocol.notifications
                else await self.protocol.receive()
            )
            method = message.get("method")
            raw_params = message.get("params")
            params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
            if method == "error":
                failure = _safe_provider_error(params.get("error"))
                if params.get("willRetry") is True and failure.code != "native_provider_refusal":
                    continue
                raise self._attach_observation(
                    failure, answer=answer, turn_id=turn_id, usage=usage
                )
            if method == "item/started" and params.get("item", {}).get("type") not in (
                "userMessage",
                "agentMessage",
                "reasoning",
            ):
                raise NativeRuntimeError(
                    "native_tool_denied", "Native reasoning emitted an unexpected tool or item."
                )
            if method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                answer = params["item"].get("text", "")
            elif method == "thread/tokenUsage/updated":
                usage, latest_total = _turn_usage(
                    params.get("tokenUsage"), turn_baseline
                )
            elif method == "model/rerouted" and params.get("threadId") == self.thread_id:
                self.observed_model = params.get("toModel") or self.observed_model
            elif method == "turn/completed":
                raw_turn = params.get("turn")
                turn: dict[str, Any] = raw_turn if isinstance(raw_turn, dict) else {}
                if turn.get("status") != "completed":
                    raise self._attach_observation(
                        _safe_provider_error(turn.get("error")),
                        answer=answer,
                        turn_id=turn_id,
                        usage=usage,
                    )
                self.total_usage = latest_total
                return NativeTurnObservation(
                    answer_text=answer,
                    thread_id=self.thread_id,
                    turn_id=turn_id,
                    observed_model=self.observed_model,
                    usage=usage,
                    runtime=self.runtime_name,
                )

    async def close(self) -> None:
        try:
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 5)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
        finally:
            self.tempdir.cleanup()


class NativeRuntimeManager:
    """Own one retained process/thread for each active logical generation."""

    def __init__(self) -> None:
        self._runtimes: dict[tuple[str, int], _RetainedRuntime] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _start(self, key: NativeRuntimeKey, instructions: str) -> _RetainedRuntime:
        binary = _runtime_binary()
        auth_root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        auth = auth_root / "auth.json"
        if not auth.is_file():
            raise NativeRuntimeError(
                "native_auth_unavailable",
                "Existing Codex file-based ChatGPT subscription sign-in is unavailable.",
            )
        tempdir = tempfile.TemporaryDirectory(prefix="agent-hub-native-")
        root = Path(tempdir.name)
        home, work = root / "home", root / "work"
        home.mkdir(mode=0o700)
        work.mkdir(mode=0o700)
        (home / "config.toml").write_text(_profile_config(binary))
        (home / "auth.json").symlink_to(auth.resolve())
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "CODEX_HOME": str(home),
            "LANG": "C.UTF-8",
        }
        process: asyncio.subprocess.Process | None = None
        try:
            await _sandbox_preflight(binary, home, work, env)
            process = await create_process(
                str(binary),
                "app-server",
                "--stdio",
                working_dir=work,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=2**20,
            )
            protocol = _Protocol(process)
            initialized = await protocol.request(
                "initialize",
                {
                    "clientInfo": {"name": "agent-hub", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            await protocol.send({"method": "initialized"})
            account = await protocol.request("account/read", {"refreshToken": False})
            if (account.get("account") or {}).get("type") != "chatgpt":
                raise NativeRuntimeError(
                    "native_auth_unavailable",
                    "Native continuation requires existing ChatGPT subscription authentication.",
                )
            native_model = key.model.removeprefix("codex/")
            thread = await protocol.request(
                "thread/start",
                {
                    "cwd": str(work),
                    "ephemeral": True,
                    "developerInstructions": instructions,
                    "model": native_model,
                },
            )
            return _RetainedRuntime(
                key=key,
                tempdir=tempdir,
                process=process,
                protocol=protocol,
                thread_id=thread["thread"]["id"],
                observed_model=thread.get("model") or native_model,
                runtime_name=initialized.get("userAgent"),
            )
        except BaseException:
            if process is not None and process.returncode is None:
                process.kill()
                await asyncio.shield(process.wait())
            tempdir.cleanup()
            raise

    async def execute(
        self,
        key: NativeRuntimeKey,
        *,
        mode: str,
        instructions: str,
        prompt: str,
        output_schema: dict[str, Any] | None,
        close_after: bool,
    ) -> NativeTurnObservation:
        identity = (key.session_id, key.generation)
        lock = self._locks.setdefault(key.session_id, asyncio.Lock())
        async with lock:
            runtime = self._runtimes.get(identity)
            try:
                async with asyncio.timeout(180):
                    if mode == "snapshot":
                        stale = [
                            (runtime_identity, retained)
                            for runtime_identity, retained in self._runtimes.items()
                            if runtime_identity[0] == key.session_id
                        ]
                        for runtime_identity, retained in stale:
                            self._runtimes.pop(runtime_identity, None)
                            await retained.close()
                        runtime = await self._start(key, instructions)
                        self._runtimes[identity] = runtime
                    elif runtime is None or runtime.key != key:
                        raise NativeRuntimeLost()
                    result = await runtime.turn(prompt, output_schema)
            except BaseException:
                self._runtimes.pop(identity, None)
                if runtime is not None:
                    await asyncio.shield(runtime.close())
                raise
            if close_after:
                self._runtimes.pop(identity, None)
                await runtime.close()
            return result

    async def close(self, session_id: str, generation: int) -> bool:
        identity = (session_id, generation)
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            runtime = self._runtimes.pop(identity, None)
            if runtime is None:
                return False
            await runtime.close()
            return True

    async def shutdown(self) -> None:
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        for runtime in runtimes:
            await runtime.close()


_MANAGER = NativeRuntimeManager()


def get_native_runtime_manager() -> NativeRuntimeManager:
    return _MANAGER


async def shutdown_native_runtime_manager() -> None:
    await _MANAGER.shutdown()
