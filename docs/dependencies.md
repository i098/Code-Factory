# Dependencies

Everything the recipe installs, grouped by the file that pins it. A version appears only where a file pins one; everything else tracks its upstream repository or latest release. `./factory plan` installs none of this.

## Repository tooling

`bootstrap.sh`, `toolchain.lock.json`, `pyproject.toml`, `uv.lock`

- uv 0.12.5 (sha256-locked), then `uv sync --locked`: ansible-core 2.21.4, jsonschema 4.26.0, PyYAML 6.0.3.
- Dev group: pytest 9.0.2, ruff 0.16.3.

## Pinned toolchain

`toolchain.lock.json`, installed by `scripts/install_tools.py`. Every archive is sha256-locked and linked into `~/.local/bin`.

- Always: uv 0.12.5.
- `development` profile: rustup-init 1.29.0, installing Rust 1.97.1 (minimal profile + rustfmt + clippy).

## Latest releases

Not pinned: every `./factory apply` resolves the newest release once and installs exactly that, so re-running apply upgrades an existing host. The installer records the releases it installed in `~/.local/share/code-factory/resolved.json`, which the container smoke compares against; `ansible/tasks/verify.yml` also asserts that the herdr service and omp run the resolved releases.

Native tools, linked into `~/.local/bin`. Each asset is verified against the SHA-256 its publisher lists for that exact release; a release that lists none fails the apply instead of installing an unverified binary.

- Always: herdr ([herdrdev/herdr](https://github.com/herdrdev/herdr/releases/latest)), bun ([oven-sh/bun](https://github.com/oven-sh/bun/releases/latest), the x64 `baseline` build), verified against the GitHub release-asset digest. A herdr upgrade rewrites and restarts `herdr.service`.
- Always: node, the newest release in the [nodejs.org index](https://nodejs.org/dist/index.json) (not the LTS line), verified against that release's `SHASUMS256.txt`.
- `agents` profile: gh ([cli/cli](https://github.com/cli/cli/releases/latest)), no-mistakes ([kunchenguid/no-mistakes](https://github.com/kunchenguid/no-mistakes/releases/latest)), treehouse ([kunchenguid/treehouse](https://github.com/kunchenguid/treehouse/releases/latest)), verified against the GitHub release-asset digest.

The GitHub lookups use the GitHub API, which allows 60 unauthenticated requests an hour per IP (shared IPs such as CI runners exhaust it); one apply makes five. The lookups authenticate with `GITHUB_TOKEN` from the environment that runs `./factory apply`, else run unauthenticated; the token is sent to the GitHub API only. Container builds take the token as the optional BuildKit secret `github_token` (`docker build --secret id=github_token,env=GITHUB_TOKEN ...`), so it never lands in the image.

npm tools, `agents` profile: the npm registry's `latest` version of omp (`@oh-my-pi/pi-coding-agent`), chrome-devtools-axi, gh-axi, lavish-axi, quota-axi, and tasks-axi, each installed with `npm install` into `~/.local/share/code-factory/<tool>/<version>` (npm checks the registry integrity). Superseded versions stay on disk. The fleet requires at least quota-axi 0.1.54 and tasks-axi 0.2.6.

## Agent CLIs

`tools/npm/package.json`, installed with `npm ci` from `tools/npm/package-lock.json` under the `agents` profile.

- acpx 0.18.0 (runs the no-mistakes gate agent `acp:omp`).
- chrome-devtools-mcp 1.9.0 (the MCP build chrome-devtools-axi launches through `CHROME_DEVTOOLS_AXI_MCP_PATH`).

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
- The recipe installs the latest gh later, under `agents`; the Quick start needs an authenticated `gh` before that.

Also needed, depending on profile:

- Membership in the `docker` group for the account that runs fleet guards. Opt in with `factory_docker_group_users`.
- `psmisc` (`fuser`) for `fleet-browser seed`.
- `iproute2` (`ss`) for the CLIENTS column of `fleet-browser status`. Without `ss`, every tier reports 0 clients and gc can stop a tier in use. Only the `desktop` profile installs `iproute2`.
- A VNC password created by the operator, for the `desktop` profile.
