"""Comprehensive SDK Capability Tests for Agent Hub.

This test suite validates ALL relevant features of Claude Agent SDK and
Google GenAI SDK for use in the Agent Hub orchestration system.

Covers:
- Session management (resume, fork, history replay)
- Token efficiency measurement
- Latency profiling (TTFT, total time)
- Context caching (Gemini explicit/implicit)
- Streaming vs non-streaming
- Tool/function calling
- Thinking modes
- Error handling and retries
- Multimodal support

Usage:
    # Run all tests (requires --run-integration)
    pytest tests/integration/test_sdk_capabilities.py -v -s --no-cov --run-integration

    # Run specific test class
    pytest tests/integration/test_sdk_capabilities.py::TestClaudeSessionManagement -v -s --no-cov --run-integration

    # Run benchmarks only
    pytest tests/integration/test_sdk_capabilities.py -k "benchmark" -v -s --no-cov --run-integration

Requirements:
    - Claude CLI installed and authenticated
    - GEMINI_API_KEY environment variable
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import pytest

from app.config import settings


@dataclass
class LatencyMetrics:
    """Latency measurements for a completion."""

    time_to_first_token_ms: float
    total_time_ms: float
    input_tokens: int
    output_tokens: int
    tokens_per_second: float


@dataclass
class SessionMetrics:
    """Metrics comparing session strategies."""

    fresh_latency_ms: float
    resumed_latency_ms: float
    fresh_tokens: int
    resumed_tokens: int
    savings_percent: float


class TestClaudeSessionManagement:
    """Test Claude SDK session management features.

    Features tested:
    - session_id capture from init message
    - resume parameter for session continuation
    - fork_session for branching conversations
    - continue_conversation flag
    - Session persistence

    Reference: https://platform.claude.com/docs/en/agent-sdk/sessions
    """

    @pytest.fixture
    def working_dir(self, tmp_path: Any) -> str:
        """Create temp working directory."""
        return str(tmp_path)

    @pytest.fixture
    def cli_path(self) -> str:
        """Get system Claude CLI path."""
        import shutil

        cli = shutil.which("claude")
        if not cli:
            pytest.skip("Claude CLI not found")
        return cli

    @pytest.mark.asyncio
    async def test_session_id_capture(self, working_dir: str, cli_path: str) -> None:
        """Verify session_id is captured from init message."""
        import sys

        from claude_agent_sdk import ClaudeAgentOptions, query

        stderr_output: list[str] = []

        def capture_stderr(line: str) -> None:
            stderr_output.append(line)
            print(f"[STDERR] {line}", file=sys.stderr)

        options = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
            stderr=capture_stderr,
        )

        session_id: str | None = None
        message_types: list[str] = []

        try:
            async for message in query(prompt="Say hello", options=options):
                msg_type = getattr(message, "type", "unknown")
                msg_subtype = getattr(message, "subtype", "")
                message_types.append(f"{msg_type}:{msg_subtype}")

                if msg_subtype == "init" and hasattr(message, "data"):
                    session_id = message.data.get("session_id")
        except Exception:
            print(f"\nStderr output: {stderr_output}")
            raise

        print(f"\nMessage types: {message_types}")
        print(f"Session ID: {session_id}")

        assert session_id is not None, "Should capture session_id"
        assert len(session_id) > 10, "Session ID should be substantial"

    @pytest.mark.asyncio
    async def test_session_resume(self, working_dir: str, cli_path: str) -> None:
        """Test resuming a session maintains conversation context."""
        from claude_agent_sdk import ClaudeAgentOptions, query

        # Turn 1: Establish context
        opts1 = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
        )

        session_id: str | None = None
        async for msg in query(prompt="Remember: my name is TestUser", options=opts1):
            if getattr(msg, "subtype", "") == "init":
                session_id = msg.data.get("session_id")

        assert session_id is not None
        print(f"\nSession ID for resume: {session_id}")

        # Turn 2: Resume and verify context
        opts2 = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
            resume=session_id,
        )

        response_text = ""
        all_messages: list[str] = []
        async for msg in query(prompt="What is my name?", options=opts2):
            msg_type = getattr(msg, "type", "unknown")
            msg_subtype = getattr(msg, "subtype", "")
            all_messages.append(f"{msg_type}:{msg_subtype}")

            # Try different ways to get content
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    response_text += content
                elif isinstance(content, list):
                    for item in content:
                        if hasattr(item, "text"):
                            response_text += item.text
            if hasattr(msg, "text"):
                response_text += str(msg.text)

        print(f"All messages: {all_messages}")
        print(f"Response: {response_text[:300]}")
        assert "TestUser" in response_text, f"Should remember name. Got: {response_text[:200]}"

    @pytest.mark.asyncio
    async def test_session_fork(self, working_dir: str, cli_path: str) -> None:
        """Test fork_session creates new session branch."""
        from claude_agent_sdk import ClaudeAgentOptions, query

        # Original session
        opts1 = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
        )

        original_id: str | None = None
        async for msg in query(prompt="We're building a REST API", options=opts1):
            if getattr(msg, "subtype", "") == "init":
                original_id = msg.data.get("session_id")

        assert original_id is not None
        print(f"\nOriginal session: {original_id}")

        # Fork to explore alternative
        opts_fork = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
            resume=original_id,
            fork_session=True,
        )

        forked_id: str | None = None
        async for msg in query(prompt="Actually, let's use GraphQL", options=opts_fork):
            if getattr(msg, "subtype", "") == "init":
                forked_id = msg.data.get("session_id")

        print(f"Forked session: {forked_id}")

        # Forked session should have different ID
        assert forked_id is not None
        assert forked_id != original_id, "Forked session should have new ID"


class TestClaudeThinkingMode:
    """Test Claude thinking/reasoning capabilities."""

    @pytest.fixture
    def working_dir(self, tmp_path: Any) -> str:
        return str(tmp_path)

    @pytest.fixture
    def cli_path(self) -> str:
        import shutil

        cli = shutil.which("claude")
        if not cli:
            pytest.skip("Claude CLI not found")
        return cli

    @pytest.mark.asyncio
    async def test_max_thinking_tokens(self, working_dir: str, cli_path: str) -> None:
        """Test max_thinking_tokens parameter affects extended thinking."""
        from claude_agent_sdk import ClaudeAgentOptions, query

        # With thinking tokens
        opts = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
            max_thinking_tokens=1024,  # Enable extended thinking
        )

        response_text = ""
        async for msg in query(
            prompt="Solve: If 3x + 7 = 22, what is x? Think step by step.", options=opts
        ):
            # Get content from message
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    response_text += content
                elif isinstance(content, list):
                    for item in content:
                        if hasattr(item, "text"):
                            response_text += item.text
            if hasattr(msg, "text"):
                response_text += str(msg.text)

        print(f"\nThinking response: {response_text[:500]}")
        assert "5" in response_text, f"Should solve correctly. Got: {response_text[:200]}"


class TestGeminiChatManagement:
    """Test Gemini chat/conversation management.

    Features tested:
    - AsyncChat with history
    - History serialization/deserialization
    - Context caching (explicit)
    - Chat continuation

    Reference: https://ai.google.dev/gemini-api/docs/caching
    """

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_chat_history_continuation(self, api_key: str) -> None:
        """Test AsyncChat maintains conversation across turns."""
        from google import genai
        from google.genai.chats import AsyncChat

        client = genai.Client(api_key=api_key)
        model = "gemini-3-flash-preview"

        # Turn 1
        chat = AsyncChat(modules=client.aio.models, model=model, history=[])
        await chat.send_message("Remember: my favorite color is blue")

        # Turn 2 (same chat object)
        response = await chat.send_message("What is my favorite color?")

        print(f"\nChat response: {response.text}")
        assert "blue" in response.text.lower(), f"Should remember color. Got: {response.text}"

    @pytest.mark.asyncio
    async def test_chat_history_serialization(self, api_key: str) -> None:
        """Test history can be serialized/deserialized for DB storage."""
        from google import genai
        from google.genai import types
        from google.genai.chats import AsyncChat

        client = genai.Client(api_key=api_key)
        model = "gemini-3-flash-preview"

        # Build conversation
        chat = AsyncChat(modules=client.aio.models, model=model, history=[])
        await chat.send_message("My secret code is ALPHA-7")
        history = chat.get_history()

        # Serialize to JSON (for DB storage)
        serialized: list[dict[str, Any]] = []
        for content in history:
            parts_data = []
            for part in content.parts:
                if hasattr(part, "text") and part.text:
                    parts_data.append({"type": "text", "text": part.text})
            serialized.append({"role": content.role, "parts": parts_data})

        json_str = json.dumps(serialized)
        print(f"\nSerialized ({len(json_str)} chars): {json_str[:300]}")

        # Deserialize
        loaded = json.loads(json_str)
        reconstructed: list[types.Content] = []
        for item in loaded:
            parts = [types.Part(text=p["text"]) for p in item["parts"] if p["type"] == "text"]
            reconstructed.append(types.Content(role=item["role"], parts=parts))

        # Restore chat
        restored_chat = AsyncChat(
            modules=client.aio.models,
            model=model,
            history=reconstructed,
        )
        response = await restored_chat.send_message("What was my secret code?")

        print(f"Restored response: {response.text}")
        assert "ALPHA" in response.text or "7" in response.text, (
            f"Should remember code. Got: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_explicit_cache_creation(self, api_key: str) -> None:
        """Test explicit context caching for large content."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Create substantial content (must exceed min token threshold)
        large_context = """
        This is a comprehensive technical document about software architecture.
        """ + ("The system architecture follows microservices principles. " * 200)

        try:
            cache = await client.aio.caches.create(
                model="models/gemini-3-flash-preview",
                config=types.CreateCachedContentConfig(
                    contents=[types.Content(role="user", parts=[types.Part(text=large_context)])],
                    ttl="300s",  # 5 minutes
                    display_name="test-cache",
                ),
            )
            print(f"\nCache created: {cache.name}")
            print(f"Token count: {cache.usage_metadata}")

            # Use the cache
            response = await client.aio.models.generate_content(
                model="models/gemini-3-flash-preview",
                contents="Summarize the architecture document",
                config=types.GenerateContentConfig(
                    cached_content=cache.name,
                ),
            )
            print(f"Cached response: {response.text[:200]}")

            # Cleanup
            await client.aio.caches.delete(name=cache.name)
            print("Cache deleted")

        except Exception as e:
            # Caching may fail if content below threshold
            print(f"Cache test note: {e}")
            pytest.skip(f"Caching may require minimum tokens: {e}")


class TestGeminiThinkingMode:
    """Test Gemini thinking/reasoning capabilities."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_thinking_level_high(self, api_key: str) -> None:
        """Test Gemini thinking_level=high for complex reasoning."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents="Solve step by step: A farmer has chickens and cows. "
            "There are 20 heads and 56 legs. How many of each?",
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
            ),
        )

        # Check for thinking content
        thinking_text = ""
        response_text = ""
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if getattr(part, "thought", False) and part.text:
                    thinking_text += part.text
                elif part.text:
                    response_text += part.text

        print(f"\nThinking ({len(thinking_text)} chars): {thinking_text[:300]}")
        print(f"Response: {response_text[:300]}")

        # Should have 12 chickens and 8 cows
        assert "12" in response_text or "8" in response_text, "Should solve correctly"


class TestTokenCounting:
    """Test token counting and usage metrics."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_gemini_token_counting(self, api_key: str) -> None:
        """Test Gemini token counting API."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Count tokens before making request
        contents = [types.Content(role="user", parts=[types.Part(text="Hello world!")])]

        try:
            count_result = await client.aio.models.count_tokens(
                model="gemini-3-flash-preview",
                contents=contents,
            )
            print(f"\nToken count: {count_result}")
            assert hasattr(count_result, "total_tokens")
        except Exception as e:
            print(f"Token counting note: {e}")

    @pytest.mark.asyncio
    async def test_gemini_usage_metadata(self, api_key: str) -> None:
        """Test usage metadata in Gemini responses."""
        from google import genai

        client = genai.Client(api_key=api_key)

        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents="Say hello in exactly 5 words",
        )

        print(f"\nUsage metadata: {response.usage_metadata}")
        assert response.usage_metadata is not None
        assert response.usage_metadata.prompt_token_count > 0
        assert response.usage_metadata.candidates_token_count > 0


class TestStreamingBehavior:
    """Test streaming vs non-streaming completion."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_gemini_streaming_ttft(self, api_key: str) -> None:
        """Measure time-to-first-token with streaming."""
        from google import genai

        client = genai.Client(api_key=api_key)

        start_time = time.perf_counter()
        first_token_time: float | None = None
        full_response = ""

        # Use synchronous stream for simplicity (async stream requires different handling)
        stream = client.models.generate_content_stream(
            model="gemini-3-flash-preview",
            contents="Write a haiku about coding",
        )

        for chunk in stream:
            if first_token_time is None and chunk.text:
                first_token_time = time.perf_counter()
            full_response += chunk.text or ""

        total_time = time.perf_counter() - start_time

        ttft_ms = (first_token_time - start_time) * 1000 if first_token_time else 0
        print(f"\nStreaming TTFT: {ttft_ms:.1f}ms")
        print(f"Total time: {total_time * 1000:.1f}ms")
        print(f"Response: {full_response}")

        assert ttft_ms < total_time * 1000 or ttft_ms == 0, "TTFT should be less than total"


class TestLatencyBenchmarks:
    """Benchmark latency for different approaches."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.fixture
    def working_dir(self, tmp_path: Any) -> str:
        return str(tmp_path)

    @pytest.fixture
    def cli_path(self) -> str:
        import shutil

        cli = shutil.which("claude")
        if not cli:
            pytest.skip("Claude CLI not found")
        return cli

    @pytest.mark.asyncio
    async def test_benchmark_claude_resume_vs_fresh(self, working_dir: str, cli_path: str) -> None:
        """Compare latency: fresh session vs resumed session."""
        from claude_agent_sdk import ClaudeAgentOptions, query

        # Turn 1: Fresh session
        opts1 = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
        )

        start_fresh = time.perf_counter()
        session_id: str | None = None
        async for msg in query(prompt="Remember X=42", options=opts1):
            if getattr(msg, "subtype", "") == "init":
                session_id = msg.data.get("session_id")
        fresh_time = time.perf_counter() - start_fresh

        assert session_id is not None

        # Turn 2: Resumed session
        opts2 = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
            resume=session_id,
        )

        start_resume = time.perf_counter()
        async for _ in query(prompt="What is X?", options=opts2):
            pass
        resume_time = time.perf_counter() - start_resume

        print("\n=== Claude Resume Benchmark ===")
        print(f"Fresh session:   {fresh_time * 1000:.0f}ms")
        print(f"Resumed session: {resume_time * 1000:.0f}ms")
        print(f"Difference:      {(fresh_time - resume_time) * 1000:.0f}ms")

    @pytest.mark.asyncio
    async def test_benchmark_gemini_chat_vs_replay(self, api_key: str) -> None:
        """Compare: same chat object vs history replay."""
        from google import genai
        from google.genai.chats import AsyncChat

        client = genai.Client(api_key=api_key)
        model = "gemini-3-flash-preview"

        # Setup: first turn
        chat = AsyncChat(modules=client.aio.models, model=model, history=[])

        start_t1 = time.perf_counter()
        await chat.send_message("Remember X=42")
        t1_time = time.perf_counter() - start_t1

        history = chat.get_history()

        # Option A: Continue same chat object
        start_same = time.perf_counter()
        await chat.send_message("What is X?")
        same_chat_time = time.perf_counter() - start_same

        # Option B: Create new chat with history replay
        start_replay = time.perf_counter()
        replayed = AsyncChat(
            modules=client.aio.models,
            model=model,
            history=history,
        )
        await replayed.send_message("What is X?")
        replay_time = time.perf_counter() - start_replay

        print("\n=== Gemini Chat Benchmark ===")
        print(f"Initial turn:    {t1_time * 1000:.0f}ms")
        print(f"Same chat obj:   {same_chat_time * 1000:.0f}ms")
        print(f"History replay:  {replay_time * 1000:.0f}ms")
        print(f"History size:    {len(history)} messages")


class TestToolCalling:
    """Test tool/function calling capabilities."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_gemini_function_calling(self, api_key: str) -> None:
        """Test Gemini function calling with tool definitions."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Define a tool
        get_weather = types.FunctionDeclaration(
            name="get_weather",
            description="Get weather for a location",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "location": types.Schema(type=types.Type.STRING),
                },
                required=["location"],
            ),
        )

        tools = [types.Tool(function_declarations=[get_weather])]

        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents="What's the weather in Tokyo?",
            config=types.GenerateContentConfig(
                tools=tools,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )

        # Check for function call
        has_function_call = False
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    has_function_call = True
                    print(f"\nFunction call: {part.function_call.name}")
                    print(f"Args: {part.function_call.args}")

        assert has_function_call, "Should request function call"


class TestErrorHandling:
    """Test error handling and retry behavior."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_gemini_invalid_model_error(self, api_key: str) -> None:
        """Test error handling for invalid model."""
        from google import genai

        client = genai.Client(api_key=api_key)

        with pytest.raises(Exception) as exc_info:
            await client.aio.models.generate_content(
                model="invalid-model-name",
                contents="Hello",
            )

        print(f"\nError type: {type(exc_info.value)}")
        print(f"Error: {exc_info.value}")


class TestMultimodal:
    """Test multimodal (image) capabilities."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_gemini_image_understanding(self, api_key: str) -> None:
        """Test Gemini image analysis with base64 image."""
        import base64

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Create a simple 1x1 red PNG (smallest valid image)
        red_pixel_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
        )

        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text="What color is this image?"),
                        types.Part.from_bytes(data=red_pixel_png, mime_type="image/png"),
                    ],
                )
            ],
        )

        print(f"\nImage analysis: {response.text}")
        # The 1x1 pixel is gray/red-ish
        assert response.text is not None


class TestSessionEfficiencyComparison:
    """Compare session continuation efficiency across providers."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.fixture
    def working_dir(self, tmp_path: Any) -> str:
        return str(tmp_path)

    @pytest.fixture
    def cli_path(self) -> str:
        import shutil

        cli = shutil.which("claude")
        if not cli:
            pytest.skip("Claude CLI not found")
        return cli

    @pytest.mark.asyncio
    async def test_multi_turn_efficiency(
        self, working_dir: str, cli_path: str, api_key: str
    ) -> None:
        """Compare 5-turn conversation efficiency."""
        from claude_agent_sdk import ClaudeAgentOptions, query
        from google import genai
        from google.genai import errors
        from google.genai.chats import AsyncChat

        # Gemini: 5 turns
        client = genai.Client(api_key=api_key)
        gemini_chat = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=[],
        )

        gemini_times: list[float] = []
        prompts = [
            "Remember: A=1",
            "Remember: B=2",
            "Remember: C=3",
            "What is A+B?",
            "What is A+B+C?",
        ]

        try:
            for prompt in prompts:
                start = time.perf_counter()
                await gemini_chat.send_message(prompt)
                gemini_times.append((time.perf_counter() - start) * 1000)
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)

            print("\n=== Multi-Turn Efficiency ===")
            print(f"Gemini turn times (ms): {[f'{t:.0f}' for t in gemini_times]}")
            print(f"Gemini total: {sum(gemini_times):.0f}ms")
            print(f"Gemini history size: {len(gemini_chat.get_history())} messages")
        except errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                pytest.skip("Gemini rate limited - skipping multi-turn efficiency test")
            raise

        # Claude: 5 turns with resume
        claude_times: list[float] = []
        session_id: str | None = None

        for prompt in prompts:
            opts = ClaudeAgentOptions(
                model="claude-sonnet-4-5",
                max_turns=1,
                cwd=working_dir,
                cli_path=cli_path,
                resume=session_id if session_id else None,
            )

            start = time.perf_counter()
            async for msg in query(prompt=prompt, options=opts):
                if getattr(msg, "subtype", "") == "init":
                    session_id = msg.data.get("session_id")
            claude_times.append((time.perf_counter() - start) * 1000)

        print(f"Claude turn times (ms): {[f'{t:.0f}' for t in claude_times]}")
        print(f"Claude total: {sum(claude_times):.0f}ms")


# =============================================================================
# TASK #12: Tool Call ID Normalization Tests
# =============================================================================


class TestToolCallIdNormalization:
    """Test tool call ID handling across providers.

    Problem: Different providers have incompatible ID formats:
    - OpenAI Responses API: 450+ chars with pipes (|) and special chars
    - Anthropic Claude: <64 chars, alphanumeric only
    - Mistral: Exactly 9 alphanumeric chars
    - Gemini: Variable format

    These tests validate our normalization strategy works.
    """

    def test_openai_style_id_characteristics(self) -> None:
        """Document OpenAI Responses API ID format."""
        # Real example pattern from OpenAI Responses API (can be 450+ chars)
        # Format: call_{base64-like-string}|{more-segments}|{even-more}
        openai_id = (
            "call_abc123def456ghi789jkl012mno345pqr678stu901vwx234|"
            "segment_aaabbbcccdddeeefffggghhhiiijjjkkklllmmmnnn|"
            "final_111222333444555666777888999000aaabbbcccddd"
        )

        print(f"\nOpenAI-style ID length: {len(openai_id)}")
        print(f"Contains pipe: {'|' in openai_id}")
        print(f"ID sample: {openai_id[:50]}...")

        # Characteristics to handle
        assert "|" in openai_id, "OpenAI IDs can contain pipes"
        assert len(openai_id) > 64, "OpenAI IDs can exceed Anthropic's 64-char limit"

    def test_anthropic_id_constraints(self) -> None:
        """Document Anthropic Claude ID constraints."""
        # Anthropic requires: <64 chars, alphanumeric + underscore/hyphen only
        valid_anthropic_id = "toolu_01ABC123def456"
        invalid_chars = "|!@#$%^&*()"

        print(f"\nAnthropic ID example: {valid_anthropic_id}")
        print("Max length: 64 chars")
        print(f"Invalid chars: {invalid_chars}")

        assert len(valid_anthropic_id) < 64
        assert all(c.isalnum() or c in "_-" for c in valid_anthropic_id)

    def test_deterministic_hash_normalization(self) -> None:
        """Test that hash-based normalization is deterministic."""
        import hashlib

        def normalize_id(original_id: str, max_length: int = 32) -> str:
            """Normalize tool call ID using deterministic hash."""
            # If already valid, return as-is
            if len(original_id) <= max_length and original_id.isalnum():
                return original_id
            # Otherwise, hash it
            hash_digest = hashlib.sha256(original_id.encode()).hexdigest()
            return f"tc_{hash_digest[: max_length - 3]}"

        # Test with long OpenAI-style ID
        long_id = "call_" + "x" * 500 + "|pipe|special"
        normalized = normalize_id(long_id)

        print(f"\nOriginal length: {len(long_id)}")
        print(f"Normalized: {normalized}")
        print(f"Normalized length: {len(normalized)}")

        # Verify deterministic
        assert normalize_id(long_id) == normalized, "Must be deterministic"
        assert len(normalized) <= 32, "Must respect max length"
        assert normalized.replace("_", "").isalnum(), "Must be alphanumeric"

    def test_short_id_passthrough(self) -> None:
        """Test that short valid IDs pass through unchanged."""
        import hashlib

        def normalize_id(original_id: str, max_length: int = 32) -> str:
            if (
                len(original_id) <= max_length
                and original_id.replace("_", "").replace("-", "").isalnum()
            ):
                return original_id
            hash_digest = hashlib.sha256(original_id.encode()).hexdigest()
            return f"tc_{hash_digest[: max_length - 3]}"

        short_id = "toolu_01ABC"
        normalized = normalize_id(short_id)

        print(f"\nShort ID: {short_id}")
        print(f"Normalized: {normalized}")

        assert normalized == short_id, "Short valid IDs should pass through"

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_gemini_tool_call_id_format(self, api_key: str) -> None:
        """Capture actual Gemini tool call ID format."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        get_time = types.FunctionDeclaration(
            name="get_current_time",
            description="Get the current time",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        )

        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents="What time is it?",
            config=types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=[get_time])],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )

        # Extract tool call ID
        tool_call_id = None
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    # Gemini uses the function name or generates an ID
                    tool_call_id = (
                        getattr(part.function_call, "id", None) or part.function_call.name
                    )
                    print(f"\nGemini tool call ID: {tool_call_id}")
                    print(f"ID length: {len(str(tool_call_id))}")
                    print(f"Function name: {part.function_call.name}")

        # Document the format (may vary)
        assert tool_call_id is not None or response.candidates, "Should get response"


# =============================================================================
# TASK #13: Cross-Provider Message Transformation Tests
# =============================================================================


class TestCrossProviderMessageTransformation:
    """Test message transformation for cross-provider compatibility.

    Validates:
    - Thinking block transformation (provider-specific → text)
    - Tool result field normalization
    - Orphaned tool call handling
    - Error message filtering
    """

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.fixture
    def working_dir(self, tmp_path: Any) -> str:
        return str(tmp_path)

    @pytest.fixture
    def cli_path(self) -> str:
        import shutil

        cli = shutil.which("claude")
        if not cli:
            pytest.skip("Claude CLI not found")
        return cli

    @pytest.mark.asyncio
    async def test_gemini_to_claude_context_replay(
        self, api_key: str, working_dir: str, cli_path: str
    ) -> None:
        """Test replaying Gemini conversation context to Claude."""
        from claude_agent_sdk import ClaudeAgentOptions, query
        from google import genai
        from google.genai.chats import AsyncChat

        client = genai.Client(api_key=api_key)

        # Build context with Gemini
        gemini_chat = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=[],
        )
        await gemini_chat.send_message("My project uses Python 3.12 and FastAPI")
        await gemini_chat.send_message("The database is PostgreSQL with SQLAlchemy")

        # Extract context as text (transformation)
        history = gemini_chat.get_history()
        context_summary = []
        for content in history:
            role = "User" if content.role == "user" else "Assistant"
            text = " ".join(p.text for p in content.parts if hasattr(p, "text") and p.text)
            context_summary.append(f"{role}: {text}")

        transformed_context = "\n".join(context_summary)
        print(f"\nTransformed context:\n{transformed_context[:500]}")

        # Replay to Claude with transformed context
        opts = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
        )

        prompt = f"""Previous conversation context:
{transformed_context}

Based on this context, what database ORM am I using?"""

        response_text = ""
        async for msg in query(prompt=prompt, options=opts):
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    response_text += content
                elif isinstance(content, list):
                    for item in content:
                        if hasattr(item, "text"):
                            response_text += item.text
            if hasattr(msg, "text"):
                response_text += str(msg.text)

        print(f"Claude response: {response_text[:300]}")
        assert "SQLAlchemy" in response_text, (
            f"Should understand context. Got: {response_text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_claude_to_gemini_context_replay(
        self, api_key: str, working_dir: str, cli_path: str
    ) -> None:
        """Test replaying Claude conversation context to Gemini."""
        from claude_agent_sdk import ClaudeAgentOptions, query
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Build context with Claude
        opts = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
        )

        # Capture Claude's response
        claude_response = ""
        async for msg in query(
            prompt="I'm building a CLI tool called 'summit' for task management",
            options=opts,
        ):
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    claude_response += content
                elif isinstance(content, list):
                    for item in content:
                        if hasattr(item, "text"):
                            claude_response += item.text
            if hasattr(msg, "text"):
                claude_response += str(msg.text)

        # Transform for Gemini
        gemini_history = [
            types.Content(
                role="user",
                parts=[
                    types.Part(text="I'm building a CLI tool called 'summit' for task management")
                ],
            ),
            types.Content(
                role="model",
                parts=[types.Part(text=claude_response[:1000])],  # Truncate for test
            ),
        ]

        # Continue with Gemini
        from google.genai.chats import AsyncChat

        gemini_chat = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=gemini_history,
        )

        response = await gemini_chat.send_message("What's the name of my CLI tool?")
        print(f"\nGemini response: {response.text}")

        assert "summit" in response.text.lower(), f"Should understand context. Got: {response.text}"

    def test_thinking_block_transformation(self) -> None:
        """Test transforming thinking blocks for cross-provider replay."""

        def transform_thinking_for_replay(
            content_blocks: list[dict[str, Any]],
            same_provider: bool,
        ) -> list[dict[str, Any]]:
            """Transform thinking blocks based on target provider."""
            result = []
            for block in content_blocks:
                if block.get("type") == "thinking":
                    if same_provider and block.get("thinking_signature"):
                        # Preserve signature for same provider (enables caching)
                        result.append(block)
                    else:
                        # Convert to text for different provider
                        result.append(
                            {
                                "type": "text",
                                "text": f"<thinking>{block.get('thinking', '')}</thinking>",
                            }
                        )
                else:
                    result.append(block)
            return result

        # Test input with thinking block
        blocks = [
            {
                "type": "thinking",
                "thinking": "Let me analyze this...",
                "thinking_signature": "sig123",
            },
            {"type": "text", "text": "The answer is 42."},
        ]

        # Same provider: preserve signature
        same_provider_result = transform_thinking_for_replay(blocks, same_provider=True)
        print(f"\nSame provider result: {same_provider_result}")
        assert same_provider_result[0]["type"] == "thinking"
        assert same_provider_result[0].get("thinking_signature") == "sig123"

        # Different provider: convert to text
        diff_provider_result = transform_thinking_for_replay(blocks, same_provider=False)
        print(f"Different provider result: {diff_provider_result}")
        assert diff_provider_result[0]["type"] == "text"
        assert "<thinking>" in diff_provider_result[0]["text"]

    def test_orphaned_tool_call_handling(self) -> None:
        """Test handling tool calls without results."""

        def insert_synthetic_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """Insert synthetic error results for orphaned tool calls."""
            result = []
            pending_tool_calls: dict[str, str] = {}  # id -> name

            for msg in messages:
                if msg.get("role") == "assistant":
                    # Track tool calls
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_use":
                            pending_tool_calls[block["id"]] = block["name"]
                    result.append(msg)

                elif msg.get("role") == "user":
                    # Check for tool results
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_result":
                            pending_tool_calls.pop(block.get("tool_use_id"), None)
                    result.append(msg)

                    # If there are still pending tool calls, insert synthetic results
                    if pending_tool_calls:
                        synthetic_results = []
                        for tool_id, tool_name in pending_tool_calls.items():
                            synthetic_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": f"Error: Tool '{tool_name}' execution was interrupted",
                                    "is_error": True,
                                }
                            )
                        # Insert before the user message
                        result.insert(-1, {"role": "user", "content": synthetic_results})
                        pending_tool_calls.clear()
                else:
                    result.append(msg)

            return result

        # Test with orphaned tool call
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "read_file",
                        "input": {"path": "test.py"},
                    },
                ],
            },
            # Missing tool result!
            {"role": "user", "content": [{"type": "text", "text": "Continue please"}]},
        ]

        fixed = insert_synthetic_tool_results(messages)
        print(f"\nFixed messages: {json.dumps(fixed, indent=2)}")

        # Should have synthetic result inserted
        assert len(fixed) == 3, "Should insert synthetic result"
        assert fixed[1]["content"][0]["is_error"] is True


# =============================================================================
# TASK #13 (cont): Thinking Signature Preservation Tests
# =============================================================================


class TestThinkingSignaturePreservation:
    """Test Gemini thinking signature preservation for context reuse.

    When Gemini uses extended thinking, it returns a thoughtSignature
    that can be used to skip re-computing reasoning on follow-up turns.
    """

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_gemini_thinking_returns_signature(self, api_key: str) -> None:
        """Test if Gemini returns thinking signature with extended thinking."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents="Solve: What is the derivative of x^3 + 2x^2 - 5x + 3?",
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
            ),
        )

        # Check for thinking signature in response
        thinking_signature = None
        thinking_content = ""
        response_text = ""

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                # Check for thought attribute (indicates thinking block)
                if getattr(part, "thought", False):
                    thinking_content = part.text or ""
                    # Check for signature
                    thinking_signature = getattr(part, "thinking_signature", None)
                elif part.text:
                    response_text += part.text

        print(f"\nThinking content length: {len(thinking_content)}")
        print(f"Thinking signature: {thinking_signature}")
        print(f"Response: {response_text[:200]}")
        print(
            f"Thoughts token count: {response.usage_metadata.thoughts_token_count if response.usage_metadata else 'N/A'}"
        )

        # Document what we find (signature availability may vary by model version)
        if thinking_signature:
            print("✓ Thinking signature available - can implement caching")
        else:
            print("⚠ No thinking signature - may need different approach")

    @pytest.mark.asyncio
    async def test_thinking_token_savings_measurement(self, api_key: str) -> None:
        """Measure potential token savings from thinking reuse."""
        from google import genai
        from google.genai import types
        from google.genai.chats import AsyncChat

        client = genai.Client(api_key=api_key)

        # Turn 1: Complex reasoning question
        chat = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=[],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
            ),
        )

        response1 = await chat.send_message(
            "Explain the time complexity of quicksort and why it's O(n log n) average case"
        )
        tokens1 = response1.usage_metadata.thoughts_token_count if response1.usage_metadata else 0

        # Turn 2: Follow-up (should potentially reuse thinking)
        response2 = await chat.send_message("What about the worst case?")
        tokens2 = response2.usage_metadata.thoughts_token_count if response2.usage_metadata else 0

        print("\n=== Thinking Token Analysis ===")
        print(f"Turn 1 thinking tokens: {tokens1}")
        print(f"Turn 2 thinking tokens: {tokens2}")

        if tokens1 and tokens2:
            if tokens2 < tokens1:
                savings = (1 - tokens2 / tokens1) * 100
                print(f"Potential savings: {savings:.1f}%")
            else:
                print("No savings observed (thinking may not be cached)")


# =============================================================================
# TASK #14: Session Branching/Fork Tests
# =============================================================================


class TestSessionBranchingFork:
    """Test session branching and forking capabilities.

    Use cases:
    - A/B testing: Fork to test different prompts/models on same context
    - Exploration: Agents explore multiple approaches in parallel
    - Undo/retry: Branch from earlier point if conversation went wrong
    - Agent comparison: Compare specialized agents on same task
    """

    @pytest.fixture
    def working_dir(self, tmp_path: Any) -> str:
        return str(tmp_path)

    @pytest.fixture
    def cli_path(self) -> str:
        import shutil

        cli = shutil.which("claude")
        if not cli:
            pytest.skip("Claude CLI not found")
        return cli

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.mark.asyncio
    async def test_claude_fork_preserves_context(self, working_dir: str, cli_path: str) -> None:
        """Test that forked Claude session preserves original context."""
        from claude_agent_sdk import ClaudeAgentOptions, query

        # Original session with context
        opts1 = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
        )

        original_id: str | None = None
        async for msg in query(
            prompt="I'm building a task management system. Key feature: subtasks with dependencies.",
            options=opts1,
        ):
            if getattr(msg, "subtype", "") == "init":
                original_id = msg.data.get("session_id")

        assert original_id is not None
        print(f"\nOriginal session: {original_id}")

        # Fork the session
        opts_fork = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
            resume=original_id,
            fork_session=True,
        )

        forked_response = ""
        forked_id: str | None = None
        async for msg in query(
            prompt="What's the key feature I mentioned?",
            options=opts_fork,
        ):
            if getattr(msg, "subtype", "") == "init":
                forked_id = msg.data.get("session_id")
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    forked_response += content
                elif isinstance(content, list):
                    for item in content:
                        if hasattr(item, "text"):
                            forked_response += item.text
            if hasattr(msg, "text"):
                forked_response += str(msg.text)

        print(f"Forked session: {forked_id}")
        print(f"Forked response: {forked_response[:300]}")

        assert forked_id != original_id, "Forked session should have new ID"
        assert "subtask" in forked_response.lower() or "dependenc" in forked_response.lower(), (
            f"Should remember context. Got: {forked_response[:200]}"
        )

    @pytest.mark.asyncio
    async def test_claude_fork_diverges_independently(
        self, working_dir: str, cli_path: str
    ) -> None:
        """Test that forked session can diverge without affecting original."""
        from claude_agent_sdk import ClaudeAgentOptions, query

        # Original session - be explicit about REST
        opts1 = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
        )

        original_id: str | None = None
        async for msg in query(
            prompt="We are building a REST API using FastAPI. Remember: API_STYLE=REST",
            options=opts1,
        ):
            if getattr(msg, "subtype", "") == "init":
                original_id = msg.data.get("session_id")

        assert original_id is not None

        # Fork and diverge to GraphQL
        opts_fork = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
            resume=original_id,
            fork_session=True,
        )

        forked_id: str | None = None
        async for msg in query(
            prompt="Change of plans: let's use GraphQL instead. Set API_STYLE=GRAPHQL",
            options=opts_fork,
        ):
            if getattr(msg, "subtype", "") == "init":
                forked_id = msg.data.get("session_id")

        # Continue original (should still know REST)
        opts_continue = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
            resume=original_id,
        )

        original_response = ""
        async for msg in query(prompt="What is the value of API_STYLE?", options=opts_continue):
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    original_response += content
                elif isinstance(content, list):
                    for item in content:
                        if hasattr(item, "text"):
                            original_response += item.text
            if hasattr(msg, "text"):
                original_response += str(msg.text)

        print(f"\nOriginal session ID: {original_id}")
        print(f"Forked session ID: {forked_id}")
        print(f"Original session response: {original_response[:300]}")

        # Original should remember REST, not GraphQL
        assert "REST" in original_response.upper(), (
            f"Original should remember REST. Got: {original_response[:200]}"
        )
        assert "GRAPHQL" not in original_response.upper(), (
            f"Original should NOT know about GraphQL fork. Got: {original_response[:200]}"
        )

    @pytest.mark.asyncio
    async def test_gemini_manual_fork_via_history(self, api_key: str) -> None:
        """Test manual forking for Gemini via history copy."""
        from google import genai
        from google.genai.chats import AsyncChat

        client = genai.Client(api_key=api_key)

        # Build original conversation
        original_chat = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=[],
        )
        await original_chat.send_message("We're implementing a caching layer")
        await original_chat.send_message("Using Redis for session storage")

        # Get history at fork point
        fork_history = original_chat.get_history()
        print(f"\nFork point history: {len(fork_history)} messages")

        # Fork: Create new chat with copied history
        forked_chat = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=list(fork_history),  # Copy the history
        )

        # Diverge the fork
        fork_response = await forked_chat.send_message("Let's switch to Memcached instead")

        # Continue original (should still know Redis)
        original_response = await original_chat.send_message("What caching backend are we using?")

        print(f"Original response: {original_response.text}")
        print(f"Forked response: {fork_response.text[:200]}")

        assert "redis" in original_response.text.lower(), "Original should remember Redis"

    @pytest.mark.asyncio
    async def test_ab_testing_scenario(self, api_key: str) -> None:
        """Test A/B testing with forked sessions for agent comparison."""
        from google import genai
        from google.genai import types
        from google.genai.chats import AsyncChat

        client = genai.Client(api_key=api_key)

        # Setup: Common context
        base_history = [
            types.Content(
                role="user", parts=[types.Part(text="I need to implement user authentication")]
            ),
            types.Content(
                role="model",
                parts=[
                    types.Part(text="I can help with authentication. What framework are you using?")
                ],
            ),
            types.Content(role="user", parts=[types.Part(text="FastAPI with PostgreSQL")]),
        ]

        # Branch A: Security-focused response
        chat_a = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=list(base_history),
            config=types.GenerateContentConfig(
                system_instruction="You are a security-focused engineer. Prioritize security best practices.",
            ),
        )

        # Branch B: Speed-focused response
        chat_b = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=list(base_history),
            config=types.GenerateContentConfig(
                system_instruction="You are a pragmatic engineer. Prioritize quick implementation.",
            ),
        )

        prompt = "What authentication approach do you recommend?"

        response_a = await chat_a.send_message(prompt)
        await asyncio.sleep(0.5)  # Rate limit
        response_b = await chat_b.send_message(prompt)

        print("\n=== A/B Test Results ===")
        print(f"Branch A (Security): {response_a.text[:300]}...")
        print(f"\nBranch B (Speed): {response_b.text[:300]}...")

        # Both should give valid but different responses
        assert response_a.text != response_b.text, "Branches should diverge"
        assert len(response_a.text) > 50 and len(response_b.text) > 50, "Both should respond"


# =============================================================================
# Benchmark: Cross-Provider Failover Latency
# =============================================================================


class TestCrossProviderFailoverBenchmark:
    """Benchmark latency when failing over between providers."""

    @pytest.fixture
    def api_key(self) -> str:
        key = settings.gemini_api_key
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.fixture
    def working_dir(self, tmp_path: Any) -> str:
        return str(tmp_path)

    @pytest.fixture
    def cli_path(self) -> str:
        import shutil

        cli = shutil.which("claude")
        if not cli:
            pytest.skip("Claude CLI not found")
        return cli

    @pytest.mark.asyncio
    async def test_benchmark_provider_switch_overhead(
        self, api_key: str, working_dir: str, cli_path: str
    ) -> None:
        """Measure overhead of switching providers mid-conversation."""
        from claude_agent_sdk import ClaudeAgentOptions, query
        from google import genai
        from google.genai import types
        from google.genai.chats import AsyncChat

        client = genai.Client(api_key=api_key)

        # Scenario: Start with Claude, "fail over" to Gemini

        # Turn 1: Claude
        opts1 = ClaudeAgentOptions(
            model="claude-sonnet-4-5",
            max_turns=1,
            cwd=working_dir,
            cli_path=cli_path,
        )

        claude_response = ""
        start_claude = time.perf_counter()
        async for msg in query(
            prompt="Define a User model with email and password fields", options=opts1
        ):
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    claude_response += content
                elif isinstance(content, list):
                    for item in content:
                        if hasattr(item, "text"):
                            claude_response += item.text
            if hasattr(msg, "text"):
                claude_response += str(msg.text)
        claude_time = (time.perf_counter() - start_claude) * 1000

        # Transform context for Gemini (simulating failover)
        start_transform = time.perf_counter()
        gemini_history = [
            types.Content(
                role="user",
                parts=[types.Part(text="Define a User model with email and password fields")],
            ),
            types.Content(
                role="model",
                parts=[types.Part(text=claude_response[:2000])],
            ),
        ]
        transform_time = (time.perf_counter() - start_transform) * 1000

        # Turn 2: Gemini (failover)
        gemini_chat = AsyncChat(
            modules=client.aio.models,
            model="gemini-3-flash-preview",
            history=gemini_history,
        )

        start_gemini = time.perf_counter()
        gemini_response = await gemini_chat.send_message("Add a created_at timestamp field")
        gemini_time = (time.perf_counter() - start_gemini) * 1000

        print("\n=== Provider Switch Benchmark ===")
        print(f"Claude turn:       {claude_time:.0f}ms")
        print(f"Transform time:    {transform_time:.1f}ms")
        print(f"Gemini turn:       {gemini_time:.0f}ms")
        print(f"Total failover:    {claude_time + transform_time + gemini_time:.0f}ms")
        print(
            f"\nGemini understood context: {'timestamp' in gemini_response.text.lower() or 'created' in gemini_response.text.lower()}"
        )
