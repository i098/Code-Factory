# iMessage bridge

The iMessage bridge lets the owner talk to Firstmate from a phone. It is a small Bun service, `fm-imessage.service`, that connects to the iMessage line of a [Photon Spectrum](https://photon.codes/docs/spectrum-ts) project. It is off by default.

## What it does

For each message from the owner, the service does these steps:

1. It turns the message into text. A threaded reply, an edit, a message effect, or a group of messages is unwrapped, so nothing that he writes is lost. A threaded reply also names the text that it replies to. A message kind that the service does not know becomes a note that names the kind. Tapbacks, typing, read receipts, unsends, and chat changes are only signals, and the service ignores them.
2. It files the text as a Firstmate inbox note (`fm-inbox.sh note`) first, so the wake never waits on a model. The note wakes Firstmate, which answers in full with `fm-imessage`. If the note fails, the service replies "firstmate did not get that, send it again" and stops there.
3. It marks the text as read.
4. It starts the quiet period, 4 seconds. Each new text from the owner starts the quiet period again. Any send, tapback, or typing bubble from Firstmate since his last text stops the desk for that burst of texts.
5. If the quiet period ends and Firstmate stayed silent, the front desk gets one turn for the whole burst. The front desk is a one-shot `omp -p` call with one tool, `zoom`. It gets its view of the whole conversation (see [Desk memory](#desk-memory)), the output of `fm-inbox.sh status`, and every message since his burst began, each with its kind as a prefix. It shows the typing bubble while it writes.
6. The desk acts like a person who texts, not like a bot. Its answer is one of three things, in this order of preference: `SKIP` (it sends nothing), `REACT:` and one emoji that it picks itself (a tapback on his latest text), or a short text. The text style is short, blunt, Gen Z, and lowercase. The desk never claims work that it cannot see, never promises a time, and never invents facts.
7. Before it sends, the service checks again. If the owner sent a new text or Firstmate became active while the desk wrote, the service drops the draft. The next quiet period reads the whole conversation again.

Photon reports no typing events from the owner, so only a new text starts the wait again.

If the desk fails or times out after 45 seconds, the service sends nothing: Firstmate has the note. The service appends the outcome of each desk turn (time, message id, `skip`, `react <emoji>`, or the reply text) to `~/.local/state/fm-imessage/desk.log`, which is private to the account, so Firstmate can read what the desk did.

The desk's system prompt is `deskPrompt` in `imessage/desk.ts`. The owner's name and the two model names come from the config.

The service ignores texts from all other senders. It saves attachments in `~/.local/state/fm-imessage/attachments/` for Firstmate to open. That directory is private to the account (mode `0700`). The service also keeps the owner's latest text in `~/.local/state/fm-imessage/latest`, so replies still work after a restart.

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
factory:
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
| `fm-imessage 'text'` | Sends the text to the owner. Without an argument, it reads the text from stdin. Paragraphs that a blank line separates become separate chat bubbles. The lines of one paragraph, for example a list or a schedule, stay in one bubble. Before each bubble after the first, the typing bubble shows for 400 ms plus 25 ms for each character, 2.5 seconds at most. |
| `fm-imessage --reply N 'text'` | Sends the text, but threads the first bubble as a reply to the owner's Nth most recent text (1 is the latest). The service keeps at most 10 texts, and only those received since it started. If the Nth text is not kept, nothing is sent and the command exits non-zero. Use it only when the answer is about a text a few bubbles up. Any other value of N sends nothing and exits with code 2. |
| `fm-imessage --typing` | Shows the typing bubble. The next send removes it. |
| `fm-imessage --react '👍'` | Adds a tapback to the owner's latest text. |
| `fm-imessage --help` | Shows the usage. It sends nothing. |
| `fm-location` | Prints the location that the owner shares with the line in Find My, as JSON. |

If a spectrum-ts upgrade changes the internals that the service reads to reach the location client, the service logs one warning at start and keeps running. Only `fm-location` then fails, with HTTP 503, until the bridge is updated.

`fm-imessage` exits non-zero when it sends nothing. An unknown option sends nothing and exits with code 2.

## Plain messages and the shared line

A send is a plain message into the conversation of the owner's latest text. Measured on the free shared line: plain sends into the owner's own conversation work, while a conversation that the service opened itself was refused ("Target not allowed for this project"). If the line refuses a send, the service answers `/send` with HTTP 502 and the error, and logs it, so `fm-imessage` exits non-zero. Threading happens only with `--reply N`. Typing bubbles and tapbacks also go to his latest text. Before the owner sends the first text, the commands fail with HTTP 503.

## Location is personal data

`fm-location` works only while the owner shares his location with the line in Find My. The location is personal data. Use it only when the work needs it. Keep it on the host: do not put it in a commit, an issue, a PR, a log, or a chat.
