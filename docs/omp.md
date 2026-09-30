# omp configuration

omp (`@oh-my-pi/pi-coding-agent`) is the agent harness Code Factory installs. This guide covers what the recipe sets up, how to sign in, and how to change models and settings. For every omp setting, run `omp config list` or read omp's own docs.

## What the recipe sets up

With the `agents` profile on, `./factory apply`:

1. Installs the latest published omp, resolved from the npm registry on every apply (see [Dependencies](dependencies.md#latest-releases)).
2. Copies [`config/omp.yml`](../config/omp.yml) to `~/.omp/agent/config.yml` (directory `0700`, file `0600`), and [`config/omp-lsp.json`](../config/omp-lsp.json) to `~/.omp/agent/lsp.json`, which disables the markdown language server (marksman): it costs each session about 90 MB, and markdown diagnostics add nothing to agent work.
3. Installs the extension `~/.omp/agent/extensions/code-factory-herdr-sidebar.ts`, which feeds the Herdr Agent sidebar the session topic, the pane's short name, and the pull request line (pull request, issue and diff size). Every apply rewrites it. See [Herdr sidebar](herdr.md).
4. Installs the extension `~/.omp/agent/extensions/aa-mode-icons.ts` from [`config/omp-status-icons.ts`](../config/omp-status-icons.ts). Every apply rewrites it. See [Status line icons](#status-line-icons).

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

## Other seeded preferences

`config/omp.yml` also sets the theme (`dark-rose-pine`), a custom status line (see [Status line icons](#status-line-icons)), `textVerbosity: low`, `readLineNumbers: true`, steering and interrupt modes, and `mnemopi.noEmbeddings: true`. Change a single value with `omp config set <key> <value>`, or use `/settings`.

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

## Updating an existing host

Because the seed is first-write-only, an edit to `config/omp.yml` never reaches a host that already has `~/.omp/agent/config.yml`, except the two keys [Status line icons](#status-line-icons) needs. To update one:

1. Compare the two files:

   ```bash
   diff ~/.omp/agent/config.yml config/omp.yml
   ```

2. Merge the changes you want into `~/.omp/agent/config.yml` by hand, or use `/settings` and `/model` in a session.

To upgrade omp itself, run `./factory apply`: it installs the newest published omp and relinks `~/.local/bin/omp`.
