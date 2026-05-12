"""Memory layer (per convergence-map.md C4 + D9).

The adapter doesn't know what memory is. It takes a ``Context.system_prompt``
and ``Context.messages``. The memory layer assembles the prompt
(``app.memory.injection``) and post-processes the result for citations
(``app.memory.citation_extractor``).
"""

from __future__ import annotations
