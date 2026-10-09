"""install.sh and the npm launcher print the usage before any install step."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BASH = shutil.which("bash")


def sandbox(tmp_path):
    """An empty PATH (no apt-get, git or sudo) and a read-only HOME: any install step fails."""
    (tmp_path / "bin").mkdir()
    home = tmp_path / "home"
    home.mkdir(mode=0o500)
    return {"PATH": str(tmp_path / "bin"), "HOME": str(home)}


def install(env, *args):
    # Script on stdin, the way `curl | bash` and the launcher run it.
    return subprocess.run(
        [BASH, "-s", "--", *args],
        input=(ROOT / "install.sh").read_text(),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


@pytest.mark.parametrize("args", [["--help"], ["-h"], ["--container", "--help"]])
def test_help_prints_usage_and_changes_nothing(tmp_path, args):
    result = install(sandbox(tmp_path), *args)
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.startswith("Usage: crewship ")
    assert not any((tmp_path / "home").iterdir())


@pytest.mark.parametrize("args", [["--bogus"], ["--user"], ["--container", "extra"]])
def test_bad_option_prints_usage_and_fails(tmp_path, args):
    result = install(sandbox(tmp_path), *args)
    assert result.returncode == 2
    assert f"bad option: {args[-1]}" in result.stderr
    assert "Usage: crewship " in result.stderr
    assert result.stdout == ""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_launcher_help_matches_install_without_fetch(tmp_path):
    env = sandbox(tmp_path)
    # A fetch would throw, so only a local usage print can exit 0.
    stub = tmp_path / "no-fetch.js"
    stub.write_text("globalThis.fetch = () => { throw new Error('fetch called'); };\n")
    result = subprocess.run(
        [shutil.which("node"), "--require", str(stub), str(ROOT / "npm/crewship.js"), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout == install(env, "--help").stdout
