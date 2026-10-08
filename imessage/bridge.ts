// Two-way iMessage between the owner and Firstmate, over the line of a Photon Spectrum project.
// Inbound: each text the owner sends is filed first as a Firstmate inbox note, which wakes Firstmate for the
//   real answer, then marked read. A one-shot front-desk model steps in only when Firstmate stays silent for the
//   quiet period after his last text; it often skips or uses a tapback, like a person would. Photon reports no
//   inbound typing, so a new text is what restarts the wait.
// Outbound: POST text to http://127.0.0.1:$FM_IMESSAGE_PORT/send (the fm-imessage command does this).
//   It sends plain messages into the space of his latest text; a refused send fails visibly (HTTP 502). Measured on the
//   free shared line: plain sends into the owner's own conversation work, while a conversation the service opened
//   itself was refused. That text's conversation and message ids are kept in the state directory, so a restart can
//   still reach him.
// Location: when he shares his location with the line in Find My, GET /location (the fm-location command).
// Runs as the systemd --user service fm-imessage (docs/imessage.md). Docs: https://photon.codes/docs/spectrum-ts
import { appendFileSync, mkdirSync } from "node:fs";
import type { AdvancedIMessage } from "@photon-ai/advanced-imessage/grpc";
import { Spectrum, type Message } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { type Attachment, bubbles, describe, DeskTiming, deskPrompt, localCommand, parseReact, typingPause } from "./desk.ts";

const env = process.env;
const need = (name: string) => env[name] || (() => { throw new Error(`fm-imessage: ${name} is not set`); })();
const OWNER = need("FM_IMESSAGE_OWNER");
const FM_HOME = need("FM_HOME");
const INBOX = env.FM_INBOX_CMD || `${FM_HOME}/bin/fm-inbox.sh`;
const PORT = Number(env.FM_IMESSAGE_PORT || 8765);
const DESK_MODEL = env.FM_IMESSAGE_DESK_MODEL || "claude-haiku-5-5";
const DESK_PROMPT = deskPrompt(env.FM_IMESSAGE_OWNER_NAME || "the owner", DESK_MODEL, env.FM_IMESSAGE_SUPERVISOR_MODEL || "");
const QUIET_MS = 8000; // the desk waits this long for Firstmate's own answer
// systemd's StateDirectory= sets STATE_DIRECTORY; the directory is private to the account.
const STATE = env.STATE_DIRECTORY || `${env.HOME}/.local/state/fm-imessage`;
const LATEST_FILE = `${STATE}/latest`;
const DESK_DIR = `${STATE}/desk`; // empty cwd: no project context files load
const DESK_LOG = `${STATE}/desk.log`; // what the desk did, for Firstmate to read
const ATTACH_DIR = `${STATE}/attachments`; // his files, for Firstmate to open
for (const dir of [STATE, DESK_DIR, ATTACH_DIR]) mkdirSync(dir, { recursive: true, mode: 0o700 });
const thread: string[] = []; // the last few lines of the conversation, for the desk's context
const recent: Message[] = []; // his last texts, newest last, for a threaded reply to one a few bubbles up
const log = (what: string) => (e: unknown) => console.error(`fm-imessage: ${what}:`, e);
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
let latest: Message | undefined;
const saved = Bun.file(LATEST_FILE);
if (await saved.exists()) {
  try {
    const [spaceId = "", messageId = ""] = (await saved.text()).trim().split("\n");
    latest = await (await imessage(app).space.get(spaceId)).getMessage(messageId);
  } catch (e) {
    console.error("fm-imessage: could not restore the latest text; treating it as unknown:", e);
  }
}

// Stop a pending or running desk turn: he sent more, or Firstmate is active on the line.
function cancelDesk() {
  if (!deskRun) return;
  deskRun.kill();
  deskRun = undefined;
  latest?.space.stopTyping().catch(log("stop typing"));
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
    if (!latest) return new Response("no text from the owner since the bridge started; he must text the line first\n", { status: 503 });
    // Any Firstmate activity on the line means the real answer is coming, so the desk stands down.
    desk.firstmateActive();
    cancelDesk();
    // Typing shows only while Firstmate is really composing: /typing starts it, and every send clears it.
    if (url.pathname === "/typing") {
      await latest.space.startTyping();
      return new Response("typing\n");
    }
    if (url.pathname === "/react") {
      const emoji = (await req.text()).trim();
      if (!emoji) return new Response("no emoji", { status: 400 });
      await latest.react(emoji);
      thread.push(`Firstmate reacted ${emoji} to his last text`);
      return new Response("reacted\n");
    }
    const parts = bubbles(await req.text());
    if (!parts.length) return new Response("empty message", { status: 400 });
    // A plain message by default. ?reply=N threads the first bubble to his Nth most recent text, only when
    // Firstmate addresses something a few bubbles up.
    const replyTo = Number(url.searchParams.get("reply") ?? 0);
    const target = replyTo > 0 ? recent[recent.length - replyTo] : undefined;
    if (replyTo > 0 && !target) return new Response(`nothing sent: only ${recent.length} text(s) kept since the service started\n`, { status: 400 });
    try {
      for (const [i, bubble] of parts.entries()) {
        if (i > 0) {
          await latest.space.startTyping();
          await Bun.sleep(typingPause(bubble));
        }
        await latest.space.stopTyping();
        if (i === 0 && target) await target.reply(bubble);
        else await latest.space.send(bubble);
      }
    } catch (e) {
      log("send failed")(e);
      return new Response(`send failed: ${e instanceof Error ? e.message : String(e)}\n`, { status: 502 });
    }
    thread.push(`Firstmate: ${parts.join(" / ")}`);
    return new Response(`sent ${parts.length} bubble(s)\n`);
  },
});
console.log(`fm-imessage: listening on 127.0.0.1:${PORT}, latest text ${latest ? "restored" : "unknown"}`);

// One desk turn for his latest burst. It drops its draft if he sent more or Firstmate answered meanwhile.
async function runDesk(current: () => boolean) {
  const target = latest;
  if (!target) return;
  await target.space.startTyping();
  const inbox = Bun.spawn([INBOX, "status"], { cwd: FM_HOME, env: { ...env, FM_HOME }, stdout: "pipe", stderr: "ignore" });
  const status = await new Response(inbox.stdout).text();
  if (!current()) return target.space.stopTyping();
  const proc = Bun.spawn(
    ["omp", "-p", "--no-extensions", "--no-tools", "--no-skills", "--no-rules", "--no-session",
      "--thinking=off", "--model", DESK_MODEL, "--system-prompt", DESK_PROMPT,
      `Fleet status (durable records, may lag):\n${status}\n\nRecent thread:\n${thread.join("\n")}\n\nDecide your response to his latest texts.`],
    { cwd: DESK_DIR, stdout: "pipe", stderr: "ignore", timeout: 45_000 },
  );
  deskRun = proc;
  const drafted = (await new Response(proc.stdout).text()).replace(/^Working\.\.\.\s*/m, "").trim();
  const ok = (await proc.exited) === 0 && drafted !== "";
  if (deskRun !== proc) return; // cancelled while drafting
  deskRun = undefined;
  await target.space.stopTyping();
  if (!current()) return;
  const skip = !ok || /^skip\W*$/i.test(drafted); // a failed desk stays quiet; Firstmate still has the note
  const tapback = skip ? undefined : parseReact(drafted);
  if (tapback) await target.react(tapback);
  else if (!skip) await target.space.send(drafted);
  if (!skip) thread.push(tapback ? `Firstmate reacted ${tapback} to his last text` : `Firstmate: ${drafted}`);
  const outcome = !ok ? "skip (desk failed)" : skip ? "skip" : tapback ? `react ${tapback}` : drafted.replace(/\s+/g, " ");
  appendFileSync(DESK_LOG, `${new Date().toISOString()} ${target.id} ${outcome}\n`, { mode: 0o600 });
}

async function saveAttachment(c: Attachment, id: string) {
  const path = `${ATTACH_DIR}/${id}-${String(c.name ?? "file").replace(/[^\w.-]/g, "_")}`;
  await Bun.write(path, await c.read());
  return path;
}

async function handle(message: Message) {
  const text = await describe(message.content, message.id, saveAttachment);
  console.log(`fm-imessage: inbound ${message.content.type} -> ${text === undefined ? "ignored" : "note"}`);
  if (text === undefined) return;
  // Hand the text to Firstmate first, so the wake never waits on the desk model.
  const note = Bun.spawnSync(
    [INBOX, "note", "--request-id", `photon-${message.id}`, "--", `[iMessage from the owner; answer with fm-imessage] ${text}`],
    { cwd: FM_HOME, env: { ...env, FM_HOME } },
  );
  if (note.exitCode !== 0) {
    await message.reply("firstmate did not get that, send it again");
    return;
  }
  latest = message;
  recent.push(message);
  recent.splice(0, Math.max(0, recent.length - 10));
  cancelDesk();
  desk.inboundText();
  await Bun.write(LATEST_FILE, `${message.space.id}\n${message.id}\n`).catch(log("persist the latest text"));
  await message.read().catch(log("mark read"));
  thread.push(`Owner: ${text}`);
  thread.splice(0, Math.max(0, thread.length - 12));
}

for await (const [, message] of app.messages) {
  if (message.direction === "outbound") continue;
  if (message.sender?.id !== OWNER) {
    console.log(`fm-imessage: ignored a message from ${message.sender?.id ?? "unknown"}`);
    continue;
  }
  await handle(message).catch(log("failed to handle a message"));
}
