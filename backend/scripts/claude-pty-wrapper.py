#!/usr/bin/env python3
"""
Claude CLI PTY wrapper for headless/service environments.
Fixes: https://github.com/anthropics/claude-code/issues/9026

Creates a pseudo-terminal for the Claude CLI while forwarding
stdin/stdout and stripping terminal escape sequences.

Usage: claude-pty-wrapper.py [claude args...]
"""

import contextlib
import os
import pty
import re
import select
import shutil
import signal
import sys
from pathlib import Path

CLAUDE_CLI = os.environ.get("CLAUDE_CLI_PATH") or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
BUFFER_SIZE = 4096
DRAIN_TIMEOUT = 0.01
SELECT_TIMEOUT = 0.1

# Regex to strip ANSI escape sequences
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[<>=]")


def strip_ansi(data: bytes) -> bytes:
    """Strip ANSI escape sequences from bytes."""
    try:
        text = data.decode("utf-8", errors="replace")
        cleaned = ANSI_ESCAPE.sub("", text)
        return cleaned.encode("utf-8")
    except Exception:
        return data


def run_child(master_fd: int, slave_fd: int, args: list) -> None:
    """Set up PTY and exec the child process (runs in forked child)."""
    os.close(master_fd)
    os.setsid()
    os.dup2(slave_fd, 0)
    os.dup2(slave_fd, 1)
    os.dup2(slave_fd, 2)
    if slave_fd > 2:
        os.close(slave_fd)
    os.execv(CLAUDE_CLI, args)
    os._exit(1)


def write_cleaned(data: bytes, stdout_fd: int) -> None:
    """Strip ANSI from data and write to stdout if non-empty."""
    cleaned = strip_ansi(data)
    if cleaned:
        os.write(stdout_fd, cleaned)


def drain_master(master_fd: int, stdout_fd: int) -> None:
    """Read all remaining output from master_fd and forward to stdout."""
    try:
        while True:
            r, _, _ = select.select([master_fd], [], [], DRAIN_TIMEOUT)
            if master_fd not in r:
                break
            data = os.read(master_fd, BUFFER_SIZE)
            if not data:
                break
            write_cleaned(data, stdout_fd)
    except OSError:
        pass


def get_exit_code(status: int) -> int:
    """Extract exit code from waitpid status."""
    return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1


def handle_stdin(master_fd: int) -> None:
    """Forward stdin data to master PTY fd."""
    try:
        data = os.read(sys.stdin.fileno(), BUFFER_SIZE)
        if data:
            os.write(master_fd, data)
    except (OSError, BlockingIOError):
        pass


def handle_master_output(master_fd: int, stdout_fd: int) -> bool:
    """Read from master PTY and forward cleaned output to stdout. Returns False on error."""
    try:
        data = os.read(master_fd, BUFFER_SIZE)
        if data:
            write_cleaned(data, stdout_fd)
            sys.stdout.flush()
        return True
    except OSError:
        return False


def check_child_done(pid: int, master_fd: int, stdout_fd: int) -> tuple[bool, int]:
    """Check if child process has exited. Returns (done, exit_code)."""
    try:
        result = os.waitpid(pid, os.WNOHANG)
        if result[0] == 0:
            return False, 0
        exit_code = get_exit_code(result[1])
        drain_master(master_fd, stdout_fd)
        return True, exit_code
    except ChildProcessError:
        return True, 0


def dispatch_readable(readable: list, master_fd: int, stdout_fd: int) -> bool:
    """Handle readable fds; returns False if master_fd encountered an error."""
    for fd in readable:
        if fd == sys.stdin:
            handle_stdin(master_fd)
        elif fd == master_fd and not handle_master_output(master_fd, stdout_fd):
            return False
    return True


def io_loop(pid: int, master_fd: int) -> int:
    """Forward I/O between stdin/stdout and the child PTY. Returns exit code."""
    stdout_fd = sys.stdout.fileno()
    exit_code = 0

    while True:
        done, exit_code = check_child_done(pid, master_fd, stdout_fd)
        if done:
            break

        try:
            readable, _, _ = select.select([sys.stdin, master_fd], [], [], SELECT_TIMEOUT)
        except (OSError, InterruptedError, ValueError):
            continue

        if not dispatch_readable(readable, master_fd, stdout_fd):
            break

    return exit_code


def main():
    args = [CLAUDE_CLI, *sys.argv[1:]]

    master_fd, slave_fd = pty.openpty()

    pid = os.fork()
    if pid == 0:
        run_child(master_fd, slave_fd, args)

    # Parent process
    os.close(slave_fd)
    signal.signal(signal.SIGCHLD, lambda _s, _f: None)

    exit_code = 0
    try:
        exit_code = io_loop(pid, master_fd)
    except KeyboardInterrupt:
        os.kill(pid, signal.SIGTERM)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)
        exit_code = 130
    finally:
        with contextlib.suppress(OSError):
            os.close(master_fd)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
