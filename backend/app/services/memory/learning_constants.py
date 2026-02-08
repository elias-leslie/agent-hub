"""Constants for learning extraction."""

# Confidence thresholds per decision d2
PROVISIONAL_THRESHOLD = 70
CANONICAL_THRESHOLD = 90

EXTRACTION_PROMPT = """Analyze this Claude Code session transcript and extract learnings.

For each learning, determine:
1. **Type**:
   - VERIFIED (user explicitly confirmed something, 95% confidence)
   - INFERENCE (derived from successful task completion, 80% confidence)
   - PATTERN (observed behavior or practice, 60% confidence)

2. **Category**:
   - coding_standard (best practices, style guides)
   - troubleshooting_guide (gotchas, pitfalls, fixes)
   - system_design (architecture decisions)
   - operational_context (environment, deployment)
   - domain_knowledge (business logic, concepts)

3. **Confidence**: Base confidence for the type, adjust +/- 10% based on evidence strength

Output as JSON array:
```json
[
  {
    "content": "Clear, actionable statement of the learning",
    "learning_type": "verified|inference|pattern",
    "confidence": 60-100,
    "source_quote": "Brief quote from transcript supporting this",
    "category": "coding_standard|troubleshooting_guide|system_design|operational_context|domain_knowledge"
  }
]
```

Rules:
- Extract ONLY actionable learnings (not observations about the conversation itself)
- Focus on technical knowledge that would help in future sessions
- Skip trivial learnings (obvious statements, single-use fixes)
- Maximum 10 learnings per session
- Each learning should be self-contained and understandable without context

SESSION TRANSCRIPT:
{transcript}
"""
