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


ASSETS = {
    "linux-x86_64": [
        "herdr-linux-x86_64",
        "nvim-linux-x86_64.tar.gz",
        "yazi-x86_64-unknown-linux-gnu.zip",
    ],
    "linux-aarch64": [
        "herdr-linux-aarch64",
        "nvim-linux-arm64.tar.gz",
        "yazi-aarch64-unknown-linux-gnu.zip",
    ],
}


ALL = {"herdr", "nvim", "yazi", "omp"}


def release(digest, key="linux-x86_64"):
    assets = [
        {
            "name": name,
            "browser_download_url": f"https://github.com/example/releases/download/v9.9.9/{name}",
            "digest": digest,
        }
        for name in ASSETS[key]
    ]
    return {"tag_name": "v9.9.9", "assets": assets}


def registries(monkeypatch, github_release):
    def urlopen(url, **kwargs):
        url = getattr(url, "full_url", url)
        github = url.startswith("https://api.github.com/")
        body = github_release if github else {"version": "18.9.9"}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)


@pytest.mark.parametrize("key", ASSETS)
def test_latest_releases_are_pinned_to_the_digests_they_publish(monkeypatch, key):
    registries(monkeypatch, release("sha256:" + "a" * 64, key))
    latest = installer.resolve_latest(key, ALL)
    assert latest["omp"] == "18.9.9"
    for tool, kind in [("herdr", "file"), ("nvim", "tar"), ("yazi", "zip")]:
        asset = latest[tool]["assets"][key]
        assert latest[tool]["version"] == "9.9.9"
        assert asset["sha256"] == "a" * 64
        assert asset["format"] == kind
    assert latest["yazi"]["assets"][key]["binaries"] == {"yazi": "*/yazi", "ya": "*/ya"}


@pytest.mark.parametrize("digest", [None, "", "md5:abc"])
def test_release_without_a_checksum_is_refused(monkeypatch, digest):
    registries(monkeypatch, release(digest))
    with pytest.raises(ValueError, match="refusing an unverified binary"):
        installer.resolve_latest("linux-x86_64", ALL)


@pytest.mark.parametrize(("env", "expected"), [("env-token", "Bearer env-token"), ("", None)])
def test_github_lookups_authenticate_with_github_token_else_anonymous(monkeypatch, env, expected):
    seen = []

    def urlopen(url, **kwargs):
        if getattr(url, "full_url", url).startswith("https://api.github.com/"):
            seen.append(url.get_header("Authorization"))
            return io.BytesIO(json.dumps(release("sha256:" + "a" * 64)).encode())
        return io.BytesIO(json.dumps({"version": "18.9.9"}).encode())

    monkeypatch.setenv("GITHUB_TOKEN", env)
    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    installer.resolve_latest("linux-x86_64", ALL)
    assert seen == [expected] * 3


@pytest.mark.parametrize(
    ("argv", "resolved", "lookups"),
    [
        (["--tools", "herdr,node,bun,uv"], {"herdr"}, ["herdrdev/herdr"]),
        (
            ["--tools", "herdr,nvim,yazi"],
            {"herdr", "nvim", "yazi"},
            ["herdrdev/herdr", "neovim/neovim", "sxyazi/yazi"],
        ),
        (["--tools", "uv", "--npm"], {"omp"}, ["registry.npmjs.org"]),
        (["--tools", "node,uv"], set(), []),
    ],
)
def test_resolve_looks_up_only_the_selected_tools(
    monkeypatch, capsys, tmp_path, argv, resolved, lookups
):
    seen = []

    def urlopen(url, **kwargs):
        url = getattr(url, "full_url", url)
        seen.append(url)
        body = release("sha256:" + "a" * 64) if "api.github.com" in url else {"version": "18.9.9"}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(installer, "platform_key", lambda: "linux-x86_64")
    monkeypatch.setattr(
        installer.sys,
        "argv",
        [
            "install_tools.py",
            "--lock",
            str(tmp_path / "lock"),
            "--home",
            str(tmp_path),
            "--resolve",
            *argv,
        ],
    )
    installer.main()
    assert set(json.loads(capsys.readouterr().out)) == resolved
    assert len(seen) == len(lookups)
    assert all(lookup in url for lookup, url in zip(lookups, seen))
