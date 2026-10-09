# omp configuration

omp (`@oh-my-pi/pi-coding-agent`) is the agent harness Crewship installs. This guide covers what the recipe sets up, how to sign in, and how to change models and settings. For every omp setting, run `omp config list` or read omp's own docs.

## What the recipe sets up

With the `agents` profile on, `./ship.sh launch`:

1. Installs the latest published omp, resolved from the npm registry on every apply, plus the omp plugins ponytail, i-have-adhd and caveman, upgraded on every apply (see [Dependencies](dependencies.md#latest-releases)).
2. Copies [`config/omp.yml`](../config/omp.yml) to `~/.omp/agent/config.yml` (directory `0700`, file `0600`), and [`config/omp-lsp.json`](../config/omp-lsp.json) to `~/.omp/agent/lsp.json`, which disables the markdown language server (marksman): it costs each session about 90 MB, and markdown diagnostics add nothing to agent work.
3. Installs the extension `~/.omp/agent/extensions/code-factory-herdr-sidebar.ts`, which feeds the Herdr Agent sidebar the session topic, the pane's short name, and the pull request line (pull request, issue and diff size). Every apply rewrites it. See [Herdr sidebar](herdr.md).
4. Installs the extension `~/.omp/agent/extensions/aa-mode-icons.ts` from [`config/omp-status-icons.ts`](../config/omp-status-icons.ts). Every apply rewrites it. See [Status line icons](#status-line-icons).
5. Installs the extension `~/.omp/agent/extensions/fm-no-pattern-kill.ts` from [`config/omp-no-pattern-kill.ts`](../config/omp-no-pattern-kill.ts). It blocks `pkill`, `killall` and kill-by-`pgrep` commands in every omp session: all agents on the host run as one user and each worker's brief sits in its command line, so a name or pattern can match other workers. Kill a process by the PID you started instead. Every apply rewrites it. It is a best-effort seatbelt, not a barrier: it matches the command text, so it lets through an absolute path (`/usr/bin/pkill`), a kill whose targets come from `pidof`, `ps | grep` or a `pgrep` loop, and the list form in an eval cell (`subprocess.run(["pkill", ...])`), and it blocks read-only mentions such as `grep -rn pkill docs/`. Removing worker briefs from the command line is the real fix and is out of scope for this recipe.
6. Installs the extension `~/.omp/agent/extensions/code-factory-quality-gate.ts` from [`config/omp-quality-gate.ts`](../config/omp-quality-gate.ts), the sentrux and fallow check at the end of every agent turn. Every apply rewrites it. See [Quality gate](#quality-gate).
7. Sets up omp as the no-mistakes pipeline agent. See [no-mistakes pipeline agent](#no-mistakes-pipeline-agent).
8. Installs the skills in [`skills/`](../skills/) for omp and Claude Code. See [Skills](#skills).
9. Installs [`config/AGENTS.md`](../config/AGENTS.md) as the global instructions of Claude Code, omp and Codex. See [Global instructions](#global-instructions).

Both copies are first-write-only. If a file already exists, the recipe leaves it alone, so an account's own settings and provider configuration are never overwritten. The one exception is the two status line keys the [status line icons](#status-line-icons) need, which every apply ensures. See [Updating an existing host](#updating-an-existing-host).

No credentials are installed. You sign in on each host.

## Sign in

1. Start omp as the account that runs the fleet:

   ```bash
   omp
   ```

2. Sign in to each provider named in `modelRoles` in `config/omp.yml`. For Anthropic:

   ```text
   /login anthropic
   ```

   Run `/login` with no argument to pick from every provider. Logins are per provider: signing in to `anthropic` does not sign in to any other provider.

3. Optional: run `/login anthropic` again with another account. omp pools several accounts of the same provider and rotates between them.

Stored credentials live in `~/.omp/agent/agent.db`. An environment variable such as `ANTHROPIC_API_KEY` also works, but a stored login takes precedence over it. Never copy `agent.db` from another host; see [Security](security.md).

## Model access

omp talks straight to the provider APIs. `config/omp.yml` maps every model role to a provider-prefixed id (such as `anthropic/claude-sonnet-5`), and `retry.fallbackChains` uses provider-prefixed ids too. A fresh host needs no router, gateway, or proxy, and binds no extra port. Account rotation is built into omp, so more than one account is not a reason to add a gateway. Bringing back a router or gateway is an explicit operator decision; the header of `config/omp.yml` records this rule.

## Model roles

Each key under `modelRoles` picks the model for one kind of work. A role value is `provider/model-id`, optionally with a thinking suffix such as `:off`, `:high`, `:xhigh`, or `:auto`.

| Role | Used for |
| --- | --- |
| `default` | The main session model. |
| `smol`, `slow` | Fast and deep alternatives. `cycleOrder` sets the order the model switcher cycles through (`smol`, `default`, `slow`, `subagent` here). |
| `task` | Subagents spawned from a session. |
| `plan`, `commit`, `tiny`, `vision`, `memory` | Planning, commit messages, small helper calls, image input, and memory. |
| `advisor` | The advisor model. See [Advisor](#advisor). |

`config/omp.yml` also defines custom roles (`designer`, `subagent`, `Kimi`). The current model for each role is in [`config/omp.yml`](../config/omp.yml).

`retry.fallbackChains` lists, for a model id or role, the models to try when it keeps failing (rate limits, quota, outages). `retry.maxDelayMs` caps the retry backoff; a provider-stated wait longer than that fails fast instead of sleeping.

## Changing models

On one host, now: open `/model` in a session and use the **Roles** view, or edit `modelRoles` in `~/.omp/agent/config.yml`. Check the result with:

```bash
omp config get modelRoles
omp models --kind chat      # models you can assign
```

For every future host, edit [`config/omp.yml`](../config/omp.yml) in this repository and commit it. New hosts get it on their first apply. Existing hosts do not; see below.

For one repository only, create `<repo>/.omp/config.yml` with the keys to override. It is merged over the global config when omp starts in that directory. Arrays replace the global value instead of appending to it.

## Advisor

The advisor is a second model that reviews each completed turn and can add notes. `config/omp.yml` picks its model (`modelRoles.advisor`) and sets `advisor.enabled: false`, so the advisor is off. Turn it on for one session with `/advisor on`, or for every session with `advisor.enabled: true` in `~/.omp/agent/config.yml`.

Firstmate turns it on for omp crewmate and scout launches only, never secondmates, by layering the seeded `config/omp-crew-overlay.yml` over `~/.omp/agent/config.yml` (see [Seeded Firstmate and OMP configuration](architecture.md#seeded-firstmate-and-omp-configuration)). Crews get fable 5.1 at low thinking, with `providers.anthropic.serverSideFallback: false`, because Anthropic rejects the global server-side fallback on every advisor call with a 400. They never wait on it, because the overlay's `syncBacklog: "off"` overrides the global `"1"`. Turns that land during a review batch into the next call, and the advisor interrupts at most once per 10 turns. omp has no every-N-turns setting.

The omp that the no-mistakes daemon spawns gets its own advisor from a separate overlay, not from Firstmate. See [no-mistakes pipeline agent](#no-mistakes-pipeline-agent).

## Other seeded preferences

`config/omp.yml` also sets the theme (`dark-rose-pine`), a custom status line (see [Status line icons](#status-line-icons)), `textVerbosity: low`, `readLineNumbers: true`, hidden thinking blocks (`hideThinkingBlock: true`), steering, follow-up and interrupt modes, vim mode in the editor (`tui.vimMode`), and at most 128 parallel subagent tasks (`task.maxConcurrency`). Memory uses the mnemopi backend (`memory.backend: mnemopi`) with no embeddings, the `smol` model for its own calls, and polyphonic recall, enhanced recall and proactive linking on. Change a single value with `omp config set <key> <value>`, or use `/settings`.

## Status line icons

The status icons extension puts the mode indicators and the configured hooks on the main status line as one row of evenly spaced Nerd Font icons, instead of one extension status line per plugin and a separate hooks line:

- Modes: caveman, ADHD (`i-have-adhd`) and ponytail. An icon shows if and only if its mode is on in that omp session; an off mode has no icon, because omp strips all styling from extension statuses and a dimmed icon would look the same as a lit one. The extension takes over the `ponytail` and `i-have-adhd` status keys those plugins set, so their own text statuses no longer show; each plugin clears its key when its mode turns off. A plugin configured with `hideStatus` never sets its key, so its icon stays hidden even while the mode is on.
- caveman has no omp extension, and omp does not run the Claude Code hooks the `caveman@caveman` plugin ships, so nothing records caveman's state. The icon works it out from the session itself: caveman is on at the start when the session's system prompt names `skill://caveman` (an always-apply rule that keeps it in force), then every prompt you send is read with caveman's own parser from the installed plugin (`src/hooks/caveman-parse.js`), so "stop caveman", "normal mode" and `/caveman off` hide it, and "talk like caveman" or invoking the caveman skill (`/caveman`) shows it again. A skill invocation is read with its arguments, so `/skill:caveman off` hides it, and the icon updates at the end of that turn. Moving to another point in the session tree re-reads that branch. Without the plugin installed the icon never shows. It reflects what you asked for in the session, not whether the model actually writes that way.
- Hooks: the hooks in `~/.claude/settings.json` and `<cwd>/.claude/settings.json`. Known hooks get their own icon; the rest show as one icon followed by their count.

The file is installed as `aa-mode-icons.ts` on purpose: omp loads extensions in name order, and the extension must wrap the status API before the ponytail and ADHD plugins set their statuses.

The row needs two keys in `statusLine`: `status` in `leftSegments`, which shows extension statuses on the main line, and `showHookStatus: false`, which drops the separate hooks line. omp reads `leftSegments` only when `preset` is `custom`. `config/omp.yml` seeds all three. On a host whose `~/.omp/agent/config.yml` already exists and uses `preset: custom`, every apply appends `status` to `leftSegments` when it is missing and sets `showHookStatus` to `false`, and leaves every other key alone. A config with any other preset, or none, is left untouched: switch it to `preset: custom` by hand to get the row. Start a new omp session to see the change. Check the result with:

```bash
omp config get statusLine.leftSegments
omp config get statusLine.showHookStatus
```

## Quality gate

The quality gate extension runs when an agent turn ends, in the git repository of the session's working directory. It has two parts.

**Blocking.** This part runs only when the repository has `.sentrux/baseline.json` and the turn changed files (a new commit counts). It runs `sentrux gate .` once. A `DEGRADED` verdict, or a `Quality: <baseline> -> <current>` drop of more than `FM_QUALITY_MAX_DROP` points, sends the agent one continuation with the evidence: fix the structure, or re-baseline on purpose. A low score alone never blocks. The gate blocks at most once per prompt: the continuation turn it starts is never blocked again.

**Advisory.** When the repository has uncommitted changes, these checks run in the background:

- `sentrux check .`, when `.sentrux/rules.toml` exists.
- `fallow audit --changed-since HEAD`, when `package.json` or `tsconfig.json` exists.

A check that fails is shown to the agent at the start of its next prompt. The advisory checks never block. A second run does not start while one runs, or for a diff that was already checked.

A missing `sentrux` or `fallow`, a repository without a baseline, a timeout, or output the extension cannot parse never blocks. Supervisor homes without `.sentrux/baseline.json` are not gated.

Two environment variables change the gate. Set them in the environment that starts omp:

| Variable | Effect |
| --- | --- |
| `SENTRUX_GATE=advisory` | Turns the block off. The advisory checks still run. |
| `FM_QUALITY_MAX_DROP` | The quality drop, in points, that the gate tolerates. Default `250`. |

To turn the gate on for a repository, or to accept a structural change on purpose, save a new baseline and commit it:

```bash
sentrux gate --save .
git add .sentrux/baseline.json
```

This repository gates itself the same way. The `quality gate` CI job runs `bun config/omp-quality-gate.ts` (the same blocking rule, exit 1 on a block) against the committed [`.sentrux/baseline.json`](../.sentrux/baseline.json), and `fallow audit` on the changed files as a warning that never fails the job. Unlike the omp extension, the CI job fails closed: it also exits 1, naming the cause, when `.sentrux/baseline.json` is missing, when `sentrux` is missing, crashes or times out, or when its output has no parseable `Quality:` line.

## no-mistakes pipeline agent

no-mistakes has no native omp agent. omp is a Pi fork with the same `--mode json` stream, so the recipe runs omp through no-mistakes' native `pi` adapter, the only adapter that reuses one fixer session across review-fix rounds. `acp:omp` (acpx running `omp acp`) stays as the fallback, and it always starts cold. Every apply:

1. Installs [`config/omp-as-pi/`](../config/omp-as-pi/) to `~/.no-mistakes/omp-as-pi/`. The `omp-as-pi` wrapper maps `--session` to `--resume`, and `--no-context-files` to the exact neutralization no-mistakes applies to an omp gate (`--config gate-overlay.yml --no-rules --no-skills --no-extensions`, with the overlay pinned by sha256). It refuses every other argument with exit 64 and logs the refusal to `~/.no-mistakes/omp-as-pi/refusals.log`; no-mistakes then re-runs that call on `acp:omp`.
2. Checks the pi adapter of the no-mistakes release it installs. no-mistakes installs at its newest non-draft release, prereleases included, but the wrapper only translates the arguments the adapter it was proven against builds. `check-adapter.sh v<version>` fetches that release's four adapter sources (`pi.go`, `pi_profile.go`, `fallback.go`, `ompgate.go`) and compares them with the sha256 pins in `check-adapter.sh`, the only place the pins live. It exits 0 when every pin matches, 1 when a source differs from its pin or is gone from the tag (HTTP 404), and 2 when it proves nothing: a network error, a timeout, or any other HTTP status.
3. Sets the agent in `~/.no-mistakes/config.yaml`. When the check passes, it sets `agent: [pi, acp:omp]`, `agent_path_override.pi` to the installed wrapper, and `agent_config.pi` to model `anthropic/claude-sonnet-5-5` with effort `high`. When a pin differs (exit 1), it sets `agent: [acp:omp]` and prints why. When the check is inconclusive (exit 2 or any other failure), it leaves the agent setting as it is and prints a warning; the next apply checks again. Only those two agent lists are managed; any other agent choice is left alone. The rewrite drops the seed's comments, so note its rule here: never add `acp_registry_overrides` for omp, because no-mistakes refuses an overridden omp as a gate agent in repos with `disable_project_settings: true`.
4. Installs [`config/no-mistakes-omp.yml`](../config/no-mistakes-omp.yml) as `~/.no-mistakes/omp-config.yml`, an omp overlay for daemon-spawned omp only. It turns on an Opus 5.5 advisor at medium thinking and sets `modelRoles.default` to Sonnet 5.5 at `high`: no-mistakes cannot pin model or effort for `acp:omp`, so the fallback takes both from this file, while the pi path passes its own `--model` and `--thinking` from `agent_config.pi`. The systemd drop-in `~/.config/systemd/user/no-mistakes-daemon-.service.d/code-factory.conf` points `PI_CONFIG_FILES` at it; the `no-mistakes-daemon-` prefix makes systemd apply it to the daemon unit, whose name ends in a hash.

Restarting the daemon kills the pipeline runs in flight, so the recipe never does it. When the daemon's omp overlay, its systemd drop-in, or the agent setting in `~/.no-mistakes/config.yaml` changes, the apply prints a reminder: run `no-mistakes daemon restart` once no pipeline run is active.

Verification runs `~/.no-mistakes/omp-as-pi/omp-as-pi --omp-as-pi-check`, which confirms the installed omp still lists every flag the wrapper uses and the gate overlay matches its pin. CI runs the wrapper's offline tests with `bash config/omp-as-pi/test.sh`; `test.sh --live` also drives the real omp with a cheap model.

When a new no-mistakes release changes the adapter, re-prove the wrapper against it (`test.sh --live` and a pipeline run), then update the pins in `check-adapter.sh`.

## Skills

Crewship keeps skills, not personal notes, in `skills/`. `CLAUDE.md` and `AGENTS.md` stay free of personal content.

- `skills/public/<name>/SKILL.md`, with any helper files beside it: skills that ship with Crewship.
- `skills/private/<name>/SKILL.md`: skills that stay on the host. Git ignores this folder except its README, and Docker builds leave it out.

Every apply copies each skill to `~/.omp/agent/skills/<name>/` and `~/.claude/skills/<name>/` with [`scripts/skills.py`](../scripts/skills.py). A private skill wins over a public skill with the same name. The installer records the names it installed in `~/.local/share/code-factory/skills.json`. It rewrites only those skills, and removes one when its source leaves `skills/`. A skill directory that the manifest does not list belongs to the operator: the installer never replaces or removes it and reports it under `skipped`. An unchanged apply changes nothing.

## Global instructions

[`config/AGENTS.md`](../config/AGENTS.md) holds generic working rules and nothing personal: it points each agent at the skills. Every apply writes it to `~/.claude/CLAUDE.md` (Claude Code), `~/.omp/agent/AGENTS.md` (omp) and `~/.codex/AGENTS.md` (Codex) with [`scripts/instructions.py`](../scripts/instructions.py). When `~/.claude/RTK.md` exists, the Claude Code copy also gets the `@RTK.md` import.

The installer records the SHA-256 of each file it wrote in `~/.local/share/code-factory/instructions.json`. If a file on the host matches neither that record nor the new text, the user changed it: the installer moves it to `<file>.<UTC time>.bak` in the same folder before it writes, and the apply prints the backup paths. An unchanged apply changes nothing.

## Updating an existing host

Because the seed is first-write-only, an edit to `config/omp.yml` never reaches a host that already has `~/.omp/agent/config.yml`, except the two keys [Status line icons](#status-line-icons) needs. To update one:

1. Compare the two files:

   ```bash
   diff ~/.omp/agent/config.yml config/omp.yml
   ```

2. Merge the changes you want into `~/.omp/agent/config.yml` by hand, or use `/settings` and `/model` in a session.

To upgrade omp itself, run `./ship.sh launch`: it installs the newest published omp and relinks `~/.local/bin/omp`.
