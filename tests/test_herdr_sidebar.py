"""Herdr sidebar feeders: config/herdr-sidebar.ts and maintenance/herdr-spaces.py.

The reporter runs against a fixture home and stub `herdr`/`gh` commands that
record what would be reported, so the live Herdr session is never touched.
"""

import importlib.util
import json
import os
import shutil
import subprocess
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


def write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path):
    home = tmp_path / "home"
    (home / ".git").mkdir(parents=True)
    (home / "data").mkdir()
    write(home / "state/home-summary.json", json.dumps({"counts": {"decisions_open": 3}}))
    write(home / "state/fix-login.meta", "kind=ship\npr=https://github.com/o/app/pull/11\n")
    write(home / "state/fix-docs.meta", "kind=ship\npr=https://github.com/o/app/pull/12\n")
    write(home / "state/old.meta", "kind=ship\npr=https://github.com/o/app/pull/13\n")
    # Second-level homes: one with a live Space (w1) and one without (w9). The
    # stub fold reports two open decisions for each.
    write(home / "state/docs-mate-d1.meta", "kind=secondmate\nherdr_workspace_id=w1\n")
    write(home / "state/gone-mate-g1.meta", "kind=secondmate\nherdr_workspace_id=w9\n")
    write(home / "state/docs-mate-d1.status", "")
    write(home / "state/gone-mate-g1.status", "")
    write(home / "bin/fm-classify-lib.sh", "status_open_decisions() { printf 'a\\tneeds-decision\\tx\\nb\\tblocked\\ty\\n'; }\n")
    write(home / "bin/fm-tasks-axi.sh", "#!/bin/sh\n[ \"$1\" = ready ] && echo 'count: 4'\n", 0o755)
    write(home / "bin/fm-supervision-lib.sh", "fm_supervision_unhealthy() { return 0; }\n")

    stub = tmp_path / "stub"
    log = tmp_path / "reports.jsonl"
    workspaces = [
        {"workspace_id": "w1", "label": "2ndmate-docs-mate-d1"},
        {"workspace_id": "w2", "label": "firstmate-afk-daemon-1-2-3"},
    ]
    panes = [
        {"workspace_id": "w1", "cwd": str(home / "projects/app")},
        {"workspace_id": "w2", "cwd": str(home)},
    ]
    write(
        stub / "herdr",
        f"""#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if a[:2] == ["workspace", "list"]:
    print(json.dumps({{"result": {{"workspaces": {json.dumps(workspaces)}}}}}))
elif a[:2] == ["pane", "list"]:
    print(json.dumps({{"result": {{"panes": {json.dumps(panes)}}}}}))
elif a[:2] == ["workspace", "report-metadata"]:
    with open({str(log)!r}, "a") as f:
        f.write(json.dumps(a[2:]) + "\\n")
""",
        0o755,
    )
    # PR 11 green, PR 12 red, PR 13 merged.
    write(
        stub / "gh",
        """#!/usr/bin/env python3
import json, sys
path = sys.argv[2]
if "/check-runs" in path:
    sha = path.split("/commits/")[1].split("/")[0]
    conclusion = {"s11": "success", "s12": "failure"}[sha]
    print(json.dumps({"check_runs": [{"conclusion": conclusion}, {"conclusion": "skipped"}]}))
else:
    n = path.rsplit("/", 1)[1]
    print(json.dumps({"state": "closed" if n == "13" else "open", "head": {"sha": "s" + n}}))
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
    assert docs == {
        "short": "docs",
        # 3 in the ledger, less the 2 of the second-level home with its own
        # Space; the home without a live Space stays counted here.
        "decisions": "⚑ 1",
        "crew": "▶ 3",
        "queue": "◷ 4",
        "prs": "⎇ 2",
        "ci_ok": "✓1",
        "ci_bad": "✗1",
        "alert": BLANK * 2 + "⚠ watcher silent",
    }
    assert res.startswith(BLANK * 2 + "ram ") and " disk " in res
    # A helper space shows its short name only; everything else is cleared.
    assert reported["w2"] == {"short": "☾ afk"} | dict.fromkeys(spaces.TOKENS[1:])

    # Second run: CPU has a baseline now, a zero count is cleared, and a failed
    # source keeps its previous value.
    (home / "state/home-summary.json").unlink()
    write(home / "bin/fm-supervision-lib.sh", "fm_supervision_unhealthy() { return 1; }\n")
    docs = run()["w1"]
    assert docs["decisions"] == "⚑ 1"
    assert docs["alert"] is None
    assert docs["res"].startswith(BLANK * 2 + "cpu ")


def test_reporter_waits_out_a_failed_disk_measurement(fixture, tmp_path):
    _, run = fixture
    calls = tmp_path / "du-calls"
    write(tmp_path / "stub/du", f"#!/bin/sh\necho x >> {calls}\nexit 1\n", 0o755)
    assert " disk " not in run()["w1"]["res"]
    assert " disk " not in run()["w1"]["res"]
    assert len(calls.read_text().splitlines()) == 1
