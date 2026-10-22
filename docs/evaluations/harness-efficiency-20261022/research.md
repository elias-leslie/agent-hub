# Session efficiency research — 22 October 2026

The owner wants agents to spend less effort managing work, detect regressions caused by tools/processes/context, and compare Codex, Claude Code, Pi, Agent Hub and custom harnesses. This research uses public primary evidence. Local matched trials are separate; the proposed goal below is not yet achieved.

## What the evidence measures

No reviewed source establishes a universal percentage of administrative waste. Initial context, repeated context, actual provider cost, tool duration, whole-session wall time and accepted outcomes are different measurements. Necessary testing/planning is not automatically waste.

HarnessTax (September16 publication, September18 update; site republished October14) tested seven models across three harnesses,30 tasks per benchmark and three attempts per task. The first-call SWE-bench Lite data covers630 attempts per harness:

| Harness/version | Mean tools declared | Instruction characters | Compact tool-schema characters | First-call input tokens, mean±SD |
| --- | ---: | ---: | ---: | ---: |
| Pi0.85.1 |4 |2,547 |2,873 |1,972±553 |
| Codex CLI0.146.0 |7.43 |23,502 |18,114 |11,308±2,683 |
| Claude Code2.1.224 |23 |13,465 |76,995 |27,011±6,934 |

Token totals include the task prompt. Character columns are not tokens. Claude Code's main-request selection differs from the first parseable request used for Codex/Pi. These are context sizes, not measured wasted tokens. Shared-model geometric mean Claude Code cost was about2.0×Pi and1.6×Codex on SWE-bench Lite;1.5×Pi on Terminal-Bench2.0. Average success differences were approximately±2 and±5 percentage points. Native high settings, small public samples and unpublished profiling traces limit transfer to our interactive sessions. [Primary data/definitions](https://raw.githubusercontent.com/HarnessTax/HarnessTax.github.io/main/data/charts/system-agent-context-swe.06f521bdb1.json), [methods/results](https://harnesstax.github.io/), [dated publication](https://arena.ai/blog/coding-agents-harness-tax).

## Other primary evidence

| Source | Measurement | Result and limit |
| --- | --- | --- |
| [Bai et al.,v3 October2,2026](https://arxiv.org/html/2604.22750v3),§5/Table1 | OpenHands/Sonnet4.5,500 SWE-bench Verified instances; share of rounds | Setup9.98%,Explore30.37%,Fix33.53%,Validate16.59%,Closeout9.53%. These phases are neither admin-waste labels nor token/time shares. |
| [AgentDiet,v2 March15,2026/FSE2026](https://arxiv.org/html/2509.23586),§5–6 | Trae Agent,Claude4Sonnet/Gemini2.5Pro,two coding benchmarks; full token-priced API cost | Input tokens reduced39.9–59.7%; net cost21.1–35.9% lower including reduction-model overhead; observed success differences−1 to+2pp. One harness; latency not quantified. |
| [CoACT,July3,2026](https://arxiv.org/html/2607.02911v1),§V | mini-SWE-agent,three models,SWE-bench Verified | Mean token reduction33.0%. Its AgentDiet comparison cut tokens43.7% while increasing API cost10.6% because cache behavior matters. |
| [Liu/Han,October3,2026](https://arxiv.org/html/2610.04433v1),AppendixG | GLM-5.3-Flash,45 identical tasks; Claude Code2.1.263/mini-SWE-agent2.4.6/OpenCode1.18.30 | First-call input17,134/1,382/7,579; estimated preamble16,581/829/7,025. Smaller custom loops may require more steps on another model. |
| [Databricks,July8,2026](https://www.databricks.com/blog/benchmarking-coding-agents-databricks-multi-million-line-codebase) | Internal recent PR tasks,same model/thinking | Native Claude Code/Codex sometimes cost>2×Pi; Pi supplied about3×less context per turn. Company-reported private tasks/configuration; incomplete reproducibility. |

Official implementation guidance supports the mechanisms, not a universal ranking: [Claude Code costs](https://code.claude.com/docs/en/costs) distinguishes cache/compaction/API duration and wall time and documents deferred MCP definitions; [Codex caching](https://developers.openai.com/cookbook/examples/prompt_caching_201) explains stable prefixes and compaction; [Pi compaction](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md) records retained context/summarization. [OpenAI's harness evaluation](https://developers.openai.com/cookbook/examples/partners/harness_aware_plugin_evals/harness_aware_plugin_evals) shows that changing loops can improve one model and worsen another. Visible text excludes some billed reasoning; use [provider accounting](https://developers.openai.com/api/docs/guides/reasoning).

## Proposed local goal and acceptance

For a frozen matched ordinary-coding evaluation, achieve **at least20% lower full API-equivalent cost per accepted outcome** than the current workflow, with the same required verification and no loss of observed accepted outcomes.20% is a proposed experiment target rounded down from AgentDiet's minimum demonstrated21.1% net saving. It is not an industry admin norm or a time target.

Cost per accepted outcome = cost of all attempted runs / accepted outcomes. Include failures,retries,parent/child calls,compaction,auxiliary model calls and optimization effort when reported. Pin one price schedule and count disjoint uncached input,cache read/write,output/reasoning correctly. Subscription API-equivalent cost is not cash billed.

Compare Pi,Codex and Agent Hub with/without optional injected Agent Hub context, preserving required instructions/tools/permissions and exact model/effort where supported. Retain observed identity/settings mismatches, all attempts, objective acceptance, time and usage. Repeat controls versus the best candidate to expose ordinary variation. No global route change follows from a tiny screen.

Measured administrative tool time must also decrease; unknown coverage remains explicit. Do not improve a ratio just by adding substantive tool time. Retained session admin share A/(A+S+U) describes measured tool duration; U/(A+S+U) is unknown duration. Overlapping tool calls are not whole-session wall time. Mixed-turn billed tokens remain unattributed; ST text footprint remains an estimate.

If complete comparable provider usage is missing, the20% cost goal cannot be marked achieved. A narrower observed fallback is a paired admin-tool-duration reduction exceeding control-run variation, unchanged accepted outcomes/checks and explicit scope. Its percentage must come from our sessions, not from unrelated token-saving papers.

Status: public research complete; local trials, independent verification and measured goal achievement remain open.
