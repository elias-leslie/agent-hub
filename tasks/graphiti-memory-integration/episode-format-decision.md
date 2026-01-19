# Episode Format Decision

**Date:** 2026-01-19
**Task:** task-a6a4c2fe (Graphiti Memory Integration)
**Subtask:** 1.4a - Research optimal episode format

## Decision

**Use Markdown via `EpisodeType.text`** for storing rules, standards, and anti-patterns in Graphiti.

## Research Summary

### Graphiti Native Types

| Type | Use Case |
|------|----------|
| `EpisodeType.text` | Prose, markdown, unstructured text |
| `EpisodeType.json` | Structured data (REST responses, metadata) |
| `EpisodeType.message` | Conversations ("speaker: message" format) |

### Format Comparison

| Criteria | JSON | Prose | Markdown | YAML | TOON |
|----------|------|-------|----------|------|------|
| LLM Extraction | Excellent | Fair | High | High | Low |
| Semantic Search | Medium | High | High | Medium | Low |
| Token Efficiency | Low (~30% overhead) | Medium | High | Medium | Very High |
| Human Readability | Low | High | Very High | Medium | Very Low |

### Why Markdown Wins

1. **Native to LLMs** - Claude/GPT trained heavily on markdown, understand headers as hierarchy
2. **Structure Retention** - "Do vs Don't" tables preserve relationship tension for graph extraction
3. **Semantic Anchors** - Headers (`## Variable Naming`) match natural language queries
4. **Token Efficient** - Markdown syntax (`|`, `-`, `#`) is cheap vs JSON (`{}`, `":"`)
5. **Human Debuggable** - Inspect stored episodes easily

### Why NOT JSON

- ~30% token overhead from syntax characters
- Embedding noise from brackets/quotes dilutes semantic matching
- Agent wastes tokens parsing structure vs reading content

### Why NOT TOON

- Graphiti's extraction prompts optimized for natural language
- Compressed syntax causes entity extraction errors
- Poor retrieval: "how to name variables" won't match `VarName`

## Implementation

### Episode Chunking Strategy

**Split by H2 headers** - don't store whole files as single episodes.

```python
# Good: One section per episode
add_episode(
    name="Coding Standards - State Management",
    episode_body="""
    ## State Management
    | Do | Don't |
    | Use const | Mutate directly |
    """,
    source=EpisodeType.text
)

# Bad: Entire file as one episode
add_episode(name="all-rules", episode_body=entire_file_content, ...)
```

### CLI Command Format

For CLI references, use markdown code blocks or YAML-like structure:

```python
add_episode(
    name="st CLI - Active Workflow",
    episode_body="""
    ## Active Workflow Commands

    | Command | Description |
    |---------|-------------|
    | `st ready` | Find available work |
    | `st context <id>` | Get full task context |
    | `st update <id> --status running` | Claim task |
    """,
    source=EpisodeType.text
)
```

### Source Description Convention

Include metadata in `source_description` for filtering:

```
{category} {tier} source:{origin} confidence:{0-100} [cluster:{name}] migrated_from:{file}
```

Example:
```
operational_context reference source:golden_standard confidence:100 cluster:st_cli_active_workflow migrated_from:st-cli.md
```

## References

- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Zep Adding Episodes Docs](https://help.getzep.com/graphiti/core-concepts/adding-episodes)
- Gemini Pro consultation (2026-01-19)
- Auto-Claude memory patterns
- claude-mem storage format
