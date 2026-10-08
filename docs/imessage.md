# iMessage bridge

The iMessage bridge lets the owner talk to Firstmate from a phone. It is a small Bun service, `fm-imessage.service`, that connects to the iMessage line of a [Photon Spectrum](https://photon.codes/docs/spectrum-ts) project. It is off by default.

## What it does

For each text from the owner, the service does these steps:

1. It marks the text as read.
2. It shows the typing bubble and asks a front desk for an instant reply. The front desk is a one-shot `omp -p` call with no tools. It gets the owner's last texts and the output of `fm-inbox.sh status`.
3. It sends the desk's reply in the thread. When the text is only an acknowledgement (ok, thanks), the desk adds a tapback instead. The desk writes plain text, says only that it passed the text on, and never claims work that it cannot see.
4. It files the text as a Firstmate inbox note (`fm-inbox.sh note`), with the desk's reply attached. The note wakes Firstmate, which answers in full with `fm-imessage`.

If the desk fails or times out after 45 seconds, the service sends a fixed reply. If the note fails, the service asks the owner to send the text again.

The service ignores texts from all other senders. It saves attachments in `~/.local/state/fm-imessage/attachments/` for Firstmate to open. That directory is private to the account (mode `0700`). The service also keeps the owner's latest text in `~/.local/state/fm-imessage/latest`, so replies still work after a restart.

## Set up the Photon project

1. Sign in to the [Photon dashboard](https://app.photon.codes) and create a project with the iMessage provider. The free plan gives a shared line.
2. In the project settings, copy the project ID and the project secret.
3. Add them to the host's secret store, `~/super.env`, as these two lines:

   ```bash
   PHOTON_PROJECT_ID=...
   PHOTON_PROJECT_SECRET=...
   ```

   Edit `super.env` on the primary VPS, push it, and fetch it on the host, as [Shared credentials](secrets.md) describes. On a host without the shared store, add the lines to `~/super.env` directly and keep the file at mode `600`. A later fetch replaces that file.

The unit reads `~/super.env` with `EnvironmentFile=` when it starts. The credentials never go into the repository, the unit, or `.local/host.yml`.

## Enable it

Add this block to `.local/host.yml`, then run `./factory apply`. The `firstmate` profile must be on.

```yaml
factory:
  imessage:
    owner: "+<country code><number>"  # the owner's phone number, E.164 form
    desk_model: claude-haiku-5-5    # optional; this is the default
    supervisor_model: ""            # optional; the model that runs Firstmate
```

The desk tells the owner the true models when he asks: `desk_model` for itself, and `supervisor_model` for Firstmate. When `supervisor_model` is empty, the desk says that it does not know.

Apply installs these items:

- the service in `~/.local/share/code-factory/imessage/`, with the latest spectrum-ts
- the unit `~/.config/systemd/user/fm-imessage.service`, mode `0600` because it holds the owner's number
- the commands `fm-imessage` and `fm-location` in `~/.local/bin`

The service listens on `127.0.0.1:8765`. To use a different port, set `FM_IMESSAGE_PORT` in a unit drop-in (`systemctl --user edit fm-imessage`) and in the environment of the commands. `FM_INBOX_CMD` overrides the inbox command, which is `<workspace>/firstmate/bin/fm-inbox.sh` by default.

To turn it off, remove the block, then run `systemctl --user disable --now fm-imessage` and delete the unit.

## Commands

| Command | What it does |
| --- | --- |
| `fm-imessage 'text'` | Sends the text to the owner. Without an argument, it reads the text from stdin. |
| `fm-imessage --typing` | Shows the typing bubble. The next send removes it. |
| `fm-imessage --react '👍'` | Adds a tapback to the owner's latest text. |
| `fm-imessage --help` | Shows the usage. It sends nothing. |
| `fm-location` | Prints the location that the owner shares with the line in Find My, as JSON. |

`fm-imessage` exits non-zero when it sends nothing. An unknown option sends nothing and exits with code 2.

## The shared-line limit

The free shared line refuses a new message to the owner ("Target not allowed for this project"). It accepts a reply in a thread. Thus every send, typing bubble, and tapback goes to the owner's latest text. Before the owner sends the first text, the commands fail with HTTP 503.

## Location is personal data

`fm-location` works only while the owner shares his location with the line in Find My. The location is personal data. Use it only when the work needs it. Keep it on the host: do not put it in a commit, an issue, a PR, a log, or a chat.
