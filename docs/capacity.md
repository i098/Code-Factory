# Capacity and pruners

Sizing for a fleet host, and every process that prunes or reaps on its own.
Figures are estimates from a measured fleet host.

## Load estimate

### What one lane costs

| Component | Memory | Source |
| --- | --- | --- |
| omp crewmate (one agent process) | 300-750 MB RSS | measured |
| no-mistakes pipeline agent (omp) while a lane ships | about 450 MB | measured |
| `next dev` / `next-server` for a UI lane | 3-4 GB | [fleet guards](fleet-guards.md) |
| `tsc --noEmit` | about 0.6 GB; lane node scripts capped at a 2048 MB heap | measured; the seeded worktree `node` wrapper ([fleet guards](fleet-guards.md)) |
| chrome-devtools-axi bridge + `chrome-devtools-mcp` | about 0.3 GB for the MCP child; an idle bridge holds about 2 GB | measured |
| Obscura browser tier | about 25 MB idle | [browser ladder](fleet-guards.md#browser-ladder) |
| **Light lane** (docs, config, backend: agent + pipeline + tests) | **about 1.35-1.8 GB**; plan 2 GB | sum of the agent, pipeline and `tsc` rows |
| **UI lane** (agent + dev server + tsc + browser) | **5-8 GB**; plan 8 GB | [fleet guards](fleet-guards.md) |

Fixed cost, whatever the lane count: the OS, Herdr, Firstmate and its
secondmates (each an omp process), Docker, and the shared Supabase stack. Allow
about 3 GB; this is an estimate.

Firstmate refuses a new spawn while `MemAvailable` is under
`config/spawn-memory-floor-mb` (8000 MB), and free swap does not count. Plan RAM
from the top of each range:

```
RAM ≈ 8 GB spawn floor + 3 GB fixed + (light lanes × 2 GB) + (UI lanes × 8 GB)
vCPU ≈ (light lanes × 1) + (UI lanes × 2)
```

Idle chrome-devtools-axi bridges come on top: each holds about 2 GB until
`chrome-autoprune` stops it after two idle hours.

### Recommended specs

| Concurrent lanes | vCPU | RAM | Swap | Disk |
| --- | --- | --- | --- | --- |
| 2 light | 4 | 16 GB | 8 GB | 100 GB |
| 2 UI + 2 light, or 8 light | 8 | 32 GB | 16 GB | 200 GB |
| 4 UI + 8 light, or 16 light | 16 | 64 GB | 32 GB | 300 GB |

- **CPU:** the vCPU line above is an estimate for lanes while they compile.
- **RAM:** a 24 GB host fits one UI lane plus two light lanes, or six light lanes.
- **Swap:** keeps the host reachable during a spike. It is not capacity, because the spawn floor ignores it and a swapping host thrashes.
- **Disk:** Docker images and build cache grow with the lane count. The storage guard warns at 85% and prunes at 92%.
- **File watchers:** every agent runs file watchers (LSP servers, bundlers, test runners) as the one factory account, and the stock limit is 128 inotify instances per user. Every host that starts services gets `/etc/sysctl.d/60-agent-host.conf` with `fs.inotify.max_user_instances = 8192`; apply loads it with `sysctl -p` when it writes the file.

## Auto pruners

### Provisioned by this recipe

| Pruner | Profile | Runs | Removes |
| --- | --- | --- | --- |
| `chrome-autoprune.timer` → `chrome-autoprune.py --apply` | `agents` (`browser_prune.enabled`) | every `poll_seconds` (300 s) | AXI bridge browser processes idle past `idle_seconds` (7200 s). It never touches headed, attached or persistent-profile browsers. |
| `fleet-browser-gc.timer` | `fleet_browsers` or `fleet_guards` | every 5 min | Stops browser ladder tiers 2 and 3 (`chrome`, `vnc`) after 30 idle minutes with no CDP client (`FLEET_BROWSER_IDLE_MIN`). |
| `flotilla-dev-server-reaper.timer` → `dev-server-reaper.sh` | `fleet_guards` | every 2 min | `next dev` / `next-server` / `tsc --noEmit` trees whose lane is done, paused, blocked or failed, has no agent, or has been idle 30 min or more (`REAPER_IDLE_MIN`). |
| `flotilla-storage-guard.timer` → `storage-guard.sh` | `fleet_guards` | every 5 min | At CRIT (92%): build cache, dangling images, unused images older than `factory_storage_guard_image_age_hours`. Never volumes, containers, repositories, logs or home content. |
| `flotilla-devtools-bridge-reaper.timer` → `devtools-bridge-reaper.sh` | `fleet_guards` | every 10 min | Attached chrome-devtools-axi bridges (`CHROME_DEVTOOLS_AXI_BROWSER_URL` set) whose process tree used no CPU and whose session state files did not change for 60 min (`REAPER_IDLE_MIN`); never any other bridge. |
| `flotilla-docker-guard.service` → `docker-guard.sh` | `fleet_guards` | on every container create | Supabase CLI project containers other than the shared stack. Bare Postgres containers are only logged. |
| Docker `init: true` (`/etc/docker/daemon.json`) | `docker` | continuously | Zombie processes inside every container (docker-init as PID 1). |
| Firstmate `bin/fm-orphan-sweep.sh` | `firstmate` (ships with the checkout) | on Firstmate's wake drain, at most hourly | Dead per-task desktops, leaked treehouse worktrees, disowned browser, ssh-agent, caddy and websockify processes, and `/tmp` scratch older than two days. It refuses anything a live mate owns. |
| Firstmate `bin/fm-herdr-session-cleanup.sh` | `firstmate` | on every locked session start | Idle restored-shell Herdr presentation panes and their journals. Never a workspace or a pane with an agent. |
| Firstmate `bin/fm-fleet-sync.sh` (`prune_gone_branches`) | `firstmate` | on session start, in bootstrap's network stage | Local project branches whose upstream is gone; never the checked-out branch or one with a worktree. `FM_FLEET_PRUNE=0` disables it. |
| Firstmate `bin/fm-remote-job-reap-orphans.sh` | `firstmate` | on every `fm-teardown.sh` | Remote-job worker processes whose Firstmate code root was deleted. |
