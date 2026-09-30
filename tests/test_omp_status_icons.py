"""config/omp-status-icons.ts, run under bun with a fake omp extension API.

omp's `status` segment strips every escape sequence from extension statuses
and paints the whole segment in one color, so a mode's state has to show in
the text itself, not in its styling.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CAVEMAN, ADHD, PONYTAIL = "\uf066", "\U000f09d1", "\uf0c4"


def row(home: Path, statuses: dict) -> str:
    """The icons row as omp's status segment shows it."""
    ext = json.dumps(str(ROOT / "config/omp-status-icons.ts"))
    code = f"""
import ext from {ext};
const shown = {{}};
const ui = {{ theme: {{ fg: (c, s) => `\\x1b[2m${{s}}\\x1b[22m` }}, setStatus(k, t) {{ shown[k] = t; }} }};
const on = {{}};
ext({{ on: (e, f) => (on[e] = f) }});
on.session_start({{}}, {{ hasUI: true, cwd: {json.dumps(str(home))}, ui }});
for (const [k, t] of Object.entries({json.dumps(statuses)})) ui.setStatus(k, t ?? undefined);
console.log(JSON.stringify(shown["aa-modes"] ?? ""));
"""
    out = subprocess.run(
        ["bun", "-e", code], capture_output=True, text=True, check=True, env={"HOME": str(home), "PATH": os.environ["PATH"]}
    )
    return re.sub(r"\x1b\[[0-9;]*m", "", json.loads(out.stdout))


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_off_modes_are_not_shown_and_on_modes_are(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/.caveman-active").write_text("off\n")
    shown = row(tmp_path, {"ponytail": "🐴 ponytail: ⚡ FULL", "i-have-adhd": None})
    assert PONYTAIL in shown
    assert CAVEMAN not in shown
    assert ADHD not in shown

    (tmp_path / ".claude/.caveman-active").write_text("on\n")
    shown = row(tmp_path, {"ponytail": "", "i-have-adhd": "● ADHD ON"})
    assert CAVEMAN in shown
    assert ADHD in shown
    assert PONYTAIL not in shown


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_ponytail_stays_shown_while_idle(tmp_path):
    # ponytail FULL shows "○" between turns; only mode off sends "".
    assert PONYTAIL in row(tmp_path, {"ponytail": "🐴 ponytail: ○"})
