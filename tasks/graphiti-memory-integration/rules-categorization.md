# Rules Categorization for Graphiti Migration

Generated: 2026-01-19

## Injection Tier Classification

### MANDATE (Always Inject - ~150 tokens target)
Critical behavioral constraints that must always be present.

| File | MemoryCategory | Rationale |
|------|----------------|-----------|
| `anti-patterns.md` | TROUBLESHOOTING_GUIDE | Core behavioral guardrails, prevents common LLM mistakes |
| `dev-tools-exclusive.md` | CODING_STANDARD | Mandatory dt usage - prevents forbidden direct commands |
| `session-protocol.md` | OPERATIONAL_CONTEXT | Session start/end lifecycle - always relevant |
| `scope-awareness.md` | TROUBLESHOOTING_GUIDE | Prevents scope creep, context overflow |
| `interaction-style.md` | CODING_STANDARD | Communication style - always applies |

### GUARDRAIL (Type-Filtered - Retrieved based on task type)
Domain-specific rules that apply to certain task types.

| File | MemoryCategory | Task Type Filter |
|------|----------------|------------------|
| `db-architecture.md` | SYSTEM_DESIGN | database, migration, schema |
| `browser-testing.md` | CODING_STANDARD | testing, ui, frontend |
| `browser-server.md` | OPERATIONAL_CONTEXT | browser, playwright, ba |
| `verification.md` | CODING_STANDARD | testing, commit, done |
| `quality-gate.md` | OPERATIONAL_CONTEXT | commit, testing, quality |
| `cloudflare-access.md` | OPERATIONAL_CONTEXT | deploy, production, api |
| `voice-system.md` | SYSTEM_DESIGN | voice, audio, whisper |
| `tech-debt-cleanup.md` | TROUBLESHOOTING_GUIDE | migration, refactor, cleanup |

### REFERENCE (Semantic Retrieval - Retrieved when semantically relevant)
Documentation and specifications that should be retrieved based on query context.

| File | MemoryCategory | Semantic Clusters |
|------|----------------|-------------------|
| `st-cli.md` | OPERATIONAL_CONTEXT | Cluster: CLI Tools (task management, workflow) |
| `dev-standards.md` | CODING_STANDARD | Cluster: Development Workflow (code style, dt usage) |
| `output-format-standard.md` | CODING_STANDARD | Cluster: Output Formatting (TOON, CLI output) |
| `model-standards.md` | CODING_STANDARD | Cluster: AI/LLM Config (model constants, thinking) |
| `decision-making.md` | TROUBLESHOOTING_GUIDE | Cluster: Decision Process (tiers, .index.yaml) |
| `skill-triggers.md` | OPERATIONAL_CONTEXT | Cluster: Skill System (invocation patterns) |
| `rule-authoring.md` | CODING_STANDARD | Cluster: Meta Rules (rule format guidelines) |
| `api-config-pattern.md` | CODING_STANDARD | Cluster: Frontend Patterns (API config, URLs) |

## Stale/Exclusion Candidates

None identified. All rules are actively used and relevant.

## Functional Clusters for Reference Docs

Per decision d1, reference docs are grouped into functional clusters:

1. **CLI Tools** (~1 node): st-cli
2. **Development Workflow** (~1 node): dev-standards, dev-tools-exclusive
3. **Output Formatting** (~1 node): output-format-standard
4. **AI/LLM Config** (~1 node): model-standards
5. **Decision Process** (~1 node): decision-making
6. **Skill System** (~1 node): skill-triggers

Global constraints (anti-patterns, scope-awareness, interaction-style) are separate MANDATE nodes.

## Token Estimates

| Tier | Files | Estimated Tokens |
|------|-------|------------------|
| MANDATE | 5 files | ~150 tokens (summary form) |
| GUARDRAIL | 8 files | ~100 tokens (filtered subset) |
| REFERENCE | 8 files | Semantic retrieval, variable |

**Total Session Start**: ~150-200 tokens (vs 600+ from full rules loading)

## MemoryCategory Distribution

| Category | Count | Files |
|----------|-------|-------|
| CODING_STANDARD | 8 | dev-tools-exclusive, dev-standards, browser-testing, verification, output-format-standard, model-standards, rule-authoring, api-config-pattern, interaction-style |
| TROUBLESHOOTING_GUIDE | 4 | anti-patterns, scope-awareness, decision-making, tech-debt-cleanup |
| OPERATIONAL_CONTEXT | 6 | session-protocol, browser-server, quality-gate, cloudflare-access, st-cli, skill-triggers |
| SYSTEM_DESIGN | 2 | db-architecture, voice-system |
| DOMAIN_KNOWLEDGE | 0 | (none - rules are operational, not domain-specific) |
| ACTIVE_STATE | 0 | (runtime only, not static rules) |

## MemoryScope Mapping

All rules files map to **GLOBAL** scope - they are system-wide learnings that apply across all projects and tasks.
