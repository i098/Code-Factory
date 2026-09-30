# Herdr sidebar

Code Factory renders `~/.config/herdr/config.toml` from [`ansible/templates/herdr.toml.j2`](../ansible/templates/herdr.toml.j2) and the `herdr` block of `.local/host.yml`. This guide covers the two sidebar layouts it ships, Spaces and Agents, and the two feeders that report their `$` tokens: an omp extension for Agents and a reporter timer for Spaces.

The sidebar is 46 columns wide (`sidebar_width`; it may grow to `sidebar_max_width`, 56). That fits the widest pull request line: a 4-digit pull request and issue, 5-digit line counts and a 3-digit file count. There is no status word: the color of the state dot already shows it.

## Spaces: one entry per home

Spaces shows one entry per home workspace. It never repeats per-agent detail, which lives in Agents.

```text
⌂ ⚙ 41%  ▤ 18.2/31.0G 59%  ⛁ 402/937G 43%
  ● firstmate · ⚑ 3 · ▶ 1 · ◷ 4
    ⚙ 29%  ▤ 8%  ⛁ 2%
● swarms · ⚑ 2 · ◷ 3
  ⚙ 1%  ▤ 3%  ⛁ 4%
  ⚠ watcher silent
○ ☾ afk
```

| Line | Shows |
| --- | --- |
| Header | The whole machine, dimmed, on the primary home's entry only (the workspace labelled `firstmate`; without one, the first workspace listed): `⚙` CPU, `▤` used/total RAM, `⛁` used/total root filesystem, each with its share. Every other entry leaves this row empty, and Herdr hides it. Herdr then indents the primary entry's lines 1 to 3 by two columns, and the reporter indents its lines 2 and 3 by two more, so they still sit under the name. |
| 1 | The state dot, then the short name (`$short`): the primary home (`firstmate`) in bold blue, other homes in mauve. A dead helper space (label contains `-afk-daemon-`) shows `☾ afk`, dimmed, and nothing else. A space with no short name shows its own label, dimmed. Then the decision, worker and queue counts below, each in its own color. A count of zero is not shown. |
| 2 | What the space costs the machine, as shares, dimmed, indented two columns: `⚙` CPU, `▤` RAM, `⛁` disk. |
| 3 | `⚠ watcher silent` in orange, indented two columns, only when the home's watcher stopped reporting. |

| Token | Value | Source |
| --- | --- | --- |
| `$short` | `swarms` for `2ndmate-swarms-mate-s4` | The workspace label: `firstmate` stays as is, `2ndmate-<name>-mate-<id>` becomes `<name>`, `└ <task> · p:<token>` becomes `└ <task>`. Other labels have no short name. |
| `$decisions` | `⚑ N` (red, bold) | Open decisions waiting on the operator: `decisions_open` in the home's summary ledger, `state/home-summary.json`, which the home publishes from the same fold its wake drain uses. That ledger also folds in the decisions of its second-level homes; those whose home has a live Space of its own count on that home's row instead, so nothing is counted twice. Their share is the read-only `status_open_decisions` fold of the home's `bin/fm-classify-lib.sh` over each one's status log, cached until the log changes. A second-level home without a live Space stays counted on the primary row. |
| `$crew` | `▶ N` (green) | Workers running: the home's live task records, `state/*.meta`, without second-level home records (`kind=secondmate`). |
| `$queue` | `◷ N` (yellow) | Tasks queued and ready to start: `count` from the home's `bin/fm-tasks-axi.sh ready`. |
| `$res` | `⚙ 29%  ▤ 8%  ⛁ 2%` | CPU (share of all cores) and resident memory (share of `MemTotal`) summed over every process whose environment carries the space's `HERDR_WORKSPACE_ID`, so its workers count. CPU is each process's own CPU time (`utime` + `stime`) gained between two runs, for every process present in both, clamped to 0–100%. Disk is the home plus the worktree pools of its projects, as `treehouse status --json` lists them, as a share of the filesystem holding the home; a pool worktree that is itself another home is left out. On the primary home the value starts with two U+2800 blank characters. |
| `$alert` | `⚠ watcher silent` (orange) | `fm_supervision_unhealthy` from the home's `bin/fm-supervision-lib.sh`: the home has work that needs a watcher and the watcher's beacon is stale. On the primary home the value starts with two U+2800 blank characters. |
| `$host` | `⌂ ⚙ 41%  ▤ 18.2/31.0G 59%  ⛁ 402/937G 43%` | The whole machine, on the primary home only: CPU busy share from `/proc/stat`, used memory (`MemTotal` − `MemAvailable`) from `/proc/meminfo`, and the root filesystem from `statvfs`. Memory keeps one decimal while the total is under 100G (`18.2/31.0G`); disk is in whole G (`45/93G`, `402/937G`). Both are whole G from 100G and switch to T from 1000G (`1.4/1.9T`, whole T from 10T). |

There is no rate-limit warning: a rate limit takes every home down at once, so a per-home flag adds nothing.

### The reporter

[`maintenance/herdr-spaces.py`](../maintenance/herdr-spaces.py) is installed as `~/.local/bin/herdr-spaces.py` and run by the user timer `herdr-spaces.timer` every 10 seconds. It uses only the Python standard library.

For every Herdr workspace it finds the home from its panes' directories: the nearest git top-level that holds both `state/` and `data/`. It then reports the tokens above as workspace metadata under the source `code-factory:spaces`, with `herdr workspace report-metadata`, and clears every token that has no value. Helper spaces and per-task spaces (`└ …`) get `short` only. A space with no home gets `short` and CPU and RAM only. Only the primary home gets `host`.

| Source | Refresh | Cost |
| --- | --- | --- |
| CPU, RAM, counts, watcher, machine | every run (10 s) | One pass over `/proc`, one `fm-tasks-axi.sh ready` per home, and file reads; about one second in total. CPU needs two runs, so it appears from the second run on. |
| Disk | every 15 minutes | One `du` over each home and its pools. On a host with large pools this run can take a minute; the other values wait for it. |

The caches live in `~/.cache/code-factory/herdr-spaces.json`. A source that fails keeps its previous value, and a failed run never fails the unit: errors go to the journal (`journalctl --user -u herdr-spaces.service`). Herdr drops workspace tokens when its server restarts; the next run reports them again.

Inspect what a space reports:

```bash
herdr workspace get <workspace_id>
```

The result carries `tokens.short`, `tokens.decisions`, and so on.

## Agents: one entry per agent

```text
● firstmate
  Planning the release checklist
● └ fix-login
    Fixing the token refresh race
    ⎇ 1537 · ○ 1529 · +12847 · −3902 · ✎ 214
● swarms
  Fix ratings cache key collision
  ⎇ 1561 · ○ 1558 · +84 · −12 · ✎ 3
```

| Line | Shows |
| --- | --- |
| 1 | The state dot, then the pane's `who` name: the same short names as Spaces. The primary home is bold blue, other homes mauve, and a spawned worker (`└ <task>`) teal. |
| 2 | The agent's current session topic, dimmed, without omp's `π` and spinner. It is indented two columns to sit under the name; a spawned worker's topic is indented two more, so it starts right after the `└`. |
| 3 | The pull request line, for any agent whose current branch has an open pull request, workers and homes alike, and for a worker whose task names an issue. Indented to line up under the name: four columns for a worker, two for a home. |

| Token | Value | Color |
| --- | --- | --- |
| `$pr` | `⎇ <pr>`: the open pull request whose head is the current branch, in the checkout's repository or a fork | blue |
| `$issue` | `○ <issue>`: the issue the work is for | mauve |
| `$add` | `+<added>` lines | green |
| `$del` | `−<deleted>` lines (U+2212) | red |
| `$files` | `✎ <files>` changed | yellow |

Herdr indents every line after the first by two columns. For a worker, the first part present adds two U+2800 blank characters to that. The line counts come from `git diff --shortstat origin/<default branch>...HEAD` in the session's checkout, so they cover commits since the merge base with the default branch. The pull request comes from the GitHub REST API through `gh api`. It is looked up with the checkout's repository owner as the head owner first, then with the owner of each GitHub remote in `git remote -v`, in order, so a pull request opened from a fork shows as long as the checkout has the fork as a remote.

The issue comes from the worker's task record in its home first: the first `issues/<n>` link or `issue <n>` / `issue #<n>` in the task's backlog entry (`data/backlog.md`), then in its brief (`data/<task>/brief.md`). The home is the ancestor of the pane's launch directory that holds `state/<task>.meta`. So a worker shows its issue before its pull request opens, after it merges, and when the body has no closing keyword. Without a task record, the issue is the first one the pull request body closes (`Closes #N`, `Fixes #N`, `Resolves #N`).

### The omp extension

Herdr configuration alone cannot drop the `π` (omp puts it at the start of every terminal title) or know about pull requests. With the `agents` profile on, `./factory apply` installs [`config/herdr-sidebar.ts`](../config/herdr-sidebar.ts) as `~/.omp/agent/extensions/code-factory-herdr-sidebar.ts`. omp loads it at startup. Every apply rewrites it, so do not edit the installed copy.

The extension does nothing outside Herdr (`HERDR_ENV` is not `1`) or in an omp started from another omp's shell (`OMPCODE=1`). Inside a Herdr pane it:

- Sets the terminal title to the bare session topic, and sets it again within a second whenever omp resets it (rename, `/new`, `/resume`, a cwd change). A spawned worker (`FM_TASK_ID` set) gets two U+2800 blank characters in front; Herdr keeps them in `terminal_title`, which makes the extra indent.
- Reports the pane tokens `who`, `pr`, `issue`, `add`, `del` and `files` under the source `code-factory:sidebar`, and clears the ones without a value.

It reports when a session starts and when a turn ends. The pull request and the task's issue are looked up then too, at most every 5 minutes; a turn that ends sooner gets its lookup when the 5 minutes are up. The line counts are recomputed on every turn end while a pull request is open. Lookups run in the background with a timeout. A failed lookup keeps the previous value and never fails or slows a turn. Herdr drops pane tokens when its server restarts; the extension reports them again at the next turn end. All tokens are cleared when omp exits.

Inspect what a pane reports:

```bash
herdr agent get <pane_id>
```

The result carries `terminal_title` and `tokens.who`, `tokens.pr`, and so on.

## Override the layouts or turn parts off

Set these keys under `factory.herdr` in `.local/host.yml`, then run `./factory apply`:

| Key | Default | Effect |
| --- | --- | --- |
| `sidebar_width` | `46` | Expanded sidebar width in columns. |
| `sidebar_max_width` | `56` | Maximum expanded sidebar width. |
| `sidebar_space_rows` | the Spaces layout above | TOML array written as `[ui.sidebar.spaces] rows`. |
| `sidebar_agent_rows` | the Agents layout above | TOML array written as `[ui.sidebar.agents] rows`. |
| `sidebar_bg` | `#1e1e2e` | `[theme.custom] sidebar_bg`. |

Token syntax: [Herdr configuration](https://herdr.dev/docs/configuration/). Copy the default rows from [`config/default.yml`](../config/default.yml) and edit them:

- To turn a part off, delete its entry, for example `{ token = "$queue", … }` or the `$files` entry. Delete a whole row, such as the `$res` row, to drop that line.
- To change a color, edit its `fg`, `bold` or `dim`.

To check an override before applying, render it to a file and run Herdr's own validator on it without touching the live configuration:

```bash
HERDR_CONFIG_PATH=/path/to/rendered.toml herdr config check
```

## Known limits

- Agents line 2 is indented by a second state dot drawn in the sidebar background color. `sidebar_bg` is pinned to the catppuccin base (`#1e1e2e`) so that dot stays invisible. On the highlighted row the dot shows faintly. With another theme, change `sidebar_bg` and the `fg` of that dot in `sidebar_agent_rows` together.
- Agents without the extension, including non-omp agents, show only their dot on line 1: nothing reports their `who` token.
- Short names and colors match workspace labels (`firstmate`, `2ndmate-…`, `└ …`, `-afk-daemon-`). A home workspace with another name has no short name and shows its label.
- Only closing keywords in the pull request body count as issues there. Issues linked only in the GitHub UI are not shown, because the REST API does not list them.
- Spaces counts are only as fresh as the home's own records: `$decisions` follows the summary ledger, which the home republishes on its own events.
- CPU and RAM count only processes the reporter's account can read, and RAM is resident memory, so shared pages count once per process. CPU counts a process only while two runs 10 seconds apart both see it: a process that starts and ends between two runs is not counted, and the time before the first run that sees it or after the last is lost, so a space running many short builds reads low.
- The machine header fits the 42 columns Herdr shows on the first row of a Spaces entry at width 46 while neither memory nor disk is at 100%. Otherwise it can pass 42 columns, and Herdr cuts its end.
