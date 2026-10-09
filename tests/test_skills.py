import importlib.util
import re
from pathlib import Path

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


# Shapes of private detail, never the real values: a home directory, an email,
# a tailnet host, a non-loopback IPv4, a GitHub owner URL, a secrets file, and
# the word for the person who owns a fleet.
PRIVATE = re.compile(
    r"(/home/|/Users/|/root/|[\w.+-]+@[\w-]+\.[a-z]{2,}|\.ts\.net\b"
    r"|\b(?!127\.)\d{1,3}(\.\d{1,3}){3}\b|github\.com/[\w-]+|\w+\.env\b|\bcaptain\b)",
    re.IGNORECASE,
)


def test_public_skills_are_named_and_hold_no_private_details():
    public = Path(__file__).parents[1] / "skills/public"
    files = [p for p in public.rglob("*") if p.is_file()]
    assert files
    for path in files:
        text = path.read_text()
        hit = PRIVATE.search(text)
        assert not hit, f"{path.relative_to(public)}: {hit.group(0)!r}"
        if path.name == "SKILL.md":
            assert f"\nname: {path.parent.name}\n" in text.split("---")[1], path
