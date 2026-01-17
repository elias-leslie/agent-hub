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
import signal
import sys

CLAUDE_CLI = os.environ.get("CLAUDE_CLI_PATH", "/home/kasadis/.local/bin/claude")
BUFFER_SIZE = 4096

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


def main():
    args = [CLAUDE_CLI, *sys.argv[1:]]

    # Create pseudo-terminal
    master_fd, slave_fd = pty.openpty()

    pid = os.fork()
    if pid == 0:
        # Child process - run claude with PTY as controlling terminal
        os.close(master_fd)
        os.setsid()

        # Make slave the controlling terminal
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)

        if slave_fd > 2:
            os.close(slave_fd)

        os.execv(CLAUDE_CLI, args)
        os._exit(1)

    # Parent process
    os.close(slave_fd)

    def handle_sigchld(_signum, _frame):
        pass

    signal.signal(signal.SIGCHLD, handle_sigchld)

    exit_code = 0
    try:
        while True:
            # Check if child still running
            try:
                result = os.waitpid(pid, os.WNOHANG)
                if result[0] != 0:
                    exit_code = os.WEXITSTATUS(result[1]) if os.WIFEXITED(result[1]) else 1
                    # Drain remaining output
                    try:
                        while True:
                            r, _, _ = select.select([master_fd], [], [], 0.01)
                            if master_fd not in r:
                                break
                            data = os.read(master_fd, BUFFER_SIZE)
                            if not data:
                                break
                            cleaned = strip_ansi(data)
                            if cleaned:
                                os.write(sys.stdout.fileno(), cleaned)
                    except OSError:
                        pass
                    break
            except ChildProcessError:
                break

            # Wait for data
            try:
                readable, _, _ = select.select([sys.stdin, master_fd], [], [], 0.1)
            except (OSError, InterruptedError, ValueError):
                continue

            for fd in readable:
                if fd == sys.stdin:
                    try:
                        data = os.read(sys.stdin.fileno(), BUFFER_SIZE)
                        if data:
                            os.write(master_fd, data)
                        else:
                            # EOF on stdin - close master write
                            pass
                    except (OSError, BlockingIOError):
                        pass
                elif fd == master_fd:
                    try:
                        data = os.read(master_fd, BUFFER_SIZE)
                        if data:
                            cleaned = strip_ansi(data)
                            if cleaned:
                                os.write(sys.stdout.fileno(), cleaned)
                                sys.stdout.flush()
                    except OSError:
                        break

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
