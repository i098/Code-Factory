#!/usr/bin/env bash
# One-shot (2026-10-01): once no no-mistakes run is active, update no-mistakes to
# the latest release and switch the pipeline agent from cold `acp:omp` to omp
# through the native pi adapter (omp-as-pi), which reuses one fixer session
# across review-fix rounds. Every step is checked; any failed check restores the
# previous config.yaml and restarts the daemon on it. Log: LOG below.
# Every ./factory apply runs `switch-when-idle.sh --check-adapter <tag>` to decide
# between the same two agents without updating or restarting anything.
set -uo pipefail
NMH=$HOME/.no-mistakes
NM=$NMH/bin/no-mistakes
W=$NMH/omp-as-pi
CFG=$NMH/config.yaml
# no-mistakes names its unit after the first 8 hex digits of sha256(<root>).
UNIT=no-mistakes-daemon-$(printf '%s' "$NMH" | sha256sum | cut -c1-8).service
LOG=$NMH/logs/switch-when-idle.log
# Adapter sources the wrapper was proven against (no-mistakes v1.85.3).
declare -A PINNED=(
	["internal/agent/pi.go"]=cd5340ef362585592fc1fdaf856a62cdfa3303dde5d324d93b23998c4c0f8d75
	["internal/agentcfg/pi_profile.go"]=be326b6b756e1075d5bf827cec6e80069cd293a79a751ecc7e6dbf0650d490f0
	["internal/agent/fallback.go"]=7f90d1cab045d805509d470404f4263e3e5c985605e13135e357cbe7773987c4
)

# Exit 0 when every pinned adapter source at no-mistakes tag $1 matches its pin;
# otherwise print why not and exit 1.
check_adapter() {
	local f got
	for f in "${!PINNED[@]}"; do
		got=$(curl -fsSL "https://raw.githubusercontent.com/kunchenguid/no-mistakes/$1/$f" | sha256sum) ||
			{
				echo "could not fetch $f at $1 to verify it"
				return 1
			}
		[ "${got%% *}" = "${PINNED[$f]}" ] ||
			{
				echo "$f changed in $1 (sha ${got%% *}); re-prove omp-as-pi against $1 first"
				return 1
			}
	done
	echo "pi adapter sources at $1 match the pins"
}
if [ "${1:-}" = --check-adapter ]; then
	check_adapter "$2"
	exit
fi

exec >>"$LOG" 2>&1
say() { printf '%s %s\n' "$(date -Is)" "$*"; }
active_runs() {
	python3 -c "import sqlite3;c=sqlite3.connect('file:$NMH/state.sqlite?mode=ro',uri=True);print(c.execute(\"select count(*) from runs where status not in ('completed','cancelled','failed')\").fetchone()[0])"
}

say "waiting for no active runs"
for i in $(seq 1 600); do
	[ "$(active_runs)" = 0 ] && break
	[ "$i" = 600 ] && {
		say "GAVE UP: runs still active after 10h; nothing changed"
		exit 1
	}
	sleep 60
done

BAK="$CFG.bak-$(date +%Y%m%d-%H%M%S)-pre-omp-as-pi"
cp "$CFG" "$BAK" && say "config backed up to $BAK"
rollback() {
	say "ROLLBACK: $*"
	cp "$BAK" "$CFG"
	systemctl --user restart "$UNIT"
	sleep 3
	"$NM" doctor | grep -E 'daemon|gate validation'
	say "ROLLED BACK to the previous config (cold acp:omp). Wrapper not in use."
	exit 2
}

say "updating no-mistakes"
"$NM" update --yes || say "WARN: update command failed; continuing on the installed version"
ver=$("$NM" --version | grep -o -E 'v[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)
say "no-mistakes now $ver"

# The wrapper translates exactly the argv the pinned pi adapter builds. If the
# adapter sources moved in this version, do not switch.
why=$(check_adapter "$ver") || {
	say "NOT SWITCHING: $why. Update kept, agent stays acp:omp."
	systemctl --user restart "$UNIT"
	exit 3
}
say "$why"

say "switching agent to [pi, acp:omp] through omp-as-pi"
python3 - "$CFG" "$W/omp-as-pi" <<'EOF' || rollback "could not rewrite config.yaml"
import re, sys
p = sys.argv[1]
s = open(p).read()
new_agent = """# 2026-10-01 (captain order "go ahead and implement"): omp now runs through
# no-mistakes' native pi adapter via ~/.no-mistakes/omp-as-pi/omp-as-pi, the only
# path that reuses one fixer session across review-fix rounds (acp:<target> is
# always cold). omp is a Pi fork with the same --mode json stream; the wrapper
# maps --session -> --resume and --no-context-files -> the exact omp gate
# neutralization, refuses any other argument, and logs refusals to
# ~/.no-mistakes/omp-as-pi/refusals.log. acp:omp stays as the fallback: a failed
# pi start (including a wrapper refusal) re-runs that invocation cold on acp:omp.
# Proof: omp-as-pi/test.sh --live, plus an isolated v1.85.3 pipeline run where
# the fixer session was started then resumed and the AGENTS.md canary never leaked.
agent: [pi, acp:omp]
agent_path_override:
  pi: """ + sys.argv[2] + """
# Model and effort now pin natively (pi adapter: --model/--thinking). The Opus
# advisor still comes from ~/.no-mistakes/omp-config.yml via PI_CONFIG_FILES.
agent_config:
  pi:
    model: anthropic/claude-sonnet-5-5
    effort: xhigh
"""
s2, n = re.subn(r"(?m)^agent: \[acp:omp\]\n", new_agent, s, count=1)
if n != 1 or "agent_path_override:\n  pi:" in s:
    sys.exit("unexpected config shape")
open(p, "w").write(s2)
EOF

[ "$(active_runs)" = 0 ] || rollback "a run started during the switch; restoring before restart"
systemctl --user restart "$UNIT" && sleep 4

doc=$("$NM" doctor 2>&1)
printf '%s\n' "$doc" | grep -E 'daemon|gate validation'
printf '%s\n' "$doc" | grep -q '✓ gate validation' || rollback "doctor gate validation failed"
pid=$(systemctl --user show -p MainPID --value "$UNIT")
tr '\0' '\n' <"/proc/$pid/environ" | grep -q '^PI_CONFIG_FILES=' || rollback "daemon lost PI_CONFIG_FILES"
"$W/omp-as-pi" --omp-as-pi-check || rollback "omp-as-pi preflight failed"
bash "$W/test.sh" --live | tail -n 3
[ "${PIPESTATUS[0]}" = 0 ] || rollback "omp-as-pi live tests failed"

say "SWITCHED: no-mistakes $ver, agent [pi, acp:omp] via omp-as-pi, all checks green"
