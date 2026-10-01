/**
 * Refuses process kills that select targets by name or command-line pattern.
 *
 * Every omp worker on this host runs as the same uid, and a worker's full brief
 * sits in its own argv. So `pkill -f '<anything in a brief>'` matches sibling
 * workers too: on 2026-10-01 one worker's `pkill -f 'ponytail-review main'`
 * SIGTERMed two other workers, twice. Kill by PID instead (`cmd & pid=$!` then
 * `kill "$pid"`).
 *
 * Loaded by every omp session from ~/.omp/agent/extensions/ (primary,
 * crewmates, scouts, secondmates). no-mistakes gate agents run omp with
 * --no-extensions, so they are not covered here.
 */
type ToolCallEvent = { toolName?: string; input?: Record<string, unknown> };
type ToolCallResult = { block?: boolean; reason?: string };
interface GuardExtensionApi {
	on(event: "tool_call", handler: (event: ToolCallEvent) => Promise<ToolCallResult>): void;
}

const WRAPPERS = String.raw`(?:(?:sudo|doas|xargs|env|exec|nohup|time|command|setsid)\s+(?:-\S+\s+)*|\w+=\S*\s+)*`;
const NAME_KILL = String.raw`${WRAPPERS}(?:[\w.~-]*/)*(?:pkill|killall)(?=[\s;&|)"'\x60,\]]|$)`;
const SHELL_LEAD = String.raw`(?:^|[;&|(){\x60]|\$\(|\b(?:then|do|else)\s)\s*`;
const CALL_LEAD = String.raw`[(\[]\s*["']`;

const SELECTED_KILLS: RegExp[] = [
	/\b(?:pgrep|pidof|ps|grep|awk)\b[^\n;]*\|\s*xargs\b[^\n;]*\bkill\b/, // pgrep ... | xargs kill
	/\b(?:pgrep|pidof|ps|grep|awk)\b[^\n]*\|\s*while\b[^\n]*\bkill\b/, // pgrep ... | while read p; do kill $p
	/\bkill\b[^\n;]*(?:\$\(|\x60)\s*(?:pgrep|pidof)\b/, // kill $(pgrep ...)
];

const KILLS = {
	bash: [new RegExp(SHELL_LEAD + NAME_KILL, "m"), ...SELECTED_KILLS],
	eval: [new RegExp(`(?:${SHELL_LEAD}|${CALL_LEAD}\\s*)${NAME_KILL}`, "m"), ...SELECTED_KILLS],
};

const REASON =
	"Blocked: pkill/killall and kill-by-pgrep select processes by name or command line, " +
	"and every agent on this host shares one uid, so the pattern can match other workers " +
	"(their briefs sit in their argv). Kill only PIDs you started: `cmd & pid=$!`, then " +
	'`kill "$pid"`, or `kill` a PID you verified under your own process tree.';

export default function (pi: GuardExtensionApi) {
	pi.on("tool_call", async (event) => {
		const tool = event.toolName;
		if (tool !== "bash" && tool !== "eval") return {};
		const text = event.input?.[tool === "bash" ? "command" : "code"];
		return typeof text === "string" && KILLS[tool].some((re) => re.test(text)) ? { block: true, reason: REASON } : {};
	});
}
