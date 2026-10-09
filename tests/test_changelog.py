import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_release_build_assembles_fragments_into_keep_a_changelog_section(tmp_path):
    shutil.copy(ROOT / "pyproject.toml", tmp_path)
    shutil.copy(ROOT / "CHANGELOG.md", tmp_path)
    fragments = tmp_path / "changelog.d"
    fragments.mkdir()
    shutil.copy(ROOT / "changelog.d/template.md", fragments)
    (fragments / "12.fixed.md").write_text("Fix the thing.\n")
    (fragments / "7.added.md").write_text("Add a thing\n")
    (fragments / "9.added.md").write_text("Add another thing.\n")
    (fragments / "3.security.md").write_text("Close a hole.\n")
    before = (tmp_path / "CHANGELOG.md").read_text()

    subprocess.run(
        [sys.executable, "-m", "towncrier", "build", "--yes"]
        + ["--version", "9.9.9", "--date", "2026-01-02"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    link = "https://github.com/i098/Crewship/issues/"
    section = (
        "## [Unreleased]\n\n"
        "## [9.9.9] - 2026-01-02\n\n"
        "### Added\n\n"
        f"- Add a thing ([#7]({link}7)).\n"
        f"- Add another thing ([#9]({link}9)).\n\n"
        "### Fixed\n\n"
        f"- Fix the thing ([#12]({link}12)).\n\n"
        "### Security\n\n"
        f"- Close a hole ([#3]({link}3)).\n\n"
    )
    head, rest = before.split("## [Unreleased]\n", 1)
    assert (tmp_path / "CHANGELOG.md").read_text() == head + section + rest.lstrip()
    assert [p.name for p in fragments.iterdir()] == ["template.md"]
