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


@pytest.mark.parametrize("option", ["--help", "-h"])
def test_help_sends_nothing(tmp_path, option):
    result, calls = send(tmp_path, option)
    assert result.returncode == 0
    assert "Usage: fm-imessage" in result.stdout
    assert calls == []


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_desk_decisions():
    code = f"""
import {{ noteText, parseReact }} from {json.dumps(str(ROOT / "imessage/desk.ts"))};
const contents = [
  {{ type: "text", text: "ship it" }},
  {{ type: "attachment", name: "a.png" }},
  {{ type: "voice" }},
  {{ type: "contact", name: {{ formatted: "Ana" }} }},
  {{ type: "contact" }},
  {{ type: "richlink", url: "https://example.com" }},
  {{ type: "reaction" }},
  {{ type: "typing" }},
  {{ type: "read" }},
  {{ type: "edit" }},
];
const answers = ["REACT:👍", "REACT: ❤️ ", "REACT:👍 thanks", "Got it, passing this on.", "ok REACT:👍"];
console.log(JSON.stringify({{
  notes: contents.map((c) => noteText(c, "/state/attachments/1-a.png") ?? null),
  reacts: answers.map((a) => parseReact(a) ?? null),
}}));
"""
    out = subprocess.run(
        ["bun", "-e", code], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    result = json.loads(out)
    assert result["notes"] == [
        "ship it",
        "(sent an attachment, saved for Firstmate at /state/attachments/1-a.png)",
        "(sent a voice message)",
        "(sent a contact: Ana)",
        "(sent a contact: no name)",
        "https://example.com",
        None,
        None,
        None,
        None,
    ]
    assert result["reacts"] == ["👍", "❤️", None, None, None]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_service_refuses_foreign_requests():
    code = f"""
import {{ localCommand }} from {json.dumps(str(ROOT / "imessage/desk.ts"))};
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
"""
    out = subprocess.run(
        ["bun", "-e", code], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    assert json.loads(out) == [True, False, False, False, False, False, False]


@pytest.mark.parametrize("args", [("hello",), ("--typing",), ("--react", "👍")])
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
