import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "install_tools", Path(__file__).parents[1] / "scripts/install_tools.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class Download(io.BytesIO):
    def geturl(self):
        return "https://downloads.example.test/tool"


def asset(payload, checksum=None):
    return {
        "version": "1.0.0",
        "assets": {
            "linux-x86_64": {
                "url": "https://downloads.example.test/tool",
                "sha256": checksum or hashlib.sha256(payload).hexdigest(),
                "format": "file",
                "binaries": {"tool": "tool"},
            }
        },
    }


def test_verified_install_runs_and_second_install_changes_nothing(tmp_path, monkeypatch):
    payload = b"#!/bin/sh\nprintf 'tool 1.0.0\\n'\n"
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(payload))
    spec = asset(payload)
    assert installer.install_asset(tmp_path, "tool", spec, "linux-x86_64")
    command = tmp_path / ".local/bin/tool"
    assert subprocess.check_output([command], text=True).strip() == "tool 1.0.0"
    assert not installer.install_asset(tmp_path, "tool", spec, "linux-x86_64")


def test_bad_checksum_never_installs_command(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(b"corrupt"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        installer.install_asset(tmp_path, "tool", asset(b"expected"), "linux-x86_64")
    assert not (tmp_path / ".local/bin/tool").exists()


def test_unmanaged_command_is_preserved(tmp_path, monkeypatch):
    command = tmp_path / ".local/bin/tool"
    command.parent.mkdir(parents=True)
    command.write_bytes(b"user-owned")
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(b"new"))
    with pytest.raises(ValueError, match="unmanaged command"):
        installer.install_asset(tmp_path, "tool", asset(b"new"), "linux-x86_64")
    assert command.read_bytes() == b"user-owned"


def test_local_binary_drift_is_not_silently_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(b"original"))
    spec = asset(b"original")
    installer.install_asset(tmp_path, "tool", spec, "linux-x86_64")
    (tmp_path / ".local/bin/tool").write_bytes(b"changed locally")
    with pytest.raises(ValueError, match="drifted"):
        installer.install_asset(tmp_path, "tool", spec, "linux-x86_64")


@pytest.mark.parametrize("kind", ["tar", "zip"])
def test_archive_traversal_cannot_escape_staging(tmp_path, kind):
    archive = tmp_path / "archive"
    destination = tmp_path / "staging"
    destination.mkdir()
    if kind == "tar":
        with tarfile.open(archive, "w") as stream:
            member = tarfile.TarInfo("../escaped")
            member.size = 1
            stream.addfile(member, io.BytesIO(b"x"))
        error = tarfile.FilterError
    else:
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("../escaped", b"x")
        error = ValueError
    with pytest.raises(error):
        installer.extract(archive, destination, kind, "tool")
    assert not (tmp_path / "escaped").exists()


def test_download_rejects_plain_http(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        installer.download("http://example.test/tool", "0" * 64, tmp_path / "download")


def release(digest):
    asset = {
        "name": "herdr-linux-x86_64",
        "browser_download_url": "https://github.com/herdrdev/herdr/releases/download/v9.9.9/herdr-linux-x86_64",
        "digest": digest,
    }
    return {"tag_name": "v9.9.9", "assets": [asset]}


def registries(monkeypatch, herdr_release):
    def urlopen(url, **kwargs):
        url = getattr(url, "full_url", url)
        body = herdr_release if url == installer.HERDR_LATEST else {"version": "18.9.9"}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)


def test_latest_herdr_is_pinned_to_the_digest_its_release_publishes(monkeypatch):
    registries(monkeypatch, release("sha256:" + "a" * 64))
    latest = installer.resolve_latest("linux-x86_64")
    assert latest["omp"] == "18.9.9"
    assert latest["herdr"]["version"] == "9.9.9"
    assert latest["herdr"]["assets"]["linux-x86_64"]["sha256"] == "a" * 64


@pytest.mark.parametrize("digest", [None, "", "md5:abc"])
def test_herdr_release_without_a_checksum_is_refused(monkeypatch, digest):
    registries(monkeypatch, release(digest))
    with pytest.raises(ValueError, match="refusing an unverified binary"):
        installer.resolve_latest("linux-x86_64")


@pytest.mark.parametrize(("env", "expected"), [("env-token", "Bearer env-token"), ("", None)])
def test_herdr_lookup_authenticates_with_github_token_else_anonymous(monkeypatch, env, expected):
    seen = []

    def urlopen(url, **kwargs):
        if getattr(url, "full_url", url) == installer.HERDR_LATEST:
            seen.append(url.get_header("Authorization"))
            return io.BytesIO(json.dumps(release("sha256:" + "a" * 64)).encode())
        return io.BytesIO(json.dumps({"version": "18.9.9"}).encode())

    monkeypatch.setenv("GITHUB_TOKEN", env)
    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    installer.resolve_latest("linux-x86_64")
    assert seen == [expected]
