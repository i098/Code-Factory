"""super.env sync pieces with fake values: splitter round trip, Worker auth, fetch script.

The Worker runs under Node with a stubbed Access certs endpoint and an RSA key made per run.
"""

import http.server
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WORKER = ROOT / "workers/fleet-secrets"
FAKE_ENV = (
    "# fake super.env\n"
    "A=plain value with = and # inside\n"
    'QUOTED="double quoted"\n'
    "SINGLE='single'\n"
    "\n"
    "DUP=first\n"
    "#DEAD=commented values stay in the layout\n"
    'LONE="unbalanced\n'
    "DUP=last \u00e9\n"
    "FLEET_SECRETS_ACCESS_CLIENT_ID=client-1\n"
    "NO_NEWLINE=end"
)

HARNESS = """
import worker from "%s";
const { secrets, layout } = JSON.parse(process.argv[1]);
const algo = { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" };
const gen = () => crypto.subtle.generateKey(
  { ...algo, modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]) }, true,
  ["sign", "verify"]);
const [good, evil] = [await gen(), await gen()];
const jwk = { ...(await crypto.subtle.exportKey("jwk", good.publicKey)), kid: "k1" };
globalThis.fetch = async (url) => {
  if (url !== "https://team.example/cdn-cgi/access/certs") throw new Error(url);
  return Response.json({ keys: [jwk] });
};
const b64 = (b) => Buffer.from(b).toString("base64url");
async function jwt(claims, key = good.privateKey) {
  const head = b64(JSON.stringify({ alg: "RS256", kid: "k1" }));
  const body = b64(JSON.stringify(claims));
  const sig = await crypto.subtle.sign(algo, key, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64(sig)}`;
}
const env = { team_domain: "team.example", aud: "aud-1",
  super_env_layout: { get: async () => JSON.stringify(layout) } };
for (const [k, v] of Object.entries(secrets)) env[k] = { get: async () => v };
const now = Date.now() / 1000;
const ok = { iss: "https://team.example", aud: ["aud-1"], exp: now + 60, nbf: now - 1,
  common_name: "client-1" };
const cases = {
  valid: await jwt(ok),
  none: null,
  garbage: "a.b.c",
  wrong_aud: await jwt({ ...ok, aud: ["other"] }),
  wrong_client: await jwt({ ...ok, common_name: "other" }),
  email_identity: await jwt({ ...ok, common_name: undefined, email: "x@example.com" }),
  wrong_issuer: await jwt({ ...ok, iss: "https://evil.example" }),
  expired: await jwt({ ...ok, exp: now - 1 }),
  not_yet: await jwt({ ...ok, nbf: now + 60 }),
  wrong_key: await jwt(ok, evil.privateKey),
};
const out = {};
for (const [name, token] of Object.entries(cases)) {
  const headers = token ? { "Cf-Access-Jwt-Assertion": token } : {};
  const r = await worker.fetch(new Request("https://x/", { headers }), env);
  out[name] = { status: r.status, cache: r.headers.get("cache-control"), body: await r.text() };
}
const post = new Request("https://x/", { method: "POST",
  headers: { "Cf-Access-Jwt-Assertion": cases.valid } });
out.post = { status: (await worker.fetch(post, env)).status };
console.log(JSON.stringify(out));
"""


def split(text: str) -> dict:
    result = subprocess.run(
        ["jq", "-Rs", "-f", WORKER / "split.jq"],
        input=text.encode(),
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_split_names_one_secret_per_assignment():
    secrets = split(FAKE_ENV)["secrets"]
    assert secrets == {
        "A": "plain value with = and # inside",
        "QUOTED": "double quoted",
        "SINGLE": "single",
        "DUP__1": "first",
        "LONE": '"unbalanced',
        "DUP": "last \u00e9",
        "NO_NEWLINE": "end",
        "FLEET_SECRETS_ACCESS_CLIENT_ID": "client-1",
    }


@pytest.mark.parametrize("line", ["EMPTY=", "super_env_layout=x", f"BIG={'x' * 65537}"])
def test_split_refuses_values_the_store_cannot_hold(line):
    with pytest.raises(subprocess.CalledProcessError):
        split(line + "\n")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_worker_serves_exact_file_only_to_the_service_token():
    harness = HARNESS % (WORKER / "index.js").as_uri()
    result = subprocess.run(
        ["node", "--input-type=module", "-e", harness, json.dumps(split(FAKE_ENV))],
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(result.stdout)
    assert out["valid"] == {"status": 200, "cache": "no-store", "body": FAKE_ENV}
    for name, r in out.items():
        if name != "valid":
            assert r["status"] == 403, name
            assert r.get("body", "") == "", name


class Fake(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        good = (
            self.headers["CF-Access-Client-Id"] == "fake-id"
            and self.headers["CF-Access-Client-Secret"] == "fake-secret"
        )
        body = FAKE_ENV.encode() if good else b"denied"
        self.send_response(200 if good else 403)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()


def fetch(tmp_path: Path, url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ROOT / "scripts/fetch-secrets.sh"],
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "FLEET_SECRETS_URL": url},
        capture_output=True,
        text=True,
    )


def test_fetch_writes_mode_600_from_credentials_file(tmp_path, server):
    creds = tmp_path / ".config/fleet-secrets.env"
    creds.parent.mkdir()
    creds.write_text(
        "FLEET_SECRETS_ACCESS_CLIENT_ID=fake-id\nFLEET_SECRETS_ACCESS_CLIENT_SECRET=fake-secret"
    )
    creds.chmod(0o644)
    assert fetch(tmp_path, server).returncode != 0
    assert not (tmp_path / "super.env").exists()

    creds.chmod(0o600)
    result = fetch(tmp_path, server)
    assert result.returncode == 0, result.stderr
    dest = tmp_path / "super.env"
    assert dest.read_text() == FAKE_ENV
    assert dest.stat().st_mode & 0o777 == 0o600
    assert "fake-secret" not in result.stdout + result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == [".config", "super.env"]


def test_fetch_failure_leaves_existing_file(tmp_path, server):
    creds = tmp_path / ".config/fleet-secrets.env"
    creds.parent.mkdir()
    creds.write_text(
        "FLEET_SECRETS_ACCESS_CLIENT_ID=fake-id\nFLEET_SECRETS_ACCESS_CLIENT_SECRET=wrong\n"
    )
    creds.chmod(0o600)
    dest = tmp_path / "super.env"
    dest.write_text("OLD=1\n")
    result = fetch(tmp_path, server)
    assert result.returncode != 0
    assert "403" in result.stderr
    assert dest.read_text() == "OLD=1\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".config", "super.env"]
