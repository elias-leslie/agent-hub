"""Load-independent linear-time checks for scans and regexes.

A fixed wall-clock bound flakes on a busy host. Growth does not: an input 8x
larger costs ~8x when the scan is linear and ~30-60x when it is quadratic, and
the best of a few runs filters out scheduling noise.
"""

from __future__ import annotations

import time
from collections.abc import Callable

FACTOR = 8
MAX_GROWTH = 16


def growth(run: Callable[[str], object], build: Callable[[int], str], size: int, repeats: int = 5) -> float:
    """Best-of-``repeats`` time of ``run(build(size))`` over that of ``run(build(size // FACTOR))``."""

    def best(n: int) -> float:
        content = build(n)
        fastest = float("inf")
        for _ in range(repeats):
            started = time.perf_counter()
            run(content)
            fastest = min(fastest, time.perf_counter() - started)
        return fastest

    small = best(size // FACTOR)
    return best(size) / small


def assert_linear(run: Callable[[str], object], build: Callable[[int], str], size: int) -> None:
    ratio = growth(run, build, size)
    assert ratio < MAX_GROWTH, f"{FACTOR}x the input took {ratio:.1f}x as long (linear is ~{FACTOR}x)"
