# Fix: Uvicorn 100% CPU Spin

**Priority:** HIGH | **Type:** bug

## Problem

agent-hub uvicorn process spins at 100% CPU during idle periods. Observed:
- Normal API calls until ~10:38
- 7 minutes of silence in logs BUT 100% CPU
- Process consumed 25+ minutes of CPU time
- No visible activity - internal spin

## Likely Cause: google-genai SDK AFC

Logs show `"AFC is enabled with max remote calls: 10"` after every Gemini request. AFC (Automatic Function Calling) can trigger internal loops.

Possible failure modes:
1. **Leaked future/coroutine** from AFC processing
2. **Internal polling loop** stuck waiting
3. **Retry loop** without backoff after failed AFC call

## Investigation Steps

### 1. Check current SDK version
```bash
cd /home/kasadis/agent-hub/backend
source .venv/bin/activate
pip show google-genai
```

### 2. Check for AFC-related issues in SDK changelog
```bash
pip index versions google-genai 2>/dev/null || pip install google-genai --upgrade --dry-run
```

### 3. Disable AFC if not needed

In `app/adapters/gemini.py`, update the config:

```python
config = types.GenerateContentConfig(
    temperature=temperature,
    max_output_tokens=max_tokens,
    # Disable AFC to prevent internal loops
    automatic_function_calling=types.AutomaticFunctionCallingConfig(
        disable=True
    ),
)
```

### 4. Add CPU watchdog

Create `app/services/watchdog.py`:

```python
"""CPU watchdog to detect runaway processes."""

import asyncio
import logging
import os
import signal

import psutil

logger = logging.getLogger(__name__)

class CPUWatchdog:
    def __init__(
        self,
        threshold_percent: float = 80.0,
        duration_seconds: int = 60,
        check_interval: int = 10,
    ):
        self.threshold = threshold_percent
        self.duration = duration_seconds
        self.interval = check_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._high_cpu_start: float | None = None
        self._process = psutil.Process(os.getpid())

    async def _monitor_loop(self) -> None:
        while self._running:
            try:
                cpu_percent = self._process.cpu_percent(interval=1)

                if cpu_percent > self.threshold:
                    if self._high_cpu_start is None:
                        self._high_cpu_start = asyncio.get_event_loop().time()
                        logger.warning(f"CPU spike detected: {cpu_percent:.1f}%")
                    else:
                        duration = asyncio.get_event_loop().time() - self._high_cpu_start
                        if duration > self.duration:
                            logger.error(
                                f"CPU > {self.threshold}% for {duration:.0f}s - triggering restart"
                            )
                            os.kill(os.getpid(), signal.SIGTERM)
                else:
                    if self._high_cpu_start is not None:
                        logger.info("CPU returned to normal")
                    self._high_cpu_start = None

            except Exception as e:
                logger.error(f"Watchdog error: {e}")

            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("CPU watchdog started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
```

Add to `app/main.py` startup:

```python
from app.services.watchdog import CPUWatchdog

watchdog = CPUWatchdog(threshold_percent=80.0, duration_seconds=60)

@app.on_event("startup")
async def startup():
    watchdog.start()
    # ... existing startup

@app.on_event("shutdown")
async def shutdown():
    await watchdog.stop()
    # ... existing shutdown
```

### 5. Add event loop blocking detection

In `app/main.py`:

```python
import asyncio

def setup_slow_callback_logger(threshold_ms: float = 100):
    """Log warning when event loop callbacks take too long."""
    loop = asyncio.get_event_loop()
    original_run = loop._run_once

    def instrumented_run():
        start = loop.time()
        original_run()
        duration = (loop.time() - start) * 1000
        if duration > threshold_ms:
            logger.warning(f"Event loop blocked for {duration:.0f}ms")

    loop._run_once = instrumented_run
```

### 6. Apply KillMode fix (same as celery)

Update `~/.config/systemd/user/agent-hub-backend.service`:

```ini
[Service]
# ... existing config ...

# ZOMBIE PREVENTION
KillMode=control-group
KillSignal=SIGTERM
TimeoutStopSec=30
```

Then:
```bash
systemctl --user daemon-reload
systemctl --user restart agent-hub-backend
```

## Verification

```bash
# Monitor CPU after restart
watch -n 5 'ps aux | grep agent-hub.*uvicorn | grep -v grep'

# Check for high CPU
top -bn1 | grep uvicorn

# Check systemd properly tracks process
systemctl --user status agent-hub-backend
```

## Success Criteria

- [ ] No 100% CPU during idle periods
- [ ] AFC disabled or properly configured
- [ ] Watchdog alerts on sustained high CPU
- [ ] KillMode=control-group applied
- [ ] Event loop blocking detection in place

---

**Start command:** `Continue from tasks/cpu-spin-investigation.md`
