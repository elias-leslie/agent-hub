"""One fixed Agent Hub native-loop subject, using its async public SDK."""

import asyncio
import json
import sys
import time
from pathlib import Path

from agent_hub import AsyncAgentHubClient
from st_sdk.config import get_agent_hub_url
from st_sdk.credentials import load_credentials


async def main(root):
    condition = json.loads((root / "condition.json").read_text())
    arm = "on" if condition["optional_context"] else "off"
    cid, source = load_credentials(default_source="harness-efficiency-trial")
    started = time.time()
    (root / "attempt.json").write_text(json.dumps({"started": started, "harness": "agent-hub", "arm": arm}))
    try:
        async with AsyncAgentHubClient(base_url=get_agent_hub_url(), client_id=cid, request_source=source, timeout=None, source_client="st-cli") as client:
            result = await client.complete(
                agent_slug=f"harness-trial-20261022-{arm}", project_id="agent-hub",
                model="codex/gpt-6.1-sol", messages=[{"role": "user", "content": condition["task"]}],
                # Omit request override: the public request enum cannot accept
                # xhigh, but the experiment agent's supported setting is xhigh.
                temperature=0.1, disable_agent_fallbacks=True,
                use_memory=True, execute_tools=True, working_dir=str(root),
                max_turns=16, skip_cache=True,
                parent_session_id="01a164c4-7bb4-7f01-b872-6e862d9d5fa9",
                source_metadata={"experiment": "harness-efficiency-20261022", "condition": root.name},
            )
            # No prompt, response body, thinking, or tool arguments in receipts.
            receipt = result.model_dump(exclude={"content", "progress_log", "tool_calls", "memory_uuids", "cited_uuids"})
    except Exception as exc:
        receipt = {"error_type": type(exc).__name__, "error": str(exc)}
    receipt.update(started=started, ended=time.time(), whole_seconds=time.time() - started)
    (root / "result.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
