"""Tests for _sensitive_content module."""

from __future__ import annotations

import pytest

from app.services.tools._sensitive_content import secret_block_reason

AWS_KEY = "AKIA" + "ABCDEFGHIJ234567"
SLACK_TOKEN = "xoxb-" + "1234567890-abcdefghij"
PEM_HEADER = "-----BEGIN RSA PRIVATE" + " KEY-----"
PEM_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" + "a" * 12


class TestSecretBlockReason:
    def test_returns_none_for_empty_content(self):
        assert secret_block_reason("", "") is None
        assert secret_block_reason("/tmp/a.py", "") is None

    def test_returns_none_for_ordinary_content(self):
        assert secret_block_reason("/tmp/a.py", "token = os.environ['TOKEN']\n") is None

    def test_blocks_floor_credential_and_names_kind_and_path(self):
        reason = secret_block_reason("/tmp/a.py", f"key = '{AWS_KEY}'\n")
        assert reason == "content contains a credential (aws access key) (/tmp/a.py)"

    @pytest.mark.parametrize(
        ("secret", "kind"),
        [
            ("gh" + "p_" + "A1b2C3d4" * 5, "github token"),
            ("github_pat_" + "11ABCDEFG0" + "a1B2c3D4e5" * 3, "github token"),
            ("glpat-" + "abcdefghij0123456789", "gitlab token"),
            ("sk_live_" + "abcdefghij0123456789", "stripe live key"),
            (PEM_HEADER + "\n" + PEM_BODY + "\n", "private key"),
        ],
    )
    def test_blocks_each_floor_shape(self, secret: str, kind: str):
        reason = secret_block_reason("a.txt", secret)
        assert reason is not None
        assert kind in reason

    def test_bare_private_key_header_is_not_key_material(self):
        # The floor only blocks key material; code or docs naming the header still write.
        assert secret_block_reason("a.md", f"Look for `{PEM_HEADER}` in the file.\n") is None

    def test_lists_each_kind_found(self):
        reason = secret_block_reason("cfg.env", f"A={AWS_KEY}\nB={SLACK_TOKEN}\n")
        assert reason is not None
        assert "aws access key" in reason
        assert "slack token" in reason

    @pytest.mark.parametrize(
        "marker",
        ["# sensitive-scan:allow", "// sensitive-scan:allow private-key-header"],
    )
    def test_allow_marker_does_not_silence_block(self, marker: str):
        assert secret_block_reason("a.py", f"key = '{AWS_KEY}'  {marker}\n") is not None

    def test_repo_allowlist_file_is_not_honored(self, tmp_path):
        (tmp_path / ".sensitive-scan-allowlist").write_text("AKIA.*\n")
        assert secret_block_reason(str(tmp_path / "a.py"), f"key = '{AWS_KEY}'\n") is not None
