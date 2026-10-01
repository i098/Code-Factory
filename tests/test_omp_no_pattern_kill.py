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
    "bash -c 'pkill -f omp'",
    'sh -c "killall node"',
    "timeout 5 pkill -f omp",
    "nice pkill -f omp",
    "ssh host pkill -f omp",
    "docker exec c pkill node",
    "if pkill -f omp; then echo gone; fi",
    "! pkill -f omp",
    "sudo -u root pkill node",
    "echo omp | xargs -r pkill",
    "python3 -c \"import os; os.system('pkill -f x')\"",
    "kill -9 $(ps aux | grep omp | awk '{print $2}')",
    "kill `ps aux | grep omp | awk '{print $2}'`",
    "A='x' B=2 pkill -f omp",
    "ssh -p 22 host pkill -f omp",
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
    "docker ps -q | xargs docker kill",
    "command -v pkill",
    "git ls-files | xargs grep -n pkill",
    "ssh host grep pkill /etc/notes",
    "grep -c pkill docs/omp.md",
    'kill "$pid" && echo $(grep -c x f)',
    'git commit -m "pkill -f x"',
    "echo 'killall node'",
]
EVAL_BLOCKED = [
    'import subprocess\nsubprocess.run(["pkill", "-f", "omp"])',
    'import os\nos.system("killall node")',
    "await Bun.$`pkill -f omp`",
    "import subprocess\nsubprocess.run(['sh', '-c', 'pkill -f omp'])",
    'import subprocess\nsubprocess.run(\n    ["pkill", "-f", "omp"],\n    check=False,\n)',
    'import subprocess\nsubprocess.run(\n    "killall node",\n    shell=True,\n)',
    "const out = 1;\nawait Bun.$`\npkill -f omp\n`",
    'import subprocess\nsubprocess.run(["env", "A=1", "pkill", "-f", "omp"])',
]
EVAL_ALLOWED = [
    'import subprocess\nsubprocess.run(["grep", "-rn", "pkill", "docs"])',
    'print("docs about pkill")',
    'import shutil\nprint(shutil.which("pkill"))',
]
SLOW_INPUTS = [
    ("eval", "f(\n" + "".join(f"    field_{i}='value',\n" for i in range(40)) + ")"),
    ("eval", "f(" + ", ".join(f"a{i}=1" for i in range(40)) + ")"),
    ("eval", '["env", ' + ", ".join(f'"A{i}=1"' for i in range(40)) + "]"),
    ("eval", "[" + ", ".join(['"sh", "-c"'] * 40) + "]"),
    ("bash", " ".join(f'A{i}="x"' for i in range(40)) + " cmd"),
    ("bash", " ".join(["sudo -u"] * 40) + " cmd"),
    ("bash", " ".join(["grep"] * 20000) + " x"),
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
    out = subprocess.run(
        ["bun", "-e", code],
        capture_output=True,
        text=True,
        check=True,
        timeout=4,
    )
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


@pytest.mark.parametrize(("tool", "text"), SLOW_INPUTS)
def test_matching_stays_fast_on_inputs_that_match_nothing(tool, text):
    assert not blocked(tool, text)
