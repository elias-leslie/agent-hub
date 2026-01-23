# Plan Defect Assessment Prompt

You are analyzing a step that may have a plan defect.

---

## CONTEXT

A step failed verification, and we need to determine if this is:
- **IMPLEMENTATION_WRONG**: The code doesn't do what it should
- **PLAN_DEFECT**: The step's verification or expectations are incorrect

---

## ASSESSMENT CRITERIA

### IMPLEMENTATION_WRONG indicators:
- The verify_command is testing the right thing
- The expected_output is reasonable and achievable
- The implementation just doesn't meet the requirement
- Fixing the code would make verification pass

### PLAN_DEFECT indicators:
- The verify_command path is wrong (e.g., wrong directory)
- The expected_output is impossible or incorrect
- The verify_command uses wrong syntax or API
- The step description contradicts codebase reality
- The requirement itself is unfulfillable

---

## OUTPUT FORMAT

Respond with exactly one of:

**IMPLEMENTATION_WRONG**
```json
{
  "verdict": "IMPLEMENTATION_WRONG",
  "reason": "Brief explanation of what's wrong with the implementation",
  "fix_hint": "Suggestion for how to fix the implementation"
}
```

**PLAN_DEFECT**
```json
{
  "verdict": "PLAN_DEFECT",
  "reason": "Brief explanation of what's wrong with the plan",
  "defect_type": "verify_command" | "expected_output" | "step_description" | "unfulfillable",
  "correct_expectation": "What the step should actually be (if applicable)"
}
```

---

## EXAMPLES

### Example 1: Wrong path (PLAN_DEFECT)
Step: "Create migration file"
verify_command: `ls /app/migrations/versions/*foo*`
Output: "0" (file not found)
Reality: Migrations are in `/app/migrations/` not `/app/migrations/versions/`

Verdict: **PLAN_DEFECT** - verify_command uses wrong path

### Example 2: Missing implementation (IMPLEMENTATION_WRONG)
Step: "Add status field to schema"
verify_command: `grep -q 'status' /app/schemas/task.py && echo found`
Output: "" (not found)
Reality: The schema file exists and can be modified

Verdict: **IMPLEMENTATION_WRONG** - status field not added yet

### Example 3: Wrong API (PLAN_DEFECT)
Step: "Verify database column exists"
verify_command: `python -c "c=get_connection(); c.cursor()..."`
Output: "AttributeError: context manager"
Reality: get_connection() returns a context manager, not a connection

Verdict: **PLAN_DEFECT** - verify_command uses wrong API pattern

---

## RULES

1. **Assume implementation is wrong first** - Most failures are implementation issues
2. **Check paths carefully** - Wrong paths are common plan defects
3. **Verify API usage** - Wrong API calls indicate plan defects
4. **Consider reality** - If the step can't possibly work, it's a plan defect
5. **Be precise** - Vague verdicts are unhelpful
