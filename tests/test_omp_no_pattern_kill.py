"""config/omp-no-pattern-kill.ts, run under bun: which commands it blocks."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

BLOCKED = [
    "pkill -f 'ponytail-review main'",
    "sleep 1; killall node",
    "pgrep -f omp | xargs kill",
    "kill $(pgrep -f herdr)",
    "kill `pgrep omp`",
    "/usr/bin/pkill -f omp",
    "cd /tmp && /bin/killall node",
    "sudo -n pkill node",
    "FOO=1 pkill node",
    "if true; then pkill node; fi",
    "echo hi\npkill -f omp",
    "ps aux | grep omp | awk '{print $2}' | xargs kill",
    "kill $(pidof omp)",
    "pgrep omp | while read p; do kill $p; done",
]
ALLOWED = [
    'cmd & pid=$!; kill "$pid"',
    "kill 12345",
    "pgrep -f omp",
    "ls ./pkill-notes",
    "grep -rn pkill docs/",
    "rg killall",
    'git commit -m "drop pkill use"',
    "man pkill",
]
EVAL_BLOCKED = [
    'import subprocess\nsubprocess.run(["pkill", "-f", "omp"])',
    'import os\nos.system("killall node")',
    "await Bun.$`pkill -f omp`",
]
EVAL_ALLOWED = [
    'import subprocess\nsubprocess.run(["grep", "-rn", "pkill", "docs"])',
    'print("docs about pkill")',
]


def blocked(tool: str, text: str) -> bool:
    ext = json.dumps(str(ROOT / "config/omp-no-pattern-kill.ts"))
    field = "code" if tool == "eval" else "command"
    code = f"""
import ext from {ext};
let handler;
ext({{ on: (_event, h) => (handler = h) }});
const result = await handler({{ toolName: {json.dumps(tool)}, input: {{ {field}: {json.dumps(text)} }} }});
console.log(JSON.stringify(result.block === true));
"""
    out = subprocess.run(["bun", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_pattern_kills(command):
    assert blocked("bash", command)


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_pid_kills_and_mentions(command):
    assert not blocked("bash", command)


@pytest.mark.parametrize("code", EVAL_BLOCKED)
def test_blocks_pattern_kills_in_eval_code(code):
    assert blocked("eval", code)


@pytest.mark.parametrize("code", EVAL_ALLOWED)
def test_allows_mentions_in_eval_code(code):
    assert not blocked("eval", code)


def test_ignores_other_tools():
    assert not blocked("read", "pkill -f anything")
