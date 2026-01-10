#!/usr/bin/env python3
"""
OAuth False Positive Isolation Test

Systematically tests each variable to identify what triggers the
"Usage Policy" false positive when using Claude OAuth via SDK.

Hypotheses to test:
1. Session accumulation - error responses polluting context
2. Tool names / allowed_tools - OAuth validates against allowlist
3. Model version string - newer models have stricter filters
4. System prompt content - certain keywords trigger detection
5. User prompt content - task description triggers safety
6. Permission mode - "bypassPermissions" triggers detection
7. API style - ClaudeSDKClient vs query() function
8. Working directory - cwd setting affects behavior

Usage:
    python scripts/test_oauth_isolation.py
    python scripts/test_oauth_isolation.py --test model_version
    python scripts/test_oauth_isolation.py --test all --verbose
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import SDK components
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, query
from claude_agent_sdk.types import AssistantMessage, TextBlock


@dataclass
class TestResult:
    """Result of a single test."""

    name: str
    passed: bool
    response_length: int
    duration_ms: int
    error: str | None = None
    content_preview: str = ""


# =============================================================================
# Test Configuration
# =============================================================================

# SummitFlow's EXACT system prompt (from agent_hub.py:285-315)
SUMMITFLOW_SYSTEM_PROMPT = """You are a coding worker. Execute the subtask and return results.

CRITICAL: Your response MUST end with a JSON evidence contract in this EXACT format:

```json
{
  "status": "completed",
  "files": [
    {"path": "relative/path/to/file.py", "content": "full file content here"}
  ],
  "commands": [
    {"cmd": "npm install", "description": "install dependencies"}
  ],
  "verifications": [
    {"check": "file exists", "passed": true, "details": "verified"}
  ]
}
```

Status values: "completed", "blocked", "deferred", "failed"
- blocked: include "blocked_by": "task-id"
- deferred: include "deferred_reason": "reason (10+ chars)"
- failed: include "error": "what went wrong"

RULES:
1. Output valid JSON inside ```json code fence
2. Include ALL file contents in "files" array (full content, not diffs)
3. List commands to run in "commands" array
4. Minimal changes only - do not over-engineer"""

# SummitFlow's EXACT user prompt template (from agent_hub.py:317-358)
SUMMITFLOW_USER_PROMPT = """# Task: Implement feature X

Project: monkey-fight
Subtask ID: 1.1

## Steps to complete:
  1. Create the file
  2. Add the function
  3. Test it

## Objective: Add a simple helper function

## Done when:
- File created
- Function works

## Repository path:
/home/kasadis/summitflow/monkey-fight

Implement the required changes and return your evidence contract."""

# Simple prompt that should always work
SIMPLE_PROMPT = "Write a Python function that adds two numbers and returns the result."

# Auto-Claude's minimal system prompt (from followup_reviewer.py:703)
AUTO_CLAUDE_SYSTEM_PROMPT = (
    "You are a code review assistant. Analyze the provided context and provide structured feedback."
)

# Model versions to test
MODELS = {
    "shorthand": "sonnet",
    "full_45": "claude-sonnet-4-5",
    "dated_45": "claude-sonnet-4-5-20250514",
    "dated_old": "claude-sonnet-4-20250514",  # Error message suggests this
}


# =============================================================================
# Test Functions
# =============================================================================


def is_policy_error(content: str) -> bool:
    """Check if response contains the Usage Policy error."""
    return "Usage Policy" in content or "violate" in content.lower()


async def test_auto_claude_pattern() -> TestResult:
    """
    Baseline: Auto-Claude's EXACT working pattern.
    Uses query() directly with minimal options.
    """
    name = "auto_claude_pattern"
    start = time.time()

    try:
        # Ensure OAuth token is set (Auto-Claude's pattern)
        # Token should already be available to claude CLI

        content_parts = []
        async for message in query(
            prompt=SIMPLE_PROMPT,
            options=ClaudeAgentOptions(
                model="claude-sonnet-4-5-20250929",  # Auto-Claude uses dated version
                system_prompt=AUTO_CLAUDE_SYSTEM_PROMPT,
                allowed_tools=[],  # KEY: No tools
                max_turns=2,  # KEY: Short session
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_parts.append(block.text)

        content = "".join(content_parts)
        duration_ms = int((time.time() - start) * 1000)

        if is_policy_error(content):
            return TestResult(
                name=name,
                passed=False,
                response_length=len(content),
                duration_ms=duration_ms,
                error="Usage Policy error in response",
                content_preview=content[:200],
            )

        return TestResult(
            name=name,
            passed=True,
            response_length=len(content),
            duration_ms=duration_ms,
            content_preview=content[:200],
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            response_length=0,
            duration_ms=int((time.time() - start) * 1000),
            error=str(e),
        )


async def test_agent_hub_pattern() -> TestResult:
    """
    Agent-Hub's current pattern.
    Uses ClaudeSDKClient with context manager.
    """
    name = "agent_hub_pattern"
    start = time.time()

    try:
        options = ClaudeAgentOptions(
            cwd=".",
            permission_mode="bypassPermissions",
            model="sonnet",  # Agent-hub uses shorthand
        )

        content_parts = []
        client = ClaudeSDKClient(options=options)
        async with client:
            await client.query(SIMPLE_PROMPT)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            content_parts.append(block.text)

        content = "".join(content_parts)
        duration_ms = int((time.time() - start) * 1000)

        if is_policy_error(content):
            return TestResult(
                name=name,
                passed=False,
                response_length=len(content),
                duration_ms=duration_ms,
                error="Usage Policy error in response",
                content_preview=content[:200],
            )

        return TestResult(
            name=name,
            passed=True,
            response_length=len(content),
            duration_ms=duration_ms,
            content_preview=content[:200],
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            response_length=0,
            duration_ms=int((time.time() - start) * 1000),
            error=str(e),
        )


async def test_model_version(model_key: str) -> TestResult:
    """Test different model version strings."""
    name = f"model_{model_key}"
    model = MODELS[model_key]
    start = time.time()

    try:
        content_parts = []
        async for message in query(
            prompt=SIMPLE_PROMPT,
            options=ClaudeAgentOptions(
                model=model,
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_parts.append(block.text)

        content = "".join(content_parts)
        duration_ms = int((time.time() - start) * 1000)

        if is_policy_error(content):
            return TestResult(
                name=name,
                passed=False,
                response_length=len(content),
                duration_ms=duration_ms,
                error=f"Usage Policy error with model={model}",
                content_preview=content[:200],
            )

        return TestResult(
            name=name,
            passed=True,
            response_length=len(content),
            duration_ms=duration_ms,
            content_preview=content[:100],
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            response_length=0,
            duration_ms=int((time.time() - start) * 1000),
            error=str(e),
        )


async def test_system_prompt(prompt_type: str) -> TestResult:
    """Test different system prompts."""
    name = f"system_{prompt_type}"
    start = time.time()

    prompts = {
        "none": None,
        "minimal": "You are a helpful assistant.",
        "auto_claude": AUTO_CLAUDE_SYSTEM_PROMPT,
        "summitflow": SUMMITFLOW_SYSTEM_PROMPT,
    }
    system = prompts.get(prompt_type)

    try:
        content_parts = []
        async for message in query(
            prompt=SIMPLE_PROMPT,
            options=ClaudeAgentOptions(
                model="sonnet",
                system_prompt=system,
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_parts.append(block.text)

        content = "".join(content_parts)
        duration_ms = int((time.time() - start) * 1000)

        if is_policy_error(content):
            return TestResult(
                name=name,
                passed=False,
                response_length=len(content),
                duration_ms=duration_ms,
                error=f"Usage Policy error with system={prompt_type}",
                content_preview=content[:200],
            )

        return TestResult(
            name=name,
            passed=True,
            response_length=len(content),
            duration_ms=duration_ms,
            content_preview=content[:100],
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            response_length=0,
            duration_ms=int((time.time() - start) * 1000),
            error=str(e),
        )


async def test_user_prompt(prompt_type: str) -> TestResult:
    """Test different user prompts."""
    name = f"user_{prompt_type}"
    start = time.time()

    prompts = {
        "simple": SIMPLE_PROMPT,
        "coding": "Write a function to calculate factorial in Python.",
        "task_like": "# Task: Implement feature\n\nProject: test-project\n\nCreate a hello world function.",
        "summitflow": SUMMITFLOW_USER_PROMPT,
    }
    user_prompt = prompts.get(prompt_type, SIMPLE_PROMPT)

    try:
        content_parts = []
        async for message in query(
            prompt=user_prompt,
            options=ClaudeAgentOptions(
                model="sonnet",
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_parts.append(block.text)

        content = "".join(content_parts)
        duration_ms = int((time.time() - start) * 1000)

        if is_policy_error(content):
            return TestResult(
                name=name,
                passed=False,
                response_length=len(content),
                duration_ms=duration_ms,
                error=f"Usage Policy error with user={prompt_type}",
                content_preview=content[:200],
            )

        return TestResult(
            name=name,
            passed=True,
            response_length=len(content),
            duration_ms=duration_ms,
            content_preview=content[:100],
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            response_length=0,
            duration_ms=int((time.time() - start) * 1000),
            error=str(e),
        )


async def test_permission_mode(mode: str) -> TestResult:
    """Test different permission modes."""
    name = f"permission_{mode}"
    start = time.time()

    try:
        options = ClaudeAgentOptions(
            model="sonnet",
            permission_mode=mode,
            allowed_tools=[],
            max_turns=2,
        )

        content_parts = []
        async for message in query(
            prompt=SIMPLE_PROMPT,
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        content_parts.append(block.text)

        content = "".join(content_parts)
        duration_ms = int((time.time() - start) * 1000)

        if is_policy_error(content):
            return TestResult(
                name=name,
                passed=False,
                response_length=len(content),
                duration_ms=duration_ms,
                error=f"Usage Policy error with permission_mode={mode}",
                content_preview=content[:200],
            )

        return TestResult(
            name=name,
            passed=True,
            response_length=len(content),
            duration_ms=duration_ms,
            content_preview=content[:100],
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            response_length=0,
            duration_ms=int((time.time() - start) * 1000),
            error=str(e),
        )


async def test_api_style(style: str) -> TestResult:
    """Test query() vs ClaudeSDKClient."""
    name = f"api_{style}"
    start = time.time()

    try:
        content_parts = []

        if style == "query":
            async for message in query(
                prompt=SIMPLE_PROMPT,
                options=ClaudeAgentOptions(
                    model="sonnet",
                    allowed_tools=[],
                    max_turns=2,
                ),
            ):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            content_parts.append(block.text)
        else:  # client
            options = ClaudeAgentOptions(
                model="sonnet",
                allowed_tools=[],
                max_turns=2,
            )
            client = ClaudeSDKClient(options=options)
            async with client:
                await client.query(SIMPLE_PROMPT)
                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                content_parts.append(block.text)

        content = "".join(content_parts)
        duration_ms = int((time.time() - start) * 1000)

        if is_policy_error(content):
            return TestResult(
                name=name,
                passed=False,
                response_length=len(content),
                duration_ms=duration_ms,
                error=f"Usage Policy error with api={style}",
                content_preview=content[:200],
            )

        return TestResult(
            name=name,
            passed=True,
            response_length=len(content),
            duration_ms=duration_ms,
            content_preview=content[:100],
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            response_length=0,
            duration_ms=int((time.time() - start) * 1000),
            error=str(e),
        )


async def test_full_summitflow_simulation() -> TestResult:
    """
    Full simulation of what SummitFlow autocode does.
    This should reproduce the error if our analysis is correct.
    """
    name = "summitflow_full"
    start = time.time()

    try:
        # Build prompt exactly like agent_hub.py does
        system_prompt = SUMMITFLOW_SYSTEM_PROMPT
        user_prompt = SUMMITFLOW_USER_PROMPT
        full_prompt = f"{system_prompt}\n\nUser: {user_prompt}"

        options = ClaudeAgentOptions(
            cwd=".",
            permission_mode="bypassPermissions",
            model="sonnet",  # Same as DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5"
        )

        content_parts = []
        client = ClaudeSDKClient(options=options)
        async with client:
            await client.query(full_prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            content_parts.append(block.text)

        content = "".join(content_parts)
        duration_ms = int((time.time() - start) * 1000)

        if is_policy_error(content):
            return TestResult(
                name=name,
                passed=False,
                response_length=len(content),
                duration_ms=duration_ms,
                error="Usage Policy error - REPRODUCED!",
                content_preview=content[:200],
            )

        return TestResult(
            name=name,
            passed=True,
            response_length=len(content),
            duration_ms=duration_ms,
            content_preview=content[:100],
        )

    except Exception as e:
        return TestResult(
            name=name,
            passed=False,
            response_length=0,
            duration_ms=int((time.time() - start) * 1000),
            error=str(e),
        )


# =============================================================================
# Main Test Runner
# =============================================================================


async def run_all_tests(verbose: bool = False) -> dict[str, TestResult]:
    """Run all hypothesis tests."""
    results: dict[str, TestResult] = {}

    print("=" * 60)
    print("OAuth False Positive Isolation Test")
    print("=" * 60)
    print()

    # 1. Baseline: Auto-Claude pattern (should work)
    print("1. Testing Auto-Claude pattern (baseline)...")
    results["auto_claude"] = await test_auto_claude_pattern()
    print(
        f"   {'PASS' if results['auto_claude'].passed else 'FAIL'}: {results['auto_claude'].duration_ms}ms"
    )
    if not results["auto_claude"].passed:
        print(f"   ERROR: {results['auto_claude'].error}")
    print()

    # 2. Agent-Hub pattern
    print("2. Testing Agent-Hub pattern...")
    results["agent_hub"] = await test_agent_hub_pattern()
    print(
        f"   {'PASS' if results['agent_hub'].passed else 'FAIL'}: {results['agent_hub'].duration_ms}ms"
    )
    if not results["agent_hub"].passed:
        print(f"   ERROR: {results['agent_hub'].error}")
    print()

    # 3. Model versions
    print("3. Testing model versions...")
    for key in MODELS:
        results[f"model_{key}"] = await test_model_version(key)
        status = "PASS" if results[f"model_{key}"].passed else "FAIL"
        print(f"   {status}: {key} ({MODELS[key]})")
    print()

    # 4. System prompts
    print("4. Testing system prompts...")
    for pt in ["none", "minimal", "auto_claude", "summitflow"]:
        results[f"system_{pt}"] = await test_system_prompt(pt)
        status = "PASS" if results[f"system_{pt}"].passed else "FAIL"
        print(f"   {status}: {pt}")
    print()

    # 5. User prompts
    print("5. Testing user prompts...")
    for pt in ["simple", "coding", "task_like", "summitflow"]:
        results[f"user_{pt}"] = await test_user_prompt(pt)
        status = "PASS" if results[f"user_{pt}"].passed else "FAIL"
        print(f"   {status}: {pt}")
    print()

    # 6. Permission modes
    print("6. Testing permission modes...")
    for mode in ["default", "acceptEdits", "bypassPermissions"]:
        results[f"permission_{mode}"] = await test_permission_mode(mode)
        status = "PASS" if results[f"permission_{mode}"].passed else "FAIL"
        print(f"   {status}: {mode}")
    print()

    # 7. API styles
    print("7. Testing API styles...")
    for style in ["query", "client"]:
        results[f"api_{style}"] = await test_api_style(style)
        status = "PASS" if results[f"api_{style}"].passed else "FAIL"
        print(f"   {status}: {style}")
    print()

    # 8. Full SummitFlow simulation
    print("8. Testing full SummitFlow simulation...")
    results["summitflow_full"] = await test_full_summitflow_simulation()
    status = "PASS" if results["summitflow_full"].passed else "FAIL"
    print(f"   {status}: summitflow_full")
    if not results["summitflow_full"].passed:
        print(f"   ERROR: {results['summitflow_full'].error}")
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    failures = [k for k, v in results.items() if not v.passed]
    passes = [k for k, v in results.items() if v.passed]

    print(f"Passed: {len(passes)}/{len(results)}")
    print(f"Failed: {len(failures)}/{len(results)}")

    if failures:
        print("\nFailed tests:")
        for name in failures:
            r = results[name]
            print(f"  - {name}: {r.error}")
            if verbose and r.content_preview:
                print(f"    Preview: {r.content_preview[:100]}...")

    # Identify the culprit
    print("\n" + "=" * 60)
    print("ANALYSIS")
    print("=" * 60)

    if not failures:
        print("All tests passed! The issue might be:")
        print("  - Session accumulation (error history)")
        print("  - Rate limiting from previous failures")
        print("  - External state not captured in tests")
    else:
        # Find pattern in failures
        print("Failure pattern analysis:")

        # Check if it's model-related
        model_fails = [f for f in failures if f.startswith("model_")]
        if model_fails:
            print(f"  - Model-related failures: {model_fails}")

        # Check if it's system prompt related
        system_fails = [f for f in failures if f.startswith("system_")]
        if system_fails:
            print(f"  - System prompt failures: {system_fails}")

        # Check if it's user prompt related
        user_fails = [f for f in failures if f.startswith("user_")]
        if user_fails:
            print(f"  - User prompt failures: {user_fails}")

        # Check if it's permission-related
        perm_fails = [f for f in failures if f.startswith("permission_")]
        if perm_fails:
            print(f"  - Permission mode failures: {perm_fails}")

        # Check API style
        api_fails = [f for f in failures if f.startswith("api_")]
        if api_fails:
            print(f"  - API style failures: {api_fails}")

    return results


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="OAuth False Positive Isolation Test")
    parser.add_argument("--test", default="all", help="Specific test to run")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    results = await run_all_tests(verbose=args.verbose)

    # Exit with failure code if any tests failed
    failures = [k for k, v in results.items() if not v.passed]
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
