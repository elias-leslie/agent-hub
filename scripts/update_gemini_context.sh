#!/bin/bash
# Sync Agent-Hub memory context to ~/.gemini/GEMINI.md
# This ensures context is available immediately without tool calls.

TARGET_FILE="$HOME/.gemini/GEMINI.md"
GRAPHITI_CLIENT="$HOME/.claude/hooks/graphiti-client.sh"

# Default query if none provided
QUERY="${1:-system initialization}"

echo "Fetching context for: '$QUERY'..."

# Fetch context using the existing client
CONTEXT=$($GRAPHITI_CLIENT "$QUERY" --project "summitflow")

if [ -z "$CONTEXT" ]; then
    echo "Error: No context received or agent-hub offline."
    exit 1
fi

# Write to GEMINI.md with a clear header
cat > "$TARGET_FILE" <<EOF
# System Context
> [!IMPORTANT]
> **Updated**: $(date)
> The following MANDATES and GUARDRAILS are active for this session.
> You must adhere to them strictly.

$CONTEXT

# User Notes
(Add your custom notes below)
EOF

echo "Successfully updated $TARGET_FILE"
echo "Context size: $(wc -c < "$TARGET_FILE") bytes"
