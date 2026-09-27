# Moving the agents to a bigger host

This moves the agent fleet (Firstmate homes, secondmate homes, crew lanes, the no-mistakes gate) from the primary VPS to a more powerful host, for higher concurrency. The VPS is not retired. It stays up, and it keeps everything that is not an agent.

## What stays on the VPS

**sub2api stays on the VPS. Never provision, move, or recreate it on another host.** `/home/ubuntu/sub2api` is the model relay: the `sub2api` container, its Postgres (`s2a-db`), its Redis (`s2a-redis`), the volumes `sub2api_s2a_pg`, `sub2api_s2a_redis` and `sub2api_s2a_data` (`/app/data`), and `iterative-tunnel.service`, the Cloudflare tunnel in front of it. Its database holds the relay's keys and accounts, so a second copy splits them, and stopping it kills every live scan running through it. Code Factory has no sub2api profile, on purpose. Anything on the new host that used sub2api at `127.0.0.1:8099` uses the tunnel instead, because that port exists only on the VPS.

Other Docker data stays too: the shared Supabase stack, SigNoz (`~/perpetual-signoz`), and every project database. A project moves its own data only as a deliberate project decision, with a database-aware backup and restore ([App and fleet state](recovery.md#app-and-fleet-state)). The new host's `fleet_guards` profile builds its own shared Supabase from the fixture archive ([The fixture](fleet-guards.md#the-fixture)); the VPS stack keeps running.

`~/super.env` is still edited only on the VPS ([Shared credentials](secrets.md)).

## Warnings

- **Never push the main home's local `main`.** It carries local-only commits (185 ahead of upstream on 2026-09-27) that belong to this operator's home.
- **Never push a branch that carries commit `4d87c3bd`.** That commit put live credentials into the main home's history; on 2026-09-27 the branches `feat/omp-crew-overlay`, `fm/layer-personal` and `home-main-pre-u3-2026-09-25` carry it. Before you push any branch from the main home, run `git merge-base --is-ancestor 4d87c3bd <branch>`. It must exit non-zero. Exit 0 means the branch carries that commit: do not push it.
- To carry local-only commits to the new host, copy them host to host (`git bundle create` and `scp`), never through a forge.
- **`firstmate-vps.tailc4c9b.ts.net` stays with the VPS.** The VPS keeps its tailnet name and its `tailscale serve` and Funnel ports, because the machine and its services stay. The new host joins as a new device under its own name. After cutover, links to agent-side pages (the desktop wall on `:6090`, noVNC, dev previews) use the new host's name. Never give the new host the old name: Tailscale renames a duplicate, and links would reach the wrong machine.
- **Never run two copies of one home.** Two watchers on one home's state double-dispatch and fight over its inbox. The old home's agents stop only after the new one is confirmed (see [Cutover](#cutover)).

## 1. Provision the new host

1. Follow the [Quick start](../README.md#quick-start): bootstrap, init, validate, plan, apply, doctor. In `.local/host.yml`, enable the same profiles as the VPS, plus `desktop`: the fleet-browser sign-in in [What git does not carry](#2-what-git-does-not-carry) needs its TigerVNC and noVNC packages, and with `desktop` on the default installs `/usr/bin/google-chrome`, which the fleet-browser finds first.
2. Fetch `~/super.env` as described in [Fetch on a new host](secrets.md#fetch-on-a-new-host). Compare its `sha256sum` with the VPS copy.
3. Join the tailnet as a new device ([Remote access](security.md#remote-access)).

## 2. What git does not carry

| Item | How it moves |
| --- | --- |
| omp, Anthropic (claude CLI), Codex and gh logins | Sign in again on the new host: [Sign in](omp.md#sign-in), `gh auth login`. Never copy a credential store ([Security](security.md)). |
| Fleet-browser web sessions | Sign in again on the new host through the fleet-browser VNC tier: run `~/oss-fleet/browsers/fleet-browser up vnc`, then open noVNC at `http://127.0.0.1:6909/vnc.html?autoconnect=1` over an SSH tunnel (`ssh -L 6909:127.0.0.1:6909 <host>`). `cookie-sync` then shares that session with every tier ([Browser ladder](fleet-guards.md#browser-ladder)). Sign in to Amazon, Apple, Claude, Cloudflare, GitHub, Granola, LinkedIn, Microsoft, OpenAI, Phantom, Railway, Stripe, Subliminal (subliminal.inc), Swarms (swarms.world), X, and iterative.sh. Google, including YouTube, refuses sign-in inside the fleet-browser: sign in to Google by hand in an ordinary browser, not in the fleet-browser. Never read, print, or copy any cookie value ([Never export](security.md#never-export)). |
| `~/Dev/firstmate/.env` (`TYPESAFE_API_KEY`, which turns on typed dispatch resolution) | Enter it by hand on the new host, in a file with mode `600`. Typed dispatch resolution stays off until it is there. It stays out of `super.env`. |
| Project clones with unpushed commits | List them on the VPS with the loop below. Push each branch to its fork, except the main home's `main` (see [Warnings](#warnings)). |
| `data/` and `config/` of the main home (`~/Dev/firstmate`) | `rsync -a` over SSH after `./factory apply`, as the first pass of the cutover sync ([On a new host](security.md#on-a-new-host)). Add `--exclude secondmates.md`: `data/secondmates.md` holds each host's own secondmate home paths, and only that host's provisioning writes it. The next apply rewrites the seeded names in `config/` from this repository ([Seeded Firstmate and OMP configuration](architecture.md#seeded-firstmate-and-omp-configuration)). Never copy any home's `state/`: its records name host-bound Herdr panes, pids and sockets, so [Cutover](#cutover) step 2 empties it of tasks first, and a clone a home keeps there (such as swarms-mate's `state/swarms-daily-repo`) is re-created by the script that uses it. |
| Each home's `projects/` clones | Never copied: they are private project working trees ([Never export](security.md#never-export)). After the pushes above, clone each repository the main home has under `projects/` from its `origin` into the same path on the new host, before provisioning the secondmate homes (next row). |
| `data/` and `config/` of every secondmate home | Provision each home on the new host with Firstmate's secondmate-provisioning (`bin/fm-home-seed.sh`), using the id and `projects:` from its line in the VPS `data/secondmates.md`. That clones the listed projects and registers the new home in the new main home's `data/secondmates.md`; a leased treehouse slot usually has a different path than on the VPS. Clone any other repository the VPS home has under `projects/` from its `origin`. Then `rsync -a` the VPS home's `data/` and `config/` into the path the new registry gives for the same id. |
| Each home's untracked `.omp/mcp.json` and `.omp/rules/` | `rsync -a` them with the home's `data/` and `config/`; they hold no credentials. Then rewrite the home path in `.omp/mcp.json` with the `sed` of the crontab row. |
| no-mistakes | Apply seeds `~/.no-mistakes/config.yaml` with the gate agent. Merge any other settings from the VPS file by hand, without `acpx_path`, which names a VPS-only path. Then run `no-mistakes init` in every gated clone on the new host that has no `no-mistakes` remote yet (provisioning initializes the clones it makes). List the gated clones on the VPS with `python3 -c "import sqlite3; [print(r[0]) for r in sqlite3.connect('file:$HOME/.no-mistakes/state.sqlite?mode=ro', uri=True).execute('select working_path from repos')]"`, and keep only paths that still exist under a home's `projects/`; the list also holds stale ones such as `~/Dev/firstmate_old`. Do not copy `state.sqlite` or `repos/`. |
| omp settings (`~/.omp/agent/config.yml`) | Apply writes `config/omp.yml` there only when the file is absent, so the new host starts from the seed, without the VPS settings such as `task.maxConcurrency`, `memory.backend` and `tools.approvalMode`. Diff the VPS file against the new one and merge by hand ([Updating an existing host](omp.md#updating-an-existing-host)). Review host-specific keys such as `browser.cdpUrl` before merging them. |
| omp plugins and skill roots ([Plugins and skills](capacity.md#plugins-and-skills)) | Run `omp plugin marketplace add` for `DietrichGebert/ponytail`, `ayghri/i-have-adhd` and `JuliusBrussee/caveman`, then `omp plugin install` for `ponytail@ponytail`, `i-have-adhd@i-have-adhd` and `caveman@caveman`, and confirm with `omp plugin list`. Write `~/.omp/agent/i-have-adhd.json` as `{"alwaysOn": true}`. `rsync -a` the skill roots `~/.omp/agent/skills`, `~/.omp/agent/managed-skills` and `~/.agents/skills`. |
| systemd user units | Apply writes its own. After apply, list what the new host lacks: `comm -23 <(ssh <vps> 'ls ~/.config/systemd/user' \| sort) <(ls ~/.config/systemd/user \| sort)`. Move only agent-side units from that list. Never move `iterative-tunnel.service` or other sub2api units, and never copy a unit or drop-in that holds an inline credential ([Never export](security.md#never-export)). The VPS keeps its `fleet-browser-*.service.d/chrome-bin.conf` drop-in hotfix; do not move it, because on the new host the fleet-browser finds the recipe's `/usr/bin/google-chrome`. |
| User crontab | The VPS `crontab -l` entries run swarms-mate's `data/tools` scripts, and entries and scripts name that home's VPS path. After every sync of a home's `data/` to a host where its path differs, run `sed -i 's#<old path>#<new path>#g' <new path>/data/tools/*` there. [Cutover](#cutover) comments the entries out on the VPS at step 1, adds them with the new path on the new host at step 6, and deletes them on the VPS at step 8. |
| Hand-installed tools in `~/.local/bin` | After apply, list what the new host lacks: `comm -23 <(ssh <vps> 'ls ~/.local/bin' \| sort) <(ls ~/.local/bin \| sort)`. Reinstall each agent-side tool from its source and skip backups. Among them are the `fm-*` check scripts the omp extensions call and `chrome-automation-reaper.sh`, which `chrome-reaper.timer` runs. |
| omp rules, extensions and custom models (`~/.omp/agent/rules/`, `extensions/`, `models.yml`) | `rsync -a` them from the VPS; they hold no credentials (`models.yml` reads its key from `aliyun-maas.key`). Then run `herdr integration install omp`, which rewrites Herdr's own extension for the new host's herdr. |
| omp keys (`~/.omp/agent/aliyun-maas.key`, `mcp.json`, `smithery.json`) and each home's `state/secrets/` | Never copy them ([Never export](security.md#never-export)). Recreate each on the new host by hand, mode `600`, entering the keys yourself. `mcp.json` holds the swarms-marketplace MCP server, whose key `swarms-daily-run.sh` also reads. subliminal-mate's Slack MCP server reads its tokens from its home's `state/secrets/`. |

```bash
for g in ~/Dev/*/.git ~/Dev/*/projects/*/.git ~/.treehouse/*/*/*/.git ~/.treehouse/*/*/*/projects/*/.git; do
  d=${g%/.git}; c=$(git -C "$d" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) && echo "$c $d"
done | sort -u -k1,1 | while read -r common d; do
  n=$(git -C "$d" log --branches --not --remotes --oneline | wc -l)
  [ "$n" -gt 0 ] && echo "$n unpushed commits: $d"
done
```

## 3. Check the new host matches

Each check covers a gap measured on the VPS on 2026-09-26. CI runs the `agent-gate` check in `tests/container-smoke.sh` for the gate agent, ponytail-review, and tool floors.

| Gap | Check on the new host | Pass |
| --- | --- | --- |
| VNC browser tier restart-looped with "no chrome binary" (this VPS has only a puppeteer Chrome and keeps its systemd drop-in hotfix) | `test -x /usr/bin/google-chrome` | Exit `0`. |
| Crew advisor calls got a 400 from the server-side fallback | `grep -A2 '^providers:' ~/Dev/firstmate/config/omp-crew-overlay.yml` | `serverSideFallback: false` under `anthropic:`. |
| ponytail-review called the hanging claude CLI | `git -C ~/Dev/Code-Factory diff HEAD~1 \| ponytail-review --stdin; echo $?` | Exit `0` or `2`, never `1`. |
| no-mistakes gate agent (the recipe pinned no-mistakes 1.48.0, which launches `omp acp` with the target repo's AGENTS.md and CLAUDE.md loaded) | `no-mistakes --version`, `no-mistakes doctor`, `jq -r .agents.omp.command ~/.acpx/config.json`, `grep -c '^acp_registry_overrides' ~/.no-mistakes/config.yaml` | `v1.79.0`, doctor reports `acp:omp` runnable, `omp acp`, `0`. |
| AXI tool floors | `quota-axi --version; tasks-axi --version` | At least `0.1.54` and `0.2.6`. |

## Cutover

1. Pause the fleet: tell each home's Firstmate to dispatch nothing new, and comment out the VPS crontab entries.
2. Quiesce every home. First record the main home's secondmates in `data/host-move-secondmates` (first command below): those that run, and those the captain parked, with each hiatus reason. The move never starts a parked secondmate, not even to quiesce its home: tear its home's tasks down from a shell in that home. Then merge, close or tear down (`bin/fm-teardown.sh`, branch kept) every task. A PR waiting on an outside maintainer is torn down too, and re-adopted on the new host when feedback arrives. Then the second command must print nothing (task records, inbox notes, open pending replies other than those to parked secondmates, queued wakes):

   ```bash
   cd ~/Dev/firstmate/state && { grep -lx kind=secondmate *.meta | xargs -r grep -l '^window=' | xargs -r grep -L '^hiatus=' | sed 's/^/running /; s/\.meta$//'; grep -lx kind=secondmate *.meta | xargs -r grep -H '^hiatus=' | sed 's/^/parked /; s/\.meta:hiatus=/ /'; for f in hiatus/*.meta; do [ -e "$f" ] && echo "parked $(basename "$f" .meta) $(head -1 hiatus/README)"; done; } > ../data/host-move-secondmates
   cd ~/Dev/firstmate && for h in . $(sed -n 's/.*home: \([^;]*\);.*/\1/p' data/secondmates.md); do (cd "$h/state" && grep -L '^kind=secondmate$' *.meta; ls inbox | grep -vx handled; grep -L '^phase=\(resolved\|closed_unacknowledged\)$' pending-replies/* | xargs -r grep -Lx -f <(sed -n 's/^parked \([^ ]*\).*/task_id=\1/p' ~/Dev/firstmate/data/host-move-secondmates); cat .wake-queue) 2>/dev/null | sed "s|^|$h: |"; done
   ```

3. Wait for in-flight no-mistakes runs and live scans to finish. On the VPS, `python3 -c "import sqlite3; print(sqlite3.connect('file:$HOME/.no-mistakes/state.sqlite?mode=ro', uri=True).execute(\"select count(*) from runs where status='running'\").fetchone()[0])"` must print `0`.
4. Run the final sync of `data/`, `config/` and the untracked `.omp/` files for every home, as in the rows of [What git does not carry](#2-what-git-does-not-carry): without `data/secondmates.md`, each secondmate home into the new path registered for its id, and the home paths in `data/tools` and `.omp/mcp.json` rewritten as in the crontab row.
5. In the new main home, confirm `bin/fm-home-seed.sh validate` passes and each `home:` in `data/secondmates.md` holds a `.fm-secondmate-home` file that names its id.
6. Start the agents on the new host: the main home first, then, from the main home, each secondmate listed as `running` in `data/host-move-secondmates` that has no `state/<id>.meta` there yet, with `bin/fm-spawn.sh <id> --secondmate`. A `parked` secondmate stays parked on the new host until the operator restarts it by name. Then add the crontab entries with the new home paths.
7. Confirm each home: its watcher (`bin/fm-watch.sh`) is running, and one steer round trip works (`bin/fm-send.sh` from the main home to each secondmate, which acknowledges it).
8. Only then stop the old homes' agents on the VPS and delete the commented crontab entries. sub2api and the other VPS services keep running.

Rollback: first quiesce the new host's homes as in step 2, stop their agents and remove the new host's crontab entries. Before step 8, uncomment the VPS crontab entries and unpause the VPS homes; nothing else on the VPS changed. After step 8, sync `data/`, `config/` and the untracked `.omp/` files back from the new host, the same way in reverse (without `data/secondmates.md`, each secondmate home into its VPS path for the same id, and the home paths rewritten), then restart the VPS main home and its `running` secondmates as in step 6, and re-add the crontab entries with the VPS paths.

## Time per phase

| Phase | Estimate | Basis |
| --- | --- | --- |
| Provision | 15 to 30 minutes | CI applies the `agents` and `development` profiles in about 3 minutes per run. Docker, desktop and the Supabase fixture restore are not measured. |
| Logins and `super.env` | About 45 minutes | Four CLI sign-ins, 16 fleet-browser sign-ins and Google by hand, about 2 minutes each (not measured); the fetch takes seconds. |
| Hand copy | About 45 minutes | Measured 2026-09-27: main home `data/` and `config/` 12 MB, all secondmate homes about 175 MB, 14 clones with unpushed commits. The transfer takes under a minute; the time is in reviewing units and tools, pushing branches, re-cloning projects and entering the omp keys (tools and keys not measured). |
| Pause, quiesce, wait for runs | 20 to 90 minutes | A task whose PR waits on an outside maintainer is torn down, not waited for. no-mistakes runs from start to green CI, last 10 days: median 20 minutes, 90th percentile 90 minutes (47 runs). Live scans run on their own schedule. |
| Final sync, start, confirm | About 15 minutes | One rsync per home, then one watcher check and one steer per home. |
