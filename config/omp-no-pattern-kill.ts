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

const SEP = String.raw`[\s"',]+`;
const OPTS = String.raw`(?:-[\w=.{}-]+${SEP}(?:\w+${SEP})?)*`;
const LEAD = String.raw`(?:^|[;&|({\[\x60]|\$\(|\b(?:if|elif|then|else|do|while|until)\s)\s*(?:!\s*)?["']?`;
const WRAPPERS = String.raw`(?:(?:sudo|doas|env|exec|nohup|time|setsid|xargs|nice|ionice|stdbuf|(?:ba|z|da|k)?sh)${SEP}${OPTS}|timeout${SEP}${OPTS}\d\w*${SEP}|(?:ssh|(?:docker|podman|kubectl)${SEP}exec)${SEP}${OPTS}\S+?${SEP}|\w+=\S*${SEP})*`;
const NAME = String.raw`(?:[\w.~-]*/)*(?:pkill|killall)(?!["']\s*\))(?=[\s;&|)"'\x60,\]]|$)`;
const SELECTOR = String.raw`\b(?:pgrep|pidof|ps|grep|awk)\b`;

const PATTERN_KILLS: RegExp[] = [
	new RegExp(LEAD + WRAPPERS + NAME, "m"), // pkill / killall by name or pattern
	new RegExp(String.raw`${SELECTOR}[^\n;]*\|\s*xargs\s+${OPTS}kill\b`), // pgrep ... | xargs kill
	new RegExp(String.raw`${SELECTOR}[^\n]*\|\s*while\b[^\n]*\bdo\s+kill\b`), // pgrep ... | while read p; do kill $p
	new RegExp(String.raw`\bkill\b[^\n;&|]*(?:\$\(|\x60)[^)\x60\n]*\b(?:pgrep|pidof|grep|awk)\b`), // kill $(ps ... | grep ...)
];

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
		return typeof text === "string" && PATTERN_KILLS.some((re) => re.test(text)) ? { block: true, reason: REASON } : {};
	});
}
