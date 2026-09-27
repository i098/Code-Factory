# Capacity, plugins and pruners

Sizing for a fleet host, the agent plugins and skills the source host runs,
and every process that prunes or reaps on its own. Figures come from the
source host on 2026-09-17 (the incident in [fleet guards](fleet-guards.md)) and
2026-09-24 (live `ps`, `docker system df`, `df`, `systemctl --user list-timers`).

## Load estimate

### What one lane costs

| Component | Memory | Source |
| --- | --- | --- |
| omp crewmate (one agent process) | 300-750 MB RSS | measured 2026-09-24 |
| no-mistakes pipeline agent (`omp acp`) while a lane ships | about 450 MB | measured 2026-09-24 |
| `next dev` / `next-server` for a UI lane | 3-4 GB | [fleet guards](fleet-guards.md) |
| `tsc --noEmit` | about 0.6 GB; pnpm scripts capped at a 2048 MB heap | measured; seeded `.npmrc` |
| chrome-devtools-axi bridge + `chrome-devtools-mcp` | about 0.3 GB for the MCP child; nine idle bridges held about 18 GB | measured 2026-09-24 |
| Obscura browser tier | about 25 MB idle | [browser ladder](fleet-guards.md#browser-ladder) |
| **Light lane** (docs, config, backend: agent + pipeline + tests) | **about 1.35-1.8 GB**; plan 2 GB | sum of the agent, pipeline and `tsc` rows |
| **UI lane** (agent + dev server + tsc + browser) | **5-8 GB**; plan 8 GB | 2026-09-17 incident |

Fixed cost, whatever the lane count: the OS, Herdr, Firstmate and its
secondmates (each an omp process), Docker, and the shared Supabase stack. Allow
about 3 GB; this is an estimate, since most of the source host's stack sat in
swap when measured.

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

- **CPU:** the vCPU line above is an estimate for lanes while they compile. The source host (8 vCPU) sat at load average 31-36 on 2026-09-24 with 28 GB of swap in use, so it was over capacity.
- **RAM:** the source host has 24 GB. That fits one UI lane plus two light lanes, or six light lanes. Ten lanes filled it on 2026-09-17.
- **Swap:** keeps the host reachable during a spike. It is not capacity, because the spawn floor ignores it and a swapping host thrashes.
- **Disk:** the source host has 193 GB, 85% used. Docker holds 45 GB of images (18 GB reclaimable) and 9 GB of volumes. The storage guard warns at 85% and prunes at 92%.

## Plugins and skills

The recipe does not install these. They are account state on the source host,
listed so a rebuilt host can match it. Add each plugin's marketplace with
`omp plugin marketplace add`, reinstall plugins with `omp plugin install`,
then confirm with `omp plugin list`.

### omp plugins (user scope)

| Plugin | Version | Skills it ships |
| --- | --- | --- |
| `caveman@caveman` | 2.7.0 | `caveman` modes, `caveman-commit`, `caveman-compress`, `caveman-discover`, `caveman-evidence-review`, `caveman-explore`, `caveman-help`, `caveman-learn`, `caveman-manage`, `caveman-optimize`, `caveman-review`, `caveman-setup`, `caveman-stats`, `cavecrew`, `investigate-first`, `lean-build`, `migration`, `safe-refactor`, `surgical-patch`, `verify-and-stop` |
| `ponytail@ponytail` (`@dietrichgebert/ponytail`) | 4.10.0 | `ponytail`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`, `ponytail-review` |
| `i-have-adhd@i-have-adhd` | 0.3.0 | the ADHD output ruleset, always on through `~/.omp/agent/i-have-adhd.json` and hidden from model-initiated selection |

### Other skill roots

| Root | Skills |
| --- | --- |
| `~/.omp/agent/skills` | `kun`, `token-saver-config`, `vision` |
| `~/.omp/agent/managed-skills` (written by the agent's `manage_skill`) | `no-ai-slop`, `standup`, `tokensave-missing-index-fix`, `ui-screenshot-evidence-loaded-host` |
| `~/.agents/skills` | `lavish`, `no-mistakes` |
| Firstmate checkout `.agents/skills` (arrives with the `firstmate` profile) | 35 Firstmate skills, among them `ask-user-authority`, `bearings`, `firstmate-coding-guidelines`, `secondmate-provisioning`, `stuck-crewmate-recovery`, `stow` and `updatefirstmate` |
| `~/.claude/skills` | 137 Claude Code entries. The claude CLI reads them; omp crews do not. |

## Auto pruners

### Provisioned by this recipe

| Pruner | Profile | Runs | Removes |
| --- | --- | --- | --- |
| `chrome-autoprune.timer` → `chrome-autoprune.py --apply` | `agents` (`browser_prune.enabled`) | every `poll_seconds` (300 s) | AXI bridge browser processes idle past `idle_seconds` (7200 s). It never touches headed, attached or persistent-profile browsers. |
| `fleet-browser-gc.timer` | `fleet_guards` | every 5 min | Stops browser ladder tiers 2 and 3 (`chrome`, `vnc`) after 30 idle minutes with no CDP client (`FLEET_BROWSER_IDLE_MIN`). |
| `flotilla-dev-server-reaper.timer` → `dev-server-reaper.sh` | `fleet_guards` | every 2 min | `next dev` / `next-server` / `tsc --noEmit` trees whose lane is done, paused, blocked or failed, has no agent, or has been idle 30 min or more (`REAPER_IDLE_MIN`). |
| `flotilla-storage-guard.timer` → `storage-guard.sh` | `fleet_guards` | every 5 min | At CRIT (92%): build cache, dangling images, unused images older than `factory_storage_guard_image_age_hours`. Never volumes, containers, repositories, logs or home content. |
| `flotilla-devtools-bridge-reaper.timer` → `devtools-bridge-reaper.sh` | `fleet_guards` | every 10 min | Attached chrome-devtools-axi bridges (`CHROME_DEVTOOLS_AXI_BROWSER_URL` set) whose process tree used no CPU and whose session state files did not change for 60 min (`REAPER_IDLE_MIN`); never any other bridge. Nine idle bridges held about 18 GB on 2026-09-24. |
| `flotilla-docker-guard.service` → `docker-guard.sh` | `fleet_guards` | on every container create | Supabase CLI project containers other than the shared stack. Bare Postgres containers are only logged. |
| Docker `init: true` (`/etc/docker/daemon.json`) | `docker` | continuously | Zombie processes inside every container (docker-init as PID 1). |
| Firstmate `bin/fm-orphan-sweep.sh` | `firstmate` (ships with the checkout) | on Firstmate's wake drain, at most hourly | Dead per-task desktops, leaked treehouse worktrees, disowned browser, ssh-agent, caddy and websockify processes, and `/tmp` scratch older than two days. It refuses anything a live mate owns. |
| Firstmate `bin/fm-herdr-session-cleanup.sh` | `firstmate` | on every locked session start | Idle restored-shell Herdr presentation panes and their journals. Never a workspace or a pane with an agent. |
| Firstmate `bin/fm-fleet-sync.sh` (`prune_gone_branches`) | `firstmate` | on session start, in bootstrap's network stage | Local project branches whose upstream is gone; never the checked-out branch or one with a worktree. `FM_FLEET_PRUNE=0` disables it. |
| Firstmate `bin/fm-remote-job-reap-orphans.sh` | `firstmate` | on every `fm-teardown.sh` | Remote-job worker processes whose Firstmate code root was deleted. |

### Running on the source host, not reproduced

These user units run on the source host, but this recipe does not provision
them. `launchpadlib-cache-clean.timer` ships with Ubuntu's `python3-launchpadlib`
package; the rest were added by hand, and a rebuilt host does not have them
until they are exported.

| Unit | Runs | Removes |
| --- | --- | --- |
| `chrome-reaper.timer` → `~/.local/bin/chrome-automation-reaper.sh` | every 3 min | Leaked browser-automation Chrome profiles; never the VNC desktop. |
| `flotilla-mem-guardian.service` → `mem-guardian.sh` | polls every 15 s | Last-line memory defense on memory PSI or low `MemAvailable`. Kills, cheapest first: fleet build/test processes, then the fattest fleet lane (queued for restore), then stale idle Herdr agent panes. Separately, even without memory pressure, while swap in use is 16 GB or more a swap sweep reaps Herdr agent panes outside the fleet idle 72 h or more, at most 3 every 30 min, until swap is under 8 GB; these are logged to `reaped-sessions.tsv`, not queued for restore. |
| `flotilla-sentinel.timer` → `~/oss-fleet/doctor/sentinel.sh` | every 60 s | Nothing while healthy. On memory PSI `some avg60` ≥ 20, `MemAvailable` ≤ 5%, PSI ≥ 1 with `MemAvailable` ≤ 15%, load average ≥ 5 per core, or under 10 GB free on `/`, it starts a `pi` responder, at most once per 15 min. The responder may `kill -TERM` large processes on its KILLABLE list (never for a CPU storm). On a disk emergency it runs `doctor/clean-disk.sh`, which deletes cargo `target` dirs under `~/oss-fleet/repos`, the pip, npm, go-build, pre-commit, puppeteer and uv caches, Hugging Face models unmodified for 30 days, and user journal entries and `~/oss-fleet/logs` files older than 14 days, then runs `pnpm store prune`. |
| `flotilla-worktree-manager.timer` → `~/oss-fleet/doctor/worktree-manager.sh` | daily at 04:00, up to 1 h random delay | `git worktree prune` in every repo under `~/oss-fleet/repos`, empty `/tmp/wt-*` and `/tmp/ra-wt-*` dirs, then `pnpm store prune`. Worktrees with uncommitted or unpushed work are only reported. |
| `flotilla-doctor.timer` → `~/oss-fleet/doctor/run.sh` | every 4 h | Doctor `reports/snapshot-*.txt` older than 14 days and `reports/report-*.md` older than 90 days; trims `agent-run.log` to its last 200 KB. |
| `tetanus-autoprune.timer` | inactive since 2026-09-17 | Stale cargo artifact generations in tetanus lane caches. |
| `seer-logtrim.timer` | daily | Trims Seer service logs over 8 MB to their last 5000 lines. |
| `launchpadlib-cache-clean.timer` | daily | Files in `~/.launchpadlib/api.launchpad.net/cache` older than 30 days. |
