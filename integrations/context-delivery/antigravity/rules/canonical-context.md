---
trigger: always_on
---

# Agent Hub context retrieval

At session startup, retrieve the canonical supplemental context for the current
working directory with:

```bash
~/.local/bin/agent-hub-context-client deliver --surface antigravity --capability bash --cwd "$PWD" --phase native_rule --emit text
```

Read the returned context before project work. After compaction, retrieve it again
if it was not retained. This rule is a retrieval adapter; shared policy remains
in Agent Hub. Preserve the native system prompt and safety instructions. If the
command fails, warn briefly and continue with native context. Describe successful
use as retrieved context, not automatic injection or observed provider delivery.
