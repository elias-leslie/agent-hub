from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from agent_hub_st import skills
from typer.testing import CliRunner

runner = CliRunner()


def test_dirty_canonical_source_is_not_link_drift(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir()
    counts = {"ok": 1, "missing": 0, "dangling": 0, "wrong-target": 0, "real-copy": 0, "unmanaged": 0}
    with (
        patch.object(skills, "_canon", return_value=tmp_path),
        patch.object(skills, "_canon_dirty", return_value=True),
        patch.object(skills, "_expected", return_value=[]),
        patch.object(skills, "_unmanaged", return_value=[]),
        patch.object(skills, "_scan", return_value=counts),
    ):
        doctor = runner.invoke(skills.app, ["doctor"])
        status = runner.invoke(skills.app, ["status"])
    assert doctor.exit_code == 1
    assert "0 link issue(s)" in doctor.output
    assert "Review and commit" in doctor.output
    assert "--adopt" not in doctor.output
    assert "skills DIRTY:" in status.output


def test_doctor_only_recommends_adopt_for_real_copies(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir()
    with (
        patch.object(skills, "_canon", return_value=tmp_path),
        patch.object(skills, "_canon_dirty", return_value=False),
        patch.object(skills, "_expected", return_value=[("codex", tmp_path / "copy", tmp_path / "target")]),
        patch.object(skills, "_classify", return_value="real-copy"),
        patch.object(skills, "_unmanaged", return_value=[]),
    ):
        result = runner.invoke(skills.app, ["doctor"])
    assert result.exit_code == 1
    assert "--adopt" in result.output


def test_load_harnesses_with_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.toml"
    manifest.write_text("""[harness.claude]
skills_dir = "~/.claude/skills"
commands_dir = "~/.claude/commands"
exclude = []

[harness.codex]
skills_dir = "~/.codex/skills"
exclude = []

[harness.gemini]
skills_dir = "~/.gemini/config/skills"
exclude = []

[profile.default]
exclude = []
""")
    harnesses = skills._load_harnesses(tmp_path)
    names = [h.name for h in harnesses]
    assert names == ["claude", "codex", "gemini"]
    gemini = next(h for h in harnesses if h.name == "gemini")
    assert gemini.skills_dir == Path("~/.gemini/config/skills").expanduser()
    assert gemini.commands_dir is None
    assert gemini.exclude == []


def test_skill_inclusion_and_exclusion_match_manifest_scope(tmp_path: Path) -> None:
    for name in ("_shared", "design", "copy", "other"):
        (tmp_path / "skills" / name).mkdir(parents=True)
    (tmp_path / "commands").mkdir()
    (tmp_path / "manifest.toml").write_text(f"""
[harness.all]
skills_dir = "{tmp_path / 'all'}"
exclude = []

[harness.narrow]
skills_dir = "{tmp_path / 'narrow'}"
include = ["design", "copy"]
exclude = ["copy"]

[harness.empty]
skills_dir = "{tmp_path / 'empty'}"
include = []
exclude = []

[profile.backend]
exclude = ["design"]

[profile.default]
exclude = []
""")

    def names(profile: str | None = None) -> dict[str, set[str]]:
        selected: dict[str, set[str]] = {}
        for harness, destination, _ in skills._expected(tmp_path, profile_name=profile):
            selected.setdefault(harness, set()).add(destination.name)
        return selected

    assert names() == {
        "all": {"_shared", "design", "copy", "other"},
        "narrow": {"_shared", "design"},
        "empty": {"_shared"},
    }
    assert names("backend") == {
        "all": {"_shared", "copy", "other"},
        "narrow": {"_shared"},
        "empty": {"_shared"},
    }

    (tmp_path / "manifest.toml").write_text(f"""
[harness.narrow]
skills_dir = "{tmp_path / 'narrow'}"
include = ["missing"]

[profile.default]
exclude = []
""")
    with pytest.raises(ValueError, match="Unknown skills"):
        skills._load_harnesses(tmp_path)


def test_load_harnesses_fallback(tmp_path: Path) -> None:
    harnesses = skills._load_harnesses(tmp_path)
    names = [h.name for h in harnesses]
    assert "claude" in names
    assert "codex" in names
    assert "gemini" in names


def test_classify_states(tmp_path: Path) -> None:
    target = tmp_path / "canon" / "skill-a"
    target.mkdir(parents=True)

    # ok
    dest_ok = tmp_path / "dest_ok"
    dest_ok.symlink_to(target)
    assert skills._classify(dest_ok, target) == "ok"

    # missing
    dest_missing = tmp_path / "dest_missing"
    assert skills._classify(dest_missing, target) == "missing"

    # real-copy
    dest_real = tmp_path / "dest_real"
    dest_real.mkdir()
    assert skills._classify(dest_real, target) == "real-copy"

    # wrong-target
    other_target = tmp_path / "other"
    other_target.mkdir()
    dest_wrong = tmp_path / "dest_wrong"
    dest_wrong.symlink_to(other_target)
    assert skills._classify(dest_wrong, target) == "wrong-target"


def test_unmanaged_detection(tmp_path: Path) -> None:
    canon = tmp_path / "canon"
    (canon / "skills" / "skill-a").mkdir(parents=True)
    test_harness = tmp_path / "test_harness"
    test_harness.mkdir(parents=True)
    (canon / "manifest.toml").write_text(f"[harness.test]\nskills_dir = \"{test_harness}\"\n[profile.default]\nexclude = []\n")
    (test_harness / "skill-a").symlink_to(canon / "skills" / "skill-a")
    (test_harness / "unmanaged-real").mkdir()
    (test_harness / ".system").mkdir()

    unmanaged = skills._unmanaged(canon)
    assert len(unmanaged) == 1
    hname, path, kind = unmanaged[0]
    assert hname == "test"
    assert path.name == "unmanaged-real"
    assert kind == "unmanaged-copy"


def test_doctor_and_status(tmp_path: Path) -> None:
    canon = tmp_path / "canon"
    (canon / "skills" / "_shared").mkdir(parents=True)
    (canon / "skills" / "skill-a").mkdir(parents=True)
    test_harness = tmp_path / "test_harness"
    test_harness.mkdir(parents=True)
    (canon / "manifest.toml").write_text(f"[harness.test]\nskills_dir = \"{test_harness}\"\n[profile.default]\nexclude = []\n")
    (test_harness / "_shared").symlink_to(canon / "skills" / "_shared")
    (test_harness / "skill-a").symlink_to(canon / "skills" / "skill-a")

    with patch.object(skills, "_canon", return_value=canon), patch.object(skills, "_canon_dirty", return_value=False):
        res = runner.invoke(skills.app, ["status"])
        assert res.exit_code == 0
        assert "skills ok" in res.stdout

        res_doc = runner.invoke(skills.app, ["doctor"])
        assert res_doc.exit_code == 0
        assert "ok: all skills materialized" in res_doc.stdout


def test_audit_single_skill_validation(tmp_path: Path) -> None:
    skill_dir = tmp_path / "valid-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: valid-skill
description: Use when testing the valid skill audit capabilities in summitflow.
---

# Valid Skill Title

Step by step procedures.
""")
    res = skills._audit_single_skill(skill_dir)
    assert res["status"] == "ok"
    assert len(res["errors"]) == 0

    # Test broken relative link
    (skill_dir / "SKILL.md").write_text("""---
name: valid-skill
description: Use when testing the valid skill audit capabilities in summitflow.
---

Check [documentation](references/missing.md) here.
""")
    res2 = skills._audit_single_skill(skill_dir)
    assert res2["status"] == "fail"
    assert any("Broken relative markdown link" in e for e in res2["errors"])


def test_parse_github_source() -> None:
    owner, repo, ref, subpath = skills._parse_github_source("owner/my-repo")
    assert owner == "owner"
    assert repo == "my-repo"
    assert ref == "main"
    assert subpath is None

    owner, repo, ref, subpath = skills._parse_github_source("https://github.com/my-org/awesome-skills/tree/develop/skills/docker")
    assert owner == "my-org"
    assert repo == "awesome-skills"
    assert ref == "develop"
    assert subpath == "skills/docker"


def test_create_skill_scaffold(tmp_path: Path) -> None:
    canon = tmp_path / "canon"
    (canon / "skills").mkdir(parents=True)
    (canon / "manifest.toml").write_text(
        f'[harness.test]\nskills_dir = "{tmp_path / "harness"}"\ninclude = []\n[profile.default]\n'
    )
    with patch.object(skills, "_canon", return_value=canon):
        res = runner.invoke(skills.app, ["create", "test-helper", "--description", "Use for test helper automated execution routines."])
        assert res.exit_code == 0
        skill_file = canon / "skills" / "test-helper" / "SKILL.md"
        assert skill_file.exists()
        content = skill_file.read_text()
        assert "name: test-helper" in content
        assert "Use for test helper" in content


@pytest.fixture
def distribution_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """Self-contained manifest and destination roots for CLI contracts."""
    canon = tmp_path / "canon"
    home = tmp_path / "home"
    project = tmp_path / "project"
    for name in ("_shared", "general", "domain", "profiled", "copy"):
        (canon / "skills" / name).mkdir(parents=True)
    (canon / "commands").mkdir()
    (canon / "commands" / "helper.md").write_text("canonical command")
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ST_SKILLS_PROFILE", "default")
    _write_distribution(canon, project)
    return canon, home, project


def _write_distribution(canon: Path, project: Path) -> None:
    (canon / "manifest.toml").write_text(f"""[harness.global]
skills_dir = "~/.codex/skills"
commands_dir = "~/.claude/commands"
include = ["general"]

[harness.project]
skills_dir = "{project / '.claude/skills'}"
include = ["domain", "profiled", "copy"]
exclude = ["copy"]

[harness.empty]
skills_dir = "{project / '.agents/skills'}"
include = []

[profile.default]
exclude = []

[profile.backend]
exclude = ["profiled"]
""")


def test_cli_global_project_expectations_match_distribution_scope(
    distribution_roots: tuple[Path, Path, Path],
) -> None:
    canon, home, project = distribution_roots
    for profile, project_names in (("default", {"_shared", "domain", "profiled"}), ("backend", {"_shared", "domain"})):
        rows = skills._expected(canon, profile_name=profile)
        expected = {
            home / ".codex/skills": {"_shared", "general"},
            home / ".claude/commands": {"helper.md"},
            project / ".claude/skills": project_names,
            project / ".agents/skills": {"_shared"},
        }
        assert {dest for _h, dest, _target in rows} == {
            directory / name for directory, names in expected.items() for name in names
        }
        for _h, dest, target in rows:
            category = "commands" if dest.name == "helper.md" else "skills"
            assert target == canon / category / dest.name


@pytest.mark.parametrize(("manifest", "profile", "error"), [
    ('[harness.test]\nskills_dir = "~/skills"\n[profile.default]\n', "missing", "Unknown skills profile: missing"),
    ('profile = false\n[harness.test]\nskills_dir = "~/skills"\n', "default", "Invalid skills profiles"),
    ('[profile]\ndefault = false\n[harness.test]\nskills_dir = "~/skills"\n', "default", "Invalid skills profile: default"),
    ('[profile.default]\nexclude = "domain"\n[harness.test]\nskills_dir = "~/skills"\n', "default", "Invalid excludes for profile default"),
    ('[profile.default]\nexclude = [1]\n[harness.test]\nskills_dir = "~/skills"\n', "default", "Invalid excludes for profile default"),
    ('[profile.default]\n[harness.test]\nskills_dir = "~/skills"\nexclude = "domain"\n', "default", "Invalid excludes for harness test"),
    ('[profile.default]\n[harness.test]\nskills_dir = "~/skills"\nexclude = [1]\n', "default", "Invalid excludes for harness test"),
    ('[profile.default]\n[harness.test]\nskills_dir = "~/skills"\ninclude = "domain"\n', "default", "Invalid includes for harness test"),
    ('[profile.default]\n[harness.test]\nskills_dir = "~/skills"\ninclude = [1]\n', "default", "Invalid includes for harness test"),
    ('[profile.default]\n[harness.test]\nskills_dir = "~/skills"\ninclude = ["missing"]\n', "default", "Unknown skills in test include list: missing"),
    ('[profile.default]\n[harness.test]\n', "default", "Missing skills_dir for harness test"),
    ('[profile.default]\n[harness.test]\nskills_dir = 1\n', "default", "Missing skills_dir for harness test"),
    ('[profile.default]\n[harness.test]\nskills_dir = "~/skills"\ncommands_dir = false\n', "default", "Invalid commands_dir for harness test"),
    ('harness = false\n[profile.default]\n', "default", "Invalid skills harnesses"),
    ('[harness]\ntest = false\n[profile.default]\n', "default", "Invalid harness test"),
    ('[profile.default]\n', "default", "Skills manifest has no harnesses"),
])
def test_cli_rejects_invalid_manifest_config(
    distribution_roots: tuple[Path, Path, Path], manifest: str, profile: str, error: str,
) -> None:
    canon, _home, _project = distribution_roots
    (canon / "manifest.toml").write_text(manifest)
    with pytest.raises(ValueError, match=error):
        skills._load_harnesses(canon, profile_name=profile)
    with patch.object(skills, "_canon", return_value=canon):
        for command in ("status", "doctor"):
            invoked = runner.invoke(skills.app, [command, "--profile", profile])
            assert invoked.exit_code == 2
            assert error in invoked.output


def test_cli_profile_environment_and_whitespace(
    distribution_roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    canon, _home, _project = distribution_roots
    monkeypatch.setenv("ST_SKILLS_PROFILE", " backend ")
    assert all(dest.name != "profiled" for _h, dest, _target in skills._expected(canon))
    monkeypatch.setenv("ST_SKILLS_PROFILE", "unknown")
    with pytest.raises(ValueError, match="Unknown skills profile: unknown"):
        skills._expected(canon)


def test_cli_rejects_invalid_later_harness(
    distribution_roots: tuple[Path, Path, Path],
) -> None:
    canon, _home, _project = distribution_roots
    with (canon / "manifest.toml").open("a") as manifest:
        manifest.write('\n[harness.invalid]\nskills_dir = "~/invalid"\ninclude = ["missing"]\n')
    with pytest.raises(ValueError, match="Unknown skills in invalid include list: missing"):
        skills._expected(canon)


def test_cli_reports_malformed_manifest(
    distribution_roots: tuple[Path, Path, Path],
) -> None:
    canon, _home, _project = distribution_roots
    (canon / "manifest.toml").write_text("[harness.invalid")
    with patch.object(skills, "_canon", return_value=canon):
        for command in ("status", "doctor"):
            invoked = runner.invoke(skills.app, [command])
            assert invoked.exit_code == 2
            assert "Expected ']'" in invoked.output


@pytest.mark.parametrize("profile", ["", "unknown"])
def test_install_forwards_explicit_invalid_profile_and_failure(
    distribution_roots: tuple[Path, Path, Path], profile: str,
) -> None:
    canon, _home, _project = distribution_roots
    (canon / "install.sh").write_text("#!/bin/bash\nexit 3\n")
    real_run = subprocess.run
    with patch.object(skills, "_canon", return_value=canon), patch.object(skills.subprocess, "run", wraps=real_run) as run:
        result = runner.invoke(skills.app, ["install", "--profile", profile])
    assert result.exit_code == 3
    run.assert_called_once_with(["bash", str(canon / "install.sh"), "--profile", profile])


def test_installer_failure_stops_sync_before_memory_seed(
    distribution_roots: tuple[Path, Path, Path],
) -> None:
    canon, _home, _project = distribution_roots
    (canon / "install.sh").write_text("#!/bin/bash\nexit 11\n")
    real_run = subprocess.run
    with patch.object(skills, "_canon", return_value=canon), patch.object(skills.subprocess, "run", wraps=real_run) as run:
        result = runner.invoke(skills.app, ["sync"])
    assert result.exit_code == 11
    assert "Skills sync failed during install (exit 11)" in result.output
    run.assert_called_once_with(["bash", str(canon / "install.sh")], check=False)


@pytest.mark.parametrize(("failure_step", "returncode", "label"), [(0, 7, "pull"), (1, 3, "install"), (2, 4, "memory seed")])
def test_sync_stops_and_propagates_failed_step(tmp_path: Path, failure_step: int, returncode: int, label: str) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "install.sh").write_text("#!/bin/bash\n")
    responses = [subprocess.CompletedProcess([], 0) for _ in range(failure_step)]
    responses.append(subprocess.CompletedProcess([], returncode))
    with patch.object(skills, "_canon", return_value=tmp_path), patch.object(skills.subprocess, "run", side_effect=responses) as run:
        result = runner.invoke(skills.app, ["sync"])
    assert result.exit_code == returncode
    assert f"Skills sync failed during {label}" in result.output
    assert run.call_count == failure_step + 1
    expected = [
        ["git", "-C", str(tmp_path), "pull", "--ff-only"],
        ["bash", str(tmp_path / "install.sh")],
        ["st", "memory", "seed", str(tmp_path / "skills")],
    ]
    assert [call.args[0] for call in run.call_args_list] == expected[:failure_step + 1]


def test_sync_reports_missing_installer_and_spawn_failure(tmp_path: Path) -> None:
    with patch.object(skills, "_canon", return_value=tmp_path), patch.object(skills.subprocess, "run") as run:
        missing = runner.invoke(skills.app, ["sync"])
        assert missing.exit_code == 2
        assert "install.sh not found" in missing.output
        run.assert_not_called()
    (tmp_path / "install.sh").write_text("#!/bin/bash\n")
    with patch.object(skills, "_canon", return_value=tmp_path), patch.object(skills.subprocess, "run", side_effect=OSError("cannot start installer")) as run:
        failed = runner.invoke(skills.app, ["sync"])
    assert failed.exit_code == 1
    assert "Skills sync failed during install: cannot start installer" in failed.output
    assert run.call_count == 1


def test_sync_runs_all_steps_on_success_without_git(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text("#!/bin/bash\n")
    with patch.object(skills, "_canon", return_value=tmp_path), patch.object(skills.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
        result = runner.invoke(skills.app, ["sync"])
    assert result.exit_code == 0
    assert [call.args[0] for call in run.call_args_list] == [
        ["bash", str(tmp_path / "install.sh")],
        ["st", "memory", "seed", str(tmp_path / "skills")],
    ]


@pytest.mark.parametrize("explicit_include", [True, False])
def test_unmanaged_explicit_scope_coexists_with_native_skills_but_tracks_canonical_conflicts(
    distribution_roots: tuple[Path, Path, Path], tmp_path: Path, explicit_include: bool,
) -> None:
    canon, home, _project = distribution_roots
    if not explicit_include:
        manifest = canon / "manifest.toml"
        manifest.write_text(manifest.read_text().replace('include = ["general"]\n', ''))
    directory = home / ".codex/skills"
    directory.mkdir(parents=True)
    (directory / "native-skill").mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (directory / "native-link").symlink_to(foreign)
    alias = tmp_path / "alias"
    alias.symlink_to(canon / "skills/general")
    (directory / "native-alias").symlink_to(alias)
    (directory / "domain").write_text("unselected canonical name")
    (directory / "copy").symlink_to(foreign)
    (directory / "retired").symlink_to(canon / "skills/retired")
    (directory / "retired-relative").symlink_to(os.path.relpath(canon / "skills/retired-relative", directory))

    unmanaged = {path.name: kind for _h, path, kind in skills._unmanaged(canon)}
    if explicit_include:
        assert unmanaged == {
            "domain": "unmanaged-copy", "copy": "unmanaged-link",
            "retired": "unmanaged-link", "retired-relative": "unmanaged-link",
        }
    else:
        assert unmanaged == {
            "native-skill": "unmanaged-copy", "native-link": "unmanaged-link",
            "native-alias": "unmanaged-link", "retired": "unmanaged-link",
            "retired-relative": "unmanaged-link",
        }


def test_explicit_skill_scope_keeps_unmanaged_command_reporting(
    distribution_roots: tuple[Path, Path, Path],
) -> None:
    canon, home, _project = distribution_roots
    commands = home / ".claude/commands"
    commands.mkdir(parents=True)
    local = commands / "native-command.md"
    local.write_text("local command")
    assert skills._unmanaged(canon) == [("global", local, "unmanaged-copy")]


@pytest.mark.parametrize("command", ["create", "import-github"])
@pytest.mark.parametrize("adopt", [False, True])
def test_create_import_only_adopt_explicitly_and_report_observed_destination_links(
    distribution_roots: tuple[Path, Path, Path], tmp_path: Path, command: str, adopt: bool,
) -> None:
    canon, _home, _project = distribution_roots
    manifest = canon / "manifest.toml"
    manifest.write_text(manifest.read_text().replace('"domain", "profiled", "copy"', '"domain", "profiled", "copy", "new-skill"'))
    (canon / "install.sh").write_text("#!/bin/bash\nexit 0\n")
    imported = _import_source(tmp_path)
    args = ["create", "new-skill"] if command == "create" else ["import-github", "owner/repo"]
    if adopt:
        args.append("--adopt")
    real_run = subprocess.run
    with (
        patch.object(skills, "_canon", return_value=canon),
        patch.object(skills, "_download_and_extract_skill", return_value=imported),
        patch.object(skills.subprocess, "run", wraps=real_run) as run,
    ):
        result = runner.invoke(skills.app, args)
    assert result.exit_code == 0, result.output
    expected_args = ["bash", str(canon / "install.sh")] + (["--adopt"] if adopt else [])
    run.assert_called_once_with(expected_args, check=False)
    assert (canon / "skills/new-skill/SKILL.md").is_file()
    assert "Canonical links present for 'new-skill': 0/1 configured destinations." in result.output
    assert "all harnesses" not in result.output
    assert "successfully imported and linked" not in result.output


@pytest.mark.parametrize("command", ["create", "import-github"])
def test_create_import_report_zero_eligible_destinations_without_claiming_discovery(
    distribution_roots: tuple[Path, Path, Path], tmp_path: Path, command: str,
) -> None:
    canon, _home, _project = distribution_roots
    imported = _import_source(tmp_path)
    args = ["create", "new-skill"] if command == "create" else ["import-github", "owner/repo"]
    with (
        patch.object(skills, "_canon", return_value=canon),
        patch.object(skills, "_download_and_extract_skill", return_value=imported),
        patch.object(skills.subprocess, "run") as run,
    ):
        result = runner.invoke(skills.app, args)
    assert result.exit_code == 0, result.output
    run.assert_not_called()
    assert "No eligible skill destinations for 'new-skill'" in result.output
    assert "Choose its project scope in manifest.toml before enabling discovery." in result.output
    assert "Canonical skill 'new-skill'" in result.output
    assert "configured destinations." not in result.output


def test_create_with_zero_destinations_still_propagates_existing_installer_failure(
    distribution_roots: tuple[Path, Path, Path],
) -> None:
    canon, _home, _project = distribution_roots
    (canon / "install.sh").write_text("#!/bin/bash\nexit 6\n")
    with patch.object(skills, "_canon", return_value=canon):
        result = runner.invoke(skills.app, ["create", "new-skill"])
    assert result.exit_code == 6
    assert "No eligible skill destinations" in result.output
    assert "Skill installation failed (exit 6); canonical skill retained." in result.output
    assert "Canonical skill 'new-skill'" not in result.output


@pytest.mark.parametrize("command", ["create", "import-github"])
def test_create_import_installer_failure_retains_canonical_source_and_stops_success(
    distribution_roots: tuple[Path, Path, Path], tmp_path: Path, command: str,
) -> None:
    canon, _home, _project = distribution_roots
    manifest = canon / "manifest.toml"
    manifest.write_text(manifest.read_text().replace('"domain", "profiled", "copy"', '"domain", "profiled", "copy", "new-skill"'))
    (canon / "install.sh").write_text("#!/bin/bash\nexit 9\n")
    imported = _import_source(tmp_path)
    args = ["create", "new-skill"] if command == "create" else ["import-github", "owner/repo"]
    with (
        patch.object(skills, "_canon", return_value=canon),
        patch.object(skills, "_download_and_extract_skill", return_value=imported),
    ):
        result = runner.invoke(skills.app, args)
    assert result.exit_code == 9
    assert "Skill installation failed (exit 9); canonical skill retained." in result.output
    assert (canon / "skills/new-skill/SKILL.md").is_file()
    assert "Running audit" not in result.output
    assert "Canonical skill 'new-skill'" not in result.output


@pytest.mark.parametrize("failure", ["missing", "spawn"])
def test_create_reports_unavailable_installer_and_keeps_canonical_source(
    distribution_roots: tuple[Path, Path, Path], failure: str,
) -> None:
    canon, _home, _project = distribution_roots
    manifest = canon / "manifest.toml"
    manifest.write_text(manifest.read_text().replace('include = ["general"]\n', ''))
    if failure == "spawn":
        (canon / "install.sh").write_text("#!/bin/bash\n")
    with patch.object(skills, "_canon", return_value=canon), patch.object(skills.subprocess, "run", side_effect=OSError("cannot spawn")) as run:
        result = runner.invoke(skills.app, ["create", "new-skill"])
    assert result.exit_code == (2 if failure == "missing" else 1)
    assert "canonical skill retained" in result.output
    assert (canon / "skills/new-skill/SKILL.md").is_file()
    if failure == "missing":
        run.assert_not_called()
    else:
        run.assert_called_once_with(["bash", str(canon / "install.sh")], check=False)


def _import_source(tmp_path: Path) -> Path:
    imported = tmp_path / "imported"
    imported.mkdir()
    (imported / "SKILL.md").write_text(
        "---\nname: new-skill\ndescription: Use for isolated canonical skill import tests.\n---\n\nTest skill.\n"
    )
    return imported
