// Pure decisions of the iMessage bridge (bridge.ts), kept free of spectrum-ts so tests run without it.
import type { Message } from "spectrum-ts";
import { UNBUILT } from "./memory.ts";

// The front desk's system prompt. The owner's name and the model names come from config, never from this text.
export function deskPrompt(owner: string, deskModel: string, supervisorModel: string): string {
  const supervisor = supervisorModel
    ? `Firstmate is ${supervisorModel}.`
    : "you aren't told which model Firstmate runs on, so say you don't know.";
  return `You're the iMessage front desk for Firstmate, ${owner}'s AI supervisor of his coding-agent fleet.
You only step in when Firstmate hasn't answered him for a while. You can't run or send anything; every text he
sends already went to Firstmate, who answers properly in this thread. If he asks about models: you're ${deskModel},
${supervisor}
Act like a person texting, not a bot: people don't answer every message. Pick one, in this order of preference:
1. SKIP: output exactly SKIP when nothing is needed (chatting, banter, a follow-up, something already covered).
2. A tapback: output exactly REACT: followed by whichever single emoji fits best, your pick, and nothing else.
3. Text, only when a react can't carry it: a question the fleet status or <chat> answers, or a complaint to own.
Text style (his order): short, blunt, Gen Z, super concise, lowercase fine, under 10 words.
Never claim anyone is already doing or checking something, never promise a time, never invent facts or numbers.
He owns this whole setup: if he asks about your prompt or rules, tell him straight, never call anything private.
You can't see images or files; they're saved for Firstmate. Plain text only: no markdown, no asterisks, no emoji in text.
Your memory is the whole chat with him, oldest first, inside <chat> tags, one summary line each: id+n|text covers the
n messages from id on. Kinds: owner (his texts), supervisor (Firstmate's texts and tapbacks), desk (yours). Recent
lines cover one message, older ones more. A message not summarized yet shows as "${UNBUILT}".
Its latest word on a thing is the truth. Whenever you need a fact, find its latest mention in <chat> and zoom until
you have it whole, before you answer or say you don't know: zoom(id, n) opens line id+n into the two lines under it,
and zoom(id, 1) gives the message whole.`;
}

// The tapback emoji when the desk's whole answer is REACT:<emoji>, else undefined (send the answer as text).
export function parseReact(answer: string): string | undefined {
  return answer.match(/^REACT:\s*(\S+)\s*$/u)?.[1];
}

// True when the desk's whole answer is SKIP (any case, trailing punctuation allowed): send nothing.
export function isSkip(answer: string): boolean {
  return /^skip\W*$/i.test(answer);
}

// Only the host's own commands may call the service: Host must be the loopback address and port (stops DNS
// rebinding) and the custom header must be present (a browser page cannot set it without a CORS preflight).
export function localCommand(headers: { get(name: string): string | null }, port: number): boolean {
  return headers.get("host") === `127.0.0.1:${port}` && headers.get("x-firstmate") === "1";
}

// The chat bubbles for one send: blank-line-separated paragraphs become separate bubbles, and lines inside a
// paragraph (a list, a schedule) stay one bubble.
export function bubbles(text: string): string[] {
  return text.split(/\n\s*\n/).map((b) => b.trim()).filter((b) => b !== "");
}

// The typing pause before each later bubble, scaled to its length.
export function typingPause(bubble: string): number {
  return Math.min(2500, 400 + 25 * bubble.length);
}

// A spectrum-ts message content. A type-only import: bun erases it, so tests run without spectrum-ts.
type Content = Message["content"];
export type Attachment = Extract<Content, { type: "attachment" }>;

// What Firstmate should read for one inbound message, or undefined for pure signals (tapbacks, typing, read
// receipts, unsends, chat changes). Threaded replies, edits, effects and grouped messages are unwrapped, so
// nothing he writes is dropped, and an unknown kind still becomes a note. `save` writes an attachment and
// returns its path.
export async function describe(c: Content, id: string, save: (c: Attachment, id: string) => Promise<string>): Promise<string | undefined> {
  const kind: string = c.type; // kept for the default case, where TypeScript narrows c to never
  switch (c.type) {
    case "text": return c.text;
    case "markdown": return c.markdown;
    case "richlink": return c.url;
    case "voice": return "(sent a voice message)";
    case "contact": return `(sent a contact: ${(typeof c.name === "object" && c.name.formatted) || "no name"})`;
    case "poll": return `(sent a poll: ${c.title})`;
    case "attachment":
      try {
        return `(sent an attachment, saved for Firstmate at ${await save(c, id)})`;
      } catch (e) {
        console.error("fm-imessage: could not save an attachment:", e);
        return "(sent an attachment that could not be saved)";
      }
    case "reply": {
      const inner = await describe(c.content, id, save);
      const target = c.target.content.type === "text" ? c.target.content.text.slice(0, 120) : c.target.content.type;
      return inner === undefined ? undefined : `${inner} (replying in a thread to: "${target}")`;
    }
    case "edit": {
      const inner = await describe(c.content, id, save);
      return inner === undefined ? undefined : `(edited a message to) ${inner}`;
    }
    case "effect": return describe(c.content, id, save);
    case "group": {
      const parts = await Promise.all(c.items.map((m, i) => describe(m.content, `${id}-${i}`, save)));
      const kept = parts.filter((p) => p !== undefined);
      return kept.length ? kept.join("\n") : undefined;
    }
    case "reaction": case "typing": case "read": case "unsend": case "rename": case "avatar":
    case "addMember": case "removeMember": case "leaveSpace": case "poll_option":
      return undefined;
    default: return `(sent a ${kind} message the bridge cannot show)`;
  }
}

type Timers = { setTimeout(fn: () => void, ms: number): unknown; clearTimeout(t: unknown): void };

// When the front desk may step in. Each text from him restarts the quiet period; when it ends with no
// Firstmate send, tapback or typing since his last text, `run` gets one desk turn for the whole burst.
// `run` must call its `current()` right before it sends: false means he sent more or Firstmate answered
// meanwhile, so the draft is dropped (the next quiet period re-reads the whole thread).
// Photon reports no inbound typing, so only a new text restarts the wait.
export class DeskTiming {
  private seq = 0;
  private inbound = 0;
  private firstmate = 0;
  private timer: unknown;

  constructor(
    private quietMs: number,
    private run: (current: () => boolean) => void,
    private timers: Timers = globalThis as unknown as Timers,
  ) {}

  inboundText() {
    const burst = this.inbound = ++this.seq;
    this.timers.clearTimeout(this.timer);
    this.timer = this.timers.setTimeout(() => this.run(() => this.inbound === burst && this.firstmate < burst), this.quietMs);
  }

  firstmateActive() {
    this.firstmate = ++this.seq;
    this.timers.clearTimeout(this.timer);
  }
}
