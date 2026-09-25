# omp configuration

omp (`@oh-my-pi/pi-coding-agent`) is the agent harness Code Factory installs. This guide covers what the recipe sets up, how to sign in, and how to change models and settings. For every omp setting, run `omp config list` or read omp's own docs.

## What the recipe sets up

With the `agents` profile on, `./factory apply`:

1. Installs omp from `tools/npm/package-lock.json` (version in [Dependencies](dependencies.md#agent-clis)).
2. Copies [`config/omp.yml`](../config/omp.yml) to `~/.omp/agent/config.yml` (directory `0700`, file `0600`).

The copy is first-write-only. If `~/.omp/agent/config.yml` already exists, the recipe leaves it alone, so an account's own settings and provider configuration are never overwritten. See [Updating an existing host](#updating-an-existing-host).

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

Firstmate turns it on for omp crewmate and scout launches only, never secondmates, by layering the seeded `config/omp-crew-overlay.yml` over `~/.omp/agent/config.yml` (see [Seeded Firstmate and OMP configuration](architecture.md#seeded-firstmate-and-omp-configuration)). Crews get fable 5.1 at low thinking. They never wait on it, because the overlay's `syncBacklog: "off"` overrides the global `"1"`. Turns that land during a review batch into the next call, and the advisor interrupts at most once per 10 turns. omp has no every-N-turns setting.

## Other seeded preferences

`config/omp.yml` also sets the theme (`dark-rose-pine`), a custom status line, `textVerbosity: low`, `readLineNumbers: true`, steering and interrupt modes, and `mnemopi.noEmbeddings: true`. Change a single value with `omp config set <key> <value>`, or use `/settings`.

## Updating an existing host

Because the seed is first-write-only, an edit to `config/omp.yml` never reaches a host that already has `~/.omp/agent/config.yml`. To update one:

1. Compare the two files:

   ```bash
   diff ~/.omp/agent/config.yml config/omp.yml
   ```

2. Merge the changes you want into `~/.omp/agent/config.yml` by hand, or use `/settings` and `/model` in a session.

To upgrade omp itself, bump its version in `tools/npm/package.json`, regenerate `tools/npm/package-lock.json`, and apply. See [Reproducibility policy](architecture.md#reproducibility-policy).
