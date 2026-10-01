# Security and export boundary

This repository is an allowlisted reconstruction recipe, not a copy of a home directory. Keeping the repository private does not make credentials safe to commit.

## Never export

- SSH private keys, GitHub tokens, Tailscale node identity or auth keys.
- OMP, Claude, Codex, or other provider authentication stores.
- Browser profiles, cookies, password stores, desktop login sessions, or VNC passwords.
- Agent transcripts, fleet task history, private project working trees, database files, or Docker volumes.
- `.env` files, Terraform state, runtime sockets, PID files, and caches.

A service unit can carry an inline API credential. Never copy such a unit verbatim. Recreated services must load credentials from a private runtime environment file, never from tracked unit contents.

## On a new host

Authenticate each CLI interactively under the account that will run it. Do not copy an old host's credential database to make a tool appear configured. GitHub repository access, model subscriptions, organization permissions, and tailnet membership are separate prerequisites; installing a binary does not grant them.

Two exceptions move state between the operator's own hosts:

- Shared fleet credentials in `super.env`: a new host fetches them from Cloudflare Secrets Store with `scripts/fetch-super-env.sh`. See [Shared credentials](secrets.md).
- Each Firstmate home's `data/` and `config/`: they move host to host over SSH (`rsync -a`, owner-only), never through Git, a registry, or an image, and only for the cutover and rollback syncs of [Moving the agents to a new host](agent-host-move.md).

Keep local credential files outside the checkout, in owner-only directories with mode `0700`; files should have mode `0600`. Services should use `EnvironmentFile=` or Docker secrets. Do not put tokens into shell command arguments or public URLs.

The persistent desktop browser uses exactly one profile, `~/.vnc-chrome-profile`. Never clone, trim, archive into Git, or replace it. Log in on the destination device. The browser pruner excludes persistent profiles, attached browsers, and headed browsers.

## Remote access

Keep application and desktop listeners on loopback unless a reviewed deployment explicitly needs another binding. Reach them through SSH port forwarding or a configured private network. Do not publish a Docker socket or mount the host socket into an agent container; it grants host-level control.

Loopback is shared by local accounts. The optional desktop therefore requires an operator-created private VNC credential in addition to SSH transport. It never offers unauthenticated RFB access. Its service will not kill another desktop to claim an occupied display.

Tailscale installation, authentication, and SSH authorization are separate steps. Join the tailnet interactively, then use `tailscale set --ssh=true` only if Tailscale SSH is wanted. The tailnet must also authorize the connection in its SSH policy. Do not use `tailscale up --reset` to change one setting on an existing machine.

This export does not rewrite the current host's firewall, SSH policy, account membership, or credentials. Review those changes separately before applying a new-host profile.

## Updates

Tools track their latest release, and every download is verified against the checksum its publisher posts for that release (GitHub release-asset digests, Node's `SHASUMS256.txt`, rustup's `.sha256`, npm registry integrity, PyPI digests); a release without one is refused. The one exception is the three omp marketplace plugins (ponytail, i-have-adhd, caveman): no publisher checksums them, they track each author's default branch, and they load as agent instructions and hooks. The operator accepted that to keep them at the latest commit. Checksums prove a download is the published artifact; they do not establish that a publisher is trustworthy. Review added tools and installer behavior before adding them. Ubuntu security updates remain an operating-system responsibility rather than freezing an entire vulnerable package index forever.

Back up project repositories and application data separately, using encrypted storage and an application-aware restore procedure. A successful environment bootstrap is not evidence that a database backup is recoverable.
