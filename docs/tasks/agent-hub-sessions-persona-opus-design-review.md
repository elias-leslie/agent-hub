Note: both screenshot paths resolve to the same `/persona` image — no `/sessions` screenshot available. Review below is grounded in code + contract for `/sessions`.

# Agent Hub `/persona` + `/sessions` — Design Review Memo

## 1. Overall verdict

The bones are right: dark cockpit aesthetic, serious typography, correct instinct to treat `/persona` as active supervision and `/sessions` as forensic ledger. The execution is **80% there on chrome, 40% there on information architecture.**

Current `/persona` looks like a chat app in a cockpit costume. The top status bar is one line when an operator cockpit needs a two-row command deck; the right intelligence rail is absent from the visible surface; the transcript pretends to be the primary work surface when the *run* is the primary subject. `/sessions` (inferred from code) is a dense table with client-side filtering dressed as authoritative truth — a cardinal sin in a forensic surface.

Ship blockers: (a) source-of-truth ambiguity across Runtime / Preview / Draft / Advisory is not visually encoded anywhere; (b) `/sessions` reports filtered numbers without Visible/Loaded/Total framing; (c) `/persona` action scope is carried in `title=` tooltips instead of chrome. Fix those three and the product reads as a serious tool.

## 2. Current design critique

### `/persona`
- **Header is monolithic, not tiered.** One row crams: persona name, runtime dot, state pill, separator, live summary, stop/heartbeat, pause, activity link, settings. Seven competing foci at 12–14px. An operator's eye has no anchor.
- **No provenance encoding.** `renderedLiveSummary` silently collapses five sources (runtime → heartbeat fallback → heartbeat-running copy → paused copy → last-run ago → `"Ready"`). The operator cannot tell which layer they're reading. This is the single biggest integrity issue.
- **Icon-only controls for destructive/state-changing actions.** Pause, settings, analytics are all unlabeled 16px glyphs. Cockpits label their kill switches.
- **"Stop" label is surgical but backend is a broadcast.** The button says `Stop`, scope is "all cancellable live sessions for this persona." Contract says `Stop active work`. The code ships the wrong noun.
- **STEER / New thread / Status / Plan / Request lane** composer pill row (visible in screenshot) duplicates header concerns, reads as consumer-product CTA candy, and the pill styling doesn't distinguish advisory (Plan, Request lane) from real (New thread).
- **Lane count / workflow stages / budget / automation** — none of the "intelligence rail" surfaces are visible in the current screenshot layout. Either they're collapsed, buried in `UnifiedPersonaWorkspace`, or off-canvas. Either way, a cockpit cannot hide its instruments.
- **Transcript evidence density is low.** Two messages with `completed` pills, message count, and a `bash failed` tag. No turn numbers, no token/cost strip, no branch/fork hint, no linkage back to the workflow stage that produced them.
- **`HEALTHY · 4h uptime` in the left nav** is warm-fuzzy telemetry for a consumer dashboard. An operator wants the last heartbeat age, queue depth, or blocker count in that slot.

### `/sessions` (from code)
- **`SessionsHeader` receives `total` + `pageStats` but there is no `Visible / Loaded / Total` triplet surfaced as a contract.** `pageStats` is ambiguous by name. The contract is explicit and the code is not.
- **`searchQuery` filters `allSessions` in `useSessionFilters` — pure client-side.** The page can display "3 results" when the server has 12,000 unseen matches. This is operator-hostile for a forensic tool.
- **`liveSessionIds={new Set<string>()}` and `flashingSessionIds={new Set<string>()}` are hardcoded empty.** Live affordances are structurally placeholders, confirming the contract audit.
- **Expansion fetches (`useSessionExpansion`) with no visible race guard** — if an operator rapidly expands three rows, the last response wins regardless of which is current.
- **No requested-vs-effective identity surface in the table props.** The table gets `modelCosts` and `modelFilter`, not `fallback_used` / `fallback_reason`. Fallback invisibility is a forensic failure mode.
- **`message_count` semantics** — contract says user+assistant only; no evidence the UI distinguishes from `event_count`.
- **`ErrorAlert`, `LoadingState`, `InfiniteScrollFooter`** are three separate minor-component empties with no unified empty-state machine distinguishing *no data* / *no matches on loaded subset* / *fetch failed*.
- **`bg-grid-pattern opacity-60`** backdrop is ornament. Cockpits are spartan.

## 3. Cohesive design direction

**One product, two postures.**

- Shared language: **Obsidian cockpit.** Near-black base (`#070a0f`-ish), single-pixel `slate-800/60` dividers, mono for identifiers/timestamps/IDs, sans for prose, restrained motion, state carried by **color + glyph + label** (never color alone — accessibility + print/screenshot legibility).
- `/persona` posture: **live-subject-first.** The current run is the hero. Transcript is evidence *for* the run, not the page itself.
- `/sessions` posture: **ledger-first.** The table is the hero. Expansion is a drawer, not a mode switch.
- **Provenance is a first-class visual primitive.** Every datum that can be confused carries a 9px uppercase micro-badge: `RUNTIME` emerald, `SESSION` slate, `PREVIEW` violet, `ADVISORY` steel, `DRAFT` amber-outline. Badges live inline, left of the value, not floating in tooltips.
- **Action scope is a first-class visual primitive.** Any button that affects >1 entity carries a scope chip (`all lanes`, `this thread`, `persona-wide`). No silent broadcasts.
- **Two-row command deck** across both pages: Row 1 = identity + state beacon + live summary + provenance; Row 2 = scoped actions + filters + refresh meta. Sticky, same height (88–96px), same rhythm.
- **Evidence drawers, not modals.** Right-side, 480px, resizable, persistent — matches the ledger/cockpit metaphor.

## 4. `/persona` recommended hierarchy

```
┌─ COMMAND DECK (sticky, 88px, two rows) ─────────────────────────────┐
│ R1: ● Jenny  [WORKING]  RUNTIME · dispatch parser cleared branch…  │
│ R2: [⏻ Heartbeat]  [■ Stop active work (2 lanes)]  [⏸ Pause]  ⚙︎   │
├─ MAIN (3-column, 1fr | 2fr | 1.2fr) ────────────────────────────────┤
│ LEFT: Lane inbox          │ CENTER: Run surface       │ RIGHT:      │
│  - Active lanes (N)       │  - Thread header          │  Run HUD    │
│    · agent-hub · WORKING  │    · lane: agent-hub      │  - tokens   │
│    · summitflow · IDLE    │    · fork point: turn 4   │  - cost     │
│  - Workflow stages        │    · branch: heartbeat-x  │  - elapsed  │
│    (1) intake ✓ [s:abc1]  │  - Transcript/evidence    │  - blockers │
│    (2) plan ✓  [s:def2]   │    [Operator] [Raw]       │  Budget     │
│    (3) execute ● [live]   │    toggle                 │   PREVIEW   │
│    (4) verify · advisory  │  - Composer               │   vs        │
│  - Automation             │    · Draft state explicit │   RUNTIME   │
│    last run 35m ago       │    · scope chip on send   │  Workflow   │
│                           │                           │   lineage   │
└─────────────────────────────────────────────────────────────────────┘
```

Key moves:
- **Run HUD is always visible**, right rail, ~320px. Tokens, cost, elapsed, blockers, live `RUNTIME` badge.
- **Lane inbox is left-rail**, replacing the current mystery left column. Counts reflect child lanes only (contract §Lane count).
- **Workflow stages** expose `session_id` linkage inline: `[s:def2]` is a clickable session chip. Advisory-only stages carry `ADVISORY` badge and dimmed treatment.
- **Transcript has `[Operator] | [Raw]` toggle** — Operator mode cleans and groups; Raw shows every event with turn/event IDs and timestamps at nanosecond precision.
- **Composer draft state** is a persistent `DRAFT` badge above the input; send button carries scope chip (`→ this thread` or `→ new lane`).
- **Destructive/broadcast actions** always carry count: `Stop active work (2 lanes)`, not `Stop`.
- **Kill STEER / New thread / Status / Plan / Request lane pill row.** Fold `New thread` into composer; Plan/Request-lane become Advisory flows inside the lane inbox (open inspectable instruction draft per contract §Action semantics).

## 5. `/sessions` recommended hierarchy

```
┌─ COMMAND DECK (sticky, 96px, two rows) ─────────────────────────────┐
│ R1: SESSIONS LEDGER   12,847 Total · 250 Loaded · 43 Visible       │
│     Filter scope: LOADED SUBSET (client-side)  ·  last sync 12s     │
│ R2: [Status ▾] [Model ▾] [Provider ▾] [Lane ▾] [Has fallback ▾]    │
│     [🔍 search loaded subset…]  [↻ Refresh]  [⚡ Live: on/off]       │
├─ LEDGER (full-bleed table + drawer) ────────────────────────────────┤
│ ● 14:32:01  sess_a1b2  agent-hub    WORKING   ↳ live 3s ago   ⌄    │
│   │ summary oneliner                                                 │
│   │ claude-opus-4-7 → sonnet-4-6  (FALLBACK: rate_limit)            │
│   │ u+a:14  events:127  tokens:48k  $0.22  lane:root                │
│ ─────────────────────────────────────────────────────────────────── │
│ ● 14:28:44  sess_9c2d  summitflow  COMPLETE    —              ⌄    │
│   ...                                                                │
├─ DRAWER (right, 480px, opens on expand) ────────────────────────────┤
│ [Overview] [Usage] [Evidence] [Lineage]                             │
│  · parent_session_id: sess_... (jump)                               │
│  · fork_point_turn: 4                                                │
│  · branch_status: clean / drift / abandoned                         │
│  · event timeline (virtualized, paged)                              │
└─────────────────────────────────────────────────────────────────────┘
```

Key moves:
- **Visible / Loaded / Total triplet is the dominant header number**, with an explicit "Filter scope: LOADED SUBSET" tag when search is client-side. Remove ambiguity before the eye can invent it.
- **Row is information-dense but single-interaction** — entire row click toggles drawer; a dedicated caret-button owns expand keyboard focus (contract §Row expansion).
- **Requested vs effective identity always rendered**, with `FALLBACK: <reason>` chip when `fallback_used=true`. Never silent.
- **`u+a:14  events:127`** — messages and events displayed separately, never collapsed (contract §Count semantics).
- **State beacon is color + glyph + label**: `● WORKING` emerald, `◐ STALLED` amber, `◯ REAPABLE` amber-outline, `✓ COMPLETE` slate, `✗ FAILED` rose. No color-only signaling.
- **Drawer tabs** separate overview / usage / evidence / lineage — matches contract §Detail expansion.
- **Live polling opt-in per session**, visible toggle in command deck. Only active/expanded rows poll.
- **Empty-state machine**: three distinct illustrations+copy for `no-sessions` / `no-matches-on-loaded` / `fetch-error` — never one generic empty.
- **Race guard**: expansion fetches keyed by `sess_id` + `abortController`; stale responses dropped.

## 6. Shared visual language

### Tokens (design-time, enforceable)
```
--bg-base        #070a0f           // page
--bg-surface-1   #0b1018           // rails
--bg-surface-2   #10172080 (slate) // cards, drawer
--bg-surface-3   #1a2332           // expanded row
--border-hair    slate-800/60      // dividers
--border-edge    slate-700         // card edges
--text-primary   slate-50
--text-body      slate-300
--text-muted     slate-500
--text-hint      slate-600

// State (color + must be paired with glyph + label)
--state-live     emerald-400  glyph:●   label:WORKING|LIVE
--state-wait     amber-400    glyph:◐   label:WAITING|STALLED
--state-fail     rose-400     glyph:✗   label:FAILED|BLOCKED
--state-idle     slate-500    glyph:◯   label:IDLE|ARCHIVED
--state-advise   violet-400   glyph:◇   label:ADVISORY|PREVIEW

// Provenance badges (9px, uppercase, mono, 1px ring)
RUNTIME   ring-emerald-500/40 text-emerald-300
SESSION   ring-slate-600      text-slate-400
PREVIEW   ring-violet-500/40  text-violet-300
ADVISORY  ring-steel-500/40   text-steel-300
DRAFT     ring-amber-500/40   text-amber-300 (dashed ring)
```

### Typography
- Prose / summaries: `Inter` 13px / 1.5 / slate-300.
- Identifiers / IDs / timestamps / counts: `JetBrains Mono` or `Berkeley Mono` 12px / slate-400.
- Micro-labels / badges: mono 9–10px uppercase tracking `0.06em`.
- Numerals tabular-lining (`font-variant-numeric: tabular-nums`) for every count/metric.

### Reusable components (build these once)
1. `<CommandDeck>` — two-row sticky header, slot-based.
2. `<StateBeacon state glyph label />` — dot+glyph+label unit.
3. `<ProvenanceBadge source />` — the five-source badge.
4. `<ScopeChip count scope />` — `2 lanes`, `this thread`, `persona-wide`.
5. `<MetricStrip>` — horizontal tabular tokens/cost/elapsed cluster.
6. `<EvidenceDrawer>` — right-side panel, tabbed, keyboard-navigable.
7. `<EmptyState kind="no-data" | "no-match" | "error" | "degraded" />` — one component, four explicit kinds.
8. `<IdentityCell requested effective fallback />` — table cell for provider/model with fallback rendering.
9. `<CountTriplet total loaded visible scope />` — the ledger-header truth unit.
10. `<SessionChip id lane status />` — linkable session reference used in transcripts, workflow stages, drawer lineage.

### Motion
- Transitions ≤160ms, ease-out. No bouncing, no shimmer.
- Live beacons: 1.8s pulse for waiting only; live-working is solid (pulsing everything trains operators to ignore it).
- Drawer open: 180ms slide + 120ms content fade.
- Row flash on update: 600ms emerald-fade, **only** opt-in when live polling is on.

## 7. Truth and provenance guidance

Principles:
- **Encode source, don't narrate it.** A 9px `RUNTIME` badge is faster to read than the sentence "(from current session live activity)".
- **Never collapse across provenance tiers in one string.** Current `liveSummary` code does exactly this — five fallbacks into one string. Split into: `<summary>` + `<ProvenanceBadge>`. If there's no runtime signal, render `<ProvenanceBadge source="advisory" />` + `"Heartbeat running 35m ago"`.
- **Disagreement is a signal, not a bug.** When `status=completed` but `live_activity` suggests live: show both with a small `⚠︎ status mismatch` chip. Do not pick one. Contract §Row state beacon.
- **Counts must declare their universe.** `43 Visible` is meaningless without `of 250 Loaded of 12,847 Total`. Use `<CountTriplet>` everywhere any filtered count appears.
- **Fallback is always visible when it happened.** `claude-opus-4-7 → sonnet-4-6 · FALLBACK: rate_limit` in one line. Dimming the requested model + arrow + effective is fine; hiding is not.
- **Draft is dashed, persisted is solid.** Use border-style as a secondary channel so operators at a glance distinguish draft instructions from sent ones.
- **Operator-summary vs raw-evidence is a toggle, not a setting.** Make it one keystroke (`R`). Operators will use it constantly.
- **Tooltips are footnotes, not primary channels.** If a scope or source must be understood to act safely, it lives in the chrome, not in `title=`.

Anti-pattern to kill: `"Ready"` as a catch-all `liveSummary`. Replace with explicit idle state: `<ProvenanceBadge source="session" /> Idle · last heartbeat 35m ago` — same width, infinitely more truthful.

## 8. Top 10 implementation priorities

1. **Provenance badge primitive + wire through `/persona` liveSummary.** Replace the collapsed-string logic in `persona/page.tsx:93-102` with `{source, text}` tuples. Smallest change, largest truth gain. (~1d)
2. **`<CountTriplet>` + `/sessions` header correction.** Render `Visible / Loaded / Total` with explicit "filter scope: LOADED SUBSET" tag. Kills the single worst forensic lie. (~0.5d)
3. **Identity cell + fallback rendering in session rows.** Propagate `requested_provider/model`, `effective_provider/model`, `fallback_used`, `fallback_reason` into `SessionTable`; render with arrow + chip. (~1d)
4. **Action-scope chips + correct labels on `/persona` command deck.** `Stop active work (N lanes)`; scope chip on composer send; pause/resume as labeled buttons not glyphs. (~0.5d)
5. **Split `/persona` into 3-column cockpit layout.** Lane inbox left, run surface center, Run HUD right. Lift `UnifiedPersonaWorkspace` internals up; make rails first-class. (~2–3d)
6. **Evidence drawer on `/sessions` with tabs (Overview/Usage/Evidence/Lineage) + abort-controller race guard on expansion.** (~2d)
7. **Empty-state machine.** `<EmptyState kind="..." />` with four explicit kinds on `/sessions`; two on `/persona` (idle cockpit, draft-only). Remove generic fallback. (~0.5d)
8. **Workflow stage linkage + `ADVISORY` badges on `/persona`.** Render `session_id` as `<SessionChip>` when present; dim + badge advisory-only stages. (~1d)
9. **Messages vs events separation in `/sessions` rows.** `u+a:14  events:127` — wire `event_count` additive field; stop overloading `message_count`. (~0.5d backend + 0.5d frontend)
10. **Live-polling opt-in toggle on `/sessions` + real `liveSessionIds`/`flashingSessionIds` wiring.** Remove the hardcoded empty sets; poll only expanded rows or when toggle is on. (~1.5d)

Total: ~12–14 engineering days to transform both surfaces into a truthful, cohesive operator cockpit + forensic ledger. Priorities 1–4 alone (~3 days) deliver ~70% of the integrity gain and should be the first PR.
