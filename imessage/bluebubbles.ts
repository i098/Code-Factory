// The BlueBubbles transport of the iMessage bridge (bridge.ts, docs/imessage.md): self-hosted BlueBubbles servers,
// "relays", on Macs signed into the same Apple Account, used as one line in config order.
// Outbound: each call goes to the first healthy relay and fails over in order. A send that may have reached a
//   relay (a timeout or a server error after the request went out) is retried on the next relay only after no
//   relay shows it as sent, so one text is never sent twice.
// Inbound: every relay posts its webhook here, and a catch-up query fills any gap. A webhook is only a hint: the
//   message itself is read back from a relay with the password, so a forged webhook can only name a real message.
//   Messages are de-duplicated by GUID with a bounded seen-set on disk.
// The API takes the password only as a query parameter, so a request URL is never logged or put in an error.
// API: https://documenter.getpostman.com/view/765844/UV5RnfwM (BlueBubbles server 1.9).
import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import type { Attachment, LineMessage } from "./desk.ts";

export type Relay = { url: string; password: string };

const DEFAULTS = {
  pingMs: 3000, // health check timeout
  healthMs: 10_000, // how long a health result is kept
  callMs: 15_000, // any other call
  sendMs: 30_000, // a send: the server answers once Messages has the message
  delays: [1000, 2000, 4000, 8000], // between attachment download attempts
  skewMs: 60_000, // clock difference allowed between this host and a relay when looking for a sent text
  seenMax: 1000, // message GUIDs kept for de-duplication
  catchUpMs: 60_000, // between catch-up queries
};

// The tapbacks BlueBubbles can send, by emoji.
const TAPBACKS: Record<string, string> = {
  "❤️": "love", "❤": "love", "👍": "like", "👎": "dislike", "😂": "laugh", "‼️": "emphasize", "‼": "emphasize", "❓": "question",
};

// A failed relay call. `status` is the HTTP status, or undefined when the relay was not reached or did not answer.
// `maybeSent` is true when the request may have reached the relay anyway (a timeout, a server error).
class RelayError extends Error {
  constructor(message: string, readonly maybeSent: boolean, readonly status?: number) {
    super(message);
  }
}

type BBAttachment = { guid: string; transferName?: string; mimeType?: string; totalBytes?: number };
type BBMessage = {
  guid: string; text?: string | null; isFromMe?: boolean; dateCreated?: number; itemType?: number;
  handle?: { address?: string } | null; chats?: { guid: string }[]; attachments?: BBAttachment[];
  associatedMessageGuid?: string | null; threadOriginatorGuid?: string | null;
};

export class BlueBubbles implements AsyncIterable<LineMessage> {
  private opts: typeof DEFAULTS;
  private health = new Map<Relay, { ok: boolean; at: number }>();
  private unsure = new Map<string, number>(); // client GUID -> start of a send that may have gone out
  private seen = new Map<string, number>(); // message GUID -> its date, oldest first
  private seenFile: string;
  private appended = 0;
  private queue: LineMessage[] = [];
  private wake?: () => void;
  private chain = Promise.resolve();
  private since: number;

  constructor(
    private relays: Relay[],
    dir: string,
    opts: Partial<typeof DEFAULTS> = {},
    private log: (line: string) => void = (line) => console.error(`fm-imessage: bluebubbles ${line}`),
  ) {
    if (!relays.length) throw new Error("fm-imessage: no BlueBubbles relay is set");
    this.opts = { ...DEFAULTS, ...opts };
    this.seenFile = `${dir}/bluebubbles-seen`;
    if (existsSync(this.seenFile)) {
      for (const line of readFileSync(this.seenFile, "utf8").split("\n")) {
        const [guid, date] = line.split(" ");
        if (guid) this.remember(guid, Number(date) || 0);
      }
      this.compactSeen();
    }
    // Catch-up starts after the newest message seen, or a little before now on a first start.
    this.since = this.seen.size ? Math.max(...this.seen.values()) : Date.now() - this.opts.skewMs;
  }

  // Start the catch-up queries: now, then every catchUpMs.
  start() {
    void this.catchUp();
    setInterval(() => void this.catchUp(), this.opts.catchUpMs);
  }

  async *[Symbol.asyncIterator]() {
    for (;;) {
      while (this.queue.length) yield this.queue.shift()!;
      await new Promise<void>((resolve) => (this.wake = resolve));
    }
  }

  // A webhook from any relay. Only "new-message" events matter; the reply is immediate.
  async webhook(req: Request): Promise<Response> {
    if (req.method !== "POST" || new URL(req.url).pathname !== "/bluebubbles") return new Response("not found\n", { status: 404 });
    const event: unknown = await req.json().catch(() => undefined);
    const data = event && typeof event === "object" && "type" in event && event.type === "new-message" && "data" in event ? event.data : undefined;
    if (data && typeof data === "object" && "guid" in data && typeof data.guid === "string" && !("isFromMe" in data && data.isFromMe)) {
      void this.accept(data.guid);
    }
    return new Response("ok\n");
  }

  // The latest text kept by the bridge, rebuilt without a relay call so a restart works while every relay is down.
  restore(chat: string, guid: string): LineMessage {
    return this.message({ guid, text: "", chats: [{ guid: chat }] }, chat, { type: "text", text: "" });
  }

  // Queue one message by GUID, once. `data` is the message when a query already read it.
  accept(guid: string, data?: BBMessage): Promise<void> {
    if (this.seen.has(guid)) return this.chain;
    this.remember(guid, data?.dateCreated ?? 0);
    this.chain = this.chain.then(async () => {
      try {
        // The relay's own record of the message (see BBMessage); the API has no schema to check it against.
        const m = data ?? ((await this.first((r) => this.call(r, "GET", `message/${encodeURIComponent(guid)}`, { with: "chats,attachments" }))) as BBMessage);
        this.seen.set(guid, m.dateCreated ?? 0);
        this.since = Math.max(this.since, m.dateCreated ?? 0);
        appendFileSync(this.seenFile, `${guid} ${m.dateCreated ?? 0}\n`, { mode: 0o600 });
        if (++this.appended > this.opts.seenMax) this.compactSeen();
        const built = await this.build(m);
        if (built) this.push(built);
      } catch (e) {
        this.seen.delete(guid); // a later webhook or catch-up tries again
        this.log(`could not read message ${guid}: ${e instanceof Error ? e.message : String(e)}`);
      }
    });
    return this.chain;
  }

  // Ask the first healthy relay for messages since the newest one seen, and accept each in order.
  async catchUp() {
    try {
      const found = (await this.first((r) => this.call(r, "POST", "message/query", undefined,
        { after: this.since, sort: "ASC", limit: 100, with: ["chats", "attachments"] }))) as BBMessage[];
      for (const m of found) await this.accept(m.guid, m);
    } catch (e) {
      // An unreachable relay was already logged when it went down.
      if (!(e instanceof RelayError) || e.status !== undefined) this.log(`catch-up failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // Send one text into a chat, as a threaded reply when `replyTo` is a message GUID. `guid` is the client GUID
  // (BlueBubbles tempGuid): a retry that passes the same one is checked against the relays first when an earlier
  // try may have gone out, so it is never sent twice.
  async send(chat: string, text: string, replyTo?: string, guid?: string) {
    const id = guid ?? crypto.randomUUID();
    const started = this.unsure.get(id) ?? Date.now();
    let maybeSent = this.unsure.has(id);
    let last: unknown = new RelayError("no relay is reachable", false);
    for (const r of await this.healthy()) {
      try {
        if (!maybeSent || !(await this.wentOut(chat, text, started))) {
          await this.call(r, "POST", "message/text", undefined,
            { chatGuid: chat, tempGuid: id, message: text, ...(replyTo ? { selectedMessageGuid: replyTo, partIndex: 0 } : {}) }, this.opts.sendMs);
        }
        this.unsure.delete(id);
        return;
      } catch (e) {
        if (!(e instanceof RelayError)) throw e;
        last = e;
        maybeSent ||= e.maybeSent;
      }
    }
    if (maybeSent && guid) this.unsure.set(guid, started);
    throw last;
  }

  // Put a tapback on a message. BlueBubbles has six; any other emoji fails with the list.
  async react(chat: string, guid: string, emoji: string) {
    const reaction = TAPBACKS[emoji.trim()];
    if (!reaction) throw new Error(`no BlueBubbles tapback for ${emoji}; use one of ❤️ 👍 👎 😂 ‼️ ❓`);
    await this.first((r) => this.call(r, "POST", "message/react", undefined, { chatGuid: chat, selectedMessageGuid: guid, reaction, partIndex: 0 }));
  }

  // Download an attachment from whichever relay has it, with retry and backoff.
  async download(guid: string): Promise<Buffer> {
    for (let attempt = 0; ; attempt++) {
      try {
        return await this.first((r) => this.call(r, "GET", `attachment/${encodeURIComponent(guid)}/download`, { original: "true" }, undefined, this.opts.callMs, true)) as Buffer;
      } catch (e) {
        if (attempt >= this.opts.delays.length) throw e;
        await Bun.sleep(this.opts.delays[attempt]!);
      }
    }
  }

  // True when a relay shows `text` as sent into `chat` since `since`. Throws when no relay can be asked, so the
  // caller does not send again unchecked. A sent text reaches the other Macs through iCloud, which can lag: a relay
  // that did not send it may not show it yet.
  private async wentOut(chat: string, text: string, since: number): Promise<boolean> {
    let asked = false;
    for (const r of await this.healthy()) {
      try {
        const recent = (await this.call(r, "GET", `chat/${encodeURIComponent(chat)}/message`,
          { after: String(since - this.opts.skewMs), sort: "DESC", limit: "50" })) as BBMessage[];
        asked = true;
        if (recent.some((m) => m.isFromMe && m.text?.trim() === text.trim())) return true;
      } catch {
        // ask the next relay
      }
    }
    if (!asked) throw new RelayError("could not check whether an earlier try was sent; no relay answered", true);
    return false;
  }

  private typing(chat: string, method: "POST" | "DELETE"): Promise<void> {
    // A typing error never fails or delays a send: it is logged as one line and dropped.
    return this.first((r) => this.call(r, method, `chat/${encodeURIComponent(chat)}/typing`)).then(
      () => undefined,
      (e) => this.log(`typing failed: ${e instanceof Error ? e.message : String(e)}`),
    );
  }

  // Run `fn` on each healthy relay in order until one succeeds.
  private async first<T>(fn: (r: Relay) => Promise<T>): Promise<T> {
    let last: unknown = new RelayError("no relay is reachable", false);
    for (const r of await this.healthy()) {
      try {
        return await fn(r);
      } catch (e) {
        last = e;
      }
    }
    throw last;
  }

  private async healthy(): Promise<Relay[]> {
    const ok = await Promise.all(this.relays.map(async (r) => {
      const h = this.health.get(r);
      if (h && Date.now() - h.at < this.opts.healthMs) return h.ok;
      return this.call(r, "GET", "ping", undefined, undefined, this.opts.pingMs).then(() => true, () => false);
    }));
    return this.relays.filter((_, i) => ok[i]);
  }

  private name(r: Relay) {
    return `relay ${this.relays.indexOf(r) + 1} (${new URL(r.url).host})`;
  }

  // Record a relay's health; a change is logged as one line.
  private mark(r: Relay, ok: boolean, why = "") {
    const was = this.health.get(r)?.ok;
    this.health.set(r, { ok, at: Date.now() });
    if (was !== ok && (was !== undefined || !ok)) this.log(`${this.name(r)} ${ok ? "is back" : `is down: ${why}`}`);
  }

  private async call(r: Relay, method: string, path: string, query: Record<string, string> = {}, body?: unknown,
    timeout = this.opts.callMs, binary = false): Promise<unknown> {
    const url = new URL(`api/v1/${path}`, r.url.endsWith("/") ? r.url : `${r.url}/`);
    for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
    url.searchParams.set("password", r.password);
    let res: Response;
    try {
      res = await fetch(url, {
        method,
        headers: body === undefined ? undefined : { "content-type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(timeout),
      });
    } catch (e) {
      const refused = e instanceof Error && "code" in e && e.code === "ConnectionRefused";
      const why = e instanceof Error && e.name === "TimeoutError" ? `no answer in ${timeout} ms` : refused ? "connection refused" : "unreachable";
      this.mark(r, false, why);
      throw new RelayError(`${this.name(r)}: ${why}`, !refused);
    }
    this.mark(r, true);
    if (!res.ok) {
      const detail = (await res.text().catch(() => "")).replace(/\s+/g, " ").slice(0, 200);
      throw new RelayError(`${this.name(r)}: HTTP ${res.status} ${detail}`.trim(), res.status >= 500, res.status);
    }
    if (binary) return Buffer.from(await res.arrayBuffer());
    const json: unknown = await res.json();
    return json && typeof json === "object" && "data" in json ? json.data : undefined;
  }

  private remember(guid: string, date: number) {
    this.seen.set(guid, date);
    for (const old of this.seen.keys()) {
      if (this.seen.size <= this.opts.seenMax) break;
      this.seen.delete(old);
    }
  }

  private compactSeen() {
    writeFileSync(this.seenFile, [...this.seen].map(([g, d]) => `${g} ${d}\n`).join(""), { mode: 0o600 });
    this.appended = 0;
  }

  private push(m: LineMessage) {
    this.queue.push(m);
    this.wake?.();
    this.wake = undefined;
  }

  // The bridge's view of one BlueBubbles message, or undefined for one with nothing to show.
  private async build(m: BBMessage): Promise<LineMessage | undefined> {
    const chat = m.chats?.[0]?.guid;
    if (!chat) return undefined;
    if (m.associatedMessageGuid) return this.message(m, chat, { type: "reaction" } as LineMessage["content"]);
    // Messages puts U+FFFC in the text where each attachment sits.
    const text = (m.text ?? "").replace(/\uFFFC/g, "").trim();
    const parts: LineMessage["content"][] = [
      ...(text ? [{ type: "text", text } as LineMessage["content"]] : []),
      ...(m.attachments ?? []).map((a) => this.attachment(a)),
    ];
    if (!parts.length) return undefined;
    let content = parts.length === 1 ? parts[0]! : ({ type: "group", items: parts.map((c) => ({ content: c })) } as unknown as LineMessage["content"]);
    if (m.threadOriginatorGuid) {
      const target = await this.first((r) => this.call(r, "GET", `message/${encodeURIComponent(m.threadOriginatorGuid!)}`)).then(
        (t) => ({ type: "text", text: ((t as BBMessage).text ?? "").replace(/\uFFFC/g, "").trim() }),
        () => ({ type: "unknown" }),
      );
      content = { type: "reply", content, target: { content: target } } as unknown as LineMessage["content"];
    }
    return this.message(m, chat, content);
  }

  private attachment(a: BBAttachment): LineMessage["content"] {
    const c = { type: "attachment", id: a.guid, name: a.transferName || "file", mimeType: a.mimeType || "application/octet-stream", size: a.totalBytes,
      read: () => this.download(a.guid) };
    return c as unknown as Attachment;
  }

  private message(m: BBMessage, chat: string, content: LineMessage["content"]): LineMessage {
    const space = {
      id: chat,
      send: (text: string) => this.send(chat, text),
      startTyping: () => this.typing(chat, "POST"),
      stopTyping: () => this.typing(chat, "DELETE"),
    };
    return {
      id: m.guid,
      content,
      direction: m.isFromMe ? "outbound" : "inbound",
      sender: { id: m.handle?.address ?? "" },
      space,
      react: (emoji: string) => this.react(chat, m.guid, emoji),
      reply: (text: string) => this.send(chat, text, m.guid),
      read: () => this.first((r) => this.call(r, "POST", `chat/${encodeURIComponent(chat)}/read`)),
    };
  }
}
