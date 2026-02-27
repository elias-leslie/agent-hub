# Tool Execution Benchmark Results

- **Model**: haiku
- **Runs per approach**: 3
- **Date**: (see file timestamp)

## Summary (Averaged)

| Metric                | A (MCP + DirectToolHandler) | B (Deny-All + Our Tool Loop) | C (Auto-Claude (SDK Manages)) | D (AutoMaker (Bypass + Normalize)) |
| --------------------- | --------------------------- | ---------------------------- | ----------------------------- | ---------------------------------- |
| Total latency (ms)    |                       10771 |                        37856 |                          8740 |                               9190 |
| Cost (USD)            |                   $0.011858 |                    $0.034575 |                     $0.011145 |                          $0.011622 |
| Input tokens          |                          40 |                          100 |                            40 |                                 40 |
| Output tokens         |                         784 |                         2566 |                           657 |                                736 |
| Cache read tokens     |                       70039 |                       171568 |                         69959 |                              70045 |
| Cache creation tokens |                         715 |                         3590 |                           656 |                                715 |
| Peak RSS (MB)         |                       368.4 |                        368.4 |                         368.4 |                              368.4 |
| Subprocess spawns     |                           1 |                           10 |                             1 |                                  1 |
| Turns                 |                           3 |                           10 |                             3 |                                  3 |
| Permission checks     |                           6 |                           55 |                             6 |                                  0 |
| Permission denials    |                           0 |                            0 |                             0 |                                  0 |
| Correct               |                         Yes |                           NO |                           Yes |                                Yes |
| Errors                |                           0 |                            0 |                             0 |                                  0 |

## Per-Run Results

### Approach A: MCP + DirectToolHandler

| Run     | Latency (ms) |    Cost (USD) | Input Tokens | Output Tokens | Cache Read |   Turns | Correct |
| ------- | ------------ | ------------- | ------------ | ------------- | ---------- | ------- | ------- |
| 1       |        10729 |     $0.011303 |           40 |           686 |      70002 |       3 |     Yes |
| 2       |        11644 |     $0.011758 |           40 |           762 |      70010 |       3 |     Yes |
| 3       |         9942 |     $0.012514 |           40 |           904 |      70105 |       3 |     Yes |
| **Avg** |    **10771** | **$0.011858** |       **40** |       **784** |  **70039** | **3.0** | **Yes** |

### Approach B: Deny-All + Our Tool Loop

| Run     | Latency (ms) |    Cost (USD) | Input Tokens | Output Tokens | Cache Read |    Turns | Correct |
| ------- | ------------ | ------------- | ------------ | ------------- | ---------- | -------- | ------- |
| 1       |        39281 |     $0.032445 |          100 |          2966 |     175149 |       10 |     Yes |
| 2       |        37280 |     $0.029975 |          100 |          2472 |     175149 |       10 |     Yes |
| 3       |        37008 |     $0.041306 |          100 |          2260 |     164407 |       10 |      NO |
| **Avg** |    **37856** | **$0.034575** |      **100** |      **2566** | **171568** | **10.0** |  **NO** |

### Approach C: Auto-Claude (SDK Manages)

| Run     | Latency (ms) |    Cost (USD) | Input Tokens | Output Tokens | Cache Read |   Turns | Correct |
| ------- | ------------ | ------------- | ------------ | ------------- | ---------- | ------- | ------- |
| 1       |         9120 |     $0.011090 |           40 |           648 |      69945 |       3 |     Yes |
| 2       |         7800 |     $0.011122 |           40 |           649 |      69981 |       3 |     Yes |
| 3       |         9300 |     $0.011223 |           40 |           676 |      69953 |       3 |     Yes |
| **Avg** |     **8740** | **$0.011145** |       **40** |       **657** |  **69959** | **3.0** | **Yes** |

### Approach D: AutoMaker (Bypass + Normalize)

| Run     | Latency (ms) |    Cost (USD) | Input Tokens | Output Tokens | Cache Read |   Turns | Correct |
| ------- | ------------ | ------------- | ------------ | ------------- | ---------- | ------- | ------- |
| 1       |         9845 |     $0.011387 |           40 |           700 |      69957 |       3 |     Yes |
| 2       |         8354 |     $0.012061 |           40 |           806 |      70185 |       3 |     Yes |
| 3       |         9371 |     $0.011419 |           40 |           704 |      69995 |       3 |     Yes |
| **Avg** |     **9190** | **$0.011622** |       **40** |       **736** |  **70045** | **3.0** | **Yes** |

## Per-Turn Details

### Approach A: MCP + DirectToolHandler

| Turn | Latency (ms) | In Tokens | Out Tokens | Cache Read |              Tools |                                                      Results |
| ---- | ------------ | --------- | ---------- | ---------- | ------------------ | ------------------------------------------------------------ |
| 3    |            0 |         0 |          0 |          0 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |
| 6    |            0 |         0 |          0 |          0 |  read_user_context | [{'type': 'text', 'text': 'Benchmark user: prefers dark m... |
| 9    |            0 |        40 |        904 |      70105 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |

### Approach B: Deny-All + Our Tool Loop

| Turn | Latency (ms) | In Tokens | Out Tokens | Cache Read |              Tools |              Results |
| ---- | ------------ | --------- | ---------- | ---------- | ------------------ | -------------------- |
| 1    |         3416 |        10 |        212 |      17328 | write_user_context | User context updated |
| 2    |         4368 |        10 |        186 |      17375 | write_user_context | User context updated |
| 3    |         4175 |        10 |        217 |      16213 | write_user_context | User context updated |
| 4    |         3853 |        10 |        186 |      16213 | write_user_context | User context updated |
| 5    |         4043 |        10 |        232 |      16213 | write_user_context | User context updated |
| 6    |         4175 |        10 |        296 |      16213 | write_user_context | User context updated |
| 7    |         3568 |        10 |        218 |      16213 | write_user_context | User context updated |
| 8    |         3047 |        10 |        249 |      16213 | write_user_context | User context updated |
| 9    |         3392 |        10 |        232 |      16213 | write_user_context | User context updated |
| 10   |         2862 |        10 |        232 |      16213 | write_user_context | User context updated |

### Approach C: Auto-Claude (SDK Manages)

| Turn | Latency (ms) | In Tokens | Out Tokens | Cache Read |              Tools |                                                      Results |
| ---- | ------------ | --------- | ---------- | ---------- | ------------------ | ------------------------------------------------------------ |
| 3    |            0 |         0 |          0 |          0 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |
| 6    |            0 |         0 |          0 |          0 |  read_user_context | [{'type': 'text', 'text': 'Benchmark user: prefers dark m... |
| 9    |            0 |        40 |        676 |      69953 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |

### Approach D: AutoMaker (Bypass + Normalize)

| Turn | Latency (ms) | In Tokens | Out Tokens | Cache Read |              Tools |                                                      Results |
| ---- | ------------ | --------- | ---------- | ---------- | ------------------ | ------------------------------------------------------------ |
| 3    |            0 |         0 |          0 |          0 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |
| 6    |            0 |         0 |          0 |          0 |  read_user_context | [{'type': 'text', 'text': 'Benchmark user: prefers dark m... |
| 9    |            0 |        40 |        704 |      69995 | write_user_context |           [{'type': 'text', 'text': 'User context updated'}] |

## Analysis

**Lowest token cost**: C (Auto-Claude (SDK Manages)) — 697 total tokens

**Lowest latency**: C (Auto-Claude (SDK Manages)) — 8740ms

**With permissions**: A, C
**No permissions (speed-only)**: D