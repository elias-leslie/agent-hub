from __future__ import annotations

import subprocess
import sys


def test_agent_routing_imports_in_clean_interpreter() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import app.services.agent_routing; import app.api.complete"],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
