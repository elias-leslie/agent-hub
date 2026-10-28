# Claude coding step shape (27 October 2026)

Question: how should a Claude workflow step get its tools? Every arm runs the unmodified `claude` CLI on the subscription (Opus 5.5, effort high) through the shipped `claude_code` executor, on the frozen 16-check fixture from [harness-efficiency-20261022](../harness-efficiency-20261022/). Only the launch flags differ. `run.py` reuses the fixture, grading and usage code from [multi-model-workflow-20261027](../multi-model-workflow-20261027/run.py).

| Arm | Shape | Tools offered |
|---|---|---|
| A | As shipped: Claude Code's prompt, full built-in set | 25 |
| B | Lean flags: no slash commands/skills, no MCP, per-machine prompt sections moved out | Read, Edit, Write, Bash, Glob, Grep |
| E | B with Pi's four tools | Read, Edit, Write, Bash |
| C | Pi shape: a ~0.6K-char Pi-style system prompt replaces Claude Code's | Read, Edit, Write, Bash |
| D | Built-in tools off; Agent Hub's own tools over a local MCP server (`ah_mcp_server.py`) | bash, read_file, edit_file, write_file |

## Results

| run | passed | cache read | cache write | output | cost USD (catalog) | CLI cost USD | first-request prompt | wall s | tool calls |
|---|---|---|---|---|---|---|---|---|---|
| A (run 1 of the workflow eval) | 16/16 | 71,482 | 11,160 | 1,626 | 0.103 | — | — | 16.9 | 3 |
| A (run 1 repeat) | 16/16 | 71,442 | 11,114 | 1,671 | 0.103 | 0.137 | — | 16.0 | 3 |
| A | 16/16 | 71,364 | 10,973 | 1,465 | 0.099 | — | — | 16.1 | 3 |
| B | 16/16 | 31,765 | 5,517 | 1,587 | 0.066 | — | — | 21.3 | 3 |
| B-r2 | 16/16 | 22,883 | 4,757 | 1,405 | 0.057 | 0.071 | 7.9K | 19.5 | 2 |
| E | 16/16 | 14,101 | 8,967 | 1,491 | 0.078 | 0.104 (cold cache) | 6.4K | 17.4 | 2 |
| C | 16/16 | 16,291 | 7,191 | 1,568 | 0.071 | — | — | 18.6 | 3 |
| C-r2 | 16/16 | 19,231 | 4,130 | 1,379 | 0.052 | 0.064 | 4.5K | 15.6 | 3 |
| D | 7/16 (invalid: bridge crashed, no tools) | 649 | 2,652 | 4,908 | 0.112 | — | — | 41.7 | 0 |
| D-r3 | 16/16 | 16,854 | 7,129 | 1,343 | 0.066 | 0.087 | 4.7K | 19.1 | 3 |
| D-r4 | 16/16 | 18,839 | 5,198 | 1,388 | 0.058 | 0.073 | 4.7K | 28.6 | 3 |

"First-request prompt" is cache read + cache write on the step's first model request: the fixed price every later turn pays again. "CLI cost" is Claude Code's own `total_cost_usd`, which prices 1-hour cache writes above the catalog; it tracks subscription limit use better. Rows without it predate the raw-event capture. Input tokens were 2–8 on every arm.

## What it settles

- **The tool list is the lever.** Cutting 25 built-in tools to 4 takes the fixed prompt from about 17K to 6.4K tokens (E) and roughly halves the CLI cost (0.137 → 0.064–0.071 warm). Glob and Grep cost about 1.5K (B vs E); Bash covers `rg`/`find`, as Pi does.
- **Replacing Claude Code's prompt saves another ~1.9K per request (C).** That is small next to the tool cut, and it swaps out the prompt Anthropic tunes Claude Code against. Quality on hard tasks is unmeasured, so it's not adopted. C also put the worktree path into the system prompt, which breaks cross-run cache reuse; B-r2 started with 5.7K already cached because its flags are byte-stable.
- **Agent Hub's tools over MCP (D) cost the same as C once working, but fail badly.** When the bridge failed to start (the handler needed the project-root cache), Claude Code reported nothing: one run went on without tools and scored 7/16, the next hung for 10+ minutes. It also adds a Python process and DB access per step. Not adopted; `st` already reaches Claude through Bash, at no prompt cost until used.
- **Quality:** every working arm passed 16/16 with 2–3 tool calls. The fixture can't separate them on quality.

## Adopted

`executor_defaults.json` `claude_code.levels`: steps run **lean** by default (E: `--tools Read,Edit,Write,Bash --disable-slash-commands --strict-mcp-config --exclude-dynamic-system-prompt-sections`), and a step can set `"level": "full"` for Claude Code's whole set (subagents, web tools), as the research step in `docs/examples/workflows/research-report-factcheck.json` does.

Raw stream events for B-r2, C-r2, D-r3, D-r4 and E are in the gitignored `runs/` folder.
