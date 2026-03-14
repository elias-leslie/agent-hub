"""Tests for _sensitive_content module."""

from __future__ import annotations

import json

import pytest

from app.services.tools._sensitive_content import (
    _DEFAULT_BLOCK_REASON,
    _parse_scan_output,
    scan_runtime_sensitive_content,
)


class TestParseScanOutput:
    def test_extracts_finding_description_and_path(self):
        payload = {"findings": [{"description": "API key detected", "path": "/tmp/secret.py"}]}
        stdout = json.dumps(payload).encode()
        assert _parse_scan_output(stdout, b"", "/fallback") == "API key detected (/tmp/secret.py)"

    def test_uses_default_description_when_finding_missing_description(self):
        payload = {"findings": [{"path": "/tmp/secret.py"}]}
        stdout = json.dumps(payload).encode()
        assert _parse_scan_output(stdout, b"", "/fallback") == f"{_DEFAULT_BLOCK_REASON} (/tmp/secret.py)"

    def test_uses_fallback_path_when_finding_missing_path(self):
        payload = {"findings": [{"description": "API key detected"}]}
        stdout = json.dumps(payload).encode()
        assert _parse_scan_output(stdout, b"", "/fallback") == "API key detected (/fallback)"

    def test_extracts_summary_when_no_findings(self):
        payload = {"summary": "3 secrets found"}
        stdout = json.dumps(payload).encode()
        assert _parse_scan_output(stdout, b"", "/fallback") == "3 secrets found"

    def test_falls_back_to_stderr_first_line(self):
        stderr = b"Error: scan failed\nDetails: timeout"
        assert _parse_scan_output(b"", stderr, "/fallback") == "Error: scan failed"

    def test_returns_default_reason_when_no_output(self):
        assert _parse_scan_output(b"", b"", "/fallback") == _DEFAULT_BLOCK_REASON

    def test_handles_invalid_json_gracefully(self):
        assert _parse_scan_output(b"not json", b"", "/fallback") == _DEFAULT_BLOCK_REASON


class TestScanRuntimeSensitiveContent:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_path_and_content(self):
        assert await scan_runtime_sensitive_content("", "") is None

    @pytest.mark.asyncio
    async def test_returns_none_when_scanner_missing(self, monkeypatch):
        from app.services.tools import _sensitive_content

        monkeypatch.setattr(_sensitive_content, "_SCANNER", _sensitive_content.Path("/nonexistent/scanner.py"))
        result = await scan_runtime_sensitive_content("/tmp/test.py", "content")
        assert result is None
