# Herdr sidebar

Code Factory renders `~/.config/herdr/config.toml` from [`ansible/templates/herdr.toml.j2`](../ansible/templates/herdr.toml.j2) and the `herdr` block of `.local/host.yml`. This guide covers the Agent sidebar layout it ships and the omp extension that feeds it.

## What each entry shows

The sidebar is 40 columns wide (`sidebar_width`; it may grow to `sidebar_max_width`, 48). Each agent gets one entry of up to three lines. There is no status word: the color of the state dot already shows it.

```text
● firstmate
  Planning the release checklist
● 2ndmate-docs
  Reviewing the install guide
● └ fix-login
    Fixing the token refresh race
    ⎇ 1537  ◉ 1529
```

| Line | Shows |
| --- | --- |
| 1 | The state dot, then the pane's `who` name. The primary home workspace (`firstmate`) is bold blue, a second-level home workspace (name starts with `2ndmate-`) is mauve, and a spawned worker (`└ <task>`) is teal. |
| 2 | The agent's current session topic, dimmed, without omp's `π` and spinner. It is indented two columns to sit under the name; a spawned worker's topic is indented two more, so it starts right after the `└`. |
| 3 | Spawned workers with a pull request only: the pull request number (`⎇`) and the issues it closes (`◉`), aligned with the topic. |

The layout works whether a worker runs in its own `└ task · p:<token>` workspace or as a tab inside its home workspace, because line 1 shows the `who` name rather than the workspace or agent label.

## The omp extension

Herdr configuration alone cannot drop the `π` (omp puts it at the start of every terminal title) or know about pull requests. With the `agents` profile on, `./factory apply` installs [`config/herdr-sidebar.ts`](../config/herdr-sidebar.ts) as `~/.omp/agent/extensions/code-factory-herdr-sidebar.ts`. omp loads it at startup. Every apply rewrites it, so do not edit the installed copy.

The extension does nothing outside Herdr (`HERDR_ENV` is not `1`) or in an omp started from another omp's shell (`OMPCODE=1`). Inside a Herdr pane it:

- Sets the terminal title to the bare session topic, and sets it again whenever omp renames the session. A spawned worker (`FM_TASK_ID` set) gets two U+2800 blank characters in front; Herdr keeps them in `terminal_title`, which makes the extra indent.
- Reports the pane token `who` under the source `code-factory:sidebar`: `└ <FM_TASK_ID>` for a spawned worker, otherwise the label of the pane's own workspace.
- For a spawned worker only, reports the pane token `refs`: four U+2800 characters, then `⎇ <pr>` and one `◉ <issue>` per issue the pull request body closes (`Closes #N`, `Fixes #N`, `Resolves #N`), joined by two spaces. The pull request is the one whose head is the checkout's current branch, found with the GitHub REST API through `gh api`. The value is cached and looked up again at most every 5 minutes, only when a turn ends. The token is cleared when the branch has no pull request.

Lookups run in the background with a timeout. A failed lookup keeps the previous value and never fails or slows a turn. Herdr drops pane tokens when its server restarts; the extension reports them again at the next turn end.

Inspect what a pane reports:

```bash
herdr agent get <pane_id>
```

The result carries `terminal_title` and `tokens.who` / `tokens.refs`.

## Override or turn off the layout

Set these keys under `factory.herdr` in `.local/host.yml`, then run `./factory apply`:

| Key | Default | Effect |
| --- | --- | --- |
| `sidebar_width` | `40` | Expanded sidebar width in columns. |
| `sidebar_max_width` | `48` | Maximum expanded sidebar width. |
| `sidebar_agent_rows` | the layout above | TOML array written as `[ui.sidebar.agents] rows`. Token syntax: [Herdr configuration](https://herdr.dev/docs/configuration/). |
| `sidebar_bg` | `#1e1e2e` | `[theme.custom] sidebar_bg`. `""` leaves the theme's own sidebar background. |

To turn the layout off, set `sidebar_agent_rows: ""`. Herdr then uses its built-in rows, and apply removes the omp extension. Set `sidebar_bg: ""` too if you do not want the pinned background.

Apply's verification runs `herdr config check` on the rendered file, so an override Herdr rejects fails the run instead of silently falling back to defaults. To check a rendered file by hand without touching the live configuration:

```bash
HERDR_CONFIG_PATH=/path/to/rendered.toml herdr config check
```

## Known limits

- Line 2 is indented by a second state dot drawn in the sidebar background color. `sidebar_bg` is pinned to the catppuccin base (`#1e1e2e`) so that dot stays invisible. On the highlighted row the dot shows faintly. With another theme, change `sidebar_bg` and the `fg` of that dot in `sidebar_agent_rows` together.
- Agents without the extension, including non-omp agents, show only their dot on line 1: nothing reports their `who` token.
- The `firstmate` and `2ndmate-` colors match workspace names. A home workspace with another name shows in the default color.
- Only closing keywords in the pull request body count as issues. Issues linked only in the GitHub UI are not shown, because the REST API does not list them.
- The pull request lookup filters by head branch in the checkout's own repository, so a pull request opened from a fork does not show.
