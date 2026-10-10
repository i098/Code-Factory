#!/usr/bin/env bash
# worktree-env-seed.sh - every swarms-platform checkout gets the shared-backend
# .env.local, automatically, forever.
#
# Root cause this closes: treehouse hands lanes a worktree with only
# .env.example; the app refuses to boot without a Supabase URL/key
# (CONTRIBUTING.md: "Your project's URL and Key are required"), so each agent
# built its own backend. Treehouse has no post-create hook, so this runs from
# systemd: on every change to the pool directory (new worktree), on a 2-minute
# timer (new pools, deleted files), and at login.
#
# Source of truth: ~/oss-fleet/shared-supabase/swarms-platform.env.local, which
# carries the marker line below. A worktree file without the marker is an
# agent-written placeholder file and is replaced (backup kept beside it).
set -u
SRC="$HOME/oss-fleet/shared-supabase/swarms-platform.env.local"
MARK='# fleet-shared-supabase'
LOG="$HOME/oss-fleet/doctor/worktree-env-seed.log"
log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }

[ -f "$SRC" ] || { log "source $SRC missing"; exit 1; }
grep -qF "$MARK" "$SRC" || { log "source lacks marker '$MARK' - refusing"; exit 1; }

seed_one() (
  local wt=$1 f=$1/.env.local
  umask 077
  local secrets="$HOME/.local/state/code-factory/secrets/shared-postgres"
  mkdir -p "$secrets" || exit 1
  exec 9>>"$secrets/.lock" || exit 1
  flock -x 9 || exit 1
  if [ -f "$f" ] && grep -qF "$MARK" "$f"; then
    if cmp -s "$SRC" "$f"; then return 0; fi
    # Postgres owns these two lines; compare the rest without rewriting them.
    if grep -qxF '# crewship-shared-postgres' "$f" &&
       cmp -s <(grep -vE '^DATABASE_URL=' "$SRC") \
              <(grep -vE '^(# crewship-shared-postgres$|DATABASE_URL=)' "$f"); then
      return 0
    fi
  fi
  if [ -f "$f" ]; then
    cp -p "$f" "$f.pre-shared-$(date -u +%Y%m%dT%H%M%SZ)"
  fi
  install -m 600 "$SRC" "$f" && log "seeded $f"
)

# Heap cap for what a lane runs through bun, npm or npx (next dev, tsc): those
# put every ancestor directory's node_modules/.bin on PATH, existing or not, so
# a `node` in the pool slot directory above the checkout is the only node they
# start, and the cap reaches the dev server instead of the shell or Herdr
# environment (the chrome-devtools-axi bridge, chrome-devtools-mcp and acpx
# never see it). It sits outside the checkout, so it exists before the first
# `bun install` and survives `rm -rf node_modules`. bun passes neither .env
# files nor NODE_OPTIONS set in them to a script's children. A runaway compile
# then fails fast with a heap error the agent can see, instead of growing to
# 4 GB and swapping the host.
HEAP_MB=${FLEET_NODE_HEAP_MB:-2048}
seed_node_cap() {
  local dir=$1/node_modules/.bin real tmp
  real=$(command -v node) || return 0
  mkdir -p "$dir" || return 0
  tmp=$(mktemp) || return 0
  printf '#!/bin/sh\n# fleet-managed heap cap for the lane in this pool slot\nexec %q --max-old-space-size=%s "$@"\n' \
    "$real" "$HEAP_MB" > "$tmp"
  if [ -f "$dir/node" ] && cmp -s "$tmp" "$dir/node"; then rm -f "$tmp"; return 0; fi
  install -m 755 "$tmp" "$dir/node" && log "seeded $dir/node (heap cap ${HEAP_MB} MB)"
  rm -f "$tmp"
}

# Worktree pools: ~/.treehouse/<repo>-<hash>/<n>/swarms-platform. A pool slot
# directory can exist for a moment before `git worktree add` fills it; give the
# checkout up to 2 minutes to appear so a brand-new lane is covered before its
# first `bun run dev`, not on the next timer tick.
shopt -s nullglob
for slot in "$HOME"/.treehouse/swarms-platform-*/*/; do
  wt="${slot%/}/swarms-platform"
  if [ ! -d "$wt" ]; then
    for _ in $(seq 1 60); do sleep 2; [ -d "$wt" ] && break; done
    [ -d "$wt" ] || continue
  fi
  [ -e "$wt/package.json" ] || continue
  seed_one "$wt" || exit 1
  seed_node_cap "${slot%/}"
done
# Firstmate's primary checkout of the project.
for wt in "$HOME"/.treehouse/firstmate-*/*/firstmate/projects/swarms-platform; do
  if [ -e "$wt/package.json" ]; then seed_one "$wt" || exit 1; fi
done
# Restore DATABASE_URL after Supabase copies its template when both profiles run.
if [ -f "$HOME/.local/state/code-factory/shared-postgres/compose.json" ] &&
   [ -x "$HOME/.local/bin/crewship-db" ]; then
  "$HOME/.local/bin/crewship-db" --seed || exit 1
fi
exit 0
