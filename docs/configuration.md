# Configuration

`.local/host.yml` is the single source of truth for one host. It is gitignored and owner-only (`0600`).

## Commands

| Command | What it does |
| --- | --- |
| `./factory init` | Copies `config/default.yml` to `.local/host.yml` with your user, home, and `~/Dev` workspace filled in. Never overwrites an existing file. Options: `--user`, `--home`, `--container`. |
| `./factory validate` | Checks the config against `schemas/factory.schema.json` and the cross-field rules below. |
| `./factory plan` | Runs the Ansible playbook in check mode. Reports what would change; mutates nothing. |
| `./factory apply` | Runs the playbook for real. Asks for the sudo password when passwordless sudo is not available. With the `firstmate` profile on, the first successful interactive apply with omp signed in then opens the new-host questions (below). |
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
    fleet_guards: false   # Shared Supabase and the fleet's guards
    fleet_browsers: false # Browser ladder (obscura tier on 127.0.0.1:9222)
    chat: true            # Concord (Discord) and slk (Slack) terminal clients
  herdr:
    theme: rose-pine
    toast_delivery: terminal  # notifications go to the outer terminal
    sidebar_width: 46     # Spaces and Agents sidebar layouts: see herdr.md
    sidebar_max_width: 56
    sidebar_space_rows: |
      [ ... ]
    sidebar_agent_rows: |
      [ ... ]
    sidebar_bg: "reset"   # the terminal's own background
  fleet:
    supabase_project_id: <project-id>   # The shared Supabase project id; the default is set in config/default.yml
    fixture_archive: ""   # Path to DB volume tarball for fresh hosts
  firstmate:
    url: https://github.com/kunchenguid/firstmate.git
    # checklist:          # Optional; set only in .local/host.yml
    #   repo: owner/private-repo
    #   path: checklist.md
  # mac_ssh:              # Optional; set only in .local/host.yml. See security.md#ssh-to-a-mac
  #   host: <Mac tailnet name or IP>
  #   user: <Mac login>
```

`validate` also enforces these rules:

- `user` is not `root`, and `workspace` is inside `home`.
- `firstmate` and `browser_prune.enabled` need `agents`.
- `fleet_guards` needs `docker` and `firstmate`. Obscura is always its latest release. An older `.local/host.yml` that still sets `browsers.obscura_version` or `browsers.obscura_sha256` keeps working: both keys are deprecated, ignored, and reported in one warning on stderr. No edit is required.

The Firstmate checkout tracks the default branch of upstream Firstmate, not a sha. Every apply fetches `origin/main` and fast-forwards `main`, so tracking it is how a host stays current. Do not re-pin it to a sha. Each run resolves `origin/main` once and reports the sha it installed. To track a fork, set `firstmate.url` in `.local/host.yml`. The URL applies to a fresh clone; verification fails when an existing checkout's `origin` is a different URL, and provisioning never changes it for you. To switch an existing checkout, run `git -C <workspace>/firstmate remote set-url origin <url>` and `git -C <workspace>/firstmate fetch origin`, reconcile any local commits on `main` with `origin/main` by hand, then run `./factory apply`.

## New-host questions

After a successful `./factory apply` with the `firstmate` profile on, once omp has a provider login, Code Factory starts omp in the Firstmate checkout with an opening prompt. Firstmate then asks the move decisions for this host one question at a time: which secondmate homes, services, tools, and unpushed work to bring over.

- The questions follow `firstmate.checklist` when it is set and `gh` can read it: `repo` is a GitHub repository (it can be private) and `path` is the checklist file in it. Set it only in `.local/host.yml`, never in `config/default.yml`. Otherwise they follow [Agent host move](agent-host-move.md).
- They are asked once per host. When the omp session exits successfully, apply writes the marker `~/.local/share/code-factory/new-host-questions-done`; while it exists, later applies skip the questions and print one line naming it. If omp exits non-zero, apply writes no marker and prints one line saying the questions did not complete. To ask again, delete the marker and rerun `./factory apply` interactively.
- The launch needs an interactive terminal, run as `factory.user`. When stdin is not a TTY, when `CI` is set, or when another account runs apply, apply skips them without writing the marker and prints one line saying to rerun `./factory apply` interactively.
- They need an omp provider login. Apply checks with `omp models --json`; when it lists no models or fails, apply skips the questions without writing the marker and prints one line saying to sign in to omp with `/login` ([Sign in](omp.md#sign-in)) and rerun `./factory apply` interactively. On a new host the first apply installs omp, so sign in after it and then rerun apply.

The recipe refuses to overwrite a conflicting unmanaged command or an independently advanced Firstmate checkout. See [Drift and upgrades](recovery.md#drift-and-upgrades).

## Profiles

| Profile | Default | What it installs |
| --- | --- | --- |
| `agents` | on | omp, AXI tools, gh, no-mistakes, treehouse, gws (Google Workspace CLI; [sign-in](google-workspace.md) is manual), acpx; safe omp presentation and model-role settings (see [omp configuration](omp.md)); omp as the no-mistakes gate agent through the pi adapter with `acp:omp` as the fallback, or `acp:omp` alone when the adapter does not match the pins (see [no-mistakes pipeline agent](omp.md#no-mistakes-pipeline-agent)); first-write acpx config; the pattern-kill guard omp extension; `~/.local/bin/ponytail-review`; browser env defaults; Chrome autoprune timer. |
| `development` | on | Rust toolchain (stable), build essentials. |
| `firstmate` | on | Firstmate clone tracking upstream `main`, plus seeded Firstmate config: crew dispatch, crew and secondmate harness, the crew omp overlay (crew advisor, see [omp configuration](omp.md#advisor)), Herdr backend selection, startup memory budget, the spawn memory floor, presentation spaces off, and the turn-end pane-churn flag (see [Seeded Firstmate and OMP configuration](architecture.md#seeded-firstmate-and-omp-configuration)). |
| `docker` | on | Docker engine and Compose v2, with daemon defaults `init` (reaps orphaned children) and `live-restore`. Group membership is opt-in through the Ansible variable `factory_docker_group_users`. |
| `fleet_guards` | off | Shared Supabase stack, Docker event guard, dev-server reaper, devtools-bridge reaper, storage guard, env seeder. See [Fleet guards](fleet-guards.md). |
| `fleet_browsers` | off | The [browser ladder](fleet-guards.md#browser-ladder): the always-on Obscura CDP tier on `127.0.0.1:9222`, the on-demand `chrome` and `vnc` tiers with the `vnc` tier's TigerVNC and noVNC packages, the cookie sync and gc timers, and the ladder environment in shell profiles and the Herdr unit. `fleet_guards` provisions the same ladder, so a `fleet_guards` host needs no change. Needs no other profile; the ladder needs `iproute2` (`ss`) from the base image, which only `desktop` installs. |
| `chat` | on | The latest [Concord](https://github.com/chojs23/concord) (Discord) and [slk](https://github.com/gammons/slk) (Slack) terminal clients, their shared libraries, and a first-write config for each. Logins stay manual. See [Chat clients](chat.md). |
| `tailscale` | off | Tailscale daemon only. Authentication is manual; see [Security](security.md#remote-access). |
| `desktop` | off | Loopback-only XFCE + TigerVNC + noVNC operator desktop on `127.0.0.1:6080`, and the Google Chrome apt package. Needs an operator-created VNC password; see [Desktop access](recovery.md#desktop-access). |

The latest Herdr release is always installed, with the captured UI preferences, the [Spaces and Agents sidebar layouts](herdr.md) with the reporter timer that feeds Spaces, and one canonical, versioned user-service executable. What each profile installs, and where it comes from, is in [Dependencies](dependencies.md).
