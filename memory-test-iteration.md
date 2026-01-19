# Memory System Validation - Iterative Test Prompt

Use this prompt for repeated test/adjust cycles until all items reach ≥95 confidence and completeness.

---

## Iteration Prompt

Copy and paste this prompt to run a validation iteration:

```
# Memory System Validation Iteration

Continue validation of the Agent Hub memory system. Read the current state from `memory-test-state.json` and perform the following:

## Step 1: Run Validation Checks

### V1: Episode Effectiveness
```bash
# Test 5 representative queries
for query in "async patterns" "error handling best practices" "git commit workflow" "database architecture" "CLI commands"; do
  echo "=== Query: $query ==="
  curl -s "http://localhost:8003/api/memory/progressive-context?query=$query" | jq '{tokens: .total_tokens, mandates: .mandates.count, guardrails: .guardrails.count, reference: .reference.count}'
done
```

Compare results against archived rules in `~/.claude/rules.archive/`.

### V2: Token Efficiency
```bash
# Measure actual token injection
curl -s "http://localhost:8003/api/memory/progressive-context?query=project%20context%20patterns" | jq '.total_tokens'
```

Target: <500 tokens (baseline was ~35k)

### V3: Retrieval Coherence
```bash
# Test multi-row retrieval
curl -s "http://localhost:8003/api/memory/search?query=issue%20severity%20levels&limit=10" | jq '.results[].content'
```

All 3 severity definitions should be retrieved together.

## Step 2: Update Confidence/Completeness

For each finding in `memory-test-state.json`:
- **Confidence**: Your certainty about the finding (keep exploring until ≥95)
- **Completeness**: How fully the item is implemented/resolved (track progress)

## Step 3: Generate Progress Table

Output a table showing changes from previous iteration:

| ID | Item | Risk | Confidence | Δ | Completeness | Δ | Status |
|----|------|------|------------|---|--------------|---|--------|
| A1 | Bug: GOTCHA enum | CRITICAL | 100 | - | 0→? | +? | ? |
| A2 | Test coverage | HIGH | 98 | - | 30→? | +? | ? |
| ... | ... | ... | ... | ... | ... | ... | ... |

## Step 4: Update State File

Update `memory-test-state.json` with:
- New confidence/completeness scores
- Validation test results
- History entry with timestamp

## Step 5: Check Completion

If ALL findings have:
- Confidence ≥95
- Completeness ≥95
- Status = "resolved" or "acceptable"

Then: Output "VALIDATION COMPLETE" with final summary.

Otherwise: Output remaining gaps and suggested next actions.
```

---

## Quick Validation Commands

### Check Memory Stats
```bash
curl -s http://localhost:8003/api/memory/stats | jq '.'
```

### List Golden Standards
```bash
curl -s http://localhost:8003/api/memory/golden-standards | jq '.items | length'
```

### Test Progressive Context
```bash
curl -s "http://localhost:8003/api/memory/progressive-context?query=coding+patterns&debug=true" | jq '.'
```

### Count Episodes by Category
```bash
curl -s http://localhost:8003/api/memory/stats | jq '.by_category'
```

### Compare Token Counts
```bash
# Current injection
tokens=$(curl -s "http://localhost:8003/api/memory/progressive-context?query=test" | jq '.total_tokens')
echo "Current: $tokens tokens"

# Archived rules (approximate)
wc -c ~/.claude/rules.archive/*.md | tail -1 | awk '{print "Archived: " int($1/4) " tokens (estimated)"}'
```

---

## Exit Criteria

| Metric | Target | Current |
|--------|--------|---------|
| All findings confidence | ≥95 | Check state file |
| All findings completeness | ≥95 | Check state file |
| Token efficiency validated | <500 tokens | Run V2 |
| Retrieval coherence validated | All related items retrieved | Run V3 |
| Critical bugs fixed | 0 open | Check A1 status |

---

## State File Location

`/home/kasadis/agent-hub/memory-test-state.json`

Read with:
```bash
cat /home/kasadis/agent-hub/memory-test-state.json | jq '.'
```

Update the `history` array with each iteration for tracking.
