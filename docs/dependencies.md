# Dependencies

Everything the recipe installs, grouped by the file that pins it. A version appears only where a file pins one; everything else tracks its upstream repository or latest release. `./factory plan` installs none of this.

## Repository tooling

`bootstrap.sh`, `toolchain.lock.json`, `pyproject.toml`, `uv.lock`

- uv 0.12.5 (sha256-locked), then `uv sync --locked`: ansible-core 2.21.4, jsonschema 4.26.0, PyYAML 6.0.3.
- Dev group: pytest 9.0.2, ruff 0.16.3.

## Pinned toolchain

`toolchain.lock.json`, installed by `scripts/install_tools.py`. Every archive is sha256-locked and linked into `~/.local/bin`.

- Always: node 24.19.0, bun 1.4.0, uv 0.12.5.
- `agents` profile: gh 2.97.0, no-mistakes 1.79.0, treehouse 2.1.1.
- `development` profile: rustup-init 1.29.0, installing Rust 1.97.1 (minimal profile + rustfmt + clippy).

## Latest releases

Not pinned: every `./factory apply` resolves the newest release, installs exactly that, and `ansible/tasks/verify.yml` asserts the installed version equals the one the run resolved, so re-running apply upgrades an existing host. The installer records the releases it installed in `~/.local/share/code-factory/resolved.json`, which verify and the container smoke compare against.

- Always: herdr, the latest [herdrdev/herdr release](https://github.com/herdrdev/herdr/releases/latest), verified against the SHA-256 the release publishes for the platform asset. A release that publishes no checksum fails the apply instead of installing an unverified binary. The lookup uses the GitHub API, which allows 60 unauthenticated requests an hour per IP; set `GITHUB_TOKEN` if apply reports it is rate limited. An upgrade rewrites and restarts `herdr.service`.
- `agents` profile: omp (`@oh-my-pi/pi-coding-agent`), the npm registry's `latest` version, installed with `npm install` into `~/.local/share/code-factory/omp/<version>` (npm checks the registry integrity). Superseded versions stay on disk.

## Agent CLIs

`tools/npm/package.json`, installed with `npm ci` from `tools/npm/package-lock.json` under the `agents` profile.

- codex (`@openai/codex`) 0.147.0, pnpm 10.33.2, acpx 0.18.0 (runs the no-mistakes gate agent `acp:omp`).
- chrome-devtools-axi 0.1.29, chrome-devtools-mcp 1.9.0, gh-axi 0.1.30, lavish-axi 0.1.52, quota-axi 0.1.54, tasks-axi 0.2.6. The fleet requires at least quota-axi 0.1.54 and tasks-axi 0.2.6.

## Ubuntu packages

`ansible/group_vars/all.yml`, `ansible/tasks/packages.yml`. Distribution versions, not pinned.

- Base: ca-certificates, curl, git, gnupg, jq, tar, unzip, xz-utils, zstd, procps, acl, python3, python3-venv, openssl, rsync.
- `development`: build-essential, pkg-config, libssl-dev, python3-dev, cmake, ripgrep.
- `docker`: docker.io, docker-compose-v2 (Ubuntu's packages, never Docker CE).
- `desktop`: xfce4, xfce4-terminal, dbus-x11, xauth, x11-xserver-utils, fonts-dejavu-core, tigervnc-standalone-server, tigervnc-common, tigervnc-tools, novnc, websockify, iproute2.
- `tailscale`: `tailscale` from pkgs.tailscale.com, stable track. `factory_tailscale_version` pins it; empty by default.
- Google Chrome: `google-chrome-stable` from dl.google.com (`ansible/tasks/browser.yml`). Installed when `factory_chrome_install` is `true`, or `auto` (the default) with the `desktop` profile. `factory_chrome_version` pins it; empty by default.

## Fleet browsers and Supabase

`fleet_guards` profile.

- Obscura `factory.browsers.obscura_version` (0.2.2 in `config/default.yml`) from github.com/h4ckf0r0day/obscura, verified against `factory.browsers.obscura_sha256` (`ansible/tasks/fleet-browsers.yml`). x86_64 only: `factory_browser_obscura_url` hardcodes the `obscura-x86_64-linux.tar.gz` asset, and the sha256 pins it. For aarch64 behavior, see [Browser ladder](fleet-guards.md#browser-ladder).
- Supabase CLI 2.117.0 (`fleet/shared-supabase/package.json`, `npm ci` from its lockfile).

## Chrome autopruner

`agents` profile with `browser_prune.enabled`.

- psutil 7.1.0, hash-pinned into a private venv (`maintenance/requirements.txt`, `ansible/tasks/browser_prune.yml`).

## Firstmate

`firstmate` profile.

- `git clone` of `factory.firstmate.url` (upstream `https://github.com/kunchenguid/firstmate.git` by default), tracking `origin/main`, never pinned. Every apply fetches and fast-forwards `main` (`ansible/tasks/firstmate.yml`).

## Container images

`Dockerfile`, `compose.yml`

- Worker base `ubuntu:24.04@sha256:224a1869…` plus apt: bash, build-essential, ca-certificates, curl, git, iproute2, jq, less, libssl-dev, openssh-client, pkg-config, procps, python3, python3-apt, python3-venv, sudo, tar, unzip, xz-utils, zstd.
- Optional compose backing services (digest-pinned): `postgres:18-bookworm`, `redis:8-alpine`.

## Assumed on the host

The recipe never installs these. The base requirements (Ubuntu, sudo, Python, `git`, `gh`) are in the [Quick start](../README.md#quick-start). Notes on those:

- `bootstrap.sh` refuses to run without Python 3.12+.
- The recipe installs gh 2.97.0 later, under `agents`; the Quick start needs an authenticated `gh` before that.

Also needed, depending on profile:

- Membership in the `docker` group for the account that runs fleet guards. Opt in with `factory_docker_group_users`.
- `psmisc` (`fuser`) for `fleet-browser seed`.
- `iproute2` (`ss`) for the CLIENTS column of `fleet-browser status`. Without `ss`, every tier reports 0 clients and gc can stop a tier in use. Only the `desktop` profile installs `iproute2`.
- A VNC password created by the operator, for the `desktop` profile.
