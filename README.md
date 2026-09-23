# ⚡ Code Factory

> Reproducible AI-agent development environment on a fresh Ubuntu machine. One command to go from bare metal to a fully wired Herdr + Firstmate + OMP coding fleet.

Native Ansible provisioning. Pinned toolchain. Strict configuration schemas. Reviewed version locks. No Nix, no chezmoi, no cloud dependencies.

## Why

AI coding agents work best when their environment is deterministic and their sessions survive reboots. Code Factory provisions an Ubuntu host with:

- **Herdr** terminal workspace — pane management, presentation spaces, agent-aware desktops
- **Firstmate** fleet orchestrator — task dispatch, spawn memory floor, brief-rule enforcement
- **OMP/Pi** agent harness — model roles, mnemopi memory, chrome-devtools-axi browser integration. Model roles name provider ids directly (`anthropic/claude-*` in `config/omp.yml`); no router, gateway, or proxy sits in the request path
- **Fleet guards** — one shared Supabase stack, Docker event guard, [browser ladder](#browser-ladder), dev-server reaper
- **Pinned toolchain** — Node 24, Bun 1.4, uv, Rust 1.97, GitHub CLI, no-mistakes, treehouse — every binary sha256-locked in `toolchain.lock.json`

Not copied: credentials, browser profiles, account sessions, agent history, live pane/task state, private project working trees, database volumes. See [security boundaries](docs/security.md).

## Quick start

Ubuntu 24.04 or 26.04, x86_64 or aarch64. Non-root account with sudo.

```bash
# 1. Authenticate GitHub (needed for private repos and gh-axi)
gh auth login

# 2. Clone
git clone https://github.com/undeemed/Code-Factory.git
cd Code-Factory

# 3. Bootstrap pinned tooling (uv, Node, Bun, Rust, etc.)
./bootstrap.sh

# 4. Review and edit the host config
./factory init              # creates .local/host.yml (gitignored)
vim .local/host.yml         # adjust profiles, user, paths

# 5. Preview (check mode, no changes)
./factory plan

# 6. Apply
./factory apply
```

`plan` is Ansible check mode — it reports what would change but makes no mutations. `apply` is the explicit state-changing step and may request sudo.

## What gets reproduced

- Herdr 0.9.0 with captured UI preferences and one canonical, versioned user-service executable.
- Pinned Node 24, Bun 1.4, uv, Rust 1.97, GitHub CLI, no-mistakes, treehouse.
- OMP 18.x and Pi 0.84.x, Codex, AXI tools, and pnpm.
- Safe OMP/Pi presentation and model-role settings.
- Pinned Firstmate source, dispatch settings, and Herdr backend selection.
- Docker engine defaults: `init` (reap orphaned children) and `live-restore`.
- **Fleet guards** — optional but recommended for multi-lane agent work:
  - One shared local Supabase stack (read-only test fixture, event-trigger DDL guard)
  - Docker event guard (kills rogue stacks on creation)
  - Browser ladder with one shared cookie jar — see [Browser ladder](#browser-ladder)
  - Dev-server reaper (kills idle `next dev` / `tsc` trees)
  - Spawn memory floor (refuses new lanes when host RAM is low)
- Optional Tailscale, loopback-only XFCE/VNC desktop, Chrome apt package.

## Configuration

`.local/host.yml` is the single source of truth. `./factory init` creates it; `./factory validate` checks it against the JSON schema.

```yaml
factory:
  user: coder
  home: /home/coder
  workspace: /home/coder/Dev
  start_services: true
  enable_linger: true
  profiles:
    agents: true          # Chrome autoprune, AXI tools, browser defaults
    development: true     # Rust, build tools
    firstmate: true       # Firstmate clone + dispatch settings
    docker: true          # Docker engine (group membership opt-in separately)
    fleet_guards: false   # Shared Supabase, browser ladder (see "Browser ladder")
    tailscale: false      # Daemon only; authenticate separately
    desktop: false        # XFCE + TigerVNC + noVNC
  browsers:               # Obscura tier of the browser ladder (see "Browser ladder")
    obscura_version: '0.2.2'
    obscura_sha256: c1b4548e36549a0228c39c1cc842df425bc7253af2b0a56bd2a538d8ff7e3406
  fleet:
    supabase_project_id: swarms-shared
    fixture_archive: ""   # Path to DB volume tarball for fresh hosts
  firstmate:
    url: https://github.com/undeemed/firstmate.git
```

The Firstmate checkout tracks the fork's default branch instead of a sha: the fork's `main` is maintained as latest upstream Firstmate plus the fork's own layer, so tracking it is how a host stays current - which is also why it must not be re-pinned to a sha. Each run resolves `origin/main` once and reports the sha it installed.

All profiles default to `false` except `agents` and `development`. The recipe refuses conflicting unmanaged commands and independently advanced Firstmate checkouts instead of overwriting them. See [docs/](docs/) for architecture, security boundaries, and recovery procedures.

## Profiles

| Profile | What it installs |
|---------|-----------------|
| `agents` | Chrome autoprune, AXI tools, browser env defaults, agent harness config |
| `development` | Rust toolchain, build essentials, development-mode npm packages |
| `firstmate` | Firstmate clone tracking the fork's `main`, dispatch/harness config, spawn memory floor |
| `docker` | Docker engine + Compose v2. Group membership is opt-in (`docker_group_users`). |
| `fleet_guards` | Shared Supabase stack, Docker event guard, [browser ladder](#browser-ladder), dev-server reaper, env seeder |
| `tailscale` | Tailscale daemon. Auth is manual. |
| `desktop` | XFCE + TigerVNC + noVNC operator desktop on `127.0.0.1:6080`. Requires an operator-created VNC password. Also supplies the TigerVNC/noVNC packages the ladder's `vnc` tier needs (see [Browser ladder](#browser-ladder)). |

## Dependencies

Everything the recipe installs, grouped by the file that pins it. Versions appear only where a file pins one; anything else tracks its upstream repository. `plan` never installs any of this.

**Repository tooling** — `bootstrap.sh`, `toolchain.lock.json`, `pyproject.toml`, `uv.lock`

- uv 0.12.5 (sha256-locked), then `uv sync --locked`: ansible-core 2.21.4, jsonschema 4.26.0, PyYAML 6.0.3; dev group pytest 9.0.2, ruff 0.16.3.

**Pinned toolchain** — `toolchain.lock.json` via `scripts/install_tools.py`, every archive sha256-locked, linked into `~/.local/bin`

- Always: herdr 0.9.0, node 24.19.0, bun 1.4.0, uv 0.12.5.
- `agents` profile: gh 2.97.0, no-mistakes 1.48.0, treehouse 2.1.1.
- `development` profile: rustup-init 1.29.0 installing Rust 1.97.1 (minimal profile + rustfmt + clippy).

**Agent CLIs** — `tools/npm/package.json`, `npm ci` from `tools/npm/package-lock.json`, `agents` profile

- omp (`@oh-my-pi/pi-coding-agent`) 18.1.13, pi (`@earendil-works/pi-coding-agent`) 0.84.2, codex (`@openai/codex`) 0.147.0, pnpm 10.33.2.
- chrome-devtools-axi 0.1.29, chrome-devtools-mcp 1.9.0, gh-axi 0.1.30, lavish-axi 0.1.52, quota-axi 0.1.29, tasks-axi 0.2.5.

**Ubuntu packages** — `ansible/group_vars/all.yml`, `ansible/tasks/packages.yml`; distribution versions, not pinned

- Base: ca-certificates, curl, git, gnupg, jq, tar, unzip, xz-utils, zstd, procps, acl, python3, python3-venv, openssl, rsync.
- `development`: build-essential, pkg-config, libssl-dev, python3-dev, cmake, ripgrep.
- `docker`: docker.io, docker-compose-v2 (Ubuntu's packages, never Docker CE).
- `desktop`: xfce4, xfce4-terminal, dbus-x11, xauth, x11-xserver-utils, fonts-dejavu-core, tigervnc-standalone-server, tigervnc-common, tigervnc-tools, novnc, websockify, iproute2.
- `tailscale`: `tailscale` from pkgs.tailscale.com (stable track; `factory_tailscale_version` pins, empty by default).
- Google Chrome: `google-chrome-stable` from dl.google.com (`ansible/tasks/browser.yml`), installed when `factory_chrome_install` is `true` or `auto` with the `desktop` profile; `factory_chrome_version` pins, empty by default.

**Fleet browsers and Supabase** — `fleet_guards` profile

- Obscura `factory.browsers.obscura_version` (0.2.2 in `config/default.yml`) from github.com/h4ckf0r0day/obscura, sha256 `factory.browsers.obscura_sha256` (`ansible/tasks/fleet-browsers.yml`). x86_64 only: `factory_browser_obscura_url` hardcodes the `obscura-x86_64-linux.tar.gz` asset and the sha256 pins it, so on aarch64 there is no tier 1 and agents start at `chrome`.
- Supabase CLI 2.117.0 (`fleet/shared-supabase/package.json`, `npm ci` from its lockfile).

**Chrome autopruner** — `agents` profile with `browser_prune.enabled`

- psutil 7.1.0, hash-pinned into a private venv (`maintenance/requirements.txt`, `ansible/tasks/browser_prune.yml`).

**Firstmate** — `firstmate` profile

- `git clone` of `factory.firstmate.url`, tracking `origin/main`, never pinned (`ansible/tasks/firstmate.yml`).

**Container images** — `Dockerfile`, `compose.yml`

- Worker base `ubuntu:24.04@sha256:224a1869…` plus apt: bash, build-essential, ca-certificates, curl, git, iproute2, jq, less, libssl-dev, openssh-client, pkg-config, procps, python3, python3-apt, python3-venv, sudo, tar, unzip, xz-utils, zstd.
- Optional compose backing services (digest-pinned): `postgres:18-bookworm`, `redis:8-alpine`.

**Assumed on the host, never installed by the recipe:** Ubuntu 24.04/26.04 on x86_64 or aarch64 with systemd and a sudo-capable account; Python 3.12+ (`bootstrap.sh` refuses to run without it; `cloud-init/user-data.yaml` can preinstall it and the base package set); `git` to clone this repository and an authenticated `gh` for the Quick start's first step (the recipe installs gh 2.97.0 later, under `agents`); membership in the `docker` group for the account that runs fleet guards (opt in via `docker_group_users`); `psmisc` (`fuser`) for `fleet-browser seed` and `iproute2` (`ss`) for the CLIENTS column of `fleet-browser status` — without `ss` every tier reports 0 clients and gc can stop one in use (only the `desktop` profile installs `iproute2`); a VNC password created by the operator for the `desktop` profile.

## Fleet guards

The `fleet_guards` profile provisions everything a multi-lane AI agent fleet needs to run without thrashing the host:

- **Browser ladder** — three tiers sharing one cookie jar; see [Browser ladder](#browser-ladder)
- **Shared Supabase** — read-only test fixture, DDL-guarded, one stack per host enforced at the Docker event layer
- **Dev-server reaper** — kills idle `next dev` / `tsc` trees every 2 minutes
- **Spawn memory floor** — refuses fresh agent lanes when host RAM is below threshold

See [docs/fleet-guards.md](docs/fleet-guards.md) for the incident that motivated it and the full design.

## Browser ladder

Sources of truth: `fleet/browsers/fleet-browser` (runtime, `alive` probe), `fleet/browsers/env.sh` (defaults every shell inherits), `fleet/browsers/cookie-sync.ts` (jar), `ansible/tasks/fleet-browsers.yml` and `ansible/templates/fleet-browser-*.{service,timer}.j2` (units, cadences). Installed under `~/oss-fleet/browsers/` by the `fleet_guards` profile.

### The three layers

| Tier | CDP port | Always on? | Use it when |
|------|----------|------------|-------------|
| 1 `obscura` | `127.0.0.1:9222` | Yes on x86_64 (`fleet-browser-obscura.service`; the pinned release asset is x86_64-only, so an aarch64 host has no tier 1) | Default for everything: clicks, screenshots, screencast. ~25 MB idle; ~5x less RAM per page than Chrome. |
| 2 `chrome` | `127.0.0.1:9522` | On demand (`fleet-browser up chrome`) | Obscura misrenders the page, a site blocks it, or the maintainer needs pixel-exact before/after evidence. Headless Chromium, persistent profile. |
| 3 `vnc` | `127.0.0.1:9523`, noVNC `http://127.0.0.1:6909/vnc.html` | On demand (`fleet-browser up vnc`) | A human must see or drive the browser: OAuth consent, second factors, captchas, native dialogs, sites such as Google that refuse any automated browser. TigerVNC display `:9` + headed Chromium. |

Move down one layer only when the layer above cannot do the job; move back to `obscura` for the next task. Tiers 2 and 3 are stopped by `fleet-browser-gc.timer` (every 5 min) after 30 idle minutes (`FLEET_BROWSER_IDLE_MIN`, no CDP client connected). Tier 3 needs the `desktop` profile's TigerVNC/noVNC packages (`ConditionPathExists=/usr/bin/tigervncserver`); tiers 2 and 3 need a Chrome/Chromium binary (`FLEET_CHROME_BIN`, Google Chrome, Chromium, or a Playwright Chromium).

All three tiers share one session: `cookie-sync.ts` keeps a canonical jar at `~/.fleet-browser/cookies.json` and converges every live tier to it over CDP. `fleet-browser-sync.timer` runs it every 2 minutes and `fleet-browser up` runs it before returning, so a login made in any tier is present in every tier within one sync. Cookies are the synced part; localStorage is engine-local and is not.

Rule: an agent never launches its own Chrome, headless or not, and never uses a private `--user-data-dir`. A private profile has none of the fleet's logins and is outside the sync. Use the tier that is already running or bring one up with `fleet-browser up`.

The ladder's `vnc` tier is not the `desktop` profile's operator desktop (XFCE + TigerVNC, noVNC on `127.0.0.1:6080`, profile `~/.vnc-chrome-profile`, [docs/recovery.md](docs/recovery.md)). The desktop is a human workstation; the `vnc` tier is a fleet browser with a human window into it.

### Testing a tier before using it

Every shell an agent inherits sources `env.sh`, so `CHROME_DEVTOOLS_AXI_BROWSER_URL` already points at `obscura`:

```bash
fleet-browser env            # prints the exports for the default tier
fleet-browser env chrome     # or: eval "$(fleet-browser env chrome)" to escalate for one task
```

1. Probe the tier's CDP endpoint. This is the same `alive` check `fleet-browser` uses:

   ```bash
   curl -s -m 3 http://127.0.0.1:9222/json/version    # obscura
   curl -s -m 3 http://127.0.0.1:9522/json/version    # chrome
   curl -s -m 3 http://127.0.0.1:9523/json/version    # vnc
   ```

   Healthy: exit 0 and a JSON object with `"Browser"`, `"Protocol-Version": "1.3"` and a `"webSocketDebuggerUrl"` on the same port. Anything else (empty output, exit 7 or 28, HTML) means the tier is down: run `fleet-browser up chrome` or `fleet-browser up vnc` (waits until the probe answers), or for `obscura` run `systemctl --user start fleet-browser-obscura.service`.

2. Check the whole ladder at once. `STATE` is `up`/`down`, `CLIENTS` counts open CDP connections, and the `session:` line shows the jar and the last sync:

   ```bash
   fleet-browser status
   ```

3. Confirm the fleet's logins are there. The jar must exist and the sync timer must be active:

   ```bash
   ls -l ~/.fleet-browser/cookies.json
   systemctl --user list-timers fleet-browser-sync.timer
   fleet-browser sync           # force a converge now instead of waiting up to 2 min
   ```

   A site still asking for a login on every tier means nobody has signed in yet: bring up `vnc`, sign in through noVNC (`ssh -L 6909:127.0.0.1:6909 <host>`, then `http://127.0.0.1:6909/vnc.html?autoconnect=1`), and the next sync carries the session to `obscura` and `chrome`.

## Model access

OMP talks straight to the provider APIs. `config/omp.yml` maps every model role
to a provider-prefixed id (`anthropic/claude-*`) and `retry.fallbackChains`
names the same ids, so a fresh host needs no router, gateway, or proxy, and no
extra port is bound. Account rotation is native to omp - it pools several
accounts of the same provider itself - so more than one account is not a reason
to add a gateway. Credentials are authenticated interactively on the account
that runs the harness; none live in this repository.

## Docker worker

An isolated devcontainer-style Docker image can be built from the same recipe (`factory.start_services: false`). The image carries the pinned toolchain, agent configs, and fleet guards without starting any systemd services, linger, or Docker-in-Docker. See [docs/architecture.md](docs/architecture.md).

## CI

GitHub Actions runs on every push and PR:

- `uv sync` + `pytest` + `ruff`
- `./factory validate` against the JSON schema
- Full Docker worker image build + behavior smoke test
- All actions pinned to immutable commit SHAs (no `@v4` tags)

## Troubleshooting

```bash
./factory doctor    # actionable diagnostics
./factory plan      # preview what apply would change
```

Common issues:
- **`factory_guards` requires `docker` + `firstmate`** — enable both profiles
- **Empty fixture archive** — the shared DB is a read-only fixture; copy the volume snapshot from the source host
- **Spawn memory floor** — wait for a lane to finish or raise the threshold in `config/spawn-memory-floor-mb`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
