import time
from typing import Any, cast

from fastapi import Response


def build_prometheus_metrics(metrics_data: dict[str, Any], start_time: float, thrashing_events: int, circuit_trips: int, circuit_status: dict[str, Any]) -> Response:
    """Build Prometheus format output."""
    
    circuit_state_lines: list[str] = []
    for p, info in circuit_status.items():
        state_val = {"closed": 0, "half_open": 1, "open": 2}.get(cast(str, info["state"]), -1)
        circuit_state_lines.append(f'agent_hub_circuit_state{{provider="{p}"}} {state_val}')

    lines = [
        f"# HELP agent_hub_requests_total Total number of requests\n# TYPE agent_hub_requests_total counter\nagent_hub_requests_total {metrics_data['request_count']}\n",
        f"# HELP agent_hub_errors_total Total number of errors\n# TYPE agent_hub_errors_total counter\nagent_hub_errors_total {metrics_data['error_count']}\n",
        f"# HELP agent_hub_active_sessions Number of active sessions\n# TYPE agent_hub_active_sessions gauge\nagent_hub_active_sessions {metrics_data['active_sessions']}\n",
        f"# HELP agent_hub_request_latency_ms Request latency histogram\n# TYPE agent_hub_request_latency_ms summary\nagent_hub_request_latency_ms_sum {metrics_data['latency_sum_ms']}\nagent_hub_request_latency_ms_count {metrics_data['latency_count']}\n",
        f"# HELP agent_hub_uptime_seconds Service uptime in seconds\n# TYPE agent_hub_uptime_seconds gauge\nagent_hub_uptime_seconds {time.time() - start_time:.1f}\n",
        f"# HELP agent_hub_thrashing_events_total Total thrashing detection events\n# TYPE agent_hub_thrashing_events_total counter\nagent_hub_thrashing_events_total {thrashing_events}\n",
        f"# HELP agent_hub_circuit_breaker_trips_total Total circuit breaker trips\n# TYPE agent_hub_circuit_breaker_trips_total counter\nagent_hub_circuit_breaker_trips_total {circuit_trips}\n",
        "# HELP agent_hub_circuit_state Circuit breaker state (0=closed, 1=half_open, 2=open)\n# TYPE agent_hub_circuit_state gauge",
        *circuit_state_lines,
        "",
    ]
    return Response(content="\n".join(lines), media_type="text/plain; version=0.0.4; charset=utf-8")
