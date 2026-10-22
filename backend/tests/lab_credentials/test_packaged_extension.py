"""The pinned deployable wheel must carry the reviewed ST command source."""

from __future__ import annotations

import hashlib
import tomllib
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


def test_backend_pins_the_current_complete_extension_wheel():
    root = Path(__file__).resolve().parents[3]
    package = tomllib.loads((root / "packages/st-cli/pyproject.toml").read_text())
    backend = tomllib.loads((root / "backend/pyproject.toml").read_text())
    lock = tomllib.loads((root / "backend/uv.lock").read_text())
    version = package["project"]["version"]
    source = backend["tool"]["uv"]["sources"]["agent-hub-st"]["path"]
    wheel = (root / "backend" / source).resolve()

    assert f"agent-hub-st=={version}" in backend["project"]["dependencies"]
    pinned = next(item for item in lock["package"] if item["name"] == "agent-hub-st")
    assert pinned["version"] == version
    assert pinned["source"] == {"path": source}
    assert pinned["wheels"] == [{
        "filename": wheel.name,
        "hash": "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }]
    with ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read(f"agent_hub_st-{version}.dist-info/METADATA"))
        assert metadata["Version"] == version
        assert "agent-hub-st = agent_hub_st.__main__:main" in archive.read(
            f"agent_hub_st-{version}.dist-info/entry_points.txt",
        ).decode()
        package_root = root / "packages/st-cli"
        for path in sorted((package_root / "agent_hub_st").rglob("*.py")):
            assert archive.read(path.relative_to(package_root).as_posix()) == path.read_bytes()
