# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- README screenshot of a finished host, captured from demo repositories ([#35](https://github.com/i098/Crewship/issues/35)).
- Git conventions and branch rules in `CONTRIBUTING.md`, issue forms, a pull request template, `SUPPORT.md`, and `CODEOWNERS` for `.github/` ([#47](https://github.com/i098/Crewship/issues/47)).

### Changed

- The license is now FSL-1.1-Apache-2.0 (SPDX `FSL-1.1-ALv2`), not MIT: each version becomes Apache 2.0 two years after its release, and releases up to and including v0.1.0 stay MIT ([#50](https://github.com/i098/Crewship/issues/50)).
- **Breaking:** renamed the entry points and scripts to nautical names, and the old names no longer exist: `bootstrap.sh` is `onboard.sh`; `factory` is `ship.sh`, with `init`, `validate`, `plan`, `apply`, `doctor` now `dock`, `inspect`, `chart`, `launch`, `survey`; `scripts/factory.py`, `install_tools.py`, `push-super-env.sh`, `fetch-super-env.sh` are now `ship.py`, `provisions.py`, `stow-secrets.sh`, `fetch-secrets.sh`. Update notes and scripts that use the old commands ([#44](https://github.com/i098/Crewship/issues/44)).
- Renamed the project to Crewship; the repository is now i098/Crewship ([#38](https://github.com/i098/Crewship/issues/38)).
- README screenshot now shows a real Herdr session with Firstmate, with the other project names and agent text changed to generic examples ([#35](https://github.com/i098/Crewship/issues/35)).

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

[Unreleased]: https://github.com/i098/Crewship/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/i098/Crewship/releases/tag/v0.1.0
