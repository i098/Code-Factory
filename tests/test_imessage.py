"""The iMessage bridge (docs/imessage.md): the send command's options and the service's pure decisions.

No test talks to Photon: curl is a stand-in that records its arguments, and imessage/desk.ts holds
the decisions bridge.ts makes, free of spectrum-ts.
"""

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SEND = ROOT / "imessage/fm-imessage"


def send(tmp_path, *args):
    """Run fm-imessage with a curl stand-in; return the result and the recorded curl calls."""
    calls = tmp_path / "curl-calls"
    (tmp_path / "curl").write_text(f'#!/bin/bash\necho "$*" >> {calls}\ncat >/dev/null\n')
    (tmp_path / "curl").chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(SEND), *args], input="", capture_output=True, text=True, env=env, timeout=10
    )
    return result, calls.read_text().splitlines() if calls.exists() else []


def test_text_goes_to_send(tmp_path):
    result, calls = send(tmp_path, "hello")
    assert result.returncode == 0
    assert len(calls) == 1 and calls[0].endswith("http://127.0.0.1:8765/send")


@pytest.mark.parametrize("option", ["--bogus", "-x", "--typo=1"])
def test_unknown_option_sends_nothing(tmp_path, option):
    result, calls = send(tmp_path, option, "hello")
    assert result.returncode == 2
    assert "nothing sent" in result.stderr
    assert calls == []


def test_reply_threads_to_an_earlier_text(tmp_path):
    result, calls = send(tmp_path, "--reply", "3", "that one")
    assert result.returncode == 0
    assert len(calls) == 1 and calls[0].endswith("http://127.0.0.1:8765/send?reply=3")


@pytest.mark.parametrize("n", [None, "", "0", "11", "-1", "2x", "03"])
def test_reply_needs_a_kept_text_number(tmp_path, n):
    result, calls = send(tmp_path, "--reply", *([n] if n is not None else []))
    assert result.returncode == 2
    assert "nothing sent" in result.stderr
    assert calls == []


@pytest.mark.parametrize("option", ["--help", "-h"])
def test_help_sends_nothing(tmp_path, option):
    result, calls = send(tmp_path, option)
    assert result.returncode == 0
    assert "Usage: fm-imessage" in result.stdout
    assert calls == []


DESK = json.dumps(str(ROOT / "imessage/desk.ts"))


def bun(code):
    """Run TypeScript that prints one JSON value; return the value."""
    out = subprocess.run(
        ["bun", "-e", code], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    return json.loads(out)


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_describe_unwraps_what_he_writes():
    result = bun(f"""
import {{ describe }} from {DESK};
const text = (t) => ({{ type: "text", text: t }});
const save = async (c, id) => {{ if (c.name === "bad.png") throw new Error("disk full"); return `/att/${{id}}-${{c.name}}`; }};
const contents = [
  text("ship it"),
  {{ type: "attachment", name: "a.png" }},
  {{ type: "attachment", name: "bad.png" }},
  {{ type: "contact", name: {{ formatted: "Ana" }} }},
  {{ type: "contact" }},
  {{ type: "reply", content: text("yes that one"), target: {{ content: text("deploy tonight?") }} }},
  {{ type: "reply", content: text("this"), target: {{ content: {{ type: "attachment" }} }} }},
  {{ type: "reply", content: {{ type: "reaction" }}, target: {{ content: text("x") }} }},
  {{ type: "edit", content: text("fixed typo") }},
  {{ type: "effect", content: text("boom") }},
  {{ type: "group", items: [{{ content: text("one") }}, {{ content: {{ type: "typing" }} }}, {{ content: {{ type: "attachment", name: "b.png" }} }}] }},
  {{ type: "group", items: [{{ content: {{ type: "read" }} }}] }},
  {{ type: "hologram" }},
  {{ type: "reaction" }},
  {{ type: "typing" }},
  {{ type: "read" }},
  {{ type: "unsend" }},
];
console.log(JSON.stringify(await Promise.all(contents.map(async (c) => (await describe(c, "m1", save)) ?? null))));
""")
    assert result == [
        "ship it",
        "(sent an attachment, saved for Firstmate at /att/m1-a.png)",
        "(sent an attachment that could not be saved)",
        "(sent a contact: Ana)",
        "(sent a contact: no name)",
        'yes that one (replying in a thread to: "deploy tonight?")',
        'this (replying in a thread to: "attachment")',
        None,
        "(edited a message to) fixed typo",
        "boom",
        "one\n(sent an attachment, saved for Firstmate at /att/m1-2-b.png)",
        None,
        "(sent a hologram message the bridge cannot show)",
        None,
        None,
        None,
        None,
    ]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_desk_answer_and_prompt():
    result = bun(f"""
import {{ deskPrompt, isSkip, parseReact }} from {DESK};
const answers = ["REACT:👍", "REACT: 🫡 ", "REACT:👍 thanks", "got it", "ok REACT:👍", "SKIP"];
const skips = ["skip", "Skip", "SKIP.", "skip!!", "skip it", "REACT:👍", "ok"];
console.log(JSON.stringify({{
  reacts: answers.map((a) => parseReact(a) ?? null),
  skips: skips.map(isSkip),
  named: deskPrompt("Ana", "desk-model-a", "boss-model-b"),
  unnamed: deskPrompt("the owner", "desk-model-a", ""),
}}));
""")
    assert result["reacts"] == ["👍", "🫡", None, None, None, None]
    assert result["skips"] == [True, True, True, True, False, False, False]
    assert "Ana's AI supervisor" in result["named"]
    assert "you're desk-model-a" in result["named"] and "Firstmate is boss-model-b" in result["named"]
    assert "say you don't know" in result["unnamed"]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bubbles_split_paragraphs_and_keep_lists():
    result = bun(f"""
import {{ bubbles, typingPause }} from {DESK};
console.log(JSON.stringify({{
  split: bubbles("on it\\n\\nschedule:\\n9am standup\\n2pm deploy\\n  \\n\\nlmk"),
  single: bubbles("  just one  "),
  empty: bubbles("\\n \\n"),
  pauses: [typingPause("ok"), typingPause("x".repeat(400))],
}}));
""")
    assert result["split"] == ["on it", "schedule:\n9am standup\n2pm deploy", "lmk"]
    assert result["single"] == ["just one"]
    assert result["empty"] == []
    assert result["pauses"] == [450, 2500]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_desk_timing():
    """The desk gets one turn per burst after a quiet period, and stands down for Firstmate or a newer text."""
    result = bun(f"""
import {{ DeskTiming }} from {DESK};
function clock() {{
  let now = 0, next = 1;
  const pending = new Map();
  return {{
    setTimeout: (fn, ms) => {{ pending.set(next, [now + ms, fn]); return next++; }},
    clearTimeout: (id) => pending.delete(id),
    advance(ms) {{
      now += ms;
      for (const [id, [at, fn]] of [...pending]) if (at <= now) {{ pending.delete(id); fn(); }}
    }},
  }};
}}
function desk() {{
  const c = clock(), turns = [];
  const d = new DeskTiming(8000, (current) => turns.push(current), c);
  return {{ c, d, turns }};
}}
const out = {{}};
{{ // quiet period
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(7999);
  out.beforeQuiet = turns.length;
  c.advance(1);
  out.afterQuiet = turns.length; out.current = turns[0]();
}}
{{ // a burst: each text restarts the wait, one turn for all of it
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(5000); d.inboundText(); c.advance(5000);
  out.burstEarly = turns.length;
  c.advance(3000); c.advance(60000);
  out.burstTurns = turns.length;
}}
{{ // Firstmate active before the quiet period ends: no turn; his next text starts a new one
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(3000); d.firstmateActive(); c.advance(60000);
  out.standDown = turns.length;
  d.inboundText(); c.advance(8000);
  out.nextBurst = turns.length; out.nextCurrent = turns[0]();
}}
{{ // the draft is dropped when Firstmate or a newer text arrives while the desk writes
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(8000); d.firstmateActive();
  out.firstmateWhileDrafting = turns[0]();
  d.inboundText(); c.advance(1000);
  out.newerWhileDrafting = turns[0]();
}}
console.log(JSON.stringify(out));
""")
    assert result == {
        "beforeQuiet": 0,
        "afterQuiet": 1,
        "current": True,
        "burstEarly": 0,
        "burstTurns": 1,
        "standDown": 0,
        "nextBurst": 1,
        "nextCurrent": True,
        "firstmateWhileDrafting": False,
        "newerWhileDrafting": False,
    }


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_service_refuses_foreign_requests():
    result = bun(f"""
import {{ localCommand }} from {DESK};
const h = (host, marker) => new Headers({{ ...(host ? {{ host }} : {{}}), ...(marker ? {{ "x-firstmate": marker }} : {{}}) }});
console.log(JSON.stringify([
  localCommand(h("127.0.0.1:8765", "1"), 8765),
  localCommand(h("127.0.0.1:8765"), 8765),
  localCommand(h("127.0.0.1:8765", "0"), 8765),
  localCommand(h("evil.example:8765", "1"), 8765),
  localCommand(h("localhost:8765", "1"), 8765),
  localCommand(h("127.0.0.1:9000", "1"), 8765),
  localCommand(h(undefined, "1"), 8765),
]));
""")
    assert result == [True, False, False, False, False, False, False]


@pytest.mark.parametrize("args", [("hello",), ("--reply", "1", "hi"), ("--typing",), ("--react", "👍")])
def test_send_commands_carry_the_local_header(tmp_path, args):
    result, calls = send(tmp_path, *args)
    assert result.returncode == 0
    assert len(calls) == 1 and "-H X-Firstmate: 1" in calls[0]


def test_location_carries_the_local_header(tmp_path):
    (tmp_path / "curl").write_text(f'#!/bin/bash\necho "$*" >> {tmp_path / "calls"}\n')
    (tmp_path / "curl").chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(ROOT / "imessage/fm-location")], capture_output=True, text=True, env=env, timeout=10
    )
    assert result.returncode == 0
    calls = (tmp_path / "calls").read_text().splitlines()
    assert len(calls) == 1 and "-H X-Firstmate: 1" in calls[0] and calls[0].endswith("/location")


def load_factory():
    spec = importlib.util.spec_from_file_location("factory_imessage", ROOT / "scripts/factory.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda f: f["profiles"].update(firstmate=False, fleet_guards=False), "firstmate profile"),
        (lambda f: f["imessage"].update(owner="5550100"), "imessage.owner"),
        (lambda f: f["imessage"].pop("owner"), "imessage"),
    ],
)
def test_config_rejects_a_bridge_it_cannot_run(change, error):
    document = yaml.safe_load((ROOT / "config/default.yml").read_text())
    document["factory"]["imessage"] = {"owner": "+10000000000"}
    load_factory().validate_config(document)
    change(document["factory"])
    with pytest.raises(ValueError, match=error):
        load_factory().validate_config(document)
