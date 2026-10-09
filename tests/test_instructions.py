import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "instructions", Path(__file__).parents[1] / "scripts/instructions.py"
)
instructions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(instructions)


def test_install_backs_up_only_a_user_change_and_is_idempotent(tmp_path):
    home, text = tmp_path / "home", tmp_path / "AGENTS.md"
    text.write_text("generic v1\n")
    claude = home / ".claude/CLAUDE.md"
    claude.parent.mkdir(parents=True)
    claude.write_text("generic v1\n\n@RTK.md\n")  # already what Crewship writes: no backup
    (home / ".claude/RTK.md").write_text("rtk")
    dotfile, codex = tmp_path / "dotfile", home / ".codex/AGENTS.md"
    dotfile.write_text("dotfiles\n")
    codex.parent.mkdir()
    codex.symlink_to(dotfile)  # a user's link: kept as the backup, never written through

    result = instructions.install(home, text)
    assert result["changed"]
    [backup] = result["backups"]
    assert Path(backup).readlink() == dotfile and dotfile.read_text() == "dotfiles\n"
    assert claude.read_text() == "generic v1\n\n@RTK.md\n"
    for rel in instructions.TARGETS[1:]:
        assert (home / rel).read_text() == "generic v1\n"
    assert not codex.is_symlink()
    assert instructions.install(home, text) == {**result, "changed": False, "backups": []}

    # A new text replaces an untouched file in place; a hand-edited one is moved aside.
    omp = home / ".omp/agent/AGENTS.md"
    omp.write_text("mine\n")
    text.write_text("generic v2\n")
    result = instructions.install(home, text)
    assert result["changed"]
    [backup] = result["backups"]
    assert Path(backup).parent == omp.parent and Path(backup).read_text() == "mine\n"
    assert omp.read_text() == "generic v2\n"
    assert (home / ".codex/AGENTS.md").read_text() == "generic v2\n"
    assert not instructions.install(home, text)["changed"]


def test_a_failed_target_still_records_the_earlier_writes(tmp_path):
    home, text = tmp_path / "home", tmp_path / "AGENTS.md"
    home.mkdir()
    text.write_text("generic v1\n")
    instructions.install(home, text)
    text.write_text("generic v2\n")
    (home / ".codex/AGENTS.md").unlink()
    (home / ".codex").rmdir()
    (home / ".codex").write_text("in the way")
    try:
        instructions.install(home, text)
    except OSError:
        pass
    (home / ".codex").unlink()
    text.write_text("generic v3\n")
    assert instructions.install(home, text)["backups"] == []
