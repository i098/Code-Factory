# Contributing to Crewship

## How it works

Crewship is an Ansible playbook with a Python CLI wrapper (`scripts/factory.py`). The source of truth is:

- `config/default.yml` — ship defaults (every field the schema requires)
- `schemas/factory.schema.json` — JSON Schema for the host config
- `ansible/group_vars/all.yml` — Jinja vars consumed by tasks
- `ansible/tasks/*.yml` — the tasks themselves (one file per concern)
- `ansible/templates/*.j2` — systemd unit templates
- `scripts/factory.py` — CLI (`init`, `validate`, `plan`, `apply`, `doctor`)
- `scripts/install_tools.py` — latest-release tool installer (idempotent)
- `fleet/` — runtime scripts deployed to `~/oss-fleet/` on the target host
- `config/` — per-tool config templates deployed to Firstmate homes

## Design rules

Every task is idempotent; a second unchanged `apply` reports `changed=0`.

Every task is check-mode safe: `plan` (Ansible `--check`) previews without mutating.

Nothing is pinned: every tool tracks its latest release, resolved once per apply and verified by the checksum its publisher posts; what each source is verified against, and the omp marketplace plugin exception, are in [Dependencies](docs/dependencies.md). Only the repository's own Python environment (`uv.lock`) stays locked, and CI pins each GitHub Action to the commit SHA of its latest release, kept current by Dependabot.

No unconditional restarts, daemon-reloads, or bare commands.

`start_services: false` suppresses every linger, daemon-reload, and systemd start action while still writing unit files and enabling them via static symlinks.

## Development

```bash
# Install dev deps
uv sync --group dev

# Lint
uv run ruff check scripts tests

# Test (the Koncreet apply tests need root or fakeroot; unprivileged without it they skip)
uv run pytest

# Ansible syntax check
uv run ansible-playbook -i ansible/inventory.yml ansible/site.yml --syntax-check

# Full CI (runs all of the above + Docker worker smoke)
./scripts/ci-local.sh
```

## Adding a new tool

1. Add it to `GITHUB_LATEST` (a GitHub release whose assets carry a SHA-256 digest; when the release publishes its own `<asset>.sha256` files, also list it in `SHA256_FILE` to verify against those) or `NPM_LATEST` in `scripts/install_tools.py`. A tool from elsewhere needs its own resolver in `resolve_latest` that reads the checksum its publisher posts for the release.
2. Register where it installs: `factory_core_tools` in `group_vars/all.yml` for every host, `AGENT_TOOLS` in `scripts/install_tools.py` for the `agents` profile's native tools (npm tools in `NPM_LATEST` need no step), or `factory_installer_also` in `group_vars/all.yml` for a source Ansible installs itself.
3. If it needs a systemd unit, add a `.j2` template in `ansible/templates/` and wire it in the relevant task file.
4. If it needs environment variables, add them to `group_vars/all.yml` (not to shell rc files).
5. Update `docs/architecture.md` if the tool changes the host's architecture.
6. Add or update a test in `tests/`.

## Adding a new fleet guard

Fleet guards (`fleet/`) are runtime scripts deployed to `~/oss-fleet/` on the box. They are not Ansible modules — they are plain shell/TypeScript that systemd units run.

1. Write the script in `fleet/doctor/` or `fleet/browsers/`.
2. Add a `.j2` unit template in `ansible/templates/`.
3. Wire it in `ansible/tasks/fleet_guards.yml` (or `fleet-browsers.yml`).
4. Add it to `factory_fleet_units` and/or `factory_fleet_enabled_units` (or `factory_fleet_browser_units` / `factory_fleet_browser_enabled_units`) in `group_vars/all.yml`.
5. Update `docs/fleet-guards.md`.

## Pull requests

- One concern per PR.
- Tests pass (`uv run pytest`).
- Lint clean (`uv run ruff check`).
- Ansible syntax clean (`--syntax-check`).
- Idempotent: `apply` → `apply` = `changed=0` on the second run.
- Describe what changed and why in the PR body.

## Changelog and releases

[CHANGELOG.md](CHANGELOG.md) follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). Releases are [GitHub releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository) on `vX.Y.Z` tags.

1. Every PR adds one line under `## [Unreleased]`, in the section that fits: Added, Changed, Deprecated, Removed, Fixed, or Security.
2. To cut a release, open a PR that moves those lines under a new `## [X.Y.Z] - YYYY-MM-DD` heading (ISO 8601 date), leaves `## [Unreleased]` empty, and updates the link references at the bottom of the file. Choose the number:
   - patch (`Z`): fixes only;
   - minor (`Y`): a new capability;
   - major (`X`): a breaking change to the host config or the host layout.

   While the version is `0.y.z` (initial development, see SemVer item 4), a breaking change bumps the minor number instead.
3. After that PR merges, tag its merge commit on `main` as `vX.Y.Z`. Never move or reuse a published tag.
4. Publish a GitHub release for the tag, named `vX.Y.Z`, with that version's changelog section as the notes, for example `gh release create vX.Y.Z --target <merge-sha> --title vX.Y.Z --notes-file <section.md>`.
