from __future__ import annotations

import os
import subprocess
from pathlib import Path

DB_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "db.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _write_index_yaml(path: Path, project_id: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".index.yaml").write_text(f"project: {project_id}\n")


def _fake_env(tmp_path: Path, env_lines: list[str]) -> dict[str, str]:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".env.local").write_text("\n".join(env_lines) + "\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "st", "#!/usr/bin/env bash\nexit 1\n")

    env = os.environ.copy()
    for key in list(env):
        if key == "DATABASE_URL" or key.endswith("_DB_URL") or key.endswith("_DATABASE_URL"):
            env.pop(key)
    env["HOME"] = str(fake_home)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["ST_WORKSPACES_ROOT"] = str(tmp_path / "workspaces")
    return env


def test_db_query_uses_dynamic_aux_project_db_url(tmp_path: Path) -> None:
    env = _fake_env(
        tmp_path,
        ["TEST2_DB_URL=postgresql://test2_user@localhost:5432/test2"],
    )

    _write_executable(
        tmp_path / "bin" / "psql",
        """#!/usr/bin/env bash
printf 'URL=%s\n' "$1"
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    -c)
      shift
      printf 'QUERY=%s\n' "$1"
      ;;
  esac
  shift || true
done
""",
    )

    result = subprocess.run(
        [str(DB_SCRIPT), "-P", "test2", "query", "-t", "SELECT current_database()"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "URL=postgresql://test2_user@localhost:5432/test2" in result.stdout
    assert "QUERY=SELECT current_database()" in result.stdout


def test_db_query_unknown_aux_project_mentions_expected_env_var(tmp_path: Path) -> None:
    env = _fake_env(tmp_path, [])
    _write_executable(tmp_path / "bin" / "psql", "#!/usr/bin/env bash\nexit 0\n")

    result = subprocess.run(
        [str(DB_SCRIPT), "-P", "test2", "query", "-t", "SELECT 1"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Set TEST2_DB_URL" in result.stderr


def test_db_migrate_uses_dynamic_project_backend_alembic_dir(tmp_path: Path) -> None:
    env = _fake_env(
        tmp_path,
        ["DEMO_DB_URL=postgresql://demo_user@localhost:5432/demo"],
    )
    workspaces_root = Path(env["ST_WORKSPACES_ROOT"])
    backend_dir = workspaces_root / "projects" / "demo" / "backend"
    (backend_dir / "alembic").mkdir(parents=True)

    log_file = tmp_path / "alembic.log"
    env["FAKE_ALEMBIC_LOG"] = str(log_file)
    _write_executable(
        tmp_path / "bin" / "alembic",
        """#!/usr/bin/env bash
printf 'PWD=%s DATABASE_URL=%s DEMO_DB_URL=%s ARGS=%s\n' "$PWD" "$DATABASE_URL" "$DEMO_DB_URL" "$*" >> "$FAKE_ALEMBIC_LOG"
case "$1" in
  current|heads)
    printf 'abc123 (head)\n'
    ;;
  *)
    printf 'ok\n'
    ;;
esac
""",
    )

    result = subprocess.run(
        [str(DB_SCRIPT), "-P", "demo", "migrate", "status"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    log_output = log_file.read_text()
    assert f"PWD={backend_dir}" in log_output
    assert "DATABASE_URL=postgresql://demo_user@localhost:5432/demo" in log_output
    assert "DEMO_DB_URL=postgresql://demo_user@localhost:5432/demo" in log_output
    assert "ARGS=current" in log_output
    assert "ARGS=heads" in log_output


def test_db_migrate_prefers_local_index_context_root(tmp_path: Path) -> None:
    env = _fake_env(
        tmp_path,
        ["DEMO_DB_URL=postgresql://demo_user@localhost:5432/demo"],
    )
    repo_dir = tmp_path / "lane-demo"
    backend_dir = repo_dir / "backend"
    (backend_dir / "alembic").mkdir(parents=True)
    _write_index_yaml(repo_dir, "demo")

    log_file = tmp_path / "local-alembic.log"
    env["FAKE_ALEMBIC_LOG"] = str(log_file)
    _write_executable(
        tmp_path / "bin" / "alembic",
        """#!/usr/bin/env bash
printf 'PWD=%s DATABASE_URL=%s DEMO_DB_URL=%s ARGS=%s\n' "$PWD" "$DATABASE_URL" "$DEMO_DB_URL" "$*" >> "$FAKE_ALEMBIC_LOG"
case "$1" in
  current|heads)
    printf 'abc123 (head)\n'
    ;;
  *)
    printf 'ok\n'
    ;;
esac
""",
    )

    result = subprocess.run(
        [str(DB_SCRIPT), "migrate", "status"],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    log_output = log_file.read_text()
    assert f"PWD={backend_dir}" in log_output
    assert "DATABASE_URL=postgresql://demo_user@localhost:5432/demo" in log_output
    assert "DEMO_DB_URL=postgresql://demo_user@localhost:5432/demo" in log_output
