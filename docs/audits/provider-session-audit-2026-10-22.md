# Provider session audit — 22 October 2026

Task: `task-41d1f4dc89a74bd0`. Scope includes provider fidelity, retry/block visibility and a coarse global activity trend. The earlier native Codex instruction/error repair is already deployed; its event IDs, roles and tool identities remain covered by the existing regression tests.

## Supported sources

| Source | Current contract and evidence |
| --- | --- |
| Native Codex | JSONL collector and registered managed App Server receipts. Native response usage is authoritative; turn/thread counters are snapshots, not extra calls. Encrypted content stays opaque. |
| Native Claude Code | Transcript adapter accepts `claude`, `anthropic`, `claude_code`; native hooks and transcript records coexist. Usage collector also reads child transcripts. |
| Hub text runtime | Five registered protocols: OpenAI completions, Google generative AI, Anthropic messages, Codex Responses, Claude Code CLI. Provider routing uses the catalog and one shared message/tool loop. |
| Images | Existing Gemini, NVIDIA, Cloudflare and historical MiniMax image adapters; success/failure and served model are session facts. The result contract does not supply normalized billed usage. |
| External cost ingest | Project/key idempotency, separate cash/subscription/local accounting, cache partitions and occurrence time. |
| Other historical labels | Pi context-delivery hooks are supported, but no full Pi transcript ingester exists. Historical OpenCode/cloudcode rows do not establish a current transcript collector. |

The live active catalog contained Claude (3 models), Cloudflare (16), Codex (8), Gemini (8), local (3), NVIDIA (6), xAI (3), and credential-only TypeSafe (1). Inactive rows include Kimi Code and MiniMax. No xAI or other provider request was made for this audit. Provider correctness was checked through source records, stored accounting and deterministic adapter/runtime tests, not a paid prompt campaign.

## Demonstrated defects and repairs

* Claude transcript events were skipped when native sequence positions collided with independently stored hooks. Session `a907a648-ca07-4e03-aaa1-db8b4fca36c3` had 61 native tool calls but only 50 distinct projected call IDs. A PostgreSQL regression reproduced two native events becoming one. Source IDs now deduplicate while Hub allocates sequence positions; refresh retains the server cursor and commits it with the events. Historical repair appends missing source-backed records while preserving existing IDs and hooks.
* Native lifecycle/settings/compaction facts were missing from ordinary transcript projections. The added metadata projection selects public fields only and excludes prompt/replacement-history payloads. Managed command ordering keeps its existing authority; its diagnostic query reads the already registered transcript rather than creating another projection.
* Claude usage kept early stream counters. Native message `msg_011CgBWV5dLin4vuZFopPmEJ` / request `req_011CgBWV5NUS1fymFj6AGccY` reports output 21 then 191; the ledger retained 21. Final counters now reconcile under the existing key, with exactly-once daily deltas.
* Codex compaction calls disappeared because their following legacy counter repeated an earlier cumulative total. A historical Agent-home transcript (`01a159fb-cd35-7281-9168-4b3ee4c96c0d`) had 442 native responses but 438 collected calls. Four omitted compactions accounted for input 1,257,042 (including cached 1,250,560) and output 28,176. The repaired parser produces exactly 442 calls and matches native input 75,770,874 and output 435,857. Ordinary call keys remain unchanged.
* Hub multi-call runs persisted only final-call usage. Sync and streaming now retain per-call accounting and aggregate response usage without changing context replay usage. Usage-bearing failed attempts persist before fallback, including exhausted chains.
* Metered runtime pricing omitted cache partitions. Gemini cost row 47266 stores input 3,282, output 782 and cache read 8,166, but cash 0.005394 follows the formula excluding cache. With the current catalog, the regression expects 0.00600645. Pricing now consumes disjoint input/read/write partitions. Historical metered cash is not repriced using today's rates.
* Three imported bare Codex model calls had null API-equivalent values because external ingestion used only Claude pricing. It now uses the existing subscription rate resolver; an identical retry fills only a missing equivalent value, preserving cash, identity and payload conflicts.
* Hub response-cache hits repeated the original provider token/cash accounting. The cache-delivery seam now preserves history and response counts while adding no provider cost row, budget charge or token quota usage. Repeated metered/subscription cache-hit regressions reproduce and lock down the fix.
* Live Claude refresh exposed mount-dependent fallback identities. There were 123 pairs with the same inode/position/record digest/block and identical stored payloads. Identity matching now ignores only the mount device number. Supported Claude repair collapses only proven identical aliases, preserving the oldest IDs and every unrelated hook; distinct native executions are not collapsed.
* The live global view exposed PostgreSQL `SUM(bigint)` values arriving as `Decimal`, which had been treated as zero. The view now preserves these exact integral sums; the regression uses the observed PostgreSQL return type.

Red-capable managed tests cover collisions, source-backed metadata, redaction/retry, native compaction/stream updates, replay deltas, runtime cumulative/cache usage, and failed fallbacks. The full acceptance and live reconciliation results are recorded below after integration.

## Operational queries and limits

`GET /api/session-ingestion/sessions/{session_id}/turn-diagnostics` returns native stop categories/timestamps/turn IDs, requested settings, adjacent completed or stopped turns, observed setting differences and event references. Its denominator is terminal native turns in the retrieved source/event window; truncation and source-health limitations are explicit. A native completion is not proof of a productive outcome. Facts are source-backed; private classifier causes remain unknown. One changed setting is an observed association, not a causal finding.

`GET /api/admin/session-hotspots?hours=24&limit=5` includes an additive global `activity_cost` section: coarse substantive/administration/unknown shares, observed tool occupancy, recorded token coverage, top administrative command families and task rollups from unambiguous existing bindings. Cache partitions count once. Concurrent sessions add agent-time; overlapping tool intervals within one session are unioned. Explicit wait-only tool intervals are separate; thinking/idle without instrumentation remain unknown. Repeated administration does not establish avoidability. Source alternatives are not added twice and mixed turns are not split into invented per-command token costs. Identical window size and measurement method support later comparisons.

Evidence limits retained by the audit:

* Historical metered rows lack price snapshots; lost per-call usage and provider exceptions without usage cannot be reconstructed honestly.
* Image result contracts supply no normalized billed usage. The 237 historical image sessions audited had no cost rows/events; this is missing coverage, not evidence of zero provider spend.
* Old native sources may be unavailable. Explicit usage replay uses the existing 40-day file-modification scan window and bounded whole-file passes; it does not claim all-history reconstruction.
* Some native models have no catalog rate and stay visibly unpriced. Observed requested model/settings are distinct from an unreported served model.
* Claude auxiliary journal records remain flagged where their shapes are not supported; opaque/encrypted material is not reconstructed or copied.

## Neri handoff: natural start/end review

Agent Hub owns session/error/model/usage facts. Neri owns findings, bounded negative results, duplicates, weak evidence, setup churn and the next-run choice. No additional outcome table, policy store, mandatory form or tagging was added here.

At run start, Neri can join its existing investigation/run/session references to recent diagnostic outcomes and the global/task hotspot window. Review successes as well as stops, the unknown share and the top administrative repeat; choose one concrete simplification. A separate reviewer may examine an existing stopped turn through these facts and permitted existing event references while the primary run continues distinct authorized work. A stop does not justify replaying blocked content through a different route.

At run end, keep the outcome and evidence pointers in the existing Neri investigation/run/task records and link the Hub session through existing bindings. Record the actual result, uncertainty and one suggested simplification. Compare later windows with the same denominator; do not infer productive hunting from provider completion or translate all tool time into thinking time.

## Verification

Executable checkpoint `01e8e6c53dd00ca79d2b9ae029283616a7eb638d` passed full managed acceptance: **4,489 backend tests passed (3 skipped), 258 frontend tests passed**, plus lint, types and local security gates. The managed rebuild succeeded, including backend/frontend health and active workers. Deployment receipt: `/home/kasadis/.summitflow/services/jobs/ac83f6d5d16344f6a78aae3510ebb1fa.deployment.json`.

Exact content-free results are retained in [.st/provider-audit-live-results.json](../../.st/provider-audit-live-results.json); the acceptance/deployment/live-check reference is [.st/provider-audit-final-evidence.json](../../.st/provider-audit-final-evidence.json). These are local evidence artifacts, also referenced by task closeout; no raw transcript copies or credential values were retained.

| Live check | Observed result |
| --- | --- |
| Claude source projection | All 184 original IDs preserved; final 209 events; native tool identities 50 → 61. Removed 123 proven duplicate mount aliases while preserving every surviving payload. Source transcripts remain intact, so the derived rows are recoverable. Repeated supported repair changes nothing. |
| Native accounting | Named replay finished with 6,111 source cursors marked and `replay_pending=0`. Historical Codex ledger exactly matches 442 native calls/input 75,770,874/output 435,857; Claude final output is 191. Repeated pass consumes only new live tails. Replay performs no retention pruning or owner alerts. |
| Stop comparison | Native session `01a160a3-c588-72e0-9268-237877f74767`: 6 completed turns and 1 `cyber_policy` stop among 7 terminal turns; native stop time `2026-10-21T23:08:09.571Z`. The neighboring completed turn has the same recorded model/settings. This sample establishes no classifier cause. |
| External subscription | Original cost rows 47769/47780/47787 retained; missing equivalent values filled through identical ingest retries; cash remains $0. |
| Global 1-hour view | HTTP 200 in 0.458s; 20 sessions, 117,426,407 recorded tokens, 4 sessions missing usage and 20 unlinked. Of 1,261.574 measured tool seconds, 689.181 (55%) are admin/support and 572.393 (45%) unknown/mixed. Token activity is 100% unknown in this sample; this is not evidence of zero substantive work. |
| Global 24-hour view | HTTP 200 in 0.884s; 187 sessions, 954,307,961 recorded tokens, 30 missing usage and 187 unlinked. Event sampling is capped, so its 47% admin/support tool share is a sampled trend, not a complete-day activity allocation. |

A subsequent uncapped one-hour coverage check found 112 response-bearing native turn groups: 54 mixed and 58 unknown, with none wholly classifiable as substantive or administration. In its moving 24-hour window, all 189 sampled sessions lacked a reliable task link; only three task bindings exist in the full retained database. Cost rows also lack a stable native response or turn key. The next small producer-side improvement is to pass an explicit task identity through the existing work-context and session-binding path when one is known. Historical links and token splits must remain unknown unless source records establish them. The local [coverage assessment](../../.st/provider-audit-attribution-coverage-assessment.json) records the counts and join limits.

The largest observed administrative families were checks, service operations, commits and session management. Avoidability remains unknown; the concrete simplification for the next run is to batch repeated session/status queries and reuse same-source check receipts where the existing workflow permits. Keep required checks and verification. Compare the next equivalent bounded window before claiming improvement.

The standard `st service observe` route rejected this project because no trusted native observation extension is configured. The successful managed deployment receipt and explicit source-bound live probes above provide the actual runtime evidence; no replacement observation system was built.
