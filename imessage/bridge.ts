// Two-way iMessage between the owner and Firstmate, over the line of a Photon Spectrum project.
// Inbound: each text the owner sends is filed first as a Firstmate inbox note, which wakes Firstmate for the
//   real answer, then marked read. A one-shot front-desk model steps in only when Firstmate stays silent for the
//   quiet period after his last text; it often skips or uses a tapback, like a person would. Photon reports no
//   inbound typing, so a new text is what restarts the wait. The desk sees the whole chat through its memory
//   (memory.ts), which logs every text both ways.
// Outbound: POST text to http://127.0.0.1:$FM_IMESSAGE_PORT/send (the fm-imessage command does this).
//   The text goes to a durable outbox (outbox.ts) and the answer comes once it is on disk; one loop sends the outbox
//   in order, as plain messages into the space of his latest text, and tries again with backoff while the upstream
//   fails. Measured on the free shared line: plain sends into the owner's own conversation work, while a
//   conversation the service opened itself was refused. That text's conversation and message ids are kept in the
//   state directory, so a restart can still reach him.
// Location: when he shares his location with the line in Find My, GET /location (the fm-location command).
// Runs as the systemd --user service fm-imessage (docs/imessage.md). Docs: https://photon.codes/docs/spectrum-ts
import { appendFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import type { AdvancedIMessage } from "@photon-ai/advanced-imessage/grpc";
import { Spectrum, type Message } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { type Attachment, bubbles, describe, DeskTiming, deskInput, deskPrompt, isSkip, localCommand, parseReact, typingPause } from "./desk.ts";
import { type Chat, type Kind, Memory } from "./memory.ts";
import { brief, permanent, Queue, transient } from "./outbox.ts";

const env = process.env;
const need = (name: string) => env[name] || (() => { throw new Error(`fm-imessage: ${name} is not set`); })();
const OWNER = need("FM_IMESSAGE_OWNER");
const FM_HOME = need("FM_HOME");
const INBOX = env.FM_INBOX_CMD || `${FM_HOME}/bin/fm-inbox.sh`;
const PORT = Number(env.FM_IMESSAGE_PORT || 8765);
const DESK_MODEL = env.FM_IMESSAGE_DESK_MODEL || "claude-haiku-5-5";
const DESK_PROMPT = deskPrompt(env.FM_IMESSAGE_OWNER_NAME || "the owner", DESK_MODEL, env.FM_IMESSAGE_SUPERVISOR_MODEL || "");
const QUIET_MS = 4000; // the desk waits this long for Firstmate's own answer
const RETRY_MS = Number(env.FM_IMESSAGE_RETRY_MS || 1000); // the first retry step of the outbox and the downloads
// systemd's StateDirectory= sets STATE_DIRECTORY; the directory is private to the account.
const STATE = env.STATE_DIRECTORY || `${env.HOME}/.local/state/fm-imessage`;
const LATEST_FILE = `${STATE}/latest`;
const DESK_DIR = `${STATE}/desk`; // empty cwd: no project context files load
const DESK_LOG = `${STATE}/desk.log`; // what the desk did, for Firstmate to read
const ATTACH_DIR = `${STATE}/attachments`; // his files, for Firstmate to open
const MEMORY_DIR = `${STATE}/memory`; // the desk's memory: the whole chat, word for word (memory.ts)
const OUTBOX_DIR = `${STATE}/outbox`; // sends and tapbacks not delivered yet, one file each (outbox.ts)
const DOWNLOADS_DIR = `${STATE}/downloads`; // his messages with an attachment not saved yet
for (const dir of [STATE, DESK_DIR, ATTACH_DIR]) mkdirSync(dir, { recursive: true, mode: 0o700 });
let burstFrom: number | undefined; // the memory id of his first text the desk has not answered yet
const recent: Message[] = []; // his last texts, newest last, for a threaded reply to one a few bubbles up
// One line for a transient upstream failure; the whole error, with its stack, for anything else.
const log = (what: string) => (e: unknown) =>
  transient(e) ? console.error(`fm-imessage: ${what}: ${brief(e)}`) : console.error(`fm-imessage: ${what}:`, e);
// Typing bubbles are best effort: an error is logged and never fails or delays a send.
const typing = (space: Message["space"], on: boolean) =>
  void (on ? space.startTyping() : space.stopTyping()).catch(log(on ? "start typing" : "stop typing"));
// This service is the memory's one writer: systemd runs one instance of the unit.
const memory = new Memory(MEMORY_DIR, compactChat, log("memory"));
const desk = new DeskTiming(QUIET_MS, (current) => void runDesk(current).catch(log("desk failed")));
let deskRun: Bun.Subprocess | undefined;

const app = await Spectrum({
  projectId: need("PHOTON_PROJECT_ID"),
  projectSecret: need("PHOTON_PROJECT_SECRET"),
  providers: [imessage.config()],
});
// Spectrum has no public accessor for the line's Advanced iMessage client, which owns Find My locations;
// this reads its internal platform map (spectrum-ts 12.10). Recheck after a spectrum-ts upgrade.
const internals = Reflect.get(app, "__internal") as { platforms?: Map<string, { client?: { client?: AdvancedIMessage }[] }> } | undefined;
const raw = internals?.platforms?.get?.("imessage")?.client?.[0]?.client;
if (!raw) console.warn("fm-imessage: no Advanced iMessage client in spectrum-ts internals; GET /location is off until the bridge is updated for this spectrum-ts");
// A message by its conversation and message ids, which outlive a restart.
type Ref = { space: string; id: string };
// One outbox item for his text `id`: a tapback, or bubbles (`done` of them sent so far), the first one threaded to
// his text `reply` when set. `kind` is whose memory line it makes (Firstmate's unless "desk"); `silent` makes none.
type Out = Ref & { react?: string; bubbles?: string[]; done?: number; reply?: string; kind?: Kind; silent?: boolean };
let latest: Message | undefined;
let latestRef: Ref | undefined; // the ids of `latest`, kept even when it cannot be fetched after a restart
const saved = Bun.file(LATEST_FILE);
if (await saved.exists()) {
  const [space = "", id = ""] = (await saved.text()).trim().split("\n");
  latestRef = { space, id };
  latest = await find(latestRef).catch((e) => void log("could not restore the latest text; sends still go to it")(e));
}
const outbox = new Queue<Out>(OUTBOX_DIR, "outbox item", deliver, RETRY_MS);
const downloads = new Queue<Ref>(DOWNLOADS_DIR, "attachment download", fetchAgain, RETRY_MS);

// Stop a pending or running desk turn: he sent more, or Firstmate is active on the line.
function cancelDesk() {
  if (!deskRun) return;
  deskRun.kill();
  deskRun = undefined;
  if (latest) typing(latest.space, false);
}

Bun.serve({
  hostname: "127.0.0.1",
  port: PORT,
  async fetch(req) {
    if (!localCommand(req.headers, PORT)) return new Response("forbidden\n", { status: 403 });
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname === "/location") {
      if (!raw) return new Response("no location: the location client is unavailable after a spectrum-ts upgrade; the bridge needs an update\n", { status: 503 });
      try {
        return Response.json(await raw.locations.get(OWNER));
      } catch (e) {
        return new Response(`no location: ${e instanceof Error ? e.message : String(e)}; he shares it with the line in Find My\n`, { status: 503 });
      }
    }
    if (req.method !== "POST" || !["/send", "/typing", "/react"].includes(url.pathname)) return new Response("not found", { status: 404 });
    const ref = latestRef; // sends and tapbacks go to his latest text as of now
    if (!ref) return new Response("no text from the owner yet; he must text the line first\n", { status: 503 });
    // Any Firstmate activity on the line means the real answer is coming, so the desk stands down.
    desk.firstmateActive();
    burstFrom = undefined;
    cancelDesk();
    // Typing shows only while Firstmate is really composing: /typing starts it, and every send clears it.
    if (url.pathname === "/typing") {
      if (latest) typing(latest.space, true);
      return new Response("typing\n");
    }
    if (url.pathname === "/react") {
      const emoji = (await req.text()).trim();
      if (!emoji) return new Response("no emoji", { status: 400 });
      return queue({ ...ref, react: emoji }, `tapback ${emoji}`);
    }
    const parts = bubbles(await req.text());
    if (!parts.length) return new Response("empty message", { status: 400 });
    // A plain message by default. ?reply=N threads the first bubble to his Nth most recent text, only when
    // Firstmate addresses something a few bubbles up.
    const replyTo = Number(url.searchParams.get("reply") ?? 0);
    const target = replyTo > 0 ? recent[recent.length - replyTo] : undefined;
    if (replyTo > 0 && !target) return new Response(`nothing queued: only ${recent.length} text(s) kept since the service started\n`, { status: 400 });
    return queue({ ...ref, bubbles: parts, reply: target?.id }, `${parts.length} bubble(s)`);
  },
});
console.log(`fm-imessage: listening on 127.0.0.1:${PORT}, latest text ${latest ? "restored" : latestRef ? "known by id" : "unknown"}`);

// Puts one item in the outbox and answers once the item is on disk.
function queue(item: Out, what: string) {
  outbox.add(item);
  return new Response(`queued ${what}; the bridge sends in order and retries while the upstream fails\n`);
}

async function find(ref: Ref): Promise<Message> {
  const message = await (await imessage(app).space.get(ref.space)).getMessage(ref.id);
  if (!message) throw new Error(`message ${ref.id} not found`);
  return message;
}

// Delivers one outbox item: the tapback, or each bubble not sent yet, saving the progress after each bubble so a
// retry or a restart sends at most the one bubble in flight again (delivery is at least once). A reply target that
// is gone sends the first bubble unthreaded.
async function deliver(o: Out, save: (o: Out) => void) {
  const kind = o.kind ?? "supervisor";
  if (o.react) {
    await (await find(o)).react(o.react);
    remember(kind, `tapback ${o.react} on his last text`);
    return;
  }
  const space = await imessage(app).space.get(o.space);
  const parts = o.bubbles ?? [];
  const thread = o.reply && !o.done ? await find({ space: o.space, id: o.reply }).catch((e) => {
    if (!permanent(e)) throw e;
    console.error(`fm-imessage: reply target ${o.reply} gone, sending unthreaded: ${brief(e)}`);
  }) : undefined;
  for (let i = o.done ?? 0; i < parts.length; i++) {
    if (i > 0) {
      typing(space, true);
      await Bun.sleep(typingPause(parts[i]));
    }
    typing(space, false);
    if (i === 0 && thread) await thread.reply(parts[i]);
    else await space.send(parts[i]);
    save({ ...o, done: i + 1 });
  }
  if (!o.silent) remember(kind, parts.join("\n\n"));
}

// A memory error never stops a send, a tapback or the inbox note: it is logged.
function remember(kind: Kind, text: string): number | undefined {
  try {
    return memory.append(kind, text);
  } catch (e) {
    log("memory")(e);
  }
}

// One desk turn for his latest burst. It drops its draft if he sent more or Firstmate answered meanwhile.
async function runDesk(current: () => boolean) {
  const target = latest;
  if (!target) return;
  typing(target.space, true);
  const inbox = Bun.spawn([INBOX, "status"], { cwd: FM_HOME, env: { ...env, FM_HOME }, stdout: "pipe", stderr: "ignore" });
  const status = await new Response(inbox.stdout).text();
  if (!current()) return typing(target.space, false);
  // The view of the chat before his burst, then the per-turn state, then his burst, all under the ceiling.
  const from = burstFrom ?? memory.msgs.length;
  const { prompt, spent } = deskInput(DESK_PROMPT, memory.render(from), status, memory.msgs.slice(from).map((m) => `${m.kind}: ${m.text}`).join("\n"));
  const proc = Bun.spawn(
    ["omp", "-p", "--no-extensions", "-e", `${import.meta.dir}/zoom.ts`, "--no-tools", "--no-skills", "--no-rules", "--no-session",
      "--thinking=off", "--model", DESK_MODEL, "--system-prompt", DESK_PROMPT],
    { cwd: DESK_DIR, env: { ...env, FM_DESK_MEMORY: MEMORY_DIR, FM_DESK_SPENT: String(spent) }, stdin: new Blob([prompt]), stdout: "pipe", stderr: "ignore", timeout: 45_000 },
  );
  deskRun = proc;
  const drafted = (await new Response(proc.stdout).text()).replace(/^Working\.\.\.\s*/m, "").trim();
  const ok = (await proc.exited) === 0 && drafted !== "";
  if (deskRun !== proc) return; // cancelled while drafting
  deskRun = undefined;
  typing(target.space, false);
  if (!current()) return;
  burstFrom = undefined;
  const skip = !ok || isSkip(drafted); // a failed desk stays quiet; Firstmate still has the note
  const tapback = skip ? undefined : parseReact(drafted);
  const ref = { space: target.space.id, id: target.id };
  if (tapback) outbox.add({ ...ref, react: tapback, kind: "desk" });
  else if (!skip) outbox.add({ ...ref, bubbles: [drafted], kind: "desk" });
  const outcome = !ok ? "skip (desk failed)" : skip ? "skip" : tapback ? `react ${tapback}` : drafted.replace(/\s+/g, " ");
  appendFileSync(DESK_LOG, `${new Date().toISOString()} ${target.id} ${outcome}\n`, { mode: 0o600 });
}

// One compaction conversation: an omp session in its own private directory, which end() removes.
function compactChat(system: string): Chat {
  const dir = mkdtempSync(`${STATE}/compact-`);
  let turns = 0;
  return {
    async say(text) {
      const proc = Bun.spawn(
        ["omp", "-p", "--no-extensions", "--no-tools", "--no-skills", "--no-rules", "--session-dir", dir, ...(turns++ ? ["--continue"] : []),
          "--thinking=off", "--model", DESK_MODEL, "--system-prompt", system],
        { cwd: DESK_DIR, stdin: new Blob([text]), stdout: "pipe", stderr: "ignore", timeout: 60_000 },
      );
      const line = (await new Response(proc.stdout).text()).replace(/^Working\.\.\.\s*/m, "").trim();
      if ((await proc.exited) !== 0 || !line) throw new Error(`compaction call failed (exit ${proc.exitCode})`);
      return line;
    },
    end: () => rmSync(dir, { recursive: true, force: true }),
  };
}

async function saveAttachment(c: Attachment, id: string) {
  const path = `${ATTACH_DIR}/${id}-${String(c.name ?? "file").replace(/[^\w.-]/g, "_")}`;
  await Bun.write(path, await c.read());
  return path;
}

// The note text for a message, and the first error of an attachment that could not be saved.
async function noteText(message: Message) {
  let failed: unknown;
  const text = await describe(message.content, message.id, (c, id) => saveAttachment(c, id).catch((e) => {
    failed ??= e;
    throw e;
  }));
  return { text, failed };
}

// Files a Firstmate inbox note; true when the inbox took it.
function fileNote(requestId: string, text: string): boolean {
  const note = Bun.spawnSync(
    [INBOX, "note", "--request-id", requestId, "--", `[iMessage from the owner; answer with fm-imessage] ${text}`],
    { cwd: FM_HOME, env: { ...env, FM_HOME } },
  );
  return note.exitCode === 0;
}

// Tries the attachments of his message again; once all are saved, files its note again with their paths.
async function fetchAgain(ref: Ref) {
  const { text, failed } = await noteText(await find(ref));
  if (failed !== undefined) throw failed;
  if (text !== undefined && !fileNote(`photon-${ref.id}-saved`, `(an earlier attachment is saved now) ${text}`)) {
    throw new Error("the inbox note failed");
  }
}

async function handle(message: Message) {
  const { text, failed } = await noteText(message);
  console.log(`fm-imessage: inbound ${message.content.type} -> ${text === undefined ? "ignored" : "note"}`);
  if (text === undefined) return;
  // Hand the text to Firstmate first, so the wake never waits on the desk model.
  if (!fileNote(`photon-${message.id}`, text)) {
    outbox.add({ space: message.space.id, id: message.id, bubbles: ["firstmate did not get that, send it again"], reply: message.id, silent: true });
    return;
  }
  if (failed !== undefined) {
    log("download an attachment")(failed);
    downloads.add({ space: message.space.id, id: message.id });
  }
  const id = remember("owner", text);
  if (id !== undefined) burstFrom ??= id;
  latest = message;
  latestRef = { space: message.space.id, id: message.id };
  recent.push(message);
  recent.splice(0, Math.max(0, recent.length - 10));
  cancelDesk();
  desk.inboundText();
  await Bun.write(LATEST_FILE, `${message.space.id}\n${message.id}\n`).catch(log("persist the latest text"));
  await message.read().catch(log("mark read"));
}

for await (const [, message] of app.messages) {
  if (message.direction === "outbound") continue;
  if (message.sender?.id !== OWNER) {
    console.log(`fm-imessage: ignored a message from ${message.sender?.id ?? "unknown"}`);
    continue;
  }
  await handle(message).catch(log("failed to handle a message"));
}
