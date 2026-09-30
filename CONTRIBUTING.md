# Contributing to Code Factory

## How it works

Code Factory is an Ansible playbook with a Python CLI wrapper (`scripts/factory.py`). The source of truth is:

- `config/default.yml` — ship defaults (every field the schema requires)
- `schemas/factory.schema.json` — JSON Schema for the host config
- `ansible/group_vars/all.yml` — Jinja vars consumed by tasks
- `ansible/tasks/*.yml` — the tasks themselves (one file per concern)
- `ansible/templates/*.j2` — systemd unit templates
- `scripts/factory.py` — CLI (`init`, `validate`, `plan`, `apply`, `doctor`)
- `scripts/install_tools.py` — checksum-verified tool installer (idempotent)
- `toolchain.lock.json` — the pinned tools (uv, rustup-init, Rust): version, URL, sha256
- `fleet/` — runtime scripts deployed to `~/oss-fleet/` on the target host
- `config/` — per-tool config templates deployed to Firstmate homes

## Design rules

Every task is idempotent; a second unchanged `apply` reports `changed=0`.

Every task is check-mode safe: `plan` (Ansible `--check`) previews without mutating.

Only uv, rustup-init and the Rust toolchain are pinned in `toolchain.lock.json`. Every other tool tracks its latest release, resolved once per apply: native assets are verified against the SHA-256 their publisher lists for that release and refused without one, npm tools install the exact resolved version. The installer records what it resolved in `~/.local/share/code-factory/resolved.json`.

No unconditional restarts, daemon-reloads, or bare commands.

`start_services: false` suppresses every linger, daemon-reload, and systemd start action while still writing unit files and enabling them via static symlinks.

## Development

```bash
# Install dev deps
uv sync --group dev

# Lint
uv run ruff check scripts tests

# Test
uv run pytest

# Ansible syntax check
uv run ansible-playbook -i ansible/inventory.yml ansible/site.yml --syntax-check

# Full CI (runs all of the above + Docker worker smoke)
./scripts/ci-local.sh
```

## Adding a new tool

1. Pin it in `toolchain.lock.json` with the correct `format` (`file`, `tar` or `zip`), sha256, URL, and `binaries` map, and allow its name in `schemas/toolchain.schema.json`. A tool that tracks its latest release goes in `GITHUB_LATEST` or `NPM_LATEST` in `scripts/install_tools.py` instead.
2. Add the tool name to `factory_core_tools` in `group_vars/all.yml` (or a profile-gated list).
3. If it needs a systemd unit, add a `.j2` template in `ansible/templates/` and wire it in the relevant task file.
4. If it needs environment variables, add them to `group_vars/all.yml` (not to shell rc files).
5. Update `docs/architecture.md` if the tool changes the host's architecture.
6. Add or update a test in `tests/`.

## Adding a new fleet guard

Fleet guards (`fleet/`) are runtime scripts deployed to `~/oss-fleet/` on the box. They are not Ansible modules — they are plain shell/TypeScript that systemd units run.

1. Write the script in `fleet/doctor/` or `fleet/browsers/`.
2. Add a `.j2` unit template in `ansible/templates/`.
3. Wire it in `ansible/tasks/fleet_guards.yml` (or `fleet-browsers.yml`).
4. Add it to `factory_fleet_units` and/or `factory_fleet_enabled_units` in `group_vars/all.yml`.
5. Update `docs/fleet-guards.md`.

## Pull requests

- One concern per PR.
- Tests pass (`uv run pytest`).
- Lint clean (`uv run ruff check`).
- Ansible syntax clean (`--syntax-check`).
- Idempotent: `apply` → `apply` = `changed=0` on the second run.
- Describe what changed and why in the PR body.
