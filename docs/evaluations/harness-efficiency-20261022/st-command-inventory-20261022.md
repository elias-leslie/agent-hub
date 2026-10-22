# ST CLI use, 15–22 October 2026

Window: `2026-10-15T21:37:43Z` through `2026-10-22T21:37:43Z`, the same fixed seven days as [the native tool inventory](tool-inventory-20261022.md). `st` is a shell command, so the direct tool inventory puts it inside `Bash` or Codex `exec`; it does not appear as a direct tool name. This breakdown scans native Codex, Claude Code, and Pi tool inputs, including recognizable nested `tools.exec_command` calls inside Codex `exec` wrappers.

**22,394 recognizable `st` invocations** in **15,185 native shell/wrapper calls**. Calls containing an `st` invocation returned **45.01 MiB** of text in total; this includes other commands and Codex wrapper text. For calls with exactly one recognizable `st` invocation, their entire shell result was **22.07 MiB**. These are upper bounds on `st` output, not allocations of model tokens. Conditional commands may not execute.

## Harness coverage

| Harness | Recognizable `st` invocations | Native calls containing `st` | Returned text from those calls | Unparsed shell sources |
| --- | ---: | ---: | ---: | ---: |
| codex | 11,837 | 7,170 | 35.40 MiB | 1,077 / 22,096 |
| claude code | 10,036 | 7,791 | 8.82 MiB | 1,590 / 63,203 |
| pi | 521 | 224 | 0.79 MiB | 0 / 330 |

The Codex row reads nested command strings from the native `exec` script; 969 of 22,096 nested commands could not be extracted. Claude Code had 1,590 unparsed shell sources; Pi had none. These counts are lower bounds. The output totals are container text and are not additive to the 270.29 MiB in the direct-tool report.

## Top 25 `st` families by frequency

`Single-ST shell text` is the full returned text from shell calls with one recognizable `st` invocation; the call may also contain `cd`, pipes, or other commands. It is an upper bound for that family.

| Family | Invocations | Single-ST calls with results | Single-ST shell text |
| --- | ---: | ---: | ---: |
| `st sessions` | 4,013 | 2,006 | 3.65 MiB |
| `st check` | 3,379 | 2,281 | 4.09 MiB |
| `st neri` | 1,834 | 541 | 2.04 MiB |
| `st lease` | 1,774 | 894 | 2.32 MiB |
| `st db` | 1,726 | 753 | 1.10 MiB |
| `st commit` | 1,527 | 1,158 | 0.69 MiB |
| `st browser` | 1,366 | 346 | 0.86 MiB |
| `st service` | 1,181 | 728 | 1.15 MiB |
| `st tools` | 769 | 217 | 0.72 MiB |
| `st aico` | 700 | 310 | 0.38 MiB |
| `st claim` | 298 | 90 | 0.19 MiB |
| `st context` | 298 | 106 | 0.62 MiB |
| `st memory` | 288 | 134 | 0.32 MiB |
| `st done` | 272 | 152 | 0.09 MiB |
| `st create` | 255 | 147 | 0.27 MiB |
| `st ui` | 245 | 97 | 0.13 MiB |
| `st web` | 224 | 55 | 0.60 MiB |
| `st vm` | 223 | 96 | 0.14 MiB |
| `st pulse` | 215 | 79 | 0.21 MiB |
| `st backup` | 190 | 56 | 0.10 MiB |
| `st (dynamic)` | 188 | 97 | 0.64 MiB |
| `st log` | 129 | 36 | 0.07 MiB |
| `st list` | 108 | 33 | 0.13 MiB |
| `st prompt` | 97 | 17 | 0.02 MiB |
| `st bugout` | 96 | 45 | 0.04 MiB |

## Top 25 `st` families by single-ST shell text

| Family | Invocations | Single-ST calls with results | Single-ST shell text |
| --- | ---: | ---: | ---: |
| `st check` | 3,379 | 2,281 | 4.09 MiB |
| `st sessions` | 4,013 | 2,006 | 3.65 MiB |
| `st lease` | 1,774 | 894 | 2.32 MiB |
| `st neri` | 1,834 | 541 | 2.04 MiB |
| `st service` | 1,181 | 728 | 1.15 MiB |
| `st db` | 1,726 | 753 | 1.10 MiB |
| `st browser` | 1,366 | 346 | 0.86 MiB |
| `st tools` | 769 | 217 | 0.72 MiB |
| `st commit` | 1,527 | 1,158 | 0.69 MiB |
| `st (dynamic)` | 188 | 97 | 0.64 MiB |
| `st context` | 298 | 106 | 0.62 MiB |
| `st web` | 224 | 55 | 0.60 MiB |
| `st slopminer` | 73 | 53 | 0.46 MiB |
| `st aico` | 700 | 310 | 0.38 MiB |
| `st memory` | 288 | 134 | 0.32 MiB |
| `st create` | 255 | 147 | 0.27 MiB |
| `st task` | 82 | 39 | 0.24 MiB |
| `st pulse` | 215 | 79 | 0.21 MiB |
| `st claim` | 298 | 90 | 0.19 MiB |
| `st vm` | 223 | 96 | 0.14 MiB |
| `st list` | 108 | 33 | 0.13 MiB |
| `st ui` | 245 | 97 | 0.13 MiB |
| `st backup` | 190 | 56 | 0.10 MiB |
| `st monitor` | 28 | 14 | 0.09 MiB |
| `st done` | 272 | 152 | 0.09 MiB |

## Top 25 verb and subcommand pairs by frequency

| Command prefix | Invocations | Single-ST calls with results | Single-ST shell text |
| --- | ---: | ---: | ---: |
| `st check` | 1,945 | 1,454 | 2.89 MiB |
| `st lease` | 1,771 | 893 | 2.32 MiB |
| `st db query` | 1,600 | 724 | 0.87 MiB |
| `st commit` | 1,526 | 1,157 | 0.69 MiB |
| `st sessions inbox` | 1,197 | 636 | 1.50 MiB |
| `st browser` | 954 | 204 | 0.56 MiB |
| `st sessions send` | 794 | 474 | 0.55 MiB |
| `st check pytest` | 780 | 540 | 0.88 MiB |
| `st tools manifest` | 629 | 140 | 0.63 MiB |
| `st sessions ack` | 569 | 358 | 0.26 MiB |
| `st sessions confirm` | 562 | 280 | 0.24 MiB |
| `st service rebuild` | 465 | 342 | 0.25 MiB |
| `st neri target` | 364 | 73 | 0.23 MiB |
| `st service wait` | 271 | 220 | 0.56 MiB |
| `st neri hunt` | 260 | 105 | 0.34 MiB |
| `st create` | 254 | 147 | 0.27 MiB |
| `st aico root` | 233 | 122 | 0.09 MiB |
| `st service status` | 216 | 63 | 0.10 MiB |
| `st pulse` | 215 | 79 | 0.21 MiB |
| `st check vitest` | 214 | 118 | 0.05 MiB |
| `st aico roots` | 201 | 90 | 0.13 MiB |
| `st (dynamic)` | 187 | 96 | 0.64 MiB |
| `st sessions monitor` | 183 | 64 | 0.11 MiB |
| `st web fetch` | 177 | 36 | 0.40 MiB |
| `st sessions list` | 163 | 49 | 0.31 MiB |

## What this says about context waste

The heaviest repeat candidates are `st sessions` (4,013), `st lease` (1,774), `st db` (1,726, mostly 1,600 `db query`), and `st tools` (769, mostly 629 `tools manifest`). `st check` (3,379) and `st commit` (1,527) are verification and checkpoint work; their frequency alone does not make them waste. `st neri` includes substantive hunting and records work, so it must not be labelled administration from the command name.

The useful next measurement is per-session **purpose and output size** for repeated `sessions inbox`, `lease`, `tools manifest`, and `db query` calls, then compare those against accepted outcomes. Returned text can be reread in later model turns, so one-time result size does not capture cumulative input spend or resident context. The Activity page has a sampled **ST command time and text** section; this native scan is the fuller fixed-window inventory.

Method: unique native tool call IDs and event times; shell command prefixes parsed without printing arguments or results. When one shell result covers multiple commands, none of its bytes are split between subcommands. “Single-ST shell text” still includes any non-ST output in that shell call. Isolated native Bash `st` results were only 0.02 MiB; Codex single-command wrappers added 2.85 MiB of wrapper text, but that is not exact `st` stdout. Most ST calls were mixed with shell setup or Codex wrappers, so a purported exact per-command output ranking would be misleading. This report excludes images, prose, system instructions, provider cache reuse and commands hidden in scripts or unparsed dynamic expressions.
