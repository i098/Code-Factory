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


# What each fake GitHub release publishes for linux-x86_64: tag and asset name.
RELEASES = {
    "herdrdev/herdr": ("v9.9.9", "herdr-linux-x86_64"),
    "oven-sh/bun": ("bun-v9.9.9", "bun-linux-x64-baseline.zip"),
    "cli/cli": ("v9.9.9", "gh_9.9.9_linux_amd64.tar.gz"),
    "kunchenguid/no-mistakes": ("v9.9.9", "no-mistakes-v9.9.9-linux-amd64.tar.gz"),
    "kunchenguid/treehouse": ("v9.9.9", "treehouse-v9.9.9-linux-amd64.tar.gz"),
    "astral-sh/uv": ("9.9.9", "uv-x86_64-unknown-linux-gnu.tar.gz"),
    "h4ckf0r0day/obscura": ("v9.9.9", "obscura-x86_64-linux.tar.gz"),
}


def upstream(monkeypatch, unverified=None, seen=None):
    """Fake GitHub, nodejs.org, rustup, npm and PyPI; `unverified` publishes no SHA-256 for that source."""

    def urlopen(request, **kwargs):
        url = request.full_url
        if seen is not None:
            seen.append((url, request.get_header("Authorization")))
        if url.startswith("https://api.github.com/repos/"):
            repo = url.removeprefix("https://api.github.com/repos/").removesuffix(
                "/releases/latest"
            )
            tag, name = RELEASES[repo]
            digest = None if repo == unverified else "sha256:" + "a" * 64
            asset = {
                "name": name,
                "browser_download_url": f"https://github.com/{name}",
                "digest": digest,
            }
            body = {"tag_name": tag, "assets": [asset]}
        elif url == "https://nodejs.org/dist/index.json":
            body = [{"version": "v9.99.0"}, {"version": "v30.1.0"}]
        elif url == "https://nodejs.org/dist/v30.1.0/SHASUMS256.txt":
            sums = "" if unverified == "node" else "b" * 64 + "  node-v30.1.0-linux-x64.tar.xz\n"
            return io.BytesIO(("c" * 64 + "  node-v30.1.0-linux-arm64.tar.xz\n" + sums).encode())
        elif url == "https://static.rust-lang.org/rustup/release-stable.toml":
            return io.BytesIO(b"schema-version = '1'\nversion = '9.9.9'\n")
        elif url.endswith("/rustup-init.sha256"):
            checksum = "" if unverified == "rustup-init" else "d" * 64
            return io.BytesIO(f"{checksum} *./rustup-init\n".encode())
        elif url == "https://pypi.org/pypi/psutil/json":
            files = [] if unverified == "psutil" else [{"digests": {"sha256": "e" * 64}}]
            body = {"info": {"version": "9.9.9"}, "urls": files}
        else:
            body = {"version": "18.9.9"}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)


def test_latest_releases_are_pinned_to_the_digests_their_publishers_list(monkeypatch):
    upstream(monkeypatch)
    latest = installer.resolve_latest("linux-x86_64")
    for tool in ("herdr", "bun", "gh", "no-mistakes", "treehouse", "uv", "obscura"):
        assert latest[tool]["version"] == "9.9.9"
        assert latest[tool]["assets"]["linux-x86_64"]["sha256"] == "a" * 64
    assert latest["gh"]["assets"]["linux-x86_64"]["format"] == "tar"
    assert latest["bun"]["assets"]["linux-x86_64"]["format"] == "zip"
    # The newest Node release, not the first index entry, verified by SHASUMS256.
    node = latest["node"]["assets"]["linux-x86_64"]
    assert latest["node"]["version"] == "30.1.0"
    assert node["url"] == "https://nodejs.org/dist/v30.1.0/node-v30.1.0-linux-x64.tar.xz"
    assert node["sha256"] == "b" * 64
    rustup = latest["rustup-init"]["assets"]["linux-x86_64"]
    assert rustup["url"].endswith("/9.9.9/x86_64-unknown-linux-gnu/rustup-init")
    assert (rustup["sha256"], rustup["format"]) == ("d" * 64, "file")
    assert latest["psutil"] == {"version": "9.9.9", "sha256": ["e" * 64]}
    for tool in (*installer.NPM_LATEST, "supabase"):
        assert latest[tool] == "18.9.9"


@pytest.mark.parametrize("source", [*RELEASES, "node", "rustup-init", "psutil"])
def test_release_without_a_published_checksum_is_refused(monkeypatch, source):
    upstream(monkeypatch, unverified=source)
    with pytest.raises(ValueError, match="refusing an unverified binary"):
        installer.resolve_latest("linux-x86_64")


@pytest.mark.parametrize(("env", "expected"), [("env-token", "Bearer env-token"), ("", None)])
def test_github_token_goes_only_to_the_github_api(monkeypatch, env, expected):
    seen = []
    monkeypatch.setenv("GITHUB_TOKEN", env)
    upstream(monkeypatch, seen=seen)
    installer.resolve_latest("linux-x86_64")
    github = {auth for url, auth in seen if url.startswith("https://api.github.com/")}
    assert github == {expected}
    assert {auth for url, auth in seen if not url.startswith("https://api.github.com/")} == {None}


def test_commands_of_removed_packages_are_unlinked_but_user_links_kept(tmp_path):
    bin_dir = tmp_path / ".local/bin"
    bin_dir.mkdir(parents=True)
    managed = bin_dir / "codex"
    managed.symlink_to(tmp_path / ".local/share/code-factory/npm/node_modules/gone/bin.js")
    user = bin_dir / "mine"
    user.symlink_to(tmp_path / "elsewhere/gone")
    assert installer.prune_dangling_links(tmp_path)
    assert not managed.is_symlink()
    assert user.is_symlink()
