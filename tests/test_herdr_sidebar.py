"""Herdr sidebar feeders: config/herdr-sidebar.ts and maintenance/herdr-spaces.py.

The reporter runs against a fixture home and a stub `herdr` command that
records what would be reported, so the live Herdr session is never touched.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
REPORTER = ROOT / "maintenance/herdr-spaces.py"
BLANK = "\u2800"

spec = importlib.util.spec_from_file_location("herdr_spaces", REPORTER)
spaces = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spaces)

LABELS = {
    "firstmate": "firstmate",
    "2ndmate-swarms-mate-s4": "swarms",
    "2ndmate-subliminal-mate-b8": "subliminal",
    "firstmate-afk-daemon-1587287-6940-1790642036": "☾ afk",
    "└ fix-login · p:Qm3vX8kT2aLp9RwZcN4yHd": "└ fix-login",
    "scratch": "",
}


def ts(expr: str):
    """Evaluate an expression against the extension's exports with bun."""
    code = f"import * as m from {json.dumps(str(ROOT / 'config/herdr-sidebar.ts'))};"
    code += f"console.log(JSON.stringify({expr}));"
    env = {k: v for k, v in os.environ.items() if k != "FM_TASK_ID"}
    out = subprocess.run(["bun", "-e", code], capture_output=True, text=True, check=True, env=env)
    return json.loads(out.stdout)


needs_bun = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def test_short_names():
    assert {label: spaces.short_name(label) for label in LABELS} == LABELS


@needs_bun
def test_extension_short_names_match_the_reporter():
    assert (
        ts(f"Object.fromEntries({json.dumps(list(LABELS))}.map(l => [l, m.shortName(l)]))")
        == LABELS
    )


@needs_bun
def test_pr_parts():
    full = {"pr": 1537, "issue": "1529", "add": 12847, "del": 3902, "files": 214}
    assert ts(f"m.prParts({json.dumps(full)}, 4)") == {
        "pr": BLANK * 4 + "⎇ 1537",
        "issue": "○ 1529",
        "add": "+12847",
        "del": "−3902",
        "files": "✎ 214",
    }
    # A worker with an issue but no pull request: the issue carries the indent.
    assert ts('m.prParts({issue: "88"}, 2)') == {
        "pr": "",
        "issue": BLANK * 2 + "○ 88",
        "add": "",
        "del": "",
        "files": "",
    }
    assert ts("m.shortstat(' 3 files changed, 84 insertions(+), 12 deletions(-)')") == {
        "files": 3,
        "add": 84,
        "del": 12,
    }
    assert ts("m.shortstat(' 1 file changed, 2 deletions(-)')") == {"files": 1, "add": 0, "del": 2}


@needs_bun
def test_issue_sources():
    assert ts('m.closingIssue("Adds X.\\n\\nFixes #1529 and closes #7")') == "1529"
    assert ts('m.closingIssue("See #12")') == ""
    record = [
        "- [ ] fix-login - app: fix login (repo: app) (kind: ship)",
        "Implement https://github.com/o/app/issues/1383 in full. Split #1229 first.",
    ]
    assert ts(f"m.recordIssue({json.dumps(record)})") == "1383"
    assert ts('m.recordIssue(["- [ ] x - y (issue 1523) (repo: r)"])') == "1523"
    assert ts('m.recordIssue(["no issue here", ""])') == ""


@needs_bun
def test_pr_owners_from_remotes():
    remotes = (
        "fork\tgit@github.com:undeemed/swarms-platform.git (fetch)\n"
        "fork\tgit@github.com:undeemed/swarms-platform.git (push)\n"
        "origin\thttps://github.com/The-Swarm-Corporation/swarms-platform.git (fetch)\n"
        "origin\thttps://github.com/The-Swarm-Corporation/swarms-platform.git (push)\n"
        "mirror\tssh://git@github.com/undeemed/swarms-platform (fetch)\n"
        "other\thttps://gitlab.com/someone/swarms-platform.git (fetch)\n"
    )
    assert ts(f"m.prOwners({json.dumps(remotes)})") == [
        "{owner}",
        "undeemed",
        "The-Swarm-Corporation",
    ]
    assert ts('m.prOwners("")') == ["{owner}"]


def write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    home = tmp_path / "home"
    (home / ".git").mkdir(parents=True)
    (home / "data").mkdir()
    write(home / "state/fix-login.meta", "kind=ship\n")
    write(home / "state/fix-docs.meta", "kind=ship\n")
    write(home / "state/old.meta", "kind=ship\n")
    # The stub fold lists each status log's own lines as its open decisions.
    # w1, labelled firstmate, is the primary Space: its worker has one fresh
    # decision and one parked hold, which never counts.
    write(
        home / "state/fix-login.status",
        "ask\tneeds-decision\tx\ncaptain-hold-deploy\tneeds-decision\ty\n",
    )
    # Second-level homes: one with a live Space (w4) and one without (w9).
    write(home / "state/api-mate-a1.meta", "kind=secondmate\nherdr_workspace_id=w4\n")
    write(home / "state/gone-mate-g1.meta", "kind=secondmate\nherdr_workspace_id=w9\n")
    write(home / "state/api-mate-a1.status", "a\tneeds-decision\tx\nb\tblocked\ty\n")
    write(
        home / "state/gone-mate-g1.status",
        "c\tneeds-decision\tx\nd\tneeds-decision\ty\ne\tblocked\tz\n",
    )
    write(home / "bin/fm-classify-lib.sh", 'status_open_decisions() { cat "$1"; }\n')
    write(home / "bin/fm-tasks-axi.sh", "#!/bin/sh\n[ \"$1\" = ready ] && echo 'count: 4'\n", 0o755)
    write(home / "bin/fm-supervision-lib.sh", "fm_supervision_unhealthy() { return 0; }\n")

    stub = tmp_path / "stub"
    log = tmp_path / "reports.jsonl"
    workspaces = tmp_path / "workspaces.json"
    workspaces.write_text(
        json.dumps(
            [
                {"workspace_id": "w1", "label": "firstmate"},
                {"workspace_id": "w2", "label": "firstmate-afk-daemon-1-2-3"},
                {"workspace_id": "w3", "label": "scratch"},
                {"workspace_id": "w4", "label": "2ndmate-api-mate-a1"},
            ]
        )
    )
    panes = [
        {"workspace_id": "w1", "cwd": str(home / "projects/app")},
        {"workspace_id": "w2", "cwd": str(home)},
        {"workspace_id": "w4", "cwd": str(home / "projects/api")},
    ]
    write(
        stub / "herdr",
        f"""#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if a[:2] == ["workspace", "list"]:
    print(json.dumps({{"result": {{"workspaces": json.load(open({str(workspaces)!r}))}}}}))
elif a[:2] == ["pane", "list"]:
    print(json.dumps({{"result": {{"panes": {json.dumps(panes)}}}}}))
elif a[:2] == ["workspace", "report-metadata"]:
    with open({str(log)!r}, "a") as f:
        f.write(json.dumps(a[2:]) + "\\n")
""",
        0o755,
    )
    env = {
        **os.environ,
        "PATH": f"{stub}:{os.environ['PATH']}",
        "HERDR_BIN_PATH": str(stub / "herdr"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }

    def run() -> dict[str, dict[str, str | None]]:
        log.unlink(missing_ok=True)
        subprocess.run(["python3", str(REPORTER)], env=env, check=True, timeout=120)
        reported = {}
        for line in log.read_text().splitlines():
            args = json.loads(line)
            tokens = reported.setdefault(args[0], {})
            for flag, value in zip(args[3::2], args[4::2]):
                key, _, text = value.partition("=")
                tokens[key] = text if flag == "--token" else None
        return reported

    return home, run


def test_reporter_counts_from_a_fixture_home(fixture):
    home, run = fixture
    reported = run()
    docs = reported["w1"]
    res = docs.pop("res")
    host = docs.pop("host")
    assert docs == {
        "short": "firstmate",
        # Its own worker's fresh decision only: not the parked hold, not the
        # second-level homes' decisions.
        "decisions": "⚑ 1",
        "crew": "▶ 3",
        "queue": "◷ 4",
        "alert": "⚠ watcher silent",
        # No machine workspace: the machine line is its host row instead.
        "machine": None,
    }
    # Shares of the machine; CPU needs a baseline, so it waits for run two.
    # Herdr's own continuation indent puts it under the name: no padding.
    assert re.fullmatch(r"▤ \d+%  ⛁ \d+%", res)
    # The primary carries the whole-machine line, short enough for the 40
    # columns Herdr shows on a continuation row at width 46.
    size = r"[\d.]+/[\d.]+[GT] \d+%"
    assert re.fullmatch(rf"⌂ ▤ {size} ⛁ {size}", host) and len(host) <= 40
    # A helper space shows its short name only; everything else is cleared.
    assert reported["w2"] == {"short": "☾ afk"} | dict.fromkeys(spaces.TOKENS[1:])
    # A space with no home is not the primary: CPU and RAM only.
    assert reported["w3"]["res"].startswith("▤ ") and reported["w3"]["host"] is None
    # A second-level home with a live Space counts its own log there; the one
    # without a live Space is counted nowhere.
    assert reported["w4"]["decisions"] == "⚑ 2"

    # Second run: CPU has a baseline now, a zero count is cleared, and a failed
    # source keeps its previous value.
    write(home / "bin/fm-classify-lib.sh", "status_open_decisions() { return 1; }\n")
    (home / "state/fix-login.status").write_text("new\tneeds-decision\tz\n")
    write(home / "bin/fm-supervision-lib.sh", "fm_supervision_unhealthy() { return 1; }\n")
    docs = run()["w1"]
    assert docs["decisions"] == "⚑ 1"
    assert docs["alert"] is None
    assert re.fullmatch(r"⚙ \d+%  ▤ \d+%  ⛁ \d+%", docs["res"])
    assert re.fullmatch(r"⌂ ⚙ \d+% ▤ .+", docs["host"])


def test_reporter_forgets_status_logs_it_no_longer_reads(fixture):
    home, run = fixture
    cache_file = home.parent / "cache/code-factory/herdr-spaces.json"
    run()
    assert str(home / "state/fix-login.status") in json.loads(cache_file.read_text())["folds"]
    (home / "state/fix-login.meta").unlink()
    run()
    assert set(json.loads(cache_file.read_text())["folds"]) == {
        str(home / "state/api-mate-a1.status")
    }


def test_reporter_counts_no_decisions_without_a_firstmate_space(fixture, tmp_path):
    _, run = fixture
    workspaces = tmp_path / "workspaces.json"
    listed = json.loads(workspaces.read_text())
    listed[0]["label"] = "2ndmate-docs-mate-d1"
    workspaces.write_text(json.dumps(listed))
    reported = run()
    assert {wid: tokens["decisions"] for wid, tokens in reported.items()} == dict.fromkeys(reported)
    # The first listed still carries the machine line.
    assert reported["w1"]["host"].startswith("⌂ ")


def test_a_machine_workspace_carries_the_machine_line_alone(fixture, tmp_path):
    _, run = fixture
    workspaces = tmp_path / "workspaces.json"
    listed = json.loads(workspaces.read_text())
    workspaces.write_text(json.dumps([{"workspace_id": "w0", "label": "machine"}, *listed]))
    reported = run()
    machine = reported["w0"]
    assert machine.pop("machine").startswith("⌂ ")
    # Nothing else, not even a short name: the line sits alone at the left edge.
    assert machine == dict.fromkeys(spaces.TOKENS[:-1])
    # Never both: no Space carries the host row under its resource line.
    assert all(tokens["host"] is None for tokens in reported.values())
    assert all(tokens["machine"] is None for wid, tokens in reported.items() if wid != "w0")


def test_queue_count_is_cached_until_the_backlog_changes_or_a_minute_passes(tmp_path):
    home = tmp_path / "home"
    calls = tmp_path / "calls"
    write(
        home / "bin/fm-tasks-axi.sh",
        f'#!/bin/sh\necho x >> {calls}\necho "count: $(cat {tmp_path / "ready"})"\n',
        0o755,
    )
    (tmp_path / "ready").write_text("4")
    backlog = home / "data/backlog.md"
    write(backlog, "- [ ] a\n")
    saved = {}

    def calls_made() -> int:
        return len(calls.read_text().splitlines())

    assert spaces.queue(home, saved) == 4 and calls_made() == 1
    # Hit: the ready set moved, but the backlog did not and the minute is not up.
    (tmp_path / "ready").write_text("5")
    assert spaces.queue(home, saved) == 4 and calls_made() == 1
    # The backlog changed: recount.
    os.utime(backlog, ns=(0, backlog.stat().st_mtime_ns + 10**9))
    assert spaces.queue(home, saved) == 5 and calls_made() == 2
    # A minute passed with the backlog unchanged: recount.
    (tmp_path / "ready").write_text("6")
    saved[str(home)][1] -= spaces.QUEUE_TTL + 1
    assert spaces.queue(home, saved) == 6 and calls_made() == 3


def test_space_cpu_leaves_out_a_reaped_child(fixture):
    # A worker in the docs space runs a 6-second build on one core. The reporter
    # samples the build mid-way, then the worker reaps it: the next run counts
    # only live processes' own time, never the build's lifetime again through
    # the worker's child time.
    _, run = fixture
    busy = "import time\nt = time.time()\nwhile time.time() - t < 6: pass"
    worker = subprocess.Popen(
        [
            "python3",
            "-c",
            f"import subprocess, sys, time; subprocess.run([sys.executable, '-c', {busy!r}]); print(flush=True); time.sleep(30)",
        ],
        env={**os.environ, "HERDR_WORKSPACE_ID": "w1"},
        stdout=subprocess.PIPE,
    )
    try:
        time.sleep(5)
        run()
        worker.stdout.readline()
        res = run()["w1"]["res"]
    finally:
        worker.kill()
        worker.wait()
    assert int(re.search(r"⚙ (\d+)%", res)[1]) / 100 * os.cpu_count() < 1.5


@pytest.mark.parametrize(("before", "share"), [(-(10**12), "100%"), (10**12, "0%")])
def test_space_cpu_share_stays_within_0_and_100(fixture, tmp_path, before, share):
    _, run = fixture
    worker = subprocess.Popen(["sleep", "30"], env={**os.environ, "HERDR_WORKSPACE_ID": "w1"})
    try:
        cache = tmp_path / "cache/code-factory/herdr-spaces.json"
        write(
            cache,
            json.dumps({"cpu": {"w1": {str(worker.pid): before}}, "cpu_at": time.time() - 10}),
        )
        res = run()["w1"]["res"]
    finally:
        worker.kill()
        worker.wait()
    assert re.search(r"⚙ (\d+%)", res)[1] == share


@pytest.mark.parametrize(
    ("used", "total", "fine", "text"),
    [
        (7.1, 7.8, True, "7.1/7.8G"),
        (18.2, 31.0, True, "18.2/31.0G"),
        (99.9, 99.9, True, "99.9/99.9G"),
        (45.0, 93.1, False, "45/93G"),
        (402, 937, False, "402/937G"),
        (402, 937, True, "402/937G"),
        (1433.6, 1945.6, False, "1.4/1.9T"),
        (12288, 20480, True, "12/20T"),
    ],
)
def test_machine_sizes_stay_short(used, total, fine, text):
    assert spaces.used_of(used * 2**30, total * 2**30, fine) == text


@pytest.mark.parametrize("ram", [9.96, 15.6, 31.0, 99.9, 999.6, 9.96 * 1024])
@pytest.mark.parametrize("disk", [9.96, 93.1, 100.0, 999.0, 9.96 * 1024, 99 * 1024])
def test_machine_line_fits_a_continuation_spaces_row(ram, disk):
    # The 40 columns Herdr shows on a continuation row of a Spaces entry at
    # sidebar width 46, with CPU at 100% and memory and disk at 99%.
    mem = spaces.used_of(ram * 2**30, ram * 2**30, fine=True)
    root = spaces.used_of(disk * 2**30, disk * 2**30)
    assert len(f"⌂ ⚙ 100% ▤ {mem} 99% ⛁ {root} 99%") <= 40


def test_reporter_waits_out_a_failed_disk_measurement(fixture, tmp_path):
    _, run = fixture
    calls = tmp_path / "du-calls"
    write(tmp_path / "stub/du", f"#!/bin/sh\necho x >> {calls}\nexit 1\n", 0o755)
    assert " ⛁ " not in run()["w1"]["res"]
    assert " ⛁ " not in run()["w1"]["res"]
    assert len(calls.read_text().splitlines()) == 1
