# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Generic global instructions in `config/AGENTS.md`, installed by the `agents` profile as `~/.claude/CLAUDE.md`, `~/.omp/agent/AGENTS.md` and `~/.codex/AGENTS.md`; a file changed on the host is moved to a timestamped backup first, and an unchanged apply changes nothing ([#86](https://github.com/i098/Crewship/issues/86)).

## [0.2.0] - 2026-10-09

### Added

- README screenshot of a finished host, captured from demo repositories ([#35](https://github.com/i098/Crewship/issues/35)).
- Git conventions and branch rules in `CONTRIBUTING.md`, issue forms, a pull request template, `SUPPORT.md`, and `CODEOWNERS` for `.github/` ([#47](https://github.com/i098/Crewship/issues/47)).
- Sponsor button on the repository page, from `.github/FUNDING.yml`, that opens the i098 GitHub Sponsors profile ([#59](https://github.com/i098/Crewship/issues/59)).
- Optional GitHub board (`factory.github_board`): a user timer mirrors Firstmate work items to issues in a repository you choose, keeps a Project `Status` field in step (queued, in progress, in review, done), and posts new status lines as batched issue comments. The new-host questions ask whether to turn it on; without the key the host makes no GitHub calls for it ([#45](https://github.com/i098/Crewship/issues/45)).
- README: a centered header with a badge row and short links, a Why Crewship list, a collapsed Features list, a Get a machine part with sizing, a Sponsors section, and a star-history chart; `SECURITY.md`, `CODE_OF_CONDUCT.md`, and a 1280x640 social preview image ([#39](https://github.com/i098/Crewship/issues/39)).
- `skills/public/` (committed) and `skills/private/` (git-ignored) skill folders, installed for omp and Claude Code by the `agents` profile; a private skill wins over a public one of the same name, and skills added by hand are never touched ([#56](https://github.com/i098/Crewship/issues/56)).
- Each release publishes the worker container image to the GitHub Container Registry as `ghcr.io/i098/crewship:X.Y.Z` and `:latest`, so the repository page lists it under Packages ([#54](https://github.com/i098/Crewship/issues/54)).
- README sponsor list: a daily `sponsors` workflow writes the GitHub Sponsors of i098 into the Sponsors section and opens one pull request when the list changes; while there are no sponsors, the "be the first" line stays ([#68](https://github.com/i098/Crewship/issues/68)).
- One-command install for a fresh Ubuntu machine: `install.sh` (`curl … | bash`) and the `crewship` npm package (`npx crewship`), published from each release with npm trusted publishing ([#40](https://github.com/i098/Crewship/issues/40)).
- `crewboard/`, a Rust daemon and command line tool for an opt-in, host-local, in-memory message board between agents over a Unix socket; nothing installs or runs it yet ([#71](https://github.com/i098/Crewship/issues/71)).
- `harbor/`: the crewship.si landing page, a first-person ASCII walk around the docked ship that opens a card per feature, deployed to Cloudflare Workers from GitHub Actions and kept out of every host and image ([#49](https://github.com/i098/Crewship/issues/49)).

### Changed

- The license is now FSL-1.1-Apache-2.0 (SPDX `FSL-1.1-ALv2`), not MIT: each version becomes Apache 2.0 two years after its release, and releases up to and including v0.1.0 stay MIT ([#50](https://github.com/i098/Crewship/issues/50)).
- **Breaking:** the fleet guard units are now `crewship-*`, not `flotilla-*`; apply stops and deletes the old units, except that the old shared Supabase unit is deleted without being stopped, so the shared stack keeps running through the rename. The Docker guard is general and runs every hour: it removes stopped containers 24 h after they exit and reports running ones 48 h old (fixed), and it never touches a container with the `crewship.keep` label or a restart policy, volumes or images. It no longer removes second Supabase stacks; `docker-guard-allow.txt` is deleted. Tune the stopped age with `fleet.docker_guard.stopped_hours` ([#43](https://github.com/i098/Crewship/issues/43)).
- **Breaking:** renamed the entry points and scripts to nautical names, and the old names no longer exist: `bootstrap.sh` is `onboard.sh`; `factory` is `ship.sh`, with `init`, `validate`, `plan`, `apply`, `doctor` now `dock`, `inspect`, `chart`, `launch`, `survey`; `scripts/factory.py`, `install_tools.py`, `push-super-env.sh`, `fetch-super-env.sh` are now `ship.py`, `provisions.py`, `stow-secrets.sh`, `fetch-secrets.sh`. Update notes and scripts that use the old commands ([#44](https://github.com/i098/Crewship/issues/44)).
- Renamed the project to Crewship; the repository is now i098/Crewship ([#38](https://github.com/i098/Crewship/issues/38)).
- README screenshot now shows a real Herdr session with Firstmate, with the other project names and agent text changed to generic examples ([#35](https://github.com/i098/Crewship/issues/35)).

### Fixed

- `scripts/stow-secrets.sh` no longer fails with `maximum_secrets_exceeded` once `super.env` has more than 100 variables: it stores the whole file in a few chunks instead of one secret per variable, and it deletes the per-variable secrets the chunks replace. On a full store it deletes just enough of them before creating the chunks, so fetches can fail for a few seconds during that one push ([#58](https://github.com/i098/Crewship/issues/58)).
- The worker image and the compose backing services pull from `mirror.gcr.io`, Google's Docker Hub mirror, so the CI image build no longer fails on Docker Hub's anonymous pull limit (`429 Too Many Requests`); the images are the same official ones ([#63](https://github.com/i098/Crewship/issues/63)).
- The iMessage bridge no longer loses messages when the Photon service is down: every send and tapback, including the desk's and the "firstmate did not get that" reply, goes to a durable outbox that retries transient errors with backoff and keeps the order, failed attachment downloads are retried and their note is filed again with the saved path, an item that can never pass moves to a dead-letter folder instead of blocking the queue, typing errors never fail a send, and an `UNAVAILABLE` reply is logged as one line ([#61](https://github.com/i098/Crewship/issues/61)).
- The iMessage bridge no longer drops the owner's edited texts: each edit becomes a new inbox note, `[edited] <new text> (was: <old text>)`, that wakes Firstmate; when the bridge does not know the old text, the note says so ([#80](https://github.com/i098/Crewship/issues/80)).

## [0.1.0] - 2026-10-09

### Added

- Ansible recipe and `factory` CLI (`init`, `validate`, `plan`, `apply`, `doctor`) that turn a fresh Ubuntu host into an AI-agent coding host: Herdr, Firstmate, the omp agent fleet, fleet guards, Docker, and the Concord and slk chat clients, from latest checksum-verified releases.
- `herdr-patch` command that removes Herdr's opaque background fill over mosh and restores mosh images ([#2](https://github.com/i098/Crewship/pull/2), [#9](https://github.com/i098/Crewship/pull/9)).
- Fleet-browser VNC tier packages ([#7](https://github.com/i098/Crewship/pull/7)).
- Optional data disk for the Docker data root and the npm and pip caches ([#14](https://github.com/i098/Crewship/pull/14)).
- `gws` install and multi-account Google sign-in docs ([#15](https://github.com/i098/Crewship/pull/15)).
- Self-hosted CI pool of just-in-time GitHub Actions runners ([#16](https://github.com/i098/Crewship/pull/16)).
- `dia-debug`: keeps Dia running on a Mac with a prompt-free CDP port ([#18](https://github.com/i098/Crewship/pull/18)).
- Optional iMessage bridge to Firstmate over Photon Spectrum, with a persistent compressed chat memory for the front desk ([#22](https://github.com/i098/Crewship/pull/22), [#26](https://github.com/i098/Crewship/pull/26)).
- sentrux and fallow quality gate for omp agents and CI ([#32](https://github.com/i098/Crewship/pull/32)).

### Changed

- Recipe synced with the running host: chat profile, inotify limit, omp and Herdr settings ([#10](https://github.com/i098/Crewship/pull/10)).
- README shows Concord and slk in the default install ([#21](https://github.com/i098/Crewship/pull/21)).

### Fixed

- `herdr-mosh` is installed from `herdr-patch` and linked into `/usr/local/bin` ([#4](https://github.com/i098/Crewship/pull/4)).
- iMessage front desk waits a 4-second quiet period, sends multi-bubble replies, and keeps the full intake ([#25](https://github.com/i098/Crewship/pull/25), [#28](https://github.com/i098/Crewship/pull/28)).
- Firstmate inbox wake patches apply on top of upstream main ([#30](https://github.com/i098/Crewship/pull/30)).

[Unreleased]: https://github.com/i098/Crewship/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/i098/Crewship/releases/tag/v0.2.0
[0.1.0]: https://github.com/i098/Crewship/releases/tag/v0.1.0
