"""The iMessage bridge (docs/imessage.md): the send command's options and the service's pure decisions.

No test talks to Photon: curl is a stand-in that records its arguments, imessage/desk.ts holds
the decisions bridge.ts makes, free of spectrum-ts, and the outage test runs bridge.ts against a
fake spectrum-ts whose upstream returns UNAVAILABLE.
"""

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import time
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
        "(sent an attachment that could not be saved yet; the bridge retries the download and files this note again with the path)",
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
  const d = new DeskTiming(4000, (current) => turns.push(current), c);
  return {{ c, d, turns }};
}}
const out = {{}};
{{ // quiet period
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(3999);
  out.beforeQuiet = turns.length;
  c.advance(1);
  out.afterQuiet = turns.length; out.current = turns[0]();
}}
{{ // a burst: each text restarts the wait, one turn for all of it
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(2500); d.inboundText(); c.advance(2500);
  out.burstEarly = turns.length;
  c.advance(1500); c.advance(60000);
  out.burstTurns = turns.length;
}}
{{ // Firstmate active before the quiet period ends: no turn; his next text starts a new one
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(1500); d.firstmateActive(); c.advance(60000);
  out.standDown = turns.length;
  d.inboundText(); c.advance(4000);
  out.nextBurst = turns.length; out.nextCurrent = turns[0]();
}}
{{ // the draft is dropped when Firstmate or a newer text arrives while the desk writes
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(4000); d.firstmateActive();
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


MEMORY = json.dumps(str(ROOT / "imessage/memory.ts"))


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_memory_merges_in_push_order():
    """With the rollback push's list length as the budget, the view makes exactly the merges push makes."""
    result = bun(f"""
import {{ shrink }} from {MEMORY};
function push(n, s) {{
  if (s === null) return {{ keep: 0, life: 0, state: n, older: null }};
  const {{ keep, life, state, older }} = s;
  if (keep === 0) return {{ keep: 1, life, state, older }};
  if (life > 0) return {{ keep: 0, life: 0, state: n, older: {{ keep: 0, life: life - 1, state, older }} }};
  return {{ keep: 0, life, state: n, older: push(state, older) }};
}}
let s = null, view = [], bad = [];
for (let t = 0; t <= 2000; t++) {{
  s = push(t, s);
  const starts = [];
  for (let x = s; x; x = x.older) starts.unshift(x.state);
  const want = starts.map((a, k) => {{ const n = (starts[k + 1] ?? t + 1) - a; return [Math.log2(n), a / n]; }});
  view.push([0, t]);
  shrink(view, t + 1, want.length, () => 1, () => true);
  if (JSON.stringify(view) !== JSON.stringify(want)) bad.push(t);
}}
console.log(JSON.stringify(bad));
""")
    assert result == []


# A fake desk model: each conversation answers with lines of the lengths in `sizes`, one per turn.
FAKE = """
import { readdirSync, readFileSync } from "node:fs";
const calls = [];
function fake(sizes) {
  return () => {
    const turns = [];
    calls.push(turns);
    return { say: async (text) => { turns.push(text); return "x".repeat(sizes[Math.min(turns.length, sizes.length) - 1]); }, end() {} };
  };
}
async function idle(m) { while (m.pending) await Bun.sleep(0); }
const files = (dir) => Object.fromEntries(["main", "tree"].flatMap((sub) =>
  readdirSync(`${dir}/${sub}`).map((f) => [`${sub}/${f}`, readFileSync(`${dir}/${sub}/${f}`, "utf8")])).concat([["view.json", readFileSync(`${dir}/view.json`, "utf8")]]));
"""


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_memory_view_is_a_sawtooth(tmp_path):
    """The view grows one line per message and, past VIEW_MAX, drops back to at most VIEW_MIN in one batch."""
    result = bun(f"""
import {{ Memory, VIEW_MAX, VIEW_MIN }} from {MEMORY};
{FAKE}
const m = new Memory({json.dumps(str(tmp_path))}, fake([400]));
const sizes = [];
for (let n = 0; n < 3000; n++) {{
  m.append(["owner", "supervisor", "desk"][n % 3], `text ${{n}} `.padEnd(100, "."));
  sizes.push(Buffer.byteLength(m.render()));
  await idle(m);
}}
const drops = sizes.flatMap((s, k) => (k && s < sizes[k - 1] ? [s] : []));
const covered = m.view.reduce((s, [l]) => s + 2 ** l, 0);
console.log(JSON.stringify({{ max: Math.max(...sizes), drops, covered, VIEW_MAX, VIEW_MIN }}));
""")
    assert result["max"] <= result["VIEW_MAX"]
    assert len(result["drops"]) >= 2
    assert all(drop <= result["VIEW_MIN"] for drop in result["drops"])
    assert result["covered"] == 3000


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_memory_survives_a_restart(tmp_path):
    """The log, the tree and the view load back unchanged; nothing is rebuilt; zoom opens lines from disk."""
    result = bun(f"""
import {{ load, Memory, zoom }} from {MEMORY};
{FAKE}
const dir = {json.dumps(str(tmp_path))};
const a = new Memory(dir, fake([300]));
for (let n = 0; n < 40; n++) {{ a.append(n % 2 ? "desk" : "owner", n === 5 ? "y".repeat(900) : `text ${{n}}`); await idle(a); }}
const before = files(dir), callsBefore = calls.length;
const b = new Memory(dir, fake([300]));
await idle(b);
const after = files(dir);
const view = JSON.stringify(a.view) === JSON.stringify(b.view) && a.render() === b.render();
const id = b.append("owner", "after restart");
const disk = load(dir);
console.log(JSON.stringify({{
  same: JSON.stringify(before) === JSON.stringify(after),
  view,
  newCalls: calls.length - callsBefore,
  id,
  long: zoom(disk.msgs, disk.nodes, 5, 1),
  pair: zoom(disk.msgs, disk.nodes, 0, 2),
  bad: zoom(disk.msgs, disk.nodes, 3, 2),
}}));
""")
    assert result["same"] and result["view"]
    assert result["newCalls"] == 0
    assert result["id"] == 40
    assert result["long"].endswith(" desk: " + "y" * 900)
    assert result["pair"] == "0+1|owner: text 0\n1+1|desk: text 1"
    assert result["bad"].startswith("no line 3+2")


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_memory_nodes_fit_the_limit(tmp_path):
    """A line over LIMIT is asked again in the same conversation, at most TRIES calls, and every node fits."""
    result = bun(f"""
import {{ LIMIT, Memory, TRIES }} from {MEMORY};
{FAKE}
const shrinking = new Memory({json.dumps(str(tmp_path / "a"))}, fake([2000, 1000, 500]));
shrinking.append("owner", "z".repeat(3000)); await idle(shrinking);
const stubborn = new Memory({json.dumps(str(tmp_path / "b"))}, fake([2000, 1500, 900, 700, 600, 100]));
stubborn.append("owner", "z".repeat(3000)); await idle(stubborn);
const sizes = [...shrinking.nodes.values(), ...stubborn.nodes.values()].map((n) => n.size);
console.log(JSON.stringify({{ turns: calls.map((c) => c.length), sizes, LIMIT, TRIES, retry: calls[0][1] }}));
""")
    assert result["turns"] == [3, result["TRIES"]]
    assert result["sizes"] == [500, result["LIMIT"]]
    assert result["retry"].startswith("Too long: your line is 2000 bytes, over the 512-byte limit.")


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_desk_call_stays_under_the_ceiling():
    """A desk prompt with huge status and texts, plus every zoom result, never passes CEILING bytes."""
    result = bun(f"""
import {{ deskInput }} from {DESK};
import {{ Budget, CEILING, LIMIT_REACHED, OVERHEAD, ZOOM_MAX, ZOOM_RESERVE }} from {MEMORY};
const system = "s".repeat(3000), view = "v".repeat(400000); // a view grown past VIEW_MAX by a compaction outage
const {{ prompt, spent }} = deskInput(system, view, "q".repeat(500000), "HEAD" + "m".repeat(1000000) + "TAIL");
const budget = new Budget(spent);
const results = [], requests = [spent];
for (let k = 0; k < 100; k++) {{
  const r = budget.take("ZOOMHEAD" + "z".repeat(100000) + "ZOOMTAIL");
  if (r === undefined) break;
  results.push(r);
  requests.push(budget.spent);
}}
console.log(JSON.stringify({{
  first: spent, own: OVERHEAD + Buffer.byteLength(system + prompt), keepsEnds: prompt.includes("HEAD") && prompt.includes("TAIL"),
  maxRequest: Math.max(...requests), zoomSizes: results.map((r) => Buffer.byteLength(r)), zoomEnds: results[0].startsWith("ZOOMHEAD") && results[0].endsWith("ZOOMTAIL"),
  refused: results.includes(LIMIT_REACHED), CEILING, ZOOM_MAX, ZOOM_RESERVE,
}}));
""")
    assert result["first"] == result["own"] <= result["CEILING"] - result["ZOOM_RESERVE"]
    assert result["keepsEnds"] and result["zoomEnds"]
    assert result["maxRequest"] <= result["CEILING"]
    assert all(size <= result["ZOOM_MAX"] for size in result["zoomSizes"])
    assert result["refused"]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_compaction_stays_under_the_ceiling(tmp_path):
    """One huge message is clipped head and tail, and retries stop before a request passes CEILING bytes."""
    result = bun(f"""
import {{ CEILING, LIMIT, Memory, OVERHEAD }} from {MEMORY};
const requests = [], firsts = [];
const chat = (system) => {{
  let sent = Buffer.byteLength(system) + OVERHEAD;
  return {{
    async say(text) {{
      sent += Buffer.byteLength(text);
      requests.push(sent);
      if (requests.length === 1) firsts.push(text);
      const reply = "r".repeat(3000); // a model that never fits
      sent += Buffer.byteLength(reply);
      return reply;
    }},
    end() {{}},
  }};
}};
const m = new Memory({json.dumps(str(tmp_path))}, chat);
m.append("owner", "HEAD" + "m".repeat(1000000) + "TAIL");
while (m.pending) await Bun.sleep(0);
console.log(JSON.stringify({{
  requests, CEILING, keepsEnds: firsts[0].includes("owner: HEAD") && firsts[0].includes("TAIL\\n</input>"),
  size: m.nodes.get("0:0").size, LIMIT,
}}));
""")
    assert len(result["requests"]) >= 2
    assert max(result["requests"]) <= result["CEILING"]
    assert result["keepsEnds"]
    assert result["size"] <= result["LIMIT"]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_compaction_stays_under_the_ceiling_when_the_model_keeps_failing(tmp_path):
    """Short messages and a model that always throws leave the context unmerged; its request is still clipped."""
    result = bun(f"""
import {{ CEILING, Memory }} from {MEMORY};
let largest = 0;
const chat = () => ({{
  async say(text) {{ largest = Math.max(largest, Buffer.byteLength(text)); throw new Error("down"); }},
  end() {{}},
}});
const m = new Memory({json.dumps(str(tmp_path))}, chat);
for (let i = 0; i < 900; i++) m.append("owner", "x".repeat(260));
while (m.pending) await Bun.sleep(0);
console.log(JSON.stringify({{ largest, CEILING }}));
""")
    assert 0 < result["largest"] <= result["CEILING"]


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
    spec = importlib.util.spec_from_file_location("factory_imessage", ROOT / "scripts/ship.py")
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


OUTBOX = json.dumps(str(ROOT / "imessage/outbox.ts"))


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_transient_upstream_errors():
    """gRPC UNAVAILABLE in its two shapes, HTTP 502 and 503, and a wrapped cause are transient; others are not."""
    result = bun(f"""
import {{ brief, transient }} from {OUTBOX};
const err = (message, extra) => Object.assign(new Error(message), extra);
const cases = [
  err("/photon.imessage.v1.MessageService/Send UNAVAILABLE: [upstream] Service temporarily unavailable. Please retry.", {{ code: 14 }}),
  err("[upstream] Service temporarily unavailable. Please retry.", {{ grpcCode: 14 }}),
  err("Bad Gateway", {{ status: 502 }}),
  err("Service Unavailable", {{ status: 503 }}),
  err("send failed", {{ cause: err("down", {{ grpcCode: 14 }}) }}),
  err("Target not allowed for this project", {{ grpcCode: 7 }}),
  err("Internal Server Error", {{ status: 500 }}),
  "unavailable",
];
console.log(JSON.stringify({{ codes: cases.map((e) => transient(e) ?? null), line: brief(err("first\\nsecond", {{ grpcCode: 14 }})) }}));
""")
    assert result["codes"] == ["UNAVAILABLE", "UNAVAILABLE", "HTTP 502", "HTTP 503", "UNAVAILABLE", None, None, None]
    assert result["line"] == "UNAVAILABLE: first"


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_timeouts_and_dropped_connections_are_transient():
    result = bun(f"""
import {{ transient }} from {OUTBOX};
const err = (message, extra) => Object.assign(new Error(message), extra);
const codes = ["ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "EAI_AGAIN", "ENOTFOUND", "ENETUNREACH", "EHOSTUNREACH", "EPIPE"];
const cases = [
  Object.assign(new Error("The operation timed out"), {{ name: "TimeoutError" }}),
  ...codes.map((code) => err(`connect ${{code}}`, {{ code }})),
  err("deadline", {{ grpcCode: 4 }}),
  err("Gateway Timeout", {{ status: 504 }}),
  err("fetch failed", {{ cause: err("socket hang up") }}),
  err("The socket connection was closed unexpectedly"),
  err("the inbox note failed", {{ retry: true }}),
  err("message m1 not found"),
  err("Target not allowed for this project", {{ grpcCode: 7 }}),
  new SyntaxError("JSON Parse error: Unexpected identifier"),
];
console.log(JSON.stringify(cases.map((e) => transient(e) ?? null)));
""")
    assert result == ["TIMEOUT"] * 9 + ["TIMEOUT", "HTTP 504", "TIMEOUT", "TIMEOUT", "RETRY", None, None, None]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_queue_moves_items_that_cannot_pass_to_the_dead_letter_folder(tmp_path):
    """A transient failure retries the same item in order; any other failure or a corrupt file never blocks the rest."""
    queue = tmp_path / "queue"
    queue.mkdir()
    (queue / "1.json").write_text('{"v":"bad"}')
    (queue / "2.json").write_text("{not json")
    (queue / "3.json").write_text('{"v":"flaky"}')
    (queue / "4.json").write_text('{"v":"ok"}')
    result = bun(f"""
import {{ readdirSync }} from "node:fs";
import {{ Queue }} from {OUTBOX};
const done = [], tries = {{}};
const q = new Queue({json.dumps(str(queue))}, "item", async (item) => {{
  tries[item.v] = (tries[item.v] ?? 0) + 1;
  if (item.v === "bad") throw new Error("message m1 not found");
  if (item.v === "flaky" && tries.flaky < 3) throw Object.assign(new Error("down"), {{ grpcCode: 14 }});
  done.push(item.v);
}}, 5);
const end = Date.now() + 10000;
while (done.length < 2 && Date.now() < end) await Bun.sleep(10);
console.log(JSON.stringify({{ done, tries, left: readdirSync({json.dumps(str(queue))}), dead: readdirSync({json.dumps(str(queue) + "-dead")}).length }}));
process.exit(0);
""")
    assert result["done"] == ["flaky", "ok"]
    assert result["tries"] == {"bad": 1, "flaky": 3, "ok": 1}
    assert result["left"] == [] and result["dead"] == 2


# A fake spectrum-ts for bridge.ts. Its state is in FAKE_DIR, so it outlives a bridge restart: `down` holds how
# many more upstream calls fail with UNAVAILABLE, typing always fails while `typing-down` exists, `inbound/` holds
# the owner's messages for the bridge to receive, `calls` logs every call, and `sent` logs each delivered message.
FAKE_UPSTREAM = """
import { appendFileSync, existsSync, readdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
const dir = process.env.FAKE_DIR;
const unavailable = () => Object.assign(new Error("[upstream] Service temporarily unavailable. Please retry."), { name: "ConnectionError", grpcCode: 14 });
function call(op) {
  const left = Number(readFileSync(`${dir}/down`, "utf8"));
  appendFileSync(`${dir}/calls`, `${op} ${left > 0 ? "UNAVAILABLE" : "ok"}\\n`);
  if (left > 0) {
    writeFileSync(`${dir}/down`, String(left - 1));
    throw unavailable();
  }
}
async function typing() {
  appendFileSync(`${dir}/calls`, "typing UNAVAILABLE\\n");
  if (existsSync(`${dir}/typing-down`)) throw unavailable();
}
const sent = (line) => appendFileSync(`${dir}/sent`, `${line}\\n`);
const load = (id) => message(JSON.parse(readFileSync(`${dir}/messages/${id}.json`, "utf8")));
function space(id) {
  return {
    id,
    startTyping: typing,
    stopTyping: typing,
    async send(text) { call("send"); sent(`send ${text}`); },
    async getMessage(mid) { call("getMessage"); return load(mid); },
  };
}
function message(m) {
  return {
    id: m.id, direction: "inbound", sender: { id: m.sender }, space: space(m.space),
    content: m.name
      ? { type: "attachment", name: m.name, async read() { call("download"); return new TextEncoder().encode(m.data); } }
      : { type: "text", text: m.text },
    async react(emoji) { call("react"); sent(`react ${m.id} ${emoji}`); },
    async reply(text) { call("reply"); sent(`reply ${m.id} ${text}`); },
    async read() {},
  };
}
async function* messages() {
  for (;;) {
    for (const f of readdirSync(`${dir}/inbound`).sort()) {
      renameSync(`${dir}/inbound/${f}`, `${dir}/messages/${f}`);
      yield ["imessage", load(f.replace(/\\.json$/, ""))];
    }
    await Bun.sleep(20);
  }
}
export const Spectrum = async () => ({ messages: messages() });
export const imessage = Object.assign(() => ({ space: { get: async (id) => space(id) } }), { config: () => ({}) });
"""


def wait_for(check, what, timeout=30):
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end, f"timed out waiting for {what}"
        time.sleep(0.05)


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_bridge_rides_out_an_upstream_outage(tmp_path):
    """Sends, a tapback and an attachment outlive an UNAVAILABLE outage and a restart, then arrive in order."""
    app, fake, state, bin_dir = (tmp_path / d for d in ("app", "fake", "state", "bin"))
    shutil.copytree(ROOT / "imessage", app, ignore=shutil.ignore_patterns("fm-*"))
    pkg = app / "node_modules/spectrum-ts"
    pkg.mkdir(parents=True)
    exports = {".": "./index.js", "./providers/imessage": "./index.js"}
    (pkg / "package.json").write_text(json.dumps({"name": "spectrum-ts", "type": "module", "exports": exports}))
    (pkg / "index.js").write_text(FAKE_UPSTREAM)
    for d in (fake / "inbound", fake / "messages", bin_dir):
        d.mkdir(parents=True)
    (fake / "down").write_text("0")
    (fake / "typing-down").touch()
    notes = tmp_path / "notes"
    stubs = {
        "omp": f'cat >/dev/null; [ -e {fake / "desk-on"} ] && echo "desk ok" || echo SKIP',
        "fm-inbox": f'printf "%s\\n" "$*" >> {notes}',
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "FM_HOME": str(tmp_path),
        "FM_INBOX_CMD": str(bin_dir / "fm-inbox"),
        "FM_IMESSAGE_OWNER": "+10000000000",
        "FM_IMESSAGE_PORT": str(port),
        "FM_IMESSAGE_RETRY_MS": "20",
        "PHOTON_PROJECT_ID": "fake",
        "PHOTON_PROJECT_SECRET": "fake",
        "STATE_DIRECTORY": str(state),
    }
    out, err = tmp_path / "out", tmp_path / "err"
    text = lambda p: p.read_text() if p.exists() else ""  # noqa: E731

    def start(n):
        with out.open("a") as o, err.open("a") as e:
            bridge = subprocess.Popen(["bun", "bridge.ts"], cwd=app, env=env, stdout=o, stderr=e)
        wait_for(lambda: text(out).count("listening") == n, f"bridge start {n}")
        return bridge

    def inbound(mid, **fields):
        record = {"id": mid, "space": "chat-1", "sender": "+10000000000", **fields}
        (fake / "inbound" / f"{mid}.json").write_text(json.dumps(record))
        wait_for(lambda: f"photon-{mid} " in text(notes), f"the note for {mid}")

    def cli(*args):
        result = subprocess.run([str(SEND), *args], capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout

    bridge = start(1)
    try:
        inbound("m1", text="you there")
        (fake / "down").write_text("1000000")  # the outage begins
        assert cli("one\n\ntwo").startswith("queued 2 bubble(s)")
        assert cli("--react", "👍").startswith("queued tapback")
        assert cli("--reply", "1", "three").startswith("queued 1 bubble(s)")
        cli("--typing")
        inbound("m2", name="photo.jpg", data="JPEG")
        assert "could not be saved yet" in text(notes)
        wait_for(lambda: "outbox item 1 failed (try 2)" in text(err), "an outbox retry")
        wait_for(lambda: "attachment download 1 failed (try 2)" in text(err), "a download retry")
        bridge.terminate()  # a restart in the middle of the outage
        bridge.wait(10)
        assert len(list((state / "outbox").glob("*.json"))) == 3
        assert len(list((state / "downloads").glob("*.json"))) == 1
        bridge = start(2)
        cli("four")
        (fake / "desk-on").touch()
        inbound("m3", text="ping")
        inbound("m4", text="ping again")  # nobody answers, so the desk writes a late ack into the queue
        wait_for(lambda: len(list((state / "outbox").glob("*.json"))) == 5, "the desk item in the outbox")
        (fake / "down").write_text("3")  # three more failures, then the upstream recovers
        wait_for(lambda: len(text(fake / "sent").splitlines()) == 6 and "photon-m2-saved" in text(notes), "recovery")
        (fake / "messages" / "m3.json").unlink()  # the text that a threaded send points to is gone
        cli("--reply", "2", "five")
        wait_for(lambda: len(text(fake / "sent").splitlines()) == 7, "the unthreaded send")
    finally:
        bridge.terminate()
        bridge.wait(10)
    sent = ["send one", "send two", "react m1 👍", "reply m1 three", "send four", "send desk ok", "send five"]
    assert text(fake / "sent").splitlines() == sent
    assert "typing UNAVAILABLE" in text(fake / "calls")
    saved = state / "attachments/m2-photo.jpg"
    assert saved.read_text() == "JPEG"
    assert f"(an earlier attachment is saved now) (sent an attachment, saved for Firstmate at {saved})" in text(notes)
    assert list((state / "outbox").glob("*.json")) == [] and list((state / "downloads").glob("*.json")) == []
    logs = text(err)
    assert "UNAVAILABLE" in logs and not re.search(r"^\s+at ", logs, re.M), logs
