// Installed by Code Factory from config/herdr-sidebar.ts; `./factory apply`
// overwrites it. Feeds the Herdr agent sidebar layout described in
// docs/herdr.md:
//   - terminal title: the bare session topic, without omp's "π" and spinner;
//     a spawned worker (FM_TASK_ID set) gets two U+2800 blanks in front so the
//     topic lines up under its "└ task" name.
//   - pane token `who`: "└ <FM_TASK_ID>" for a worker, otherwise the label of
//     the pane's own workspace.
//   - pane token `refs` (workers only): the open pull request for the current
//     branch and the issues it closes, as "⎇ <pr>  ◉ <issue>".
// Lookups run in the background on session start and turn end and never fail
// or slow a turn.
// @ts-nocheck

import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

const BLANK = "\u2800";
const SOURCE = "code-factory:sidebar";
const REFS_REFRESH_MS = 5 * 60 * 1000;
const taskId = process.env.FM_TASK_ID || "";
const paneId = process.env.HERDR_PANE_ID;
const workspaceId = process.env.HERDR_WORKSPACE_ID;
const herdr = process.env.HERDR_BIN_PATH || "herdr";

const run = async (cmd: string, args: string[], cwd?: string): Promise<string> =>
  (await promisify(execFile)(cmd, args, { cwd, timeout: 15_000, encoding: "utf8" })).stdout;

export function titleFor(topic: string): string {
  return (taskId ? BLANK + BLANK : "") + topic;
}

// Same-repository closing keywords GitHub recognises in a PR body.
const CLOSING = /\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b/gi;

export function refsValue(pr: { number: number; body?: string | null } | undefined): string {
  if (!pr) return "";
  const issues = [...new Set([...(pr.body || "").matchAll(CLOSING)].map((m) => m[1]))];
  return BLANK.repeat(4) + [`⎇ ${pr.number}`, ...issues.map((n) => `◉ ${n}`)].join("  ");
}

async function lookupRefs(cwd: string): Promise<string> {
  const branch = (await run("git", ["-C", cwd, "branch", "--show-current"])).trim();
  if (!branch) return "";
  // REST, not GraphQL: gh fills {owner}/{repo} from the checkout's remote.
  const endpoint = `repos/{owner}/{repo}/pulls?state=open&head={owner}:${encodeURIComponent(branch)}`;
  const pulls = JSON.parse(await run("gh", ["api", "-X", "GET", endpoint], cwd));
  return refsValue(pulls[0]);
}

export default function (pi) {
  // Same guard as Herdr's own omp integration: only inside a Herdr pane, and
  // never from a nested omp started by a parent session's shell (OMPCODE=1).
  if (process.env.HERDR_ENV !== "1" || !paneId || process.env.OMPCODE === "1") return;

  let current; // latest interactive ctx
  let refs = "";
  let refsAt = 0;
  let refreshing = false;
  let trailing;
  let titleTimer;

  // Runs from a raw timer too, where a throw would take the session down.
  function applyTitle() {
    try {
      const name = current.sessionManager?.getSessionName?.() || path.basename(current.cwd || process.cwd());
      current.ui.setTitle(titleFor(name.trim()));
    } catch {}
  }

  // omp resets the title (and drops an extension override) on rename, /new,
  // /resume and cwd changes, often after its own async work, so keep
  // re-applying; the terminal sink skips unchanged titles.
  function track(ctx) {
    if (ctx?.hasUI !== true) return;
    current = ctx;
    applyTitle();
    if (!titleTimer) {
      titleTimer = setInterval(applyTitle, 1000);
      titleTimer.unref?.();
    }
  }

  async function report() {
    const who = taskId
      ? `└ ${taskId}`
      : JSON.parse(await run(herdr, ["workspace", "get", workspaceId])).result?.workspace?.label;
    const args = ["pane", "report-metadata", paneId, "--source", SOURCE];
    args.push(...(who ? ["--token", `who=${who}`] : ["--clear-token", "who"]));
    if (taskId) args.push(...(refs ? ["--token", `refs=${refs}`] : ["--clear-token", "refs"]));
    await run(herdr, args);
  }

  // Re-reporting on every call also restores tokens a Herdr restart dropped.
  // A lookup asked for while one runs or inside the throttle window is put
  // off to the window's end, not dropped.
  async function refresh(cwd?: string) {
    const wait = refsAt + REFS_REFRESH_MS - Date.now();
    if (cwd && taskId && (refreshing || wait > 0) && !trailing) {
      trailing = setTimeout(() => {
        trailing = undefined;
        void refresh(current.cwd);
      }, Math.max(wait, 1000));
      trailing.unref?.();
    }
    if (refreshing) return;
    refreshing = true;
    try {
      await report();
      if (cwd && taskId && wait <= 0) {
        refsAt = Date.now();
        const next = await lookupRefs(cwd);
        if (next !== refs) {
          refs = next;
          await report();
        }
      }
    } catch {
      // Display-only: a failed lookup or report keeps the previous value.
    } finally {
      refreshing = false;
    }
  }

  pi.on("session_start", (_event, ctx) => {
    track(ctx);
    if (current) void refresh(current.cwd);
  });
  pi.on("session_switch", (_event, ctx) => track(ctx));
  pi.on("agent_start", (_event, ctx) => track(ctx));
  // Subagent turns end here too; only the interactive session's cwd counts.
  pi.on("agent_end", () => {
    if (!current) return;
    applyTitle();
    void refresh(current.cwd);
  });
  // Tokens have no TTL, so a pane reused by another program must not keep them.
  pi.on("session_shutdown", () => {
    clearInterval(titleTimer);
    titleTimer = undefined;
    clearTimeout(trailing);
    if (current) void run(herdr, ["pane", "report-metadata", paneId, "--source", SOURCE, "--clear-token", "who", "--clear-token", "refs"]).catch(() => {});
  });
}
