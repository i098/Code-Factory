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

## Host hardening

Every apply installs [Koncreet](https://github.com/jimididit/koncreet) as `/usr/local/bin/koncreet` and renders `/etc/koncreet.conf` once, but nothing runs it. It is a first-hour hardening toolkit: a sudo user with SSH keys, sysctl, swap, a journald cap, time sync, a ufw default-deny firewall, fail2ban on SSH, unattended security updates, and finally SSH with password and root login turned off.

Upstream supports Debian 12/13 and Ubuntu 22.04/24.04 only. `patches/koncreet/ubuntu-26.04.patch` adds Ubuntu 26.04: it opens the OS gate and doctor, and restores the last fallback Koncreet uses to find your SSH client address for the fail2ban whitelist: 26.04 keeps no utmp, so `who -m` prints nothing, and the patch asks logind instead. The same change is the `ubuntu-26.04` branch of the [undeemed/koncreet](https://github.com/undeemed/koncreet/tree/ubuntu-26.04) fork; regenerate the patch from there with `git diff main...ubuntu-26.04`. Apply layers the patch on each new release and prints which case it hit: applied; skipped because the release already supports 26.04; or skipped because it no longer applies, in which case Koncreet installs as released and refuses to run on 26.04 until the patch is refreshed. The patch never fails the apply.

`/etc/koncreet.conf` makes the account that ran `./factory apply` the sudo user, installs the SSH keys it logs in with, keeps SSH open (Koncreet always allows the ports sshd listens on) and opens 41641/udp for Tailscale's direct connections. Apply never overwrites it; edit it there.

Run it once, by hand, from an SSH session you keep open until the last step works:

1. `sudo ufw allow in on tailscale0`, so the tailnet stays reachable once ufw denies incoming traffic. Koncreet keeps existing ufw rules.
2. `sudo koncreet doctor`
3. `sudo koncreet --dry-run apply -c /etc/koncreet.conf`, and read the plan.
4. `sudo koncreet apply -c /etc/koncreet.conf`
5. Open a new SSH session as that user and run `sudo true`. Only when it works: `sudo koncreet ssh apply`. Test one more new session before you close the first. Not `sudo -v`: once the account is in the `sudo` group, `sudo -v` asks for a password even when sudoers grants it NOPASSWD, and a cloud account has none.

If something goes wrong (from upstream's README):

| Problem | Fix |
|---------|-----|
| Can't SSH after harden | `sudo koncreet ssh undo` |
| Locked out by ufw | Console: `sudo ufw disable` |
| Banned by fail2ban | `sudo koncreet fail2ban unban YOUR.IP` |
| Undo baseline drop-ins | `sudo koncreet baseline undo` (keeps users/swap/timezone) |
| Need the new user password | `cat /root/USER.koncreet-password` (as root - save it before `ssh apply`) |
| Forced password change fails | `chage -d $(date -I) USER` then reconnect with your key |
| Too many authentication failures | `ssh -o IdentitiesOnly=yes -i ~/.ssh/your_key user@host` |

Logs: `/var/log/koncreet.log`. Backups: `*.koncreet.bak`. The provider's console, and `tailscale ssh` where Tailscale SSH is enabled, reach the host when sshd does not.

## Updates

Tools track their latest release, and every download is verified against the checksum its publisher posts for that release (what each source checks is in [Dependencies](dependencies.md)); a release without one is refused. The one exception is the three omp marketplace plugins (ponytail, i-have-adhd, caveman): no publisher checksums them, they track each author's default branch, and they load as agent instructions and hooks. The operator accepted that to keep them at the latest commit. Checksums prove a download is the published artifact; they do not establish that a publisher is trustworthy. Review added tools and installer behavior before adding them. Ubuntu security updates remain an operating-system responsibility rather than freezing an entire vulnerable package index forever.

Back up project repositories and application data separately, using encrypted storage and an application-aware restore procedure. A successful environment bootstrap is not evidence that a database backup is recoverable.
