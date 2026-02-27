# Tool Execution Benchmark Results

- **Model**: haiku
- **Runs per approach**: 3
- **Date**: (see file timestamp)

## Summary (Averaged)

| Metric                | A (MCP + DirectToolHandler) | C+ (Auto-Claude (3-Layer Permissions)) |
| --------------------- | --------------------------- | -------------------------------------- |
| Total latency (ms)    |                        9399 |                                   8883 |
| Cost (USD)            |                   $0.011380 |                              $0.011860 |
| Input tokens          |                          40 |                                     40 |
| Output tokens         |                         701 |                                    779 |
| Cache read tokens     |                       69993 |                                  70038 |
| Cache creation tokens |                         667 |                                    735 |
| Peak RSS (MB)         |                       365.5 |                                  368.7 |
| Subprocess spawns     |                           1 |                                      1 |
| Turns                 |                           3 |                                      3 |
| Permission checks     |                           6 |                                      6 |
| Permission denials    |                           0 |                                      0 |
| Correct               |                         Yes |                                    Yes |
| Errors                |                           0 |                                      0 |

## Per-Run Results

### Approach A: MCP + DirectToolHandler

| Run     | Latency (ms) |    Cost (USD) | Input Tokens | Output Tokens | Cache Read |   Turns | Correct |
| ------- | ------------ | ------------- | ------------ | ------------- | ---------- | ------- | ------- |
| 1       |         9238 |     $0.010930 |           40 |           626 |      69950 |       3 |     Yes |
| 2       |         9082 |     $0.011883 |           40 |           786 |      70057 |       3 |     Yes |
| 3       |         9879 |     $0.011326 |           40 |           692 |      69974 |       3 |     Yes |
| **Avg** |     **9399** | **$0.011380** |       **40** |       **701** |  **69993** | **3.0** | **Yes** |

### Approach C+: Auto-Claude (3-Layer Permissions)

| Run     | Latency (ms) |    Cost (USD) | Input Tokens | Output Tokens | Cache Read |   Turns | Correct |
| ------- | ------------ | ------------- | ------------ | ------------- | ---------- | ------- | ------- |
| 1       |         9308 |     $0.011910 |           40 |           800 |      69998 |       3 |     Yes |
| 2       |         8245 |     $0.011883 |           40 |           777 |      70063 |       3 |     Yes |
| 3       |         9097 |     $0.011788 |           40 |           761 |      70054 |       3 |     Yes |
| **Avg** |     **8883** | **$0.011860** |       **40** |       **779** |  **70038** | **3.0** | **Yes** |

## Per-Turn Details

### Approach A: MCP + DirectToolHandler

| Turn | Latency (ms) | In Tokens | Out Tokens | Cache Read |              Tools |                                                      Results |
| ---- | ------------ | --------- | ---------- | ---------- | ------------------ | ------------------------------------------------------------ |
| 3    |            0 |         0 |          0 |          0 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |
| 6    |            0 |         0 |          0 |          0 |  read_user_context | [{'type': 'text', 'text': 'Benchmark user: prefers dark m... |
| 9    |            0 |        40 |        692 |      69974 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |

### Approach C+: Auto-Claude (3-Layer Permissions)

| Turn | Latency (ms) | In Tokens | Out Tokens | Cache Read |              Tools |                                                      Results |
| ---- | ------------ | --------- | ---------- | ---------- | ------------------ | ------------------------------------------------------------ |
| 3    |            0 |         0 |          0 |          0 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |
| 6    |            0 |         0 |          0 |          0 |  read_user_context | [{'type': 'text', 'text': 'Benchmark user: prefers dark m... |
| 9    |            0 |        40 |        761 |      70054 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |

## Analysis

**Lowest token cost**: A (MCP + DirectToolHandler) — 741 total tokens

**Lowest latency**: C+ (Auto-Claude (3-Layer Permissions)) — 8883ms

**With permissions**: A, C+