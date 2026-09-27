"""fleet-browser's chrome tier finds a puppeteer Chrome when no system Chrome exists.

Without it, fleet-browser-vnc.service and fleet-browser-chrome.service exit
"no chrome binary" and restart forever on a host that has only the puppeteer
download.
CI runners ship /usr/bin/google-chrome, so this test runs only on hosts without one.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SYSTEM_CHROMES = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


@pytest.mark.skipif(
    any(os.access(p, os.X_OK) for p in SYSTEM_CHROMES),
    reason="a system Chrome is found before the browser caches",
)
@pytest.mark.parametrize(
    "cache",
    [
        ".cache/puppeteer/chrome/linux-1.0/chrome-linux64",
        ".omp/puppeteer/chrome/linux-1.0/chrome-linux64",
    ],
)
def test_chrome_tier_runs_puppeteer_chrome(tmp_path, cache):
    chrome = tmp_path / cache / "chrome"
    chrome.parent.mkdir(parents=True)
    chrome.write_text('#!/bin/sh\necho "ran $0"\n')
    chrome.chmod(0o755)
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        [ROOT / "fleet/browsers/fleet-browser", "_run-chrome"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == f"ran {chrome}", result.stdout + result.stderr
