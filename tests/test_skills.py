import importlib.util
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "skills", Path(__file__).parents[1] / "scripts/skills.py"
)
skills = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(skills)


def skill(root, kind, name, body):
    path = root / kind / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(body)
    return path


def test_install_both_sets_private_wins_and_hand_added_skills_stay(tmp_path):
    source, home = tmp_path / "skills", tmp_path / "home"
    skill(source, "public", "shared", "public shared")
    skill(source, "public", "only-public", "public only")
    helper = skill(source, "private", "shared", "private shared") / "run.sh"
    helper.write_text("#!/bin/sh\n")
    helper.chmod(0o755)
    skill(source, "private", "only-private", "private only")
    hand = home / ".claude/skills/only-public"
    hand.mkdir(parents=True)
    (hand / "SKILL.md").write_text("operator")

    result = skills.install(home, source)
    assert result["changed"]
    assert result["skipped"] == [str(hand)]
    for root in skills.ROOTS:
        base = home / root
        assert (base / "shared/SKILL.md").read_text() == "private shared"
        assert (base / "shared/run.sh").stat().st_mode & 0o111
        assert (base / "only-private/SKILL.md").read_text() == "private only"
    assert (home / ".omp/agent/skills/only-public/SKILL.md").read_text() == "public only"
    assert (hand / "SKILL.md").read_text() == "operator"

    assert not skills.install(home, source)["changed"]

    # An installed skill whose source is gone is removed; the hand-added one stays.
    (source / "private/only-private/SKILL.md").unlink()
    (source / "private/only-private").rmdir()
    (home / ".omp/agent/skills/hand-made").mkdir()
    assert skills.install(home, source)["changed"]
    for root in skills.ROOTS:
        assert not (home / root / "only-private").exists()
    assert (home / ".omp/agent/skills/hand-made").is_dir()
    assert (hand / "SKILL.md").read_text() == "operator"


def test_failed_copy_still_records_what_was_installed(tmp_path, monkeypatch):
    source, home = tmp_path / "skills", tmp_path / "home"
    skill(source, "public", "a", "a")
    skill(source, "public", "b", "b")
    real = skills.shutil.copytree

    def flaky(src, dst):
        if Path(src).name == "b":
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(skills.shutil, "copytree", flaky)
    try:
        skills.install(home, source)
    except OSError:
        pass
    monkeypatch.setattr(skills.shutil, "copytree", real)

    result = skills.install(home, source)
    assert result["skipped"] == []
    for root in skills.ROOTS:
        assert (home / root / "b/SKILL.md").read_text() == "b"


def git(*argv):
    subprocess.run(["git", *argv], check=True, capture_output=True)


def test_no_private_source_fetches_nothing_and_leaves_private_alone(tmp_path, monkeypatch):
    source, home = tmp_path / "skills", tmp_path / "home"
    skill(source, "private", "mine", "mine")
    monkeypatch.setattr(skills.subprocess, "run", lambda *a, **k: pytest.fail("fetched"))
    skills.install(home, source)
    assert [p.name for p in (source / "private").iterdir()] == ["mine"]
    assert not (home / skills.CACHE).exists()


def test_private_git_source_fills_private_and_installs_idempotently(tmp_path):
    source, home, remote = tmp_path / "skills", tmp_path / "home", tmp_path / "remote"
    skill(source, "public", "shared", "public shared")
    skill(source, "private", "by-hand", "by hand")
    skill(remote, ".", "shared", "remote shared")
    skill(remote, ".", "gone-later", "remote gone")
    skill(remote, ".", "by-hand", "remote by hand")
    git("init", "-q", "-b", "skills", str(remote))
    git("-C", str(remote), "add", ".")
    git("-C", str(remote), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    url = remote.as_uri()

    result = skills.install(home, source, url, "skills")
    assert result["changed"]
    assert result["skipped"] == [str(source / "private/by-hand")]
    assert (source / "private/by-hand/SKILL.md").read_text() == "by hand"
    for root in skills.ROOTS:
        assert (home / root / "shared/SKILL.md").read_text() == "remote shared"
        assert (home / root / "gone-later/SKILL.md").read_text() == "remote gone"
        assert (home / root / "by-hand/SKILL.md").read_text() == "by hand"

    assert not skills.install(home, source, url, "skills")["changed"]

    # A skill that leaves the source leaves skills/private and every root.
    git("-C", str(remote), "rm", "-rq", "gone-later")
    git("-C", str(remote), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "y")
    assert skills.install(home, source, url, "skills")["changed"]
    assert not (source / "private/gone-later").exists()
    for root in skills.ROOTS:
        assert not (home / root / "gone-later").exists()
        assert (home / root / "shared/SKILL.md").read_text() == "remote shared"


def test_private_local_directory_source_fills_private(tmp_path):
    source, home, local = tmp_path / "skills", tmp_path / "home", tmp_path / "local"
    skill(local, ".", "solo", "local solo")
    result = skills.install(home, source, str(local))
    assert result["installed"] == ["solo"]
    assert (source / "private/solo/SKILL.md").read_text() == "local solo"
    for root in skills.ROOTS:
        assert (home / root / "solo/SKILL.md").read_text() == "local solo"
    assert not skills.install(home, source, str(local))["changed"]
    # A missing local source fails and leaves every filled skill in place.
    with pytest.raises(FileNotFoundError):
        skills.install(home, source, str(tmp_path / "unmounted"))
    assert (source / "private/solo/SKILL.md").read_text() == "local solo"
    for root in skills.ROOTS:
        assert (home / root / "solo/SKILL.md").read_text() == "local solo"
