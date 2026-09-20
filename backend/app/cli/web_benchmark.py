"""Deterministic local benchmark for the shared web fetch stack."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.services.tools._executor_web import fetch_web_page


class _BenchmarkHandler(BaseHTTPRequestHandler):
    PRODUCT_HTML = """<!doctype html><html><head><title>Benchmark Olive Oil</title></head><body>
<article>
<h1>Pompeian Robust Extra Virgin Olive Oil</h1>
<p>Price: $38.79.</p>
<p>Package size: 68 fl oz.</p>
<p>Unit price: $0.57/fl oz.</p>
<p>Pickup store: deterministic local benchmark.</p>
</article>
</body></html>"""
    FOCUS_MARKDOWN = """# Benchmark Focus

Unrelated filler alpha about pantry planning, delivery windows, and membership notes.

Olive oil benchmark target: Pompeian robust extra virgin olive oil is $38.79 for 68 fl oz, equal to $0.57/fl oz, verified deterministic comparison benchmark data for unit-price extraction.

Unrelated filler omega about snacks, paper goods, rice, coffee, and storage bins."""

    def log_message(self, format: str, *args: object) -> None:
        return None

    def do_GET(self) -> None:
        if self.path == "/product":
            body = self.PRODUCT_HTML
            content_type = "text/html; charset=utf-8"
        elif self.path == "/focus":
            body = self.FOCUS_MARKDOWN
            content_type = "text/markdown; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _case_result(
    name: str,
    *,
    elapsed_ms: float,
    payload: dict[str, object],
    checks: dict[str, bool],
) -> dict[str, object]:
    output_chars = len(json.dumps(payload, sort_keys=True))
    content = str(payload.get("content") or "")
    return {
        "name": name,
        "passed": "error" not in payload and all(checks.values()),
        "elapsed_ms": round(elapsed_ms, 2),
        "output_chars": output_chars,
        "content_chars": len(content),
        "fetch_backend": payload.get("fetch_backend"),
        "checks": checks,
    }


async def benchmark_web(iterations: int, max_chars: int) -> str:
    """Exercise deterministic extraction, focus, error, and output-size contracts."""
    iterations = max(1, min(int(iterations), 10))
    max_chars = max(100, min(int(max_chars), 5000))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BenchmarkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    cases: list[dict[str, object]] = []
    try:
        for iteration in range(1, iterations + 1):
            started = time.perf_counter()
            product = json.loads(
                await fetch_web_page(
                    f"{base_url}/product",
                    max_chars=max_chars,
                    focus_query="olive oil price 68 fl oz unit price",
                    backend="direct",
                )
            )
            product_content = str(product.get("content") or "")
            cases.append(
                _case_result(
                    f"product_unit_price_{iteration}",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    payload=product,
                    checks={
                        "backend_direct": product.get("fetch_backend") == "direct",
                        "has_price": "$38.79" in product_content,
                        "has_quantity": "68 fl oz" in product_content,
                        "has_unit_price": "$0.57/fl oz" in product_content,
                        "content_within_budget": len(product_content) <= max_chars,
                        "output_token_efficient": len(json.dumps(product, sort_keys=True)) <= max_chars + 1600,
                    },
                )
            )

            started = time.perf_counter()
            focused = json.loads(
                await fetch_web_page(
                    f"{base_url}/focus",
                    max_chars=220,
                    focus_query="olive oil 68 fl oz unit price",
                    backend="direct",
                )
            )
            focused_content = str(focused.get("content") or "")
            cases.append(
                _case_result(
                    f"focus_budget_{iteration}",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    payload=focused,
                    checks={
                        "focused": focused.get("focused") is True,
                        "has_target": "$0.57/fl oz" in focused_content,
                        "drops_unrelated_tail": "Unrelated filler omega" not in focused_content,
                        "content_within_budget": len(focused_content) <= 220,
                        "output_token_efficient": len(json.dumps(focused, sort_keys=True)) <= 1800,
                    },
                )
            )

        started = time.perf_counter()
        invalid = json.loads(await fetch_web_page("file:///tmp/not-web", backend="direct"))
        invalid_checks = {
            "reports_error": "error" in invalid,
            "mentions_http": "http://" in str(invalid.get("error") or ""),
            "output_token_efficient": len(json.dumps(invalid, sort_keys=True)) <= 400,
        }
        cases.append(
            {
                "name": "invalid_scheme_error",
                "passed": all(invalid_checks.values()),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "output_chars": len(json.dumps(invalid, sort_keys=True)),
                "content_chars": 0,
                "fetch_backend": None,
                "checks": invalid_checks,
            }
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    return json.dumps(
        {
            "benchmark": "st web deterministic fetch",
            "deterministic_goal": (
                "all semantic extraction checks pass and benchmark payloads stay within fixed char budgets"
            ),
            "iterations": iterations,
            "max_chars": max_chars,
            "case_count": len(cases),
            "passed": all(bool(case["passed"]) for case in cases),
            "max_output_chars": max(int(case["output_chars"]) for case in cases),
            "max_elapsed_ms": max(float(case["elapsed_ms"]) for case in cases),
            "cases": cases,
        },
        indent=2,
        sort_keys=True,
    )
