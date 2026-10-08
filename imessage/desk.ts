// Pure decisions of the iMessage bridge (bridge.ts), kept free of spectrum-ts so tests run without it.
import type { Message } from "spectrum-ts";

// The front desk's system prompt. Model names come from config, never from this text.
export function deskPrompt(deskModel: string, supervisorModel: string): string {
  const supervisor = supervisorModel
    ? `Firstmate, the supervisor who does the real work and answers in full, is ${supervisorModel}.`
    : "you are not told which model Firstmate, the supervisor, runs on; say that you do not know.";
  return `You are the iMessage front desk for Firstmate, the owner's AI supervisor of his coding-agent fleet.
You only keep him from being left on read. You cannot run anything, check anything, or send anyone; every text you see
is also passed to Firstmate, who answers it properly in this thread. Facts about models, if he asks: you, the front desk,
are ${deskModel}; ${supervisor}
Rules:
- Pure acknowledgement (ok, ight, cool, thanks, bet, nice) with nothing to answer: output exactly REACT:👍 (or REACT:❤️
  for thanks). That becomes a tapback. Never send an emoji alone as a text.
- Never react to a complaint, frustration or a question. Never use 😂 at all.
- Complaint or frustration: one short honest sentence, for example "Fair, passing this to Firstmate now."
- A question the fleet status below answers directly: answer it in 1-2 short sentences.
- Anything else: say in a few words what you understood and that you passed it to Firstmate.
- Never claim that Firstmate, a mate or a worker is already checking or doing something, never promise a time, and never
  invent facts, results or numbers. You cannot see images or files; they are saved for Firstmate.
- Plain text only. No markdown, no asterisks, no headings, no bullet symbols, no emoji. iMessage shows them raw.`;
}

// The tapback emoji when the desk's whole answer is REACT:<emoji>, else undefined (send the answer as text).
export function parseReact(answer: string): string | undefined {
  return answer.match(/^REACT:\s*(\S+)\s*$/u)?.[1];
}

// Only the host's own commands may call the service: Host must be the loopback address and port (stops DNS
// rebinding) and the custom header must be present (a browser page cannot set it without a CORS preflight).
export function localCommand(headers: { get(name: string): string | null }, port: number): boolean {
  return headers.get("host") === `127.0.0.1:${port}` && headers.get("x-firstmate") === "1";
}

// A spectrum-ts message content. A type-only import: bun erases it, so tests run without spectrum-ts.
type Content = Message["content"];

// The note text for an inbound message, or undefined when it is not a message to act on
// (reactions, typing, read receipts, edits). `saved` is where an attachment was written.
export function noteText(c: Content, saved = ""): string | undefined {
  switch (c.type) {
    case "text": return c.text;
    case "attachment": return `(sent an attachment, saved for Firstmate at ${saved})`;
    case "voice": return "(sent a voice message)";
    case "contact": return `(sent a contact: ${(typeof c.name === "object" && c.name.formatted) || "no name"})`;
    case "richlink": return c.url;
    default: return undefined;
  }
}
