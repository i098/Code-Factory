# Migration and recovery

## New-device sequence

1. Start with a supported Ubuntu installation and working SSH/sudo access. `cloud-init/user-data.yaml` installs initial OS prerequisites; it does not create credentials, log in to services, or clone this private repository.
2. Authenticate GitHub on the new device and clone Crewship. Run the [Quick start](../README.md#quick-start): `onboard.sh`, then `ship.sh` `dock`, `inspect`, `chart`, `launch`, and `survey`.
3. Confirm Herdr's user service and executable agree. Both resolve to the versioned release that apply resolved and installed (see [Latest releases](dependencies.md#latest-releases)).
4. Authenticate agent/provider CLIs under the configured operator account (for omp, see [Sign in](omp.md#sign-in)). Confirm the configured models exist for that account. Recreate per-project approval/trust choices instead of copying a global auto-approval list.
5. If selected, authenticate Tailscale as a new device and review its ACL/SSH policy. Installation alone does not authorize incoming connections.
6. If selected, open the desktop through an SSH tunnel and sign in using the one persistent browser profile. Never transfer a cookie database or copy the old browser directory.
7. Restore project source and data through their own workflows. Only then register projects/work with Firstmate or re-enable autonomous fleet tasks.

Do not point two machines at the same live session, task registry, browser profile, or database directory. A Herdr layout is not a process checkpoint. Shells, agents, and servers restart from their own durable inputs.

## Troubleshooting

```bash
./ship.sh survey    # actionable diagnostics
./ship.sh chart      # preview what apply would change
```

- **`fleet guards require the docker and firstmate profiles`**: enable both profiles in `.local/host.yml`.
- **Empty fixture archive**: the shared database is a read-only fixture that cannot be rebuilt from migrations. Copy the volume snapshot from a host that has the fixture; see [The fixture](fleet-guards.md#the-fixture).
- **Spawn refused by the memory floor**: wait for a lane to finish, or lower the floor in this repository's `config/spawn-memory-floor-mb` and rerun `./ship.sh launch`. Every apply rewrites the Firstmate checkout's copy, so an edit made only there is reverted.

## Desktop access

The desktop is opt-in, loopback-only, and password-authenticated. After the first apply installs its packages and creates `~/.vnc`, configure the credential as the operator with `tigervncpasswd ~/.vnc/passwd`, set mode `0600`, and rerun apply. Missing or unsafe credentials stop provisioning before listeners are enabled. With the default `novnc_port: 6080`, forward the port from your client:

```bash
ssh -L 6080:127.0.0.1:6080 operator@host
```

Use your actual SSH alias/account, then open `http://127.0.0.1:6080/vnc.html` locally and enter the VNC password. SSH protects transport; VncAuth also protects against other local accounts. Do not open port 6080 to the public internet. `vnc-chrome` uses only the provisioned account's `~/.vnc-chrome-profile`; create logins on that device rather than copying an existing profile.

For a changed display/session configuration, restart VNC explicitly only when the desktop is idle. That terminates every process inside the display. Provisioning reports this requirement rather than silently restarting a working desktop.

## App and fleet state

This repository reconstructs the environment, not a host's live operations:

- Firstmate source and dispatch choices are installed; its private backlog, charter briefs, project registry, session lock, and operational history are not.
- Other agent runtimes on the old host own their own queues, schedules, recovery policy, and outbound authority. Restore their reviewed source and fresh configuration separately; do not automatically resume publishing jobs merely because a device was rebuilt.
- Project-specific services need their own environment files, source revisions, migrations, and data restores. A cache directory containing a running executable is not an installation artifact.
- Docker named volumes are durable data. Back them up with database-aware tools and verify a restore independently. Do not copy `/var/lib/docker` between running daemons or assume an unused volume is disposable.

The included PostgreSQL/Redis Compose services are empty development examples. They do not supply an application's schema or import production data.

## Model/proxy errors

For `thinking`/`redacted_thinking` replay errors, inspect the complete request path. Prefix-bound reasoning can fail even when the opaque thinking fields are unchanged: an intermediary may have rewritten earlier messages, system text, or tool schemas. Preserve request bodies, route affinity, and signer identity; do not strip reasoning as a generic workaround.

The inspected local Headroom/pxpipe fixes, version/hash guards, and offline regressions are in [proxy-fixes](../proxy-fixes/README.md). Default fresh Crewship agent configuration does not import machine-specific proxy URLs. Providers can be used directly; installing the optional proxies and their credentials is a separate, deliberate operation.

Never upload a raw failed HTTP request to a public issue or this repository. Such files contain prompts and may include secrets in tool output. Share only sanitized block shapes, lengths, hashes, provider/version information, and error classifications.

## Drift and upgrades

Run `./ship.sh chart` before applying; every apply upgrades each tool to its latest release, and a herdr upgrade restarts `herdr.service`. An unmanaged executable at a managed command path is a refusal, not permission to overwrite it. Firstmate refuses dirty or independently advanced checkouts. Preserve that work and decide whether to update the configuration or move to a separate clean checkout.

See [Updating an existing host](omp.md#updating-an-existing-host) for omp preferences and [omp setup](omp.md#what-the-recipe-sets-up) for model override merging.

A second unchanged provisioning pass should report `changed=0`. Runtime application activity, deliberate self-updates, and changed package indexes can create real drift; investigate it rather than weakening the check or forcing a reset.

## Resource limits and cleanup

Compose caps CPU, memory, swap, and process counts. Native parallel builds still need a concurrency budget suitable for the machine. Do not globally override Firstmate's task-owned build-cache paths with a shared unlimited Rust target directory; that bypasses normal task teardown.

The browser timer only closes eligible idle disposable AXI sessions. It neither prunes caches nor handles a hung bridge by force-killing it. A pending graceful shutdown stays visible for inspection. Source files, dirty worktrees, project data, and persistent browser state are not cleanup targets.

Disable a managed timer without deleting its script or state:

```bash
systemctl --user disable --now chrome-autoprune.timer
```

Keep the host's SSH access path intact while changing networking. In particular, changing one Tailscale preference should use `tailscale set`, not an unreviewed `tailscale up --reset`.
