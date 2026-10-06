"""Owner-maintained release metadata for the public web-research executable.

Generated explicitly by ``web-research --describe-st``; ST consumes a reviewed
copy and never executes this code for ordinary discovery.
"""

from __future__ import annotations

import argparse


def describe_extension() -> dict[str, object]:
    from app.cli.web_research import _build_parser

    parser = _build_parser()
    parser.prog = "st web"
    help_by_path = {"": parser.format_help()}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                assert isinstance(child, argparse.ArgumentParser)
                child.prog = f"st web {name}"
                help_by_path[name] = child.format_help()
    return {
        "id": "agent-hub.web", "owner": "agent-hub", "namespace": "web",
        "version": "1.1.0", "st_contract_versions": [1],
        "summary": "Public web search, research, and fetch through Agent Hub.",
        "effects": ["network", "read-remote", "write-local", "credentials", "process"],
        "help": help_by_path,
        "usage": [{
            "surface": "st.web", "cmd": "st web research --query <query>",
            "when": "research public web sources; use search or fetch for a known page",
            "precautions": ["Uses Agent Hub's supported web-research executable and owner-managed credentials.",
                            "Default ST output writes a local details artifact; --raw emits the owner's JSON.",
                            "Use --backend direct for deterministic local benchmark verification.",
                            "Lightpanda is opt-in DOM retrieval with an exact local binary pin; use doctor before retrieval.",
                            "Use --selector and --wait-script to scope Lightpanda retrieval; readiness does not prove complete source coverage.",
                            "Inspect scoped innerText in readiness predicates; document.body.textContent can match scripts/styles before readable content is ready. Verify returned facts.",
                            "Fetch retains full extracted artifacts; refocus reads the owner cache without network and batch reuses one HTTP client."],
            "examples": ["st web search --query SummitFlow --limit 1", "st web benchmark --iterations 10 --raw",
                         "st web fetch https://example.com/article --backend lightpanda --selector article --wait-script 'document.querySelector(\"article\")?.innerText.includes(\"Conclusion\")'"],
            "task_types": ["web-research", "research"], "tier": "reference",
        }],
    }
