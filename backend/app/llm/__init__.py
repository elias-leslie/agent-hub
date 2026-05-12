"""Universal LLM adapter layer.

Direct Python port of pi-mono ``packages/ai/src/`` (SHA 3d9e14d7).
See ``backend/tasks/agent-framework-convergence/`` for the convergence contract.

The single optimization criterion is "closely follow the shape of pi-mono".
When in doubt, re-read the relevant section of ``pi-mono-catalog.md`` and
match it. Public surface is documented per pi-mono's ``index.ts``.
"""

from __future__ import annotations
