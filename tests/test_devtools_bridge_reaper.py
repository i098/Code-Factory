"""fleet/doctor/devtools-bridge-reaper.sh against a fixture bridge process tree.

The fixture is a detached bash (reparented to init, like a real bridge) with
a `sleep` child, carrying a per-test marker in its command line instead of
chrome-devtools-axi-bridge.js, so real bridges on the host are never matched.
Idle time is simulated by backdating the busy timestamp in the state file.
"""

import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SESSION = "fixture"
# USR1 burns ~0.3 s of CPU in the tree, then the bridge goes back to waiting.
BRIDGE = """
trap 'for ((i = 0; i < 500000; i++)); do :; done; touch "$STUB/burned"' USR1
while :; do sleep 600 & wait $!; done
"""
STOP_STUB = 'echo "stop session=${CHROME_DEVTOOLS_AXI_SESSION:-default}" >> "$STUB/stop.log"\n'


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] != "Z"
    except (FileNotFoundError, IndexError):
        return False


class Reaper:
    def __init__(self, tmp: Path):
        self.doctor = tmp / "doctor"
        self.stub = tmp / "stub"
        self.axi = tmp / "axi"
        self.session = self.axi / "sessions" / SESSION
        for d in (self.doctor, self.stub / "bin", self.session):
            d.mkdir(parents=True)
        shutil.copy(ROOT / "fleet/doctor/devtools-bridge-reaper.sh", self.doctor)
        cli = self.stub / "bin" / "chrome-devtools-axi"
        cli.write_text("#!/usr/bin/env bash\n" + STOP_STUB)
        cli.chmod(0o755)
        self.state = self.doctor / "devtools-bridge-reaper.state"
        self.mark = f"fixture-bridge-{uuid.uuid4().hex}.js"
        self.env = {
            "PATH": f"{self.stub / 'bin'}:/usr/bin:/bin",
            "HOME": str(tmp),
            "STUB": str(self.stub),
            "BRIDGE_REAPER_MARK": self.mark,
            "BRIDGE_REAPER_AXI_STATE_DIR": str(self.axi),
        }
        self.pid = self.start_bridge()
        self.tree = [self.pid, *self.children(self.pid)]

    def start_bridge(self) -> int:
        # The wrapper backgrounds the bridge and exits, so init adopts it.
        out = subprocess.run(
            [
                "bash",
                "-c",
                'bash -c "$0" "$1" </dev/null >/dev/null 2>&1 & echo $!',
                BRIDGE,
                self.mark,
            ],
            env={**self.env, "CHROME_DEVTOOLS_AXI_SESSION": SESSION},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        pid = int(out)
        deadline = time.time() + 5
        while not self.children(pid) and time.time() < deadline:
            time.sleep(0.05)
        return pid

    @staticmethod
    def children(pid: int) -> list[int]:
        path = Path(f"/proc/{pid}/task/{pid}/children")
        return [int(c) for c in path.read_text().split()] if path.exists() else []

    def bridge_pid_file(self, pid: int, age_s: int = 7200):
        f = self.session / "bridge.pid"
        f.write_text(f'{{"pid": {pid}, "port": 9999}}\n')
        t = time.time() - age_s
        os.utime(f, (t, t))

    def backdate(self, minutes: int):
        ((key, ticks, _busy),) = (line.split() for line in self.state.read_text().splitlines())
        self.state.write_text(f"{key} {ticks} {int(time.time()) - minutes * 60}\n")

    def run(self, *args: str) -> str:
        return subprocess.run(
            [str(self.doctor / "devtools-bridge-reaper.sh"), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
            timeout=90,
        ).stdout

    def stops(self) -> list[str]:
        log = self.stub / "stop.log"
        return log.read_text().splitlines() if log.exists() else []

    def gone(self) -> bool:
        deadline = time.time() + 5
        while any(alive(p) for p in self.tree) and time.time() < deadline:
            time.sleep(0.05)
        return not any(alive(p) for p in self.tree)

    def cleanup(self):
        for p in self.tree:
            if alive(p):
                os.kill(p, signal.SIGKILL)


@pytest.fixture
def reaper(tmp_path):
    r = Reaper(tmp_path)
    r.bridge_pid_file(r.pid)
    yield r
    r.cleanup()


def test_first_sighting_is_never_reaped(reaper):
    reaper.run()
    assert all(alive(p) for p in reaper.tree)
    assert reaper.state.read_text().startswith(f"{reaper.pid}:")


def test_idle_tree_is_stopped_in_its_session_after_idle_min(reaper):
    reaper.run()
    reaper.backdate(59)
    reaper.run()
    assert all(alive(p) for p in reaper.tree)
    reaper.backdate(61)
    reaper.run()
    assert reaper.stops() == [f"stop session={SESSION}"]
    assert reaper.gone()
    assert reaper.state.read_text() == ""
    assert (
        f"REAPED bridge {reaper.pid} session={SESSION}"
        in (reaper.doctor / "devtools-bridge-reaper.log").read_text()
    )


def test_cpu_in_the_tree_keeps_it(reaper):
    reaper.run()
    reaper.backdate(61)
    os.kill(reaper.pid, signal.SIGUSR1)
    deadline = time.time() + 30
    while not (reaper.stub / "burned").exists() and time.time() < deadline:
        time.sleep(0.05)
    reaper.run()
    assert all(alive(p) for p in reaper.tree)
    assert reaper.stops() == []


def test_session_state_change_keeps_it(reaper):
    reaper.run()
    reaper.backdate(61)
    os.utime(reaper.session / "bridge.pid")
    reaper.run()
    assert all(alive(p) for p in reaper.tree)
    assert reaper.stops() == []


def test_dry_run_signals_nothing_and_writes_no_state(reaper):
    reaper.run()
    reaper.backdate(61)
    before = reaper.state.read_text()
    out = reaper.run("--dry-run")
    assert f"would reap bridge {reaper.pid} session={SESSION} idle=61min" in out
    assert all(alive(p) for p in reaper.tree)
    assert reaper.state.read_text() == before
    assert reaper.stops() == []
    assert not (reaper.doctor / "devtools-bridge-reaper.log").exists()


def test_bridge_pid_naming_another_pid_skips_stop_but_kills_the_tree(reaper):
    reaper.bridge_pid_file(reaper.pid + 100000)
    reaper.run()
    reaper.backdate(61)
    reaper.run()
    assert reaper.stops() == []
    assert reaper.gone()
