/**
 * One status-line entry of evenly spaced icons for the always-on modes:
 *   compress = caveman, brain = ADHD, scissors = ponytail (Nerd Font icons)
 * An icon shows only while the mode's own plugin reports it active: omp strips
 * all styling from extension statuses, so a dimmed icon would look lit.
 *
 * ponytail and i-have-adhd set their own text statuses ("🐴 ponytail: ⚡ FULL",
 * "● ADHD ON"). omp gives every extension the same ui object, so this wraps
 * ui.setStatus once, keeps those two keys for itself, and renders the combined
 * icons under one key. Code Factory installs it as
 * ~/.omp/agent/extensions/aa-mode-icons.ts: omp loads extensions in name order,
 * so the "aa-" name sorts first and the wrap is in place before the plugins'
 * own session_start handlers run. caveman ships no omp extension, so it shows
 * unless ~/.claude/.caveman-active says off.
 */
import { existsSync, readFileSync } from "fs";
import { join } from "path";

const KEY = "aa-modes";
const WRAPPED = Symbol.for("aa-mode-icons.wrapped");
const OWNED = new Set(["ponytail", "i-have-adhd", "caveman"]);
const CAVEMAN_MARKER = join(process.env.HOME ?? "", ".claude", ".caveman-active");

// Hooks from ~/.claude/settings.json and <cwd>/.claude/settings.json, as icons.
// Present = active; anything unmapped counts toward the hook-icon N guard-hook total.
const HOOK_ICONS: Record<string, string> = {
	"chrome-devtools-axi": "\uf268",
	"gh-axi": "\uf09b",
	"lavish-axi": "\uf1fc",
	lint: "\u{f00e2}",
	"auto-format": "\uf0d0",
	codegraph: "\uf0e8",
	"quality-gate": "\uf219",
	"herdr-agent-state": "\uf09e",
};
const HOOK_BINS = ["gh-axi", "lavish-axi", "chrome-devtools-axi", "codegraph"];
const HIDDEN = new Set(["session-start", "session-end", "notify", "headroom", "codex-review-diff", "codex-review-plan", "codex-review-surface"]);

type HookSettings = { hooks?: Record<string, Array<{ hooks?: Array<{ command?: string }> }>> };

function hookNames(cwd: string): string[] {
	const names = new Set<string>();
	for (const file of [join(process.env.HOME ?? "", ".claude", "settings.json"), join(cwd, ".claude", "settings.json")]) {
		let settings: HookSettings;
		try {
			// Local config file this account writes; a wrong shape just yields no hooks.
			settings = JSON.parse(readFileSync(file, "utf8")) as HookSettings;
		} catch {
			continue;
		}
		for (const events of Object.values(settings.hooks ?? {}))
			for (const entry of events ?? [])
				for (const { command } of entry.hooks ?? []) {
					if (!command) continue;
					for (const m of command.matchAll(/([\w][\w.-]*?)\.(?:sh|py|js|ts)\b/g)) names.add(m[1]);
					for (const bin of HOOK_BINS) if (command.includes(bin)) names.add(bin);
				}
	}
	return [...names].filter((n) => !HIDDEN.has(n));
}

export default function (pi) {
	const on: Record<string, boolean> = { caveman: true, "i-have-adhd": false, ponytail: false };

	function cavemanOn(): boolean {
		if (!existsSync(CAVEMAN_MARKER)) return true;
		return readFileSync(CAVEMAN_MARKER, "utf8").trim().toLowerCase() !== "off";
	}

	let hooks = "";

	function render(set) {
		on.caveman = cavemanOn();
		const modes = [["\uf066", on.caveman], ["\u{f09d1}", on["i-have-adhd"]], ["\uf0c4", on.ponytail]]
			.filter(([, lit]) => lit)
			.map(([glyph]) => glyph);
		set(KEY, [...modes, ...(hooks ? [hooks] : [])].join("   "));
	}

	function hookIcons(cwd: string): string {
		const names = hookNames(cwd);
		const shown = Object.entries(HOOK_ICONS).filter(([n]) => names.includes(n)).map(([, g]) => g);
		const guards = names.filter((n) => !(n in HOOK_ICONS)).length;
		return [...shown, ...(guards ? [`\u{f06e2} ${guards}`] : [])].join("   ");
	}

	function install(ctx) {
		const ui = ctx?.ui;
		if (ctx?.hasUI !== true || !ui?.setStatus) return;
		if (!ui[WRAPPED]) {
			const original = ui.setStatus.bind(ui);
			ui.setStatus = (key: string, text?: string) => {
				if (!OWNED.has(key)) return original(key, text);
				// Plugins send "" (or nothing) only when the mode is off; ponytail's "○" just means idle.
				on[key] = Boolean(text);
				original(key, undefined);
				render(original);
			};
			ui[WRAPPED] = original;
			for (const k of OWNED) original(k, undefined);
		}
		render(ui[WRAPPED]);
	}

	for (const event of ["session_start", "session_switch"])
		pi.on(event, (_event, ctx) => {
			hooks = hookIcons(ctx?.cwd ?? process.cwd());
			install(ctx);
		});
}
