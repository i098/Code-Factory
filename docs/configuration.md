# Configuration

`.local/host.yml` is the single source of truth for one host. It is gitignored and owner-only (`0600`).

## Commands

| Command | What it does |
| --- | --- |
| `./factory init` | Copies `config/default.yml` to `.local/host.yml` with your user, home, and `~/Dev` workspace filled in. Never overwrites an existing file. Options: `--user`, `--home`, `--container`. |
| `./factory validate` | Checks the config against `schemas/factory.schema.json` and the cross-field rules below, plus `toolchain.lock.json` against its schema. |
| `./factory plan` | Runs the Ansible playbook in check mode. Reports what would change; mutates nothing. |
| `./factory apply` | Runs the playbook for real. Asks for the sudo password when passwordless sudo is not available. |
| `./factory doctor` | Checks that each expected tool runs and reports `gh` authentication. Changes nothing. |

`validate`, `plan`, `apply`, and `doctor` read `--config <path>` if you pass one, otherwise `.local/host.yml`. If `.local/host.yml` does not exist, `validate`, `plan`, and `doctor` fall back to `config/default.yml` (user `coder`); `apply` refuses to run.

## The host config

An excerpt with the defaults `./factory init` writes. The full document is [`config/default.yml`](../config/default.yml).

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
    tailscale: false      # Daemon only; authenticate separately
    desktop: false        # XFCE + TigerVNC + noVNC
    fleet_guards: false   # Shared Supabase, browser ladder
  browsers:               # Obscura tier of the browser ladder
    obscura_version: '0.2.2'
    obscura_sha256: c1b4548e36549a0228c39c1cc842df425bc7253af2b0a56bd2a538d8ff7e3406
  fleet:
    supabase_project_id: swarms-shared
    fixture_archive: ""   # Path to DB volume tarball for fresh hosts
  firstmate:
    url: https://github.com/undeemed/firstmate.git
```

`validate` also enforces these rules:

- `user` is not `root`, and `workspace` is inside `home`.
- `firstmate` and `browser_prune.enabled` need `agents`.
- `fleet_guards` needs `docker` and `firstmate`, plus `browsers.obscura_version` and a 64-character hex `browsers.obscura_sha256`.

The Firstmate checkout tracks the fork's default branch, not a sha. The fork's `main` is latest upstream Firstmate plus the fork's own layer, so tracking it is how a host stays current. Do not re-pin it to a sha. Each run resolves `origin/main` once and reports the sha it installed.

The recipe refuses to overwrite a conflicting unmanaged command or an independently advanced Firstmate checkout. See [Drift and upgrades](recovery.md#drift-and-upgrades).

## Profiles

| Profile | Default | What it installs |
| --- | --- | --- |
| `agents` | on | omp, Codex, pnpm, AXI tools, gh, no-mistakes, treehouse; safe omp presentation and model-role settings (see [omp configuration](omp.md)); browser env defaults; Chrome autoprune timer. |
| `development` | on | Rust toolchain, build essentials, development-mode npm packages. |
| `firstmate` | on | Firstmate clone tracking the fork's `main`, plus seeded Firstmate config: crew dispatch, crew and secondmate harness, the crew omp overlay (crew advisor, see [omp configuration](omp.md#advisor)), Herdr backend selection, startup memory budget, and the spawn memory floor. |
| `docker` | on | Docker engine and Compose v2, with daemon defaults `init` (reaps orphaned children) and `live-restore`. Group membership is opt-in through the Ansible variable `factory_docker_group_users`. |
| `fleet_guards` | off | Shared Supabase stack, Docker event guard, [browser ladder](fleet-guards.md#browser-ladder), dev-server reaper, devtools-bridge reaper, storage guard, env seeder. See [Fleet guards](fleet-guards.md). |
| `tailscale` | off | Tailscale daemon only. Authentication is manual; see [Security](security.md#remote-access). |
| `desktop` | off | Loopback-only XFCE + TigerVNC + noVNC operator desktop on `127.0.0.1:6080`, and the Google Chrome apt package. Needs an operator-created VNC password; see [Desktop access](recovery.md#desktop-access). Also supplies the TigerVNC/noVNC packages the browser ladder's `vnc` tier needs. |

Herdr 0.9.0 is always installed, with the captured UI preferences and one canonical, versioned user-service executable. Exact versions for every profile are in [Dependencies](dependencies.md).
