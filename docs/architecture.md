# Infrastructure choice

## Decision

Use Ansible core for the native Ubuntu host and Docker Compose for isolated workloads. Keep Herdr, SSH, the user service manager, and browser lifecycle management on the host.

The source machine already uses Ubuntu packages, user-level systemd services, home-directory tools, and SSH. Ansible manages those objects directly without moving the machine to a new package store or OS. The playbook consumes a validated host document; native tools have versioned URLs and SHA-256 values, npm has a dependency lock, and the provisioning Python environment has `uv.lock`.

| Candidate | Fit here | Decision |
| --- | --- | --- |
| Ansible | Existing Ubuntu machines, apt, users, files, SSH, systemd | Primary configuration management |
| Docker / Compose | Bounded project processes, reproducible tool image, named data volumes | Optional worker and backing-service layer |
| Nix + Home Manager | Strong declarative package closure; works on Ubuntu too | Not selected: adds a daemon/store/profile migration and packaging work for locally distributed tools |
| chezmoi | Dotfile templates and per-machine configuration | Not selected: does not replace host package, user-manager, and service provisioning; a second template owner is unnecessary |
| OpenTofu | Cloud instances, networks, DNS, resource lifecycle | Add when a provider/resource contract is chosen; no pretend provider configuration is shipped |
| cloud-init | Initial VM prerequisites before configuration management | Small vendor-neutral bootstrap input only |

This is repeatable configuration, not a bit-identical OS image. Ubuntu packages receive distribution security updates. Exact agent/native-tool versions are deliberately locked. Rebuilding an environment does not recreate authenticated accounts, databases, or running processes.

## Host and container boundary

Herdr documents a persistent headless `herdr server` and SSH remote clients. The host's user manager owns that server and survives logout through lingering. Its unit names a versioned executable directly, so an old `/usr/local/bin/herdr` cannot silently win over a newer interactive CLI.

An ordinary container has a different process and filesystem lifecycle. Docker's tiny init can reap processes; it does not reproduce the host's user D-Bus, login manager, SSH identity, or desktop session. The worker image therefore disables host-service operations and does not mount host PID state, the Docker socket, credentials, browser profiles, or Herdr session state.

Use a Linux host for the native recipe. macOS and other client devices can reach that host over SSH; this repository does not claim to reproduce Linux systemd services as native macOS services. Headless Mac setup must not depend on a GUI/TCC dialog being dismissed remotely.

### Docker worker

The Dockerfile's `worker` target is an isolated, non-root, devcontainer-style image built by the same recipe. It runs `./factory apply --config containers/factory.container.yml`, which sets `start_services: false` and `enable_linger: false` and turns off the `docker`, `tailscale`, `desktop`, and `firstmate` profiles and the browser pruner. The image carries the pinned agent and development toolchain and the rendered agent configs, with no systemd services, linger, or Docker-in-Docker. The devcontainer, Compose, and CI use the same image.

```bash
docker build --target worker --tag code-factory/worker .
docker compose --profile worker up -d                    # worker only
docker compose --profile worker --profile data up -d     # + example Postgres and Redis
```

## Seeded Firstmate and OMP configuration

The `firstmate` profile copies each name in `factory_firstmate_config_names` (`ansible/group_vars/all.yml`) from this repository's `config/` into the Firstmate checkout's `config/`, which Firstmate gitignores. Preflight requires every source and verify requires every destination. The seeded files:

| File | Value |
| --- | --- |
| `crew-dispatch.json` | Default only, no rules: every crewmate spawn (ship and scout) is omp on `anthropic/claude-opus-5-5`, effort `high`, provider `anthropic`. |
| `secondmate-harness` | `omp anthropic/claude-opus-5-5 xhigh`. |
| `omp-crew-overlay.yml` | omp overlay Firstmate applies to crewmate and scout launches, never secondmates, ahead of its tracked worker overlay. It sets `modelRoles.advisor: anthropic/claude-fable-5-1:low`, `advisor.enabled: true`, `advisor.immuneTurns: 10` and `advisor.syncBacklog: "off"`, plus `providers.anthropic.serverSideFallback: false`: with the global server-side fallback on, Anthropic rejects every advisor call with a 400. Every omp crewmate runs a fable-5.1 advisor at low thinking (its lowest level). Crews never wait on it, because `syncBacklog: "off"` overrides the global `"1"`. Turns that land during a review batch into the next call instead of one call per turn, and the advisor interrupts at most once per 10 turns. omp has no every-N-turns setting. |
| `spawn-memory-floor-mb` | `8000`; see [fleet guards](fleet-guards.md). |
| `crew-harness`, `backend`, `startup-memory-budget` | Harness, Herdr backend, and startup memory budget. |

`config/omp.yml` seeds `~/.omp/agent/config.yml` on first write only. It holds the host's `modelRoles` (`default` is `anthropic/claude-opus-5-5:xhigh`, `task` and `subagent` are `anthropic/claude-opus-5-5:auto`, `memory` is `anthropic/claude-opus-5-5:off`, and `smol`, `commit` and `tiny` are `anthropic/claude-sonnet-5:off`) and `retry.fallbackChains` with no `default` chain. Its `advisor` block keeps the global advisor off (`enabled: false`) with `syncBacklog: '1'`; only crews turn it on, through the overlay above, which also sets `syncBacklog` to `"off"`. No router or gateway sits between omp and the provider.

Host sizing and every auto pruner are listed in [Capacity and pruners](capacity.md).

## Reproducibility policy

1. Update native versions and both architecture hashes together in `toolchain.lock.json`; never resolve a mutable `latest` installer during deployment. The one exception is herdr: each apply resolves its latest release once and verifies the asset against the SHA-256 that release publishes, refusing a release without one.
2. Update exact npm dependencies and regenerate `tools/npm/package-lock.json` together. Do not copy a live global package directory. The one exception is omp, which each apply resolves to the registry's latest version and installs exactly.
3. Change Python dependencies with `uv lock` and commit the lock.
4. Keep machine differences in ignored `.local/host.yml`; schema validation precedes provisioning.
5. Do not force, stash, reset, or overwrite a modified Firstmate checkout or an unmanaged command. Resolve that conflict explicitly.
6. Keep authentication and mutable application state outside the recipe. Provider model access must be checked on the destination account.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on pushes to `main`, on every pull request, and on manual dispatch:

- `uv sync --locked --group dev`, then `ruff check` and `pytest`.
- `./factory validate` for `config/default.yml` and `containers/factory.container.yml`.
- Audits of the Dockerfile, devcontainer, and Compose definitions (digest-pinned images, no host namespaces or socket, resource caps).
- A full worker image build and the behavior smoke in `tests/container-smoke.sh`.

Every action is pinned to an immutable commit SHA, and the token is read-only. The uv version comes from `toolchain.lock.json`, the same pin `./bootstrap.sh` installs.

## Primary sources

- [Herdr installation](https://herdr.dev/docs/install/), [headless/SSH persistence](https://herdr.dev/docs/persistence-remote/), [session-state limits](https://herdr.dev/docs/session-state/), [config reference](https://herdr.dev/docs/config-reference/).
- [Herdr latest release](https://github.com/herdrdev/herdr/releases/latest). Assets are verified against the SHA-256 digest GitHub publishes for each release asset; no claim is made that the release supplies an independent SBOM or signature bundle.
- [Ansible introduction](https://docs.ansible.com/projects/ansible/latest/getting_started/index.html), [checksummed downloads](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/get_url_module.html), [user systemd/D-Bus requirements](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/systemd_service_module.html).
- [systemd lingering](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html).
- [Docker process boundaries](https://docs.docker.com/engine/containers/multi-service_container/), [Docker and host firewall behavior](https://docs.docker.com/engine/network/firewall-iptables/).
- [Nix multi-user installation](https://nix.dev/manual/nix/stable/installation/multi-user.html), [standalone Home Manager](https://nix-community.github.io/home-manager/installation/standalone.html).
- [chezmoi setup](https://www.chezmoi.io/user-guide/setup/), [OpenTofu scope](https://opentofu.org/docs/intro/).
