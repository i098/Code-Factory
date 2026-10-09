// The bridge's durable queues (bridge.ts): the outbox of sends and tapbacks, and the attachment downloads to try
// again. Kept free of spectrum-ts so tests run without it.
import { closeSync, fsyncSync, mkdirSync, openSync, readdirSync, readFileSync, renameSync, unlinkSync, writeSync } from "node:fs";

// The code of a transient upstream failure, which a later try may pass: gRPC UNAVAILABLE (code 14, which Photon's
// HTTP client also gives for HTTP 502 and 503) or an HTTP 502 or 503. Undefined for any other error.
export function transient(e: unknown): string | undefined {
  for (let x: unknown = e; x instanceof Object; x = Reflect.get(x, "cause")) {
    const status = Reflect.get(x, "status");
    if (Reflect.get(x, "grpcCode") === 14 || Reflect.get(x, "code") === 14 || /\bUNAVAILABLE\b/.test(String(Reflect.get(x, "message")))) return "UNAVAILABLE";
    if (status === 502 || status === 503) return `HTTP ${status}`;
  }
}

// One line for a failed operation: the transient code (else the error name), then the first line of the message.
export function brief(e: unknown): string {
  const message = (e instanceof Error ? e.message : String(e)).split("\n")[0];
  return `${transient(e) ?? (e instanceof Error ? e.name : "error")}: ${message}`;
}

// A durable FIFO queue in `dir`: one JSON file per item, named by a rising sequence number and written atomically
// (fsync, then rename), so an item survives a crash or a restart once add() returns. One loop delivers the oldest
// item; when it fails, the loop logs one line, waits one backoff step (at most 60 × `retryMs`) and tries the same
// item again, so the order holds and nothing is dropped. Deleting an item's file drops it by hand. `deliver` may
// save progress (the bubbles already sent) with `save`. The constructor starts on the items already queued.
export class Queue<T> {
  private next: number;
  private busy = false;

  constructor(
    private dir: string,
    private name: string,
    private deliver: (item: T, save: (item: T) => void) => Promise<void>,
    private retryMs: number,
  ) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    this.next = (this.seqs().at(-1) ?? 0) + 1;
    void this.drain();
  }

  add(item: T) {
    this.write(this.next++, item);
    void this.drain();
  }

  private seqs(): number[] {
    return readdirSync(this.dir).filter((f) => /^\d+\.json$/.test(f)).map((f) => parseInt(f, 10)).sort((a, b) => a - b);
  }

  private file(seq: number): string {
    return `${this.dir}/${seq}.json`;
  }

  private write(seq: number, item: T) {
    const tmp = `${this.file(seq)}.tmp`;
    const fd = openSync(tmp, "w", 0o600);
    try {
      writeSync(fd, JSON.stringify(item));
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    renameSync(tmp, this.file(seq));
    const dir = openSync(this.dir, "r");
    try {
      fsyncSync(dir);
    } finally {
      closeSync(dir);
    }
  }

  private async drain() {
    if (this.busy) return;
    this.busy = true;
    let head: number | undefined;
    let attempt = 0;
    try {
      for (let seq = this.seqs()[0]; seq !== undefined; seq = this.seqs()[0]) {
        if (seq !== head) [head, attempt] = [seq, 0];
        try {
          await this.deliver(JSON.parse(readFileSync(this.file(seq), "utf8")), (item) => this.write(seq, item));
          unlinkSync(this.file(seq));
        } catch (e) {
          // Capped exponential backoff with jitter, so retries spread out.
          const wait = Math.min(60 * this.retryMs, this.retryMs * 2 ** attempt++) * (0.5 + Math.random() / 2);
          console.error(`fm-imessage: ${this.name} ${seq} failed (try ${attempt}), next try in ${(wait / 1000).toFixed(1)} s: ${brief(e)}`);
          await Bun.sleep(wait);
        }
      }
    } finally {
      this.busy = false;
    }
  }
}
