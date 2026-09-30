#!/usr/bin/env python3
"""Install public tools into a user-owned Code Factory prefix.

Stdlib-only: also bootstraps uv before repository dependencies exist. stdout is
one JSON result; installer progress goes to stderr. Existing unmanaged commands
are never replaced. Archives cannot write outside their staging directory.
uv, rustup-init and the Rust toolchain are pinned in the lock. Every other tool
tracks its latest release: native assets are verified against the SHA-256 their
publisher lists for that release (the GitHub release-asset digest, or Node's
SHASUMS256.txt), npm tools against the integrity npm records for the resolved
version.
"""

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

GITHUB_API = "https://api.github.com/repos/{}/releases/latest"
# How release asset names spell each platform.
ARCH = {
    "linux-x86_64": {"node": "x64", "go": "amd64", "bun": "x64-baseline"},
    "linux-aarch64": {"node": "arm64", "go": "arm64", "bun": "aarch64"},
}
# Native tools on their latest GitHub release: repository, tag prefix, asset
# name, and where each command sits inside the asset.
GITHUB_LATEST = {
    "herdr": ("herdrdev/herdr", "v", "herdr-{key}", {"herdr": "herdr"}),
    "bun": ("oven-sh/bun", "bun-v", "bun-linux-{bun}.zip", {"bun": "bun-linux-*/bun"}),
    "gh": ("cli/cli", "v", "gh_{v}_linux_{go}.tar.gz", {"gh": "gh_*/bin/gh"}),
    "no-mistakes": (
        "kunchenguid/no-mistakes",
        "v",
        "no-mistakes-v{v}-linux-{go}.tar.gz",
        {"no-mistakes": "no-mistakes"},
    ),
    "treehouse": (
        "kunchenguid/treehouse",
        "v",
        "treehouse-v{v}-linux-{go}.tar.gz",
        {"treehouse": "treehouse"},
    ),
}
# npm tools on the registry's latest version, each installed into its own prefix.
NPM_LATEST = {
    "omp": "@oh-my-pi/pi-coding-agent",
    "chrome-devtools-axi": "chrome-devtools-axi",
    "gh-axi": "gh-axi",
    "lavish-axi": "lavish-axi",
    "quota-axi": "quota-axi",
    "tasks-axi": "tasks-axi",
}
# Native tools the agents profile adds.
AGENT_TOOLS = ["gh", "no-mistakes", "treehouse"]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def platform_key():
    machine = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(
        platform.machine().lower()
    )
    if platform.system() != "Linux" or machine is None:
        raise ValueError(
            "native provisioning supports Linux x86_64/aarch64; other devices can use SSH Herdr clients"
        )
    return "linux-" + machine


def fetch(url, what):
    # The GitHub token only ever goes to the GitHub API. Unauthenticated calls
    # there share a 60/hour budget per IP.
    token = os.environ.get("GITHUB_TOKEN")
    github = url.startswith("https://api.github.com/")
    headers = {"Authorization": f"Bearer {token}"} if token and github else {}
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=60
        ) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise ValueError(
            f"cannot resolve the latest {what} (HTTP {error.code}); "
            "if rate limited, set GITHUB_TOKEN and re-run"
        ) from None


def verified(tool, version, key, name, url, checksum, binaries):
    """A lock-shaped spec, only when the publisher lists a SHA-256 for the asset."""
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError(
            f"{tool} {version} publishes no SHA-256 for {name}; refusing an unverified binary"
        )
    kind = "zip" if name.endswith(".zip") else "tar" if ".tar." in name else "file"
    asset = {"url": url, "sha256": checksum, "format": kind, "binaries": binaries}
    return {"version": version, "assets": {key: asset}}


def resolve_latest(key):
    """Specs for the newest native releases, and the newest npm tool versions."""
    latest = {}
    for tool, (repo, prefix, pattern, binaries) in GITHUB_LATEST.items():
        release = json.loads(fetch(GITHUB_API.format(repo), f"{tool} release"))
        version = release["tag_name"].removeprefix(prefix)
        name = pattern.format(v=version, key=key, **ARCH[key])
        asset = next((a for a in release["assets"] if a["name"] == name), {})
        checksum = (asset.get("digest") or "").removeprefix("sha256:")
        url = asset.get("browser_download_url", "")
        latest[tool] = verified(tool, version, key, name, url, checksum, binaries)
    releases = json.loads(fetch("https://nodejs.org/dist/index.json", "node release"))
    tag = max((r["version"] for r in releases), key=lambda v: tuple(map(int, v[1:].split("."))))
    name = f"node-{tag}-linux-{ARCH[key]['node']}.tar.xz"
    sums = fetch(f"https://nodejs.org/dist/{tag}/SHASUMS256.txt", "node checksums").decode()
    match = re.search(rf"^([0-9a-f]{{64}})  {re.escape(name)}$", sums, re.M)
    binaries = {command: f"node-v*/bin/{command}" for command in ("node", "npm", "npx")}
    latest["node"] = verified(
        "node",
        tag.removeprefix("v"),
        key,
        name,
        f"https://nodejs.org/dist/{tag}/{name}",
        match[1] if match else "",
        binaries,
    )
    for tool, package in NPM_LATEST.items():
        registry = fetch(f"https://registry.npmjs.org/{package}/latest", f"{tool} version")
        latest[tool] = json.loads(registry)["version"]
    return latest


def download(url, checksum, destination):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[0-9a-f]{64}", checksum)
    ):
        raise ValueError("downloads require HTTPS and an explicit SHA-256")
    print(f"Downloading {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as stream:
        if urllib.parse.urlsplit(response.geturl()).scheme != "https":
            raise ValueError("refusing an insecure download redirect")
        shutil.copyfileobj(response, stream)
    if digest(destination) != checksum:
        raise ValueError(f"checksum mismatch for {url}")


def extract(archive, destination, kind, name):
    if kind == "file":
        shutil.copyfile(archive, destination / name)
    elif kind == "tar":
        with tarfile.open(archive) as source:
            source.extractall(destination, filter="data")
    elif kind == "zip":
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                path = PurePosixPath(item.filename)
                mode = item.external_attr >> 16
                if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
                    raise ValueError("unsafe ZIP member")
            source.extractall(destination)
    else:
        raise ValueError(f"unsupported archive format: {kind}")


def binaries_in(root, patterns):
    result = {}
    for name, pattern in patterns.items():
        if name in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("unsafe binary name")
        matches = [p for p in root.glob(pattern) if p.is_file()]
        if len(matches) != 1 or not matches[0].resolve().is_relative_to(root.resolve()):
            raise ValueError(f"expected one safe binary for {name}, found {len(matches)}")
        result[name] = matches[0]
    return result


def link_binary(home, name, target):
    link = home / ".local/bin" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() and link.resolve() == target.resolve():
        return False
    if os.path.lexists(link):
        old = link.resolve()
        if not link.is_symlink() or not (
            old.is_relative_to(home / ".local/share/code-factory")
            or old.is_relative_to(home / ".cargo")
        ):
            raise ValueError(
                f"unmanaged command exists: {link}; choose a clean account or relocate it explicitly"
            )
        link.unlink()
    link.symlink_to(target)
    return True


def install_asset(home, name, spec, key):
    version = spec["version"]
    if (
        name in (".", "..")
        or version in (".", "..")
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", version)
    ):
        raise ValueError("unsafe tool name/version")
    asset = spec["assets"][key]
    final = home / ".local/share/code-factory/tools" / name / version / key
    stamp = final / ".asset.json"
    expected = hashlib.sha256(json.dumps(asset, sort_keys=True).encode()).hexdigest()
    valid = False
    if stamp.is_file():
        saved = json.loads(stamp.read_text())
        paths = binaries_in(final, asset["binaries"])
        valid = saved.get("spec") == expected and saved.get("files") == {
            n: digest(p) for n, p in paths.items()
        }
    changed = False
    if not valid:
        if final.exists():
            raise ValueError(
                f"installed artifact drifted or is incomplete: {final}; inspect it before replacing"
            )
        final.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=final.parent) as temporary:
            temporary = Path(temporary)
            archive = temporary / "download"
            unpacked = temporary / "contents"
            unpacked.mkdir()
            download(asset["url"], asset["sha256"], archive)
            extract(archive, unpacked, asset["format"], name)
            paths = binaries_in(unpacked, asset["binaries"])
            for path in paths.values():
                path.chmod(0o755)
            (unpacked / ".asset.json").write_text(
                json.dumps({"spec": expected, "files": {n: digest(p) for n, p in paths.items()}})
                + "\n"
            )
            unpacked.rename(final)
        changed = True
    for binary, path in binaries_in(final, asset["binaries"]).items():
        changed = link_binary(home, binary, path) or changed
    return changed


def command(argv, environment):
    subprocess.run([str(arg) for arg in argv], env=environment, check=True, stdout=sys.stderr)


def npm_install(repo, home, environment):
    source = repo / "tools/npm"
    manifest = json.loads((source / "package.json").read_text())
    lock_hash = digest(source / "package-lock.json")
    destination = home / ".local/share/code-factory/npm"
    stamp = destination / ".code-factory-lock"
    expected = lock_hash + ":" + digest(source / "package.json")
    installed = stamp.is_file() and stamp.read_text().strip() == expected
    for name, version in manifest["dependencies"].items():
        package = destination / "node_modules" / name / "package.json"
        if not package.is_file() or json.loads(package.read_text()).get("version") != version:
            installed = False
    changed = False
    if not installed:
        if (
            destination.exists()
            and any(destination.iterdir())
            and not stamp.exists()
            and not (destination / "package-lock.json").exists()
        ):
            raise ValueError(f"refusing unmanaged npm prefix: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(source / name, destination / name)
        command(
            [home / ".local/bin/npm", "ci", "--prefix", destination, "--no-audit", "--no-fund"],
            environment,
        )
        stamp.write_text(expected + "\n")
        changed = True
    return link_package_bins(home, destination, manifest["dependencies"]) or changed


def link_package_bins(home, destination, package_names):
    # Only expose explicitly requested packages, not incidental dependency bins.
    changed = False
    for package_name in package_names:
        root = destination / "node_modules" / package_name
        package = json.loads((root / "package.json").read_text())
        bins = package.get("bin", {})
        if isinstance(bins, str):
            bins = {package_name.rsplit("/", 1)[-1]: bins}
        for name, relative in bins.items():
            target = root / relative
            if not target.is_file() or not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"invalid installed package command: {name}")
            changed = link_binary(home, name, target) or changed
    return changed


def npm_latest_install(home, tool, version, environment):
    """Install exactly this version into its own prefix; a new version relinks the tool."""
    package_name = NPM_LATEST[tool]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+-]*", version):
        raise ValueError(f"unsafe {tool} version")
    # ponytail: superseded versions stay on disk so running agents keep their files;
    # prune them by hand or add a sweep if disk use matters.
    final = home / ".local/share/code-factory" / tool / version
    package = final / "node_modules" / package_name / "package.json"
    changed = False
    if not package.is_file() or json.loads(package.read_text()).get("version") != version:
        if final.exists():
            raise ValueError(f"incomplete {tool} install: {final}; inspect it before replacing")
        final.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=final.parent) as temporary:
            staging = Path(temporary) / "prefix"
            staging.mkdir()
            command(
                [
                    home / ".local/bin/npm",
                    "install",
                    "--prefix",
                    staging,
                    "--no-audit",
                    "--no-fund",
                    f"{package_name}@{version}",
                ],
                environment,
            )
            staging.rename(final)
        changed = True
    return link_package_bins(home, final, [package_name]) or changed


def prune_dangling_links(home):
    """Remove managed commands whose package is no longer installed."""
    changed = False
    for link in (home / ".local/bin").iterdir():
        if link.is_symlink() and not link.exists():
            if Path(os.readlink(link)).is_relative_to(home / ".local/share/code-factory"):
                link.unlink()
                changed = True
    return changed


def rust_install(home, version, environment):
    rustup = home / ".cargo/bin/rustup"
    environment = {
        **environment,
        "CARGO_HOME": str(home / ".cargo"),
        "RUSTUP_HOME": str(home / ".rustup"),
    }
    changed = False
    if not rustup.exists():
        command(
            [
                home / ".local/bin/rustup-init",
                "-y",
                "--no-modify-path",
                "--profile",
                "minimal",
                "--default-toolchain",
                version,
                "--component",
                "rustfmt",
                "--component",
                "clippy",
            ],
            environment,
        )
        changed = True
    else:
        result = subprocess.run(
            [rustup, "run", version, "rustc", "--version"],
            env=environment,
            capture_output=True,
            text=True,
        )
        if result.returncode or not result.stdout.startswith(f"rustc {version} "):
            command(
                [
                    rustup,
                    "toolchain",
                    "install",
                    version,
                    "--profile",
                    "minimal",
                    "--component",
                    "rustfmt",
                    "--component",
                    "clippy",
                ],
                environment,
            )
            changed = True
        components = subprocess.run(
            [rustup, "component", "list", "--installed", "--toolchain", version],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        missing = [
            name
            for name in ("rustfmt", "clippy")
            if not any(line.startswith(name + "-") for line in components.splitlines())
        ]
        if missing:
            command([rustup, "component", "add", "--toolchain", version, *missing], environment)
            changed = True
        current = subprocess.run(
            [rustup, "default"], env=environment, capture_output=True, text=True, check=True
        ).stdout
        if not current.startswith(version + "-"):
            command([rustup, "default", version], environment)
            changed = True
    for name in (
        "rustup",
        "cargo",
        "rustc",
        "rustfmt",
        "cargo-fmt",
        "cargo-clippy",
        "clippy-driver",
    ):
        changed = link_binary(home, name, home / ".cargo/bin" / name) or changed
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--tools", default="herdr,node,bun,uv")
    parser.add_argument("--npm", action="store_true")
    parser.add_argument("--development", action="store_true")
    parser.add_argument(
        "--resolve", action="store_true", help="print the latest releases as JSON and exit"
    )
    parser.add_argument(
        "--resolved", type=json.loads, help="--resolve output to install instead of resolving"
    )
    args = parser.parse_args()
    key = platform_key()
    if args.resolve:
        print(json.dumps(resolve_latest(key)))
        return
    home = args.home.resolve(strict=True)
    if home.stat().st_uid != os.geteuid():
        parser.error("run as the user who owns --home")
    lock = json.loads(args.lock.read_text())
    if lock.get("schema_version") != 1:
        parser.error("unsupported toolchain lock schema")
    names = list(dict.fromkeys(args.tools.split(",") + (AGENT_TOOLS if args.npm else [])))
    if args.development:
        names.append("rustup-init")
    wanted = args.npm or any(name == "node" or name in GITHUB_LATEST for name in names)
    latest = args.resolved or (resolve_latest(key) if wanted else {})
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": str(home / ".local/bin") + ":/usr/local/bin:/usr/bin:/bin",
    }
    prefix = home / ".local/share/code-factory"
    prefix.mkdir(parents=True, exist_ok=True)
    with (prefix / ".install.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        changed = False
        for name in names:
            spec = latest[name] if name in latest else lock["tools"][name]
            changed = install_asset(home, name, spec, key) or changed
        if args.npm:
            changed = npm_install(args.lock.resolve().parent, home, environment) or changed
            for tool in NPM_LATEST:
                changed = npm_latest_install(home, tool, latest[tool], environment) or changed
            changed = prune_dangling_links(home) or changed
        if args.development:
            changed = rust_install(home, lock["rust_toolchain"], environment) or changed
        # The record checks compare against, so a later upstream release cannot
        # make an unchanged install look wrong.
        if latest:
            (prefix / "resolved.json").write_text(json.dumps(latest, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "changed": changed,
                "installed": names,
                "npm": args.npm,
                "development": args.development,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"install_tools: {error}", file=sys.stderr)
        sys.exit(1)
