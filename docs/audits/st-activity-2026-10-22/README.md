# ST Activity: isolated review checkpoint

Task `task-41d2b7c4d1e542e4`, branch `review/st-activity-20261022`, based on Agent Hub `941a602b9`. No landing, deployment or publication. Independent review passed after one performance correction (below). The coordinator owns integration and live verification. Following the coordinator's scope clarification, this checkpoint finishes the Activity read side; separate ST background capture and subsequent trend/goal integration remain with the coordinator.

Activity now shows ST command count, elapsed time and input/output text estimates directly below its existing accounting cards. A native disclosure ranks safe command families by estimated text footprint, shows each family's class and coverage, and links to a source-backed session. It reuses the existing bounded hotspot API and retained session events. No ST invocation code, new ledger, raw-output query, database schema, runtime command output or prompt injection changes.

## Measured fields and estimates

- `commands`: recognizable ST command entries in sampled shell source, **not proof that conditional commands ran**. `calls_with_st` counts containing shell calls; these are different denominators. `shell_calls_unparsed`, `shared_commands`, unknown classes and the existing event cap remain explicit.
- `measured_seconds`: sum of reported nonnegative integer durations for isolated ST calls, including known zero. Concurrent calls add. This differs from the existing union of tool occupancy. Shared shell duration/output is never divided or assigned to an individual command.
- `input_tokens_estimate`: reference tokenizer count of normalized command argv using the existing `cl100k_base` reference encoding, bounded to 4,096 characters per command and 65,536 per snapshot. Beyond either budget, normalized characters / 4 rounded up supplies the estimate. `commands_with_tokenized_input` exposes exact method coverage globally and per family in the API/UI. Counts, elapsed time and output observations are preserved. Protocol/tool JSON framing and other shell text are excluded. Special-token-looking strings are ordinary text.
- `output_tokens_estimate`: ceiling of retained returned-character count / 4 for each isolated call. This uses ST tools cost's existing character approximation; output contents are not fetched or tokenized. Missing output has unknown size; known empty output is zero. This measures retained text only and cannot reconstruct truncated/unretained text.
- Family class and safe names live in `activity_policy.json`, shared by existing Activity classification and the new ST summary. Old admin/support families remain; tools/aico/agents/export/pulse are recognized as admin, vcs as support, search/web/browser/graphify as substantive, db/wiki/help as unknown. An unrecognized verb becomes `st.unknown`; arbitrary arguments never become display labels. Class does not establish necessity or waste.
- Existing exact wrapper suppression and `(session, call_id)` deduplication are reused. Ambiguous wrapper correlations can still duplicate evidence. Orphan results cannot establish an ST command. Session/project drill links come only from retained Hub session identities. Durable task-binding and provider-usage precedence rules are unchanged; no causal billed-token allocation was added.

The existing async query still returns output lengths rather than payloads and still caps event rows at 20,000. The snapshot calculation, including tokenizer initialization, now runs in a thread; it does not block the async event loop.

## Synthetic cross-boundary evidence

The backend-generated [API snapshot](../../../frontend/src/__tests__/fixtures/st-activity-snapshot.json) is reproduced by a backend regression and consumed by the frontend boundary/component test. It contains four ST command entries across three recognized calls, plus one unparsed shell call:

| Field | Result |
| --- | --- |
| Admin/support · substantive · unknown entries | 3 · 1 · 0 |
| Known elapsed time | 2 seconds across 2/4 entries, including one known 0 ms |
| Input estimate | 19 reference tokens: 6 context + 4 web + 4 check + 5 commit |
| Output estimate | 21 tokens: ceiling(81/4), plus known empty output |
| Output coverage | 2/4 entries |
| Shared shell | check + commit retain input estimates; their 10 seconds and 1,000 output characters remain unallocated |
| Provider usage | Unavailable; no provider tokens invented from the text estimate |

Sanitized calibration against the available reference tokenizer: English status, session-list, JSON and error output totalled 115 reference tokens versus 120 estimated (+4.3%). Individual English examples ranged from -9.5% to +40%. A short Chinese example was 14 reference tokens versus 3 estimated (-78.6%). This is a small calibration sample, not an accuracy guarantee; the UI explicitly qualifies language and formatting effects.

## Overhead

[Local synthetic microbenchmark after the correction](overhead.json): 1,000 calls / 2,000 events, five warm repetitions. The same snapshot function ran with and without only the new ST summary. Median CPU elapsed was 22.958 ms without and 39.586 ms with: +16.628 ms per Activity snapshot. Cold tokenizer initialization took 77.325 ms in the benchmark process. The summary added 1,801 compact JSON bytes with one family. This excludes database and HTTP latency; it is not a production API benchmark or a full-cap scale measurement.

ST's executable path is unchanged, so this read-side checkpoint adds zero per-command output bytes, agent context tokens or network calls by construction. The measured overhead is paid when Activity is requested. It does **not** measure the separately planned ST capture overhead.

## Checks and rendered review

Managed quick gates pass architecture, Ruff, Python types, Biome, TypeScript, **16 frontend tests** and gitleaks. The explicit combined backend gate passes **30 tests** across existing Activity accounting and ST regressions; the focused changed-only gate selects the **13 ST tests** after the first checkpoint. The commit runs the managed gate again. Regression coverage includes shared/conditional shell results, quote/operator handling, unsupported syntax, safe labels, wrapper/dedup/orphan handling, unknown classes, zero/missing measurements, fixture reconciliation, existing task links, older-server unavailable data, invalid API metrics, disclosure and source links. The tokenizer-bound regression records encoder inputs and checks both budgets without losing measurements. Existing loading/error/stale/retry tests remain passing. Checks report the expected isolated-worktree registry identity qualification.

The actual Activity component was rendered with the synthetic API sample to standalone HTML using the installed TSX loader and existing main-checkout built CSS. Managed isolated Chrome observed 1280×720 desktop and 390×844 phone layouts, without horizontal overflow. Clicking the disclosure and pressing Enter closed/reopened it; Tab reached the first session link with visible focus. Hrefs were inspected, not followed into a live session. Empty, unavailable and capped ST states were rendered and their text checked; fallback coverage was recaptured after the correction. [Desktop](desktop.png), [phone](mobile.png), and [rendered text/coverage](rendered.json) are retained. Initial captures: 2026-10-22 around 16:51–16:53 UTC; final captures after the correction around 17:08 UTC. Explicit dark theme, no Dark Reader in this browser session. Shared design guide revision 3 and existing product tokens were used; no Agent Hub copy profile exists, so copy follows owner voice.

These are standalone component observations, **not** authenticated live API, production PostgreSQL, full Next.js navigation, or post-deployment evidence. The coordinator retains live verification.

## Independent review

One fresh native verifier was requested as GPT-6.1 Sol xhigh; that route was accepted by the client. Delivered model/effort identity is not independently exposed. It inspected the diff, raw managed check receipts, cross-boundary fixture, rendered artifacts and overhead report.

The first review found one P2: full-argv tokenization took 4,068 ms for a synthetic 120,000-character message argument. Row caps do not bound bytes. The correction adds the configured per-command/snapshot budgets and honest character-fallback coverage described above. In the verifier's canonical `st check cleanroom` follow-up, the same case took 149.961 ms with its command retained and fallback exposed. A boundary probe retained 20 commands while encoding exactly 16 × 4,096 = 65,536 characters (maximum encoded command 4,096); total ST summary time was 100.468 ms. These are independently reported local synthetic timings, not production latency. Source parsing and existing argument fetches still scale with retained bytes; this is a tokenizer-work bound, not a total-request resource guarantee.

The second scoped review returned **PASS: P2 resolved, no remaining defect found**. It confirmed count/duration/known-zero/output semantics, regression and API/UI method coverage, and inspected the passing 13 ST / 16 frontend receipts. No third review round was requested. Probe stdout is retained in the native review tool results, not a separate repository artifact. Live integration and separate ST capture remain outside the verdict.

## Gaps for the ST capture integration

Retained shell events cannot prove each subcommand executed, split compound result/duration, see ST hidden in wrappers/scripts, or fill missing native/Pi/Claude durations. Output is a length-only approximation, and event caps/ingestion gaps can omit commands. There is no independent ST invocation identity, authoritative ST-wide count, background ST execution metadata transport, hourly time trend or owner-selected goal in this checkpoint. The coordinator created a separate ST capture task for those requirements. Reconcile that source against native shell events before combining totals; never add both blindly or infer project/task bindings from command args.

`st done` cannot close unlanded work from a linked checkout: its verified implementation requires the checkpoint to be an ancestor of the registered checkout. The task remains claimed for the coordinator to close after review and landing; this is not a request to deploy.

Tooling qualification: `st commit --task` refused this isolated checkout because claim renewal requires the registered project root. Explicit project/repository selection gave the same error. The supported local `st commit` checkpoint is therefore used without that flag; its hash is reported to the coordinator and task history separately. No ST tooling change or check bypass was made.
