// Two-way iMessage between the owner and Firstmate, over the line of a Photon Spectrum project.
// Inbound: each text the owner sends is filed first as a Firstmate inbox note, which wakes Firstmate, then marked read.
//   A one-shot front-desk model (typing bubble while it writes) answers beside the message loop, with a tapback
//   or a few words, so he is never left on read while Firstmate is busy. A desk failure becomes a thumbs-up tapback.
// Outbound: POST text to http://127.0.0.1:$FM_IMESSAGE_PORT/send (the fm-imessage command does this).
//   The free shared line refuses space.send ("Target not allowed for this project") but accepts a
//   threaded reply, so outbound replies to his latest text. That text's conversation and message ids
//   are kept in the state directory, so a restart can still reply to it.
// Location: when he shares his location with the line in Find My, GET /location (the fm-location command).
// Runs as the systemd --user service fm-imessage (docs/imessage.md). Docs: https://photon.codes/docs/spectrum-ts
import { appendFileSync, mkdirSync } from "node:fs";
import type { AdvancedIMessage } from "@photon-ai/advanced-imessage/grpc";
import { Spectrum, type Message } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { deskPrompt, localCommand, noteText, parseReact } from "./desk.ts";

const env = process.env;
const need = (name: string) => env[name] || (() => { throw new Error(`fm-imessage: ${name} is not set`); })();
const OWNER = need("FM_IMESSAGE_OWNER");
const FM_HOME = need("FM_HOME");
const INBOX = env.FM_INBOX_CMD || `${FM_HOME}/bin/fm-inbox.sh`;
const PORT = Number(env.FM_IMESSAGE_PORT || 8765);
const DESK_MODEL = env.FM_IMESSAGE_DESK_MODEL || "claude-haiku-5-5";
const DESK_PROMPT = deskPrompt(DESK_MODEL, env.FM_IMESSAGE_SUPERVISOR_MODEL || "");
// systemd's StateDirectory= sets STATE_DIRECTORY; the directory is private to the account.
const STATE = env.STATE_DIRECTORY || `${env.HOME}/.local/state/fm-imessage`;
const LATEST_FILE = `${STATE}/latest`;
const DESK_DIR = `${STATE}/desk`; // empty cwd: no project context files load
const DESK_LOG = `${STATE}/desk.log`; // what the desk sent, for Firstmate to read
const ATTACH_DIR = `${STATE}/attachments`; // his files, for Firstmate to open
for (const dir of [STATE, DESK_DIR, ATTACH_DIR]) mkdirSync(dir, { recursive: true, mode: 0o700 });
const thread: string[] = []; // the last few lines of the conversation, for the desk's context

const app = await Spectrum({
  projectId: need("PHOTON_PROJECT_ID"),
  projectSecret: need("PHOTON_PROJECT_SECRET"),
  providers: [imessage.config()],
});
// Spectrum has no public accessor for the line's Advanced iMessage client, which owns Find My locations;
// this reads its internal platform map (spectrum-ts 12.10). Recheck after a spectrum-ts upgrade.
const platforms = Reflect.get(Reflect.get(app, "__internal") as object, "platforms") as Map<string, { client: { client: AdvancedIMessage }[] }>;
const raw = platforms.get("imessage")?.client[0]?.client;
if (!raw) throw new Error("fm-imessage: no Advanced iMessage client in spectrum-ts internals; recheck after an upgrade");
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

Bun.serve({
  hostname: "127.0.0.1",
  port: PORT,
  async fetch(req) {
    if (!localCommand(req.headers, PORT)) return new Response("forbidden\n", { status: 403 });
    const path = new URL(req.url).pathname;
    if (req.method === "GET" && path === "/location") {
      try {
        return Response.json(await raw.locations.get(OWNER));
      } catch (e) {
        return new Response(`no location: ${e instanceof Error ? e.message : String(e)}; he shares it with the line in Find My\n`, { status: 503 });
      }
    }
    if (req.method !== "POST" || !["/send", "/typing", "/react"].includes(path)) return new Response("not found", { status: 404 });
    if (!latest) return new Response("no text from the owner since the bridge started; he must text the line first\n", { status: 503 });
    // Typing shows only while Firstmate is really composing: /typing starts it, and every send clears it.
    if (path === "/typing") {
      await latest.space.startTyping();
      return new Response("typing\n");
    }
    if (path === "/react") {
      const emoji = (await req.text()).trim();
      if (!emoji) return new Response("no emoji", { status: 400 });
      await latest.react(emoji);
      thread.push(`Firstmate reacted ${emoji} to his last text`);
      return new Response("reacted\n");
    }
    const text = (await req.text()).trim();
    if (!text) return new Response("empty message", { status: 400 });
    await latest.space.stopTyping();
    await latest.reply(text);
    thread.push(`Firstmate: ${text}`);
    return new Response("sent\n");
  },
});
console.log(`fm-imessage: listening on 127.0.0.1:${PORT}, latest text ${latest ? "restored" : "unknown"}`);

const log = (what: string) => (e: unknown) => console.error(`fm-imessage: ${what}:`, e);
const FALLBACK = "REACT:👍";

async function draft(id: string): Promise<string> {
  const inbox = Bun.spawn([INBOX, "status"], { cwd: FM_HOME, env: { ...env, FM_HOME }, stdout: "pipe", stderr: "ignore" });
  const status = await new Response(inbox.stdout).text();
  const desk = Bun.spawn(
    ["omp", "-p", "--no-extensions", "--no-tools", "--no-skills", "--no-rules", "--no-session",
      "--thinking=off", "--model", DESK_MODEL, "--system-prompt", DESK_PROMPT,
      `Fleet status (durable records, may lag):\n${status}\n\nRecent thread:\n${thread.join("\n")}\n\nWrite your reply to his last text.`],
    { cwd: DESK_DIR, stdout: "pipe", stderr: "ignore", timeout: 45_000 },
  );
  const drafted = (await new Response(desk.stdout).text()).replace(/^Working\.\.\.\s*/m, "").trim();
  if ((await desk.exited) !== 0 || !drafted) throw new Error(`the desk gave no answer to ${id}`);
  return drafted;
}

async function send(message: Message, answer: string): Promise<string> {
  const tapback = parseReact(answer);
  if (tapback) await message.react(tapback);
  else await message.reply(answer);
  thread.push(tapback ? `Firstmate reacted ${tapback} to his last text` : `Firstmate: ${answer}`);
  return tapback ? `react ${tapback}` : answer.replace(/\s+/g, " ");
}

async function frontDesk(message: Message) {
  const answer = await draft(message.id).catch((e) => { log("desk failed, tapping back")(e); return FALLBACK; });
  await message.space.stopTyping().catch(log("stop typing"));
  const outcome = await send(message, answer).catch(async (e) => {
    log("desk send failed, tapping back")(e);
    return send(message, FALLBACK).catch((e2) => { log("fallback tapback failed")(e2); return `send failed: ${answer.replace(/\s+/g, " ")}`; });
  });
  appendFileSync(DESK_LOG, `${new Date().toISOString()} ${message.id} ${outcome}\n`, { mode: 0o600 });
}

async function handle(message: Message) {
  const c = message.content;
  let file = "";
  let attachmentLost = false;
  if (c.type === "attachment") {
    try {
      file = `${ATTACH_DIR}/${message.id}-${String(c.name ?? "file").replace(/[^\w.-]/g, "_")}`;
      await Bun.write(file, await c.read());
    } catch (e) {
      attachmentLost = true;
      log("could not save an attachment")(e);
    }
  }
  const text = attachmentLost ? "(sent an attachment that could not be saved)" : noteText(c, file);
  if (text === undefined) return;
  const note = Bun.spawnSync(
    [INBOX, "note", "--request-id", `photon-${message.id}`, "--", `[iMessage from the owner; answer with fm-imessage] ${text}`],
    { cwd: FM_HOME, env: { ...env, FM_HOME } },
  );
  if (note.exitCode !== 0) {
    await message.reply("firstmate did not get that, send it again");
    return;
  }
  latest = message;
  await Bun.write(LATEST_FILE, `${message.space.id}\n${message.id}\n`).catch(log("persist the latest text"));
  await message.read().catch(log("mark read"));
  await message.space.startTyping().catch(log("start typing"));
  thread.push(`Owner: ${text}`);
  thread.splice(0, Math.max(0, thread.length - 12));
  frontDesk(message).catch(log("front desk failed"));
}

for await (const [, message] of app.messages) {
  if (message.direction === "outbound") continue;
  if (message.sender?.id !== OWNER) {
    console.log(`fm-imessage: ignored a message from ${message.sender?.id ?? "unknown"}`);
    continue;
  }
  await handle(message).catch(log("failed to handle a message"));
}
