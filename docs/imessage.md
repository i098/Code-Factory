# iMessage bridge

The iMessage bridge lets the owner talk to Firstmate from a phone. It is a small Bun service, `fm-imessage.service`, that connects to the iMessage line of a [Photon Spectrum](https://photon.codes/docs/spectrum-ts) project. It is off by default.

## What it does

For each message from the owner, the service does these steps:

1. It turns the message into text. A threaded reply, a message effect, or a group of messages is unwrapped, so nothing that he writes is lost. A threaded reply also names the text that it replies to. A message kind that the service does not know becomes a note that names the kind. Tapbacks, typing, read receipts, unsends, and chat changes are only signals, and the service ignores them.
2. It files the text as a Firstmate inbox note (`fm-inbox.sh note`) first, so the wake never waits on a model. The note wakes Firstmate, which answers in full with `fm-imessage`. If the note fails, the service replies "firstmate did not get that, send it again" and stops there.
3. It marks the text as read.
4. It starts the quiet period, 4 seconds. Each new text from the owner starts the quiet period again. Any send, tapback, or typing bubble from Firstmate since his last text stops the desk for that burst of texts.
5. If the quiet period ends and Firstmate stayed silent, the front desk gets one turn for the whole burst. The front desk is a one-shot `omp -p` call with one tool, `zoom`. It gets its view of the whole conversation (see [Desk memory](#desk-memory)), the output of `fm-inbox.sh status`, and every message since his burst began, each with its kind as a prefix. It shows the typing bubble while it writes.
6. The desk acts like a person who texts, not like a bot. Its answer is one of three things, in this order of preference: `SKIP` (it sends nothing), `REACT:` and one emoji that it picks itself (a tapback on his latest text), or a short text. The text style is short, blunt, Gen Z, and lowercase. The desk never claims work that it cannot see, never promises a time, and never invents facts.
7. Before it sends, the service checks again. If the owner sent a new text or Firstmate became active while the desk wrote, the service drops the draft. The next quiet period reads the whole conversation again.

Photon reports no typing events from the owner, so only a new text starts the wait again.

When the owner edits a text, the service files a new note, `[edited] <new text> (was: <old text>)`, and the note wakes Firstmate like a new text. The service keeps his last 100 texts in memory for the old text. If it does not know the old text (for example, the text came before the last restart), the note says so. spectrum-ts does not pass edits on, so the service reads them from its own event stream on the line's client. An edit that the owner makes while that stream is down is lost.

If the desk fails or times out after 45 seconds, the service sends nothing: Firstmate has the note. The service appends the outcome of each desk turn (time, message id, `skip`, `react <emoji>`, or the reply text) to `~/.local/state/fm-imessage/desk.log`, which is private to the account, so Firstmate can read what the desk did.

The desk's system prompt is `deskPrompt` in `imessage/desk.ts`. The owner's name and the two model names come from the config.

The service ignores texts from all other senders. It saves attachments in `~/.local/state/fm-imessage/attachments/` for Firstmate to open. That directory is private to the account (mode `0700`). The service also keeps the owner's latest text in `~/.local/state/fm-imessage/latest`, so replies still work after a restart.

## Upstream outages

The Photon service can be unavailable for minutes. It then answers `UNAVAILABLE` (gRPC) or HTTP 502 or 503. The service keeps every message through such an outage. The code is `imessage/outbox.ts`.

- **The outbox.** Each send and tapback goes to `~/.local/state/fm-imessage/outbox/` first, as one file. This covers the answers of Firstmate, the desk's text and tapback, and the "firstmate did not get that" reply, so they all keep one order. The service writes the file to a temporary name, syncs it to disk, and renames it. The file name is a sequence number that only goes up. The service answers `fm-imessage` only after the file is on disk. A desk message that waited out an outage is still sent, late.
- **Delivery.** One loop sends the oldest file, then deletes it. If a send fails, the loop tries the same file again after a wait: 1 second, then 2, 4, and so on, up to 60 seconds, each with random jitter. This holds for an outage (`UNAVAILABLE`, HTTP 502, 503 or 504, a timeout, a network failure such as a dropped connection or a DNS error) and for every error that the service does not know. Thus the order stays the same and no message is lost. After each bubble of a message, the service records the bubbles that it sent. Delivery is at least once: if the upstream accepts a send but the answer fails, or the service stops between a send and the record, that one bubble can arrive twice. If the text that a send threads to is gone, the service sends it without the thread.
- **Downloads.** If an attachment download fails, the note says that the attachment could not be saved yet. The service records the message id in `~/.local/state/fm-imessage/downloads/` and tries the download again with the same waits. When the download works, the service files a second note with the saved path. If the download moves to the dead-letter folder (see below), the service files a second note with the message id that says the attachment is lost, so Firstmate stops waiting for a path.
- **Restarts.** The outbox and the downloads are on disk, so they survive a restart of the service. At start, the service continues with the files that it finds.
- **Typing.** Typing bubbles are best effort. A typing error is logged and never fails or delays a send.
- **Logs.** Each failed try writes one log line with the operation and the code, for example `outbox item 3 failed (try 4), next try in 6.2 s: UNAVAILABLE: ...`. A transient error never writes a stack trace.

Only an item that is provably bad leaves the queue: a message or an attachment that is not found or has expired (HTTP 404 or 410, gRPC `NOT_FOUND`), an item that the upstream refuses as invalid (HTTP 400 or 422, gRPC `INVALID_ARGUMENT`), or a file that does not parse. The service moves its file to `~/.local/state/fm-imessage/outbox-dead/` (for a download: `downloads-dead/`), writes one log line, and goes on with the next item. Nothing is dropped without a trace. To send or fetch it again, move the file back to the queue directory under a new sequence number. To drop an item by hand, delete its file. An error that can be systemic (for example HTTP 429 or 500, or `PERMISSION_DENIED`) holds the queue in order while it retries, and the log shows each try. `FM_IMESSAGE_RETRY_MS` sets the first wait in milliseconds (default 1000); the longest wait is 60 times that value.

## Desk memory

The desk remembers the whole conversation, after the design in [UniiChat: one chat that never ends](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449). The code is `imessage/memory.ts`.

- **The log.** The service appends one record for each text from the owner, each send and tapback from Firstmate, and each desk text and tapback. The records are in `~/.local/state/fm-imessage/memory/main/YYYY-MM-DD.jsonl`. The service never edits or deletes a record.
- **The tree.** In the background, the desk model compresses the log into a binary tree of one-line summaries of at most 512 bytes. A text that fits in 512 bytes is its own line. Two adjacent lines merge into one line, again and again. The nodes are in `memory/tree/YYYY-MM-DD.jsonl`. At most 3 compaction calls run at the same time, and they never delay a desk turn.
- **The view.** Each desk turn gets a list of lines that covers the whole conversation: recent lines are fine, old lines are coarse. The view grows by one line for each message. When it is larger than 64 KB, one batch merges lines until it is 32 KB or less. The view is in `memory/view.json`, and the service loads it at start.
- **Zoom.** When a line is too vague, the desk calls `zoom(id, n)` to open the line into the two lines under it. `zoom(id, 1)` gives one message whole. A text that is not summarized yet shows as "(not summarized yet: zoom it)".
- **The input cap.** The model's price rises past 100,000 tokens of input, so no desk or compaction request sends more than 180,000 bytes (about 60,000 tokens, counted as bytes / 3). The service clips the fleet status, long texts, and each zoom result (16 KB) to their head and tail. After the cap, zoom returns "context limit reached".

The memory holds the owner's texts word for word, on the host only. The directory is private to the account (mode `0700`). To make the desk forget everything, stop the service, delete `~/.local/state/fm-imessage/memory/`, and start the service again.

A memory error never stops a send, a tapback, or the inbox note: the service logs it and goes on. At start, the service skips a log line that does not parse (a torn last line after a crash).

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

Add this block to `.local/host.yml`, then run `./ship.sh launch`. The `firstmate` profile must be on.

```yaml
crewship:
  imessage:
    owner: "+<country code><number>"  # the owner's phone number, E.164 form
    owner_name: the owner           # optional; this is the default; how the desk prompt names him
    desk_model: claude-haiku-5-5    # optional; this is the default
    supervisor_model: ""            # optional; the model that runs Firstmate
```

The desk tells the owner the true models when he asks: `desk_model` for itself, and `supervisor_model` for Firstmate. When `supervisor_model` is empty, the desk says that it does not know.

Apply installs these items:

- the service in `~/.local/share/code-factory/imessage/`, with the latest spectrum-ts
- the unit `~/.config/systemd/user/fm-imessage.service`, mode `0600` because it holds the owner's number
- the commands `fm-imessage` and `fm-location` in `~/.local/bin`

The service listens on `127.0.0.1:8765`. To use a different port, set `FM_IMESSAGE_PORT` in a unit drop-in (`systemctl --user edit fm-imessage`) and in the environment of the commands. `FM_INBOX_CMD` overrides the inbox command, which is `<workspace>/firstmate/bin/fm-inbox.sh` by default.

The service is for the host's own commands (`fm-imessage`, `fm-location`) only. It answers `403` to any request that lacks the header `X-Firstmate: 1` or whose `Host` is not exactly `127.0.0.1:<port>`, before it looks at the path. A web page open in a browser on the host cannot set a custom header without a CORS preflight, which the service never answers, and the `Host` check stops DNS rebinding. So a page cannot send messages as Firstmate or read the location. If you call the service with your own `curl`, add `-H "X-Firstmate: 1"`.

To turn it off, remove the block, then run `systemctl --user disable --now fm-imessage` and delete the unit.

## Commands

| Command | What it does |
| --- | --- |
| `fm-imessage 'text'` | Queues the text for the owner. Without an argument, it reads the text from stdin. Paragraphs that a blank line separates become separate chat bubbles. The lines of one paragraph, for example a list or a schedule, stay in one bubble. Before each bubble after the first, the typing bubble shows for 400 ms plus 25 ms for each character, 2.5 seconds at most. |
| `fm-imessage --reply N 'text'` | Queues the text, but threads the first bubble as a reply to the owner's Nth most recent text (1 is the latest). The command picks the text when it runs, and the queued message keeps the id of that text. Thus the reply goes to the same text if he sends more before the delivery, or if the service restarts. The service keeps at most 10 texts, and only those received since it started. If the Nth text is not kept, nothing is queued and the command exits non-zero. Use it only when the answer is about a text a few bubbles up. Any other value of N queues nothing and exits with code 2. |
| `fm-imessage --typing` | Shows the typing bubble, best effort. The next send removes it. A typing error is only logged, so the command exits 0. |
| `fm-imessage --react '👍'` | Queues a tapback in the outbox, in order with the sends. The tapback goes on the text that was his latest when the command ran. |
| `fm-imessage --help` | Shows the usage. It queues nothing. |
| `fm-location` | Prints the location that the owner shares with the line in Find My, as JSON. |

If a spectrum-ts upgrade changes the internals that the service reads to reach the line's client, the service logs one warning at start and keeps running. Until the bridge is updated, `fm-location` fails with HTTP 503 and the service does not see edits.

`fm-imessage` exits 0 only when the message is on disk in the outbox, and prints that it is queued. It exits non-zero when it queues nothing. An unknown option queues nothing and exits with code 2.

## Plain messages and the shared line

A send is a plain message into the conversation of the owner's latest text. Measured on the free shared line: plain sends into the owner's own conversation work, while a conversation that the service opened itself was refused ("Target not allowed for this project"). If the line refuses a send, the send stays in the outbox and the service logs each try (see [Upstream outages](#upstream-outages)). Threading happens only with `--reply N`. Typing bubbles and tapbacks also go to his latest text. Before the owner sends the first text, the commands fail with HTTP 503.

## Location is personal data

`fm-location` works only while the owner shares his location with the line in Find My. The location is personal data. Use it only when the work needs it. Keep it on the host: do not put it in a commit, an issue, a PR, a log, or a chat.
