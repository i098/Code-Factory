"""config/omp-as-pi/switch-when-idle.sh --check-adapter, run with a stub curl: exit codes."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "config/omp-as-pi/switch-when-idle.sh"

STUB_CURL = """#!/usr/bin/env bash
url=${@: -1}
case "$STUB_CURL" in
fail) exit 22 ;;
changed) echo "not the pinned source" ;;
mixed)
	case "$url" in
	*/pi.go) exit 28 ;;
	*) echo "not the pinned source" ;;
	esac
	;;
esac
"""


def _check_adapter(tmp_path, behaviour):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(STUB_CURL)
    curl.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT), "--check-adapter", "v9.9.9"],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "STUB_CURL": behaviour},
        timeout=30,
    )


def test_a_source_that_differs_from_its_pin_exits_1(tmp_path):
    result = _check_adapter(tmp_path, "changed")
    assert result.returncode == 1
    assert "changed in v9.9.9" in result.stdout


def test_sources_that_cannot_be_fetched_exit_2(tmp_path):
    result = _check_adapter(tmp_path, "fail")
    assert result.returncode == 2
    assert "could not fetch" in result.stdout
    assert "changed in" not in result.stdout


def test_a_proven_mismatch_wins_over_a_failed_fetch(tmp_path):
    result = _check_adapter(tmp_path, "mixed")
    assert result.returncode == 1
    assert "changed in v9.9.9" in result.stdout
