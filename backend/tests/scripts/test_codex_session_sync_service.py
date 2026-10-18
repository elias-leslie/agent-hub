from pathlib import Path

SYSTEMD_DIR = Path(__file__).resolve().parents[3] / "scripts" / "systemd"


def test_frequent_scan_and_slower_inactive_close_are_separate_units() -> None:
    scan = (SYSTEMD_DIR / "codex-session-sync.service").read_text(encoding="utf-8")
    close = (SYSTEMD_DIR / "codex-session-close-inactive.service").read_text(encoding="utf-8")

    assert "codex-session-sync.py --scan\n" in scan
    assert "--close-inactive" not in scan
    assert "codex-session-sync.py --scan --close-inactive\n" in close
    for service in (scan, close):
        assert "__PROJECT_ROOT__/backend/.venv/bin/python __PROJECT_ROOT__/scripts/codex-session-sync.py" in service
        assert "--verbose" not in service
        assert "StandardOutput=journal" in service
        assert "StandardError=journal" in service
    assert "OnCalendar=*:0/2" in (SYSTEMD_DIR / "codex-session-sync.timer").read_text()
    assert "OnCalendar=*:1/5" in (
        SYSTEMD_DIR / "codex-session-close-inactive.timer"
    ).read_text()
