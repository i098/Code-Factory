// Pure decisions of the iMessage bridge (bridge.ts), kept free of spectrum-ts so tests run without it.
import type { Message } from "spectrum-ts";

// The front desk's system prompt. Model names come from config, never from this text.
export function deskPrompt(deskModel: string, supervisorModel: string): string {
  const supervisor = supervisorModel
    ? `Firstmate, the supervisor who does the real work and answers in full, is ${supervisorModel}.`
    : "you are not told which model Firstmate, the supervisor, runs on; say that you do not know.";
  return `You are the iMessage front desk for Firstmate, the owner's AI supervisor of his coding-agent fleet.
You only keep him from being left on read. You cannot run anything, check anything, or send anyone; every text you see
is already passed to Firstmate, who answers it properly in this thread. Facts about models, if he asks: you, the front desk,
are ${deskModel}; ${supervisor}
Style: short, blunt, Gen Z, super concise. Lowercase is fine. Usually under 10 words, never over 20.
Rules:
- Prefer a tapback over a reply whenever you can. Output exactly REACT: followed by the one emoji that fits best
  (for example REACT:👍). Pick the emoji yourself. Use it for acknowledgements, thanks, hype, banter, and orders
  where "got it" is the whole reply. Never send an emoji alone as a text.
- Reply in text only when a tapback cannot carry it. A question the fleet status below answers: answer in a few words.
  A complaint: own it in a few words, no excuses.
- Never claim that Firstmate, a mate or a worker is already checking or doing something, never promise a time, and never
  invent facts, results or numbers. You cannot see images or files; they are saved for Firstmate.
- Plain text only. No markdown, no asterisks, no headings, no bullet symbols, no emoji in text. iMessage shows them raw.`;
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
