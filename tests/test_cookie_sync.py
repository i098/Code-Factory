"""fleet/browsers/cookie-sync.ts never fans Google cookies out between tiers.

Two file-only tiers run the real sync without a browser. The vnc tier holds a
Google sign-in and a GitHub session; the obscura tier holds nothing, and the
canonical jar still carries a Google cookie from an earlier sync. After one
sync the GitHub session reaches obscura, no Google cookie does, and vnc keeps
its own Google cookie.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cookie(name: str, domain: str, value: str = "v") -> dict:
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "expires": None,
    }


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_google_cookies_stay_in_their_tier(tmp_path: Path) -> None:
    vnc, obscura, state = tmp_path / "vnc.json", tmp_path / "obscura.json", tmp_path / "state"
    vnc.write_text(
        json.dumps(
            [
                cookie("__Secure-1PSID", ".google.com", "vnc-sid"),
                cookie("SID", ".youtube.com", "vnc-yt"),
                cookie("user_session", "github.com"),
            ]
        )
    )
    obscura.write_text(json.dumps([cookie("sb-auth-token", "localhost")]))
    state.mkdir()
    stale = cookie("SID", ".google.com", "stale-from-canonical")
    stale["expires"] = -1
    (state / "cookies.json").write_text(json.dumps({"google.com|/|SID": stale}))

    subprocess.run(
        [
            "bun",
            str(ROOT / "fleet/browsers/cookie-sync.ts"),
            "--state",
            str(state),
            f"obscura=file://{obscura}",
            f"vnc=file://{vnc}",
        ],
        check=True,
    )

    got_obscura = {c["name"]: c for c in json.loads(obscura.read_text())}
    got_vnc = {(c["domain"], c["name"]): c["value"] for c in json.loads(vnc.read_text())}
    assert set(got_obscura) == {"user_session", "sb-auth-token"}, (
        "Google cookie pushed into another tier"
    )
    # vnc's file is rewritten to receive sb-auth-token, so its Google cookies must survive the rewrite.
    assert ("localhost", "sb-auth-token") in got_vnc, "normal cookie did not sync"
    assert got_vnc[(".google.com", "__Secure-1PSID")] == "vnc-sid", (
        "Google cookie deleted from its tier"
    )
    assert got_vnc[(".youtube.com", "SID")] == "vnc-yt", "Google cookie deleted from its tier"
    assert ("google.com", "SID") not in got_vnc and (".google.com", "SID") not in got_vnc
    assert "google" not in (state / "cookies.json").read_text()
