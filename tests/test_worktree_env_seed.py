"""fleet/doctor/worktree-env-seed.sh against a throwaway home and treehouse pool."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SEED = ROOT / "fleet/doctor/worktree-env-seed.sh"
PROBE = "JSON.stringify([process.execArgv, require('v8').getHeapStatistics().heap_size_limit])"
CAP_FLAG = "--max-old-space-size=2048"
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


def seeded_worktree(home):
    (home / "oss-fleet/doctor").mkdir(parents=True)
    shared = home / "oss-fleet/shared-supabase"
    shared.mkdir()
    (shared / "swarms-platform.env.local").write_text("# fleet-shared-supabase\nX=1\n")
    worktree = home / ".treehouse/swarms-platform-abc123/1/swarms-platform"
    worktree.mkdir(parents=True)
    (worktree / "package.json").write_text(json.dumps({"scripts": {"probe": f'node -p "{PROBE}"'}}))
    return worktree


def seed(home):
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("NODE_OPTIONS", "BUN_OPTIONS")
    }
    result = subprocess.run(
        ["bash", SEED], env={**env, "HOME": str(home)}, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return env | {"HOME": str(home)}


def probed(command, worktree, env):
    result = subprocess.run(command, cwd=worktree, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node
@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_a_fresh_lane_gets_the_heap_cap_before_and_after_its_first_install(tmp_path):
    worktree = seeded_worktree(tmp_path)
    env = seed(tmp_path)
    assert not (worktree / "node_modules").exists()
    flags, limit = probed(["bun", "run", "probe"], worktree, env)
    assert CAP_FLAG in flags
    assert 2048 * 2**20 <= limit < 2560 * 2**20
    dev = worktree / "node_modules/.bin/dev"
    dev.parent.mkdir(parents=True)
    dev.write_text(f"#!/usr/bin/env node\nconsole.log({PROBE})\n")
    dev.chmod(0o755)
    (worktree / "package.json").write_text(json.dumps({"scripts": {"dev": "dev"}}))
    flags, limit = probed(["bun", "run", "dev"], worktree, env)
    assert CAP_FLAG in flags
    assert 2048 * 2**20 <= limit < 2560 * 2**20
    flags, _ = probed(["node", "-p", PROBE], worktree, env)
    assert CAP_FLAG not in flags
    assert (worktree / ".env.local").read_text() == "# fleet-shared-supabase\nX=1\n"


@needs_node
def test_seeding_is_idempotent_and_never_touches_the_checkouts_node_modules(tmp_path):
    worktree = seeded_worktree(tmp_path)
    seed(tmp_path)
    wrapper = worktree.parent / "node_modules/.bin/node"
    first = wrapper.stat().st_mtime_ns
    seed(tmp_path)
    assert wrapper.stat().st_mtime_ns == first
    assert not (worktree / "node_modules").exists()
    assert (worktree / ".env.local").is_file()
